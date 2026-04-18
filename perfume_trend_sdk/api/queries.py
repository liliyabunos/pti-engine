from __future__ import annotations

"""
Shared batch-query helpers for Market Terminal API routes.

All functions accept a live SQLAlchemy session and return Python dicts
that can be used as lookup tables by route handlers — no N+1 patterns.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import EntityMarket
from perfume_trend_sdk.db.market.signal import Signal


# ---------------------------------------------------------------------------
# Slug utility (mirrors logic in seed/sync scripts)
# ---------------------------------------------------------------------------

def _slugify(value: str) -> str:
    s = re.sub(r"[^\w\s-]", "", value.lower().strip())
    return re.sub(r"[\s_]+", "-", s).strip("-")


# ---------------------------------------------------------------------------
# Brand name lookup
# ---------------------------------------------------------------------------

def fetch_brand_name_map(db: Session) -> Dict[str, str]:
    """Return {slugified_perfume_name: brand_name} for all perfumes in the market catalog.

    Uses a raw SQL query against the v2 UUID schema (migration 003+).
    v2 brands/perfumes use 'name' — not 'canonical_name' (that was the v1 schema, dropped in 003).
    """
    try:
        rows = db.execute(
            text(
                "SELECT p.name, b.name "
                "FROM perfumes p JOIN brands b ON p.brand_id = b.id "
                "WHERE p.name IS NOT NULL AND b.name IS NOT NULL"
            )
        ).fetchall()
    except Exception:
        # If the perfumes/brands tables don't exist or have a different shape,
        # rollback to clear any aborted transaction state, then return empty map.
        try:
            db.rollback()
        except Exception:
            pass
        return {}
    return {_slugify(perfume_name): brand_name for perfume_name, brand_name in rows}


def get_brand_name(
    entity: EntityMarket,
    brand_name_map: Dict[str, str],
) -> Optional[str]:
    """Resolve brand_name for a single entity row.

    Priority:
    1. entity_market.brand_name — denormalized at aggregation time (fast path).
    2. brand_name_map slug lookup — fallback for rows written before the column existed.
    3. For brand entities: canonical_name IS the brand name.
    """
    if entity.entity_type == "brand":
        return entity.canonical_name
    if entity.brand_name:
        return entity.brand_name
    slug = _slugify(entity.entity_id)
    return brand_name_map.get(slug)


# ---------------------------------------------------------------------------
# Latest signal per entity
# ---------------------------------------------------------------------------

def fetch_latest_signal_map(
    db: Session,
) -> Dict[uuid.UUID, Tuple[str, Optional[float]]]:
    """Return {entity_uuid: (signal_type, strength)} for the most-recent signal
    per entity.  Only entities that have at least one signal appear in the map.
    Returns {} on any query failure so callers always get a safe value.
    """
    import logging
    try:
        sub = (
            db.query(
                Signal.entity_id,
                func.max(Signal.detected_at).label("max_dt"),
            )
            .group_by(Signal.entity_id)
            .subquery()
        )
        rows = (
            db.query(Signal)
            .join(
                sub,
                (Signal.entity_id == sub.c.entity_id)
                & (Signal.detected_at == sub.c.max_dt),
            )
            .all()
        )
    except Exception as exc:
        logging.getLogger(__name__).error(
            "[PTI] fetch_latest_signal_map failed: %s", exc
        )
        try:
            db.rollback()
        except Exception:
            pass
        return {}
    # If two signals share the exact same detected_at timestamp, keep highest strength.
    result: Dict[uuid.UUID, Tuple[str, Optional[float]]] = {}
    for r in rows:
        existing = result.get(r.entity_id)
        if existing is None or (r.strength or 0.0) > (existing[1] or 0.0):
            result[r.entity_id] = (r.signal_type, r.strength)
    return result


# ---------------------------------------------------------------------------
# Latest snapshot subquery (reusable)
# ---------------------------------------------------------------------------

def latest_snapshot_subquery(db: Session):
    """SQLAlchemy subquery: most-recent snapshot date per entity UUID."""
    return (
        db.query(
            EntityTimeSeriesDaily.entity_id,
            func.max(EntityTimeSeriesDaily.date).label("max_date"),
        )
        .group_by(EntityTimeSeriesDaily.entity_id)
        .subquery()
    )


def fetch_latest_rows(db: Session):
    """Return (EntityMarket, EntityTimeSeriesDaily|None) pairs, latest snapshot each."""
    sub = latest_snapshot_subquery(db)
    return (
        db.query(EntityMarket, EntityTimeSeriesDaily)
        .outerjoin(sub, EntityMarket.id == sub.c.entity_id)
        .outerjoin(
            EntityTimeSeriesDaily,
            (EntityTimeSeriesDaily.entity_id == sub.c.entity_id)
            & (EntityTimeSeriesDaily.date == sub.c.max_date),
        )
        .order_by(EntityTimeSeriesDaily.composite_market_score.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# KPI helpers
# ---------------------------------------------------------------------------

def fetch_dashboard_kpis(
    db: Session,
    rows,
    signal_rows,
    brand_name_map: Optional[Dict[str, str]] = None,
) -> dict:
    """Compute headline KPIs from already-loaded data — no extra DB round-trips.

    Args:
        rows:           output of fetch_latest_rows()
        signal_rows:    list of (Signal, EntityMarket) tuples (recent window)
        brand_name_map: output of fetch_brand_name_map() — used to count distinct
                        brands that have at least one active entity in entity_market.
                        When omitted, falls back to counting entity_type='brand' rows.
    """
    brand_name_map = brand_name_map or {}

    # Determine the most-recent date present in the loaded snapshots
    dates = [snap.date for _, snap in rows if snap is not None]
    latest_date: Optional[date] = max(dates) if dates else None

    # tracked_perfumes: entity_market rows with entity_type='perfume'
    tracked_perfumes = sum(1 for em, _ in rows if em.entity_type == "perfume")

    # tracked_brands: distinct brands that have at least one active entity in entity_market.
    # This counts brands visible in the market engine regardless of whether they have
    # their own entity_market row (most brands are represented through their perfumes).
    active_brand_names: set = set()
    for em, snap in rows:
        if snap is None:
            continue
        if em.entity_type == "brand":
            active_brand_names.add(em.canonical_name)
        else:
            bn = get_brand_name(em, brand_name_map)
            if bn:
                active_brand_names.add(bn)
    tracked_brands = len(active_brand_names)

    # Active movers = entities with at least one snapshot and score > 0
    active_movers = sum(
        1 for _, snap in rows
        if snap is not None and (snap.composite_market_score or 0.0) > 0
    )

    # Signal counts for the most-recent date
    breakout_today = 0
    acceleration_today = 0
    total_today = 0
    if latest_date:
        for sig, _ in signal_rows:
            sig_date = (
                sig.detected_at.date()
                if isinstance(sig.detected_at, datetime)
                else sig.detected_at
            )
            if sig_date == latest_date:
                total_today += 1
                if sig.signal_type == "breakout":
                    breakout_today += 1
                elif sig.signal_type == "acceleration_spike":
                    acceleration_today += 1

    # Average score + confidence from most-recent snapshots only
    if latest_date:
        latest_snaps = [
            snap for _, snap in rows
            if snap is not None and snap.date == latest_date
        ]
    else:
        latest_snaps = [snap for _, snap in rows if snap is not None]

    scores = [s.composite_market_score for s in latest_snaps if s.composite_market_score is not None]
    confs = [s.confidence_avg for s in latest_snaps if s.confidence_avg is not None]

    avg_score = round(sum(scores) / len(scores), 4) if scores else None
    avg_conf = round(sum(confs) / len(confs), 4) if confs else None

    return {
        "tracked_brands": tracked_brands,
        "tracked_perfumes": tracked_perfumes,
        "active_movers": active_movers,
        "breakout_signals_today": breakout_today,
        "acceleration_signals_today": acceleration_today,
        "total_signals_today": total_today,
        "avg_market_score_today": avg_score,
        "avg_confidence_today": avg_conf,
        "as_of_date": latest_date.isoformat() if latest_date else None,
    }
