from __future__ import annotations

"""
Dashboard and Screener routes — Market Terminal API v1.

GET /api/v1/dashboard  — headline KPIs + top movers + signal feed preview
GET /api/v1/screener   — filterable, sortable, paginated entity screener

All data is precomputed by the aggregation job. These routes serve it directly.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from perfume_trend_sdk.analysis.ranking.variant_collapser import collapse_and_rank
from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.queries import (
    fetch_brand_name_map,
    fetch_dashboard_kpis,
    fetch_latest_rows,
    fetch_latest_signal_map,
    get_brand_name,
)
from perfume_trend_sdk.api.schemas.dashboard import (
    DashboardKPIs,
    DashboardResponse,
    ScreenerResponse,
    TopMoverRow,
)
from perfume_trend_sdk.api.schemas.entity import EntitySummary, SignalRow
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import EntityMarket
from perfume_trend_sdk.db.market.signal import Signal

router = APIRouter()

_VALID_SIGNAL_TYPES = {"new_entry", "breakout", "acceleration_spike", "reversal"}

_SORT_FIELDS = {
    "composite_market_score",
    "momentum",
    "growth_rate",
    "mention_count",
    "engagement_sum",
    "acceleration",
    "volatility",
    "confidence_avg",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_recent_signals(db: Session, days: int) -> List:
    """Return (Signal, EntityMarket) rows for the lookback window, newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(Signal, EntityMarket)
        .join(EntityMarket, Signal.entity_id == EntityMarket.id)
        .filter(Signal.detected_at >= cutoff)
        .order_by(Signal.detected_at.desc())
        .all()
    )


def _fmt_detected_at(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


# ---------------------------------------------------------------------------
# Dashboard — GET /api/v1/dashboard
# ---------------------------------------------------------------------------

@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    top_n: int = Query(20, ge=1, le=100),
    signal_days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db_session),
) -> DashboardResponse:
    # Batch loads — one query each, no N+1
    rows = fetch_latest_rows(db)
    signal_rows = _fetch_recent_signals(db, days=signal_days)
    brand_name_map = fetch_brand_name_map(db)
    latest_signal_map = fetch_latest_signal_map(db)

    # Headline KPIs (computed from raw rows before collapsing — preserves full entity counts)
    kpis_dict = fetch_dashboard_kpis(db, rows, signal_rows, brand_name_map=brand_name_map)
    kpis = DashboardKPIs(**kpis_dict)

    # Collapse concentration variants + apply flood dampening, then sort by effective_rank_score
    collapsed_rows = collapse_and_rank(
        rows,
        latest_signal_map=latest_signal_map,
        brand_name_map=brand_name_map,
    )

    # Top movers — built from collapsed/dampened rows, already sorted by effective_rank_score
    top_movers: List[TopMoverRow] = []
    breakout_entity_ids = {
        em.entity_id
        for sig, em in signal_rows
        if sig.signal_type == "breakout"
    }

    for rank, cr in enumerate(collapsed_rows[:top_n], start=1):
        top_movers.append(TopMoverRow(
            rank=rank,
            entity_id=cr.entity_id,
            entity_type=cr.entity_type,
            ticker=cr.ticker,
            canonical_name=cr.canonical_name,
            name=cr.canonical_name,
            brand_name=cr.brand_name,
            composite_market_score=cr.composite_market_score,
            effective_rank_score=cr.effective_rank_score,
            mention_count=cr.mention_count,
            unique_authors=cr.unique_authors,
            is_flood_dampened=cr.is_flood_dampened,
            growth_rate=cr.growth_rate,
            confidence_avg=cr.confidence_avg,
            momentum=cr.momentum,
            acceleration=cr.acceleration,
            volatility=cr.volatility,
            latest_signal=cr.latest_signal,
            latest_signal_strength=cr.latest_signal_strength,
            variant_names=cr.variant_names,
        ))

    breakouts = [m for m in top_movers if m.entity_id in breakout_entity_ids]

    # Signal feed preview — latest 20
    recent_signals: List[SignalRow] = []
    for sig, em in signal_rows[:20]:
        brand_name = get_brand_name(em, brand_name_map)
        recent_signals.append(SignalRow(
            entity_id=em.entity_id,
            signal_type=sig.signal_type,
            detected_at=_fmt_detected_at(sig.detected_at),
            strength=sig.strength or 0.0,
            confidence=sig.confidence,
            ticker=em.ticker,
            canonical_name=em.canonical_name,
            entity_type=em.entity_type,
            brand_name=brand_name,
            metadata_json=sig.metadata_json,
        ))

    return DashboardResponse(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        total_entities=len(rows),
        kpis=kpis,
        top_movers=top_movers,
        recent_signals=recent_signals,
        breakouts=breakouts,
    )


# ---------------------------------------------------------------------------
# Screener — GET /api/v1/screener
# ---------------------------------------------------------------------------

@router.get("/screener", response_model=ScreenerResponse)
def get_screener(
    # Filters
    entity_type: Optional[str] = Query(None, description="perfume | brand"),
    min_score: float = Query(0.0, description="Minimum composite_market_score"),
    min_confidence: float = Query(0.0, description="Minimum confidence_avg"),
    min_mentions: float = Query(0.0, description="Minimum mention_count"),
    signal_type: Optional[str] = Query(None, description="Filter to entities with this signal type"),
    has_signals: Optional[bool] = Query(None, description="true = only entities with any signal"),
    # Sorting
    sort_by: str = Query("composite_market_score", description=f"One of: {', '.join(sorted(_SORT_FIELDS))}"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    # Pagination
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> ScreenerResponse:
    rows = fetch_latest_rows(db)
    brand_name_map = fetch_brand_name_map(db)
    latest_signal_map = fetch_latest_signal_map(db)

    if sort_by not in _SORT_FIELDS:
        sort_by = "composite_market_score"

    # Build set of entity UUIDs that have signals (for has_signals / signal_type filters)
    entity_uuids_with_signal: Optional[set] = None
    if has_signals is True or signal_type is not None:
        q = db.query(Signal.entity_id)
        if signal_type and signal_type in _VALID_SIGNAL_TYPES:
            q = q.filter(Signal.signal_type == signal_type)
        entity_uuids_with_signal = {r[0] for r in q.distinct().all()}

    summaries: List[EntitySummary] = []
    for em, snap in rows:
        score = snap.composite_market_score if snap else 0.0
        mentions = snap.mention_count if snap else 0.0
        confidence = snap.confidence_avg if snap else 0.0

        # Apply filters
        if entity_type and em.entity_type != entity_type:
            continue
        if (score or 0.0) < min_score:
            continue
        if (confidence or 0.0) < min_confidence:
            continue
        if (mentions or 0.0) < min_mentions:
            continue
        if entity_uuids_with_signal is not None and em.id not in entity_uuids_with_signal:
            continue

        sig_info = latest_signal_map.get(em.id)
        brand_name = get_brand_name(em, brand_name_map)

        summaries.append(EntitySummary(
            entity_id=em.entity_id,
            entity_type=em.entity_type,
            ticker=em.ticker,
            canonical_name=em.canonical_name,
            brand_name=brand_name,
            date=snap.date.isoformat() if snap and snap.date else None,
            mention_count=snap.mention_count if snap else None,
            engagement_sum=snap.engagement_sum if snap else None,
            composite_market_score=snap.composite_market_score if snap else None,
            confidence_avg=snap.confidence_avg if snap else None,
            momentum=snap.momentum if snap else None,
            acceleration=snap.acceleration if snap else None,
            volatility=snap.volatility if snap else None,
            growth_rate=snap.growth_rate if snap else None,
            latest_signal_type=sig_info[0] if sig_info else None,
            latest_signal_strength=sig_info[1] if sig_info else None,
        ))

    # Sort
    reverse = order == "desc"
    summaries.sort(key=lambda s: getattr(s, sort_by) or 0.0, reverse=reverse)

    total = len(summaries)
    page = summaries[offset: offset + limit]

    return ScreenerResponse(
        total=total,
        limit=limit,
        offset=offset,
        rows=page,
    )
