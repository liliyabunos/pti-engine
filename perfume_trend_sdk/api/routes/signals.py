from __future__ import annotations

"""
Signal feed routes — Market Terminal API v1.

GET /api/v1/signals — recent market signal events across all entities.

Filters supported:
  days          — lookback window (default 7)
  signal_type   — filter by type (new_entry | breakout | acceleration_spike | reversal)
  entity_type   — filter by entity type (perfume | brand)
  date_from     — ISO date YYYY-MM-DD, inclusive
  date_to       — ISO date YYYY-MM-DD, inclusive

Results are sorted newest first. Each row includes entity display fields
(name, ticker, brand_name where applicable).
"""

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.queries import fetch_brand_name_map, get_brand_name
from perfume_trend_sdk.api.schemas.entity import SignalRow
from perfume_trend_sdk.db.market.models import EntityMarket
from perfume_trend_sdk.db.market.signal import Signal

router = APIRouter()

_VALID_SIGNAL_TYPES = {
    "new_entry", "breakout", "acceleration_spike", "reversal"
}


def _fmt_dt(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


@router.get("", response_model=List[SignalRow])
def list_signals(
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    signal_type: Optional[str] = Query(None, description="Filter by signal type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (perfume | brand)"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD (inclusive)"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD (inclusive)"),
    limit: int = Query(100, ge=1, le=500, description="Max rows to return"),
    db: Session = Depends(get_db_session),
) -> List[SignalRow]:
    """Return market signal events, newest first."""

    # Validate and parse date filters
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            dt_from = None
    else:
        dt_from = datetime.now(timezone.utc) - timedelta(days=days)

    if date_to:
        try:
            # Inclusive: end of the given day
            dt_to = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            dt_to = None
    else:
        dt_to = None

    # Build query with joins
    query = (
        db.query(Signal, EntityMarket)
        .join(EntityMarket, Signal.entity_id == EntityMarket.id)
    )

    if dt_from:
        query = query.filter(Signal.detected_at >= dt_from)
    if dt_to:
        query = query.filter(Signal.detected_at <= dt_to)

    if signal_type:
        if signal_type not in _VALID_SIGNAL_TYPES:
            return []
        query = query.filter(Signal.signal_type == signal_type)

    if entity_type:
        query = query.filter(EntityMarket.entity_type == entity_type)

    rows = query.order_by(Signal.detected_at.desc()).limit(limit).all()

    # Batch load brand names — one query
    brand_name_map = fetch_brand_name_map(db)

    result: List[SignalRow] = []
    for sig, em in rows:
        brand_name = get_brand_name(em, brand_name_map)
        result.append(SignalRow(
            entity_id=em.entity_id,
            signal_type=sig.signal_type,
            detected_at=_fmt_dt(sig.detected_at),
            strength=sig.strength or 0.0,
            confidence=sig.confidence,
            ticker=em.ticker,
            canonical_name=em.canonical_name,
            entity_type=em.entity_type,
            brand_name=brand_name,
            metadata_json=sig.metadata_json,
        ))

    return result
