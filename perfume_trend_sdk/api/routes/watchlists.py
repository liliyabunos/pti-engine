from __future__ import annotations

"""
Watchlists routes — Market Terminal API v1.

GET    /api/v1/watchlists                     — list all watchlists
POST   /api/v1/watchlists                     — create watchlist
GET    /api/v1/watchlists/{id}                — watchlist detail (enriched items)
POST   /api/v1/watchlists/{id}/items          — add entity to watchlist
DELETE /api/v1/watchlists/{id}/items/{entity_id} — remove entity

V1 auth strategy:
  All operations use DEV_OWNER_KEY ("dev") — a single implicit owner.
  No authentication is required. When a real auth layer is added, replace
  the hardcoded owner_key filter with the authenticated user's identifier.
"""

import uuid
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.queries import (
    fetch_brand_name_map,
    fetch_latest_signal_map,
    get_brand_name,
)
from perfume_trend_sdk.api.schemas.watchlists import (
    WatchlistCreate,
    WatchlistDetail,
    WatchlistItemAdd,
    WatchlistItemRow,
    WatchlistListResponse,
    WatchlistSummary,
)
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import EntityMarket
from perfume_trend_sdk.db.market.watchlist import DEV_OWNER_KEY, Watchlist, WatchlistItem
from sqlalchemy import func

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _get_watchlist_or_404(db: Session, watchlist_id: str) -> Watchlist:
    wl = (
        db.query(Watchlist)
        .filter_by(id=uuid.UUID(watchlist_id), owner_key=DEV_OWNER_KEY)
        .first()
    )
    if wl is None:
        raise HTTPException(status_code=404, detail=f"Watchlist not found: {watchlist_id}")
    return wl


def _item_count_map(db: Session, watchlist_ids: list) -> dict[str, int]:
    """Return {watchlist_id_str: item_count} for a list of watchlist UUIDs."""
    if not watchlist_ids:
        return {}
    rows = (
        db.query(WatchlistItem.watchlist_id, func.count(WatchlistItem.id))
        .filter(WatchlistItem.watchlist_id.in_(watchlist_ids))
        .group_by(WatchlistItem.watchlist_id)
        .all()
    )
    return {str(wid): cnt for wid, cnt in rows}


def _enrich_items(
    db: Session,
    items: list[WatchlistItem],
) -> list[WatchlistItemRow]:
    """Fetch current market data for each watchlist item (batch, no N+1)."""
    if not items:
        return []

    entity_ids = [it.entity_id for it in items]

    # Batch-load EntityMarket rows
    em_rows = (
        db.query(EntityMarket)
        .filter(EntityMarket.entity_id.in_(entity_ids))
        .all()
    )
    em_map: dict[str, EntityMarket] = {em.entity_id: em for em in em_rows}

    # Batch-load latest snapshots
    # Sub-select the max date per entity UUID
    entity_uuids = [em.id for em in em_rows]
    sub = (
        db.query(
            EntityTimeSeriesDaily.entity_id,
            func.max(EntityTimeSeriesDaily.date).label("max_date"),
        )
        .filter(EntityTimeSeriesDaily.entity_id.in_(entity_uuids))
        .group_by(EntityTimeSeriesDaily.entity_id)
        .subquery()
    )
    snap_rows = (
        db.query(EntityTimeSeriesDaily)
        .join(
            sub,
            (EntityTimeSeriesDaily.entity_id == sub.c.entity_id)
            & (EntityTimeSeriesDaily.date == sub.c.max_date),
        )
        .all()
    )
    snap_map: dict[uuid.UUID, EntityTimeSeriesDaily] = {
        s.entity_id: s for s in snap_rows
    }

    brand_name_map = fetch_brand_name_map(db)
    latest_signal_map = fetch_latest_signal_map(db)

    result: list[WatchlistItemRow] = []
    for item in items:
        em = em_map.get(item.entity_id)
        snap = snap_map.get(em.id) if em else None
        sig = latest_signal_map.get(em.id) if em else None

        result.append(
            WatchlistItemRow(
                entity_id=item.entity_id,
                entity_type=item.entity_type,
                ticker=em.ticker if em else item.entity_id,
                canonical_name=em.canonical_name if em else item.entity_id,
                brand_name=get_brand_name(em, brand_name_map) if em else None,
                composite_market_score=(
                    round(snap.composite_market_score, 4) if snap and snap.composite_market_score is not None else None
                ),
                growth_rate=(
                    round(snap.growth_rate, 4) if snap and snap.growth_rate is not None else None
                ),
                mention_count=snap.mention_count if snap else None,
                confidence_avg=(
                    round(snap.confidence_avg, 4) if snap and snap.confidence_avg is not None else None
                ),
                latest_signal=sig[0] if sig else None,
                latest_date=snap.date.isoformat() if snap else None,
                added_at=_fmt_dt(item.added_at),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=WatchlistListResponse)
def list_watchlists(db: Session = Depends(get_db_session)):
    """Return all watchlists for the dev owner with item counts."""
    wls = (
        db.query(Watchlist)
        .filter_by(owner_key=DEV_OWNER_KEY)
        .order_by(Watchlist.updated_at.desc())
        .all()
    )
    counts = _item_count_map(db, [wl.id for wl in wls])
    return WatchlistListResponse(
        watchlists=[
            WatchlistSummary(
                id=str(wl.id),
                name=wl.name,
                description=wl.description,
                item_count=counts.get(str(wl.id), 0),
                created_at=_fmt_dt(wl.created_at),
                updated_at=_fmt_dt(wl.updated_at),
            )
            for wl in wls
        ]
    )


@router.post("", response_model=WatchlistSummary, status_code=201)
def create_watchlist(
    body: WatchlistCreate,
    db: Session = Depends(get_db_session),
):
    """Create a new watchlist."""
    wl = Watchlist(
        id=uuid.uuid4(),
        owner_key=DEV_OWNER_KEY,
        name=body.name.strip(),
        description=body.description,
    )
    db.add(wl)
    db.flush()
    return WatchlistSummary(
        id=str(wl.id),
        name=wl.name,
        description=wl.description,
        item_count=0,
        created_at=_fmt_dt(wl.created_at),
        updated_at=_fmt_dt(wl.updated_at),
    )


@router.get("/{watchlist_id}", response_model=WatchlistDetail)
def get_watchlist(
    watchlist_id: str,
    db: Session = Depends(get_db_session),
):
    """Return full watchlist detail with enriched market data per item."""
    wl = _get_watchlist_or_404(db, watchlist_id)
    items = (
        db.query(WatchlistItem)
        .filter_by(watchlist_id=wl.id)
        .order_by(WatchlistItem.added_at.desc())
        .all()
    )
    enriched = _enrich_items(db, items)
    return WatchlistDetail(
        id=str(wl.id),
        name=wl.name,
        description=wl.description,
        created_at=_fmt_dt(wl.created_at),
        updated_at=_fmt_dt(wl.updated_at),
        items=enriched,
    )


@router.post("/{watchlist_id}/items", response_model=WatchlistDetail, status_code=201)
def add_watchlist_item(
    watchlist_id: str,
    body: WatchlistItemAdd,
    db: Session = Depends(get_db_session),
):
    """Add an entity to a watchlist. Returns the updated watchlist detail."""
    wl = _get_watchlist_or_404(db, watchlist_id)

    # Verify the entity exists in entity_market
    em = db.query(EntityMarket).filter_by(entity_id=body.entity_id).first()
    if em is None:
        raise HTTPException(status_code=404, detail=f"Entity not found: {body.entity_id}")

    item = WatchlistItem(
        id=uuid.uuid4(),
        watchlist_id=wl.id,
        entity_id=body.entity_id,
        entity_type=body.entity_type,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Entity '{body.entity_id}' is already in this watchlist.",
        )

    # Touch updated_at
    wl.updated_at = datetime.utcnow()
    db.flush()

    return get_watchlist(watchlist_id, db)


@router.delete("/{watchlist_id}/items/{entity_id}", status_code=204)
def remove_watchlist_item(
    watchlist_id: str,
    entity_id: str,
    db: Session = Depends(get_db_session),
):
    """Remove an entity from a watchlist."""
    wl = _get_watchlist_or_404(db, watchlist_id)
    item = (
        db.query(WatchlistItem)
        .filter_by(watchlist_id=wl.id, entity_id=entity_id)
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{entity_id}' not found in this watchlist.",
        )
    db.delete(item)
    wl.updated_at = datetime.utcnow()
    db.flush()
