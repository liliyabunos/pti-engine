from __future__ import annotations

"""
Shared batch-query helpers for Market Terminal API routes.

All functions accept a live SQLAlchemy session and return Python dicts
that can be used as lookup tables by route handlers — no N+1 patterns.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import EntityMarket
from perfume_trend_sdk.db.market.signal import Signal


# ---------------------------------------------------------------------------
# Ranged snapshot dataclass (multi-day aggregation drop-in)
# ---------------------------------------------------------------------------

@dataclass
class RangedSnapshot:
    """Synthetic snapshot for multi-day aggregated rows.

    Mirrors EntityTimeSeriesDaily field names so collapse_and_rank() —
    which uses only attribute access — accepts it as a drop-in.
    """
    date: Optional[date] = None
    mention_count: float = 0.0
    unique_authors: int = 0
    engagement_sum: float = 0.0
    composite_market_score: float = 0.0
    weighted_signal_score: Optional[float] = None
    growth_rate: Optional[float] = None
    momentum: Optional[float] = None
    acceleration: Optional[float] = None
    volatility: Optional[float] = None
    confidence_avg: Optional[float] = None
    trend_state: Optional[str] = None


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

    # Determine the most-recent date with real market activity (mention_count > 0).
    # Carry-forward rows (mention_count=0) advance the global max date without
    # any real signal activity, causing KPI cards to show 0 signals for a quiet
    # carry-forward day while Recent Signals and Movers show prior-day activity.
    # Using the latest active date keeps KPIs consistent with the rest of the dashboard.
    active_dates = [
        snap.date
        for _, snap in rows
        if snap is not None and (snap.mention_count or 0) > 0
    ]
    _global_latest: Optional[date] = max(
        (snap.date for _, snap in rows if snap is not None), default=None
    )
    latest_date: Optional[date] = max(active_dates) if active_dates else _global_latest

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


# ---------------------------------------------------------------------------
# Date-range helpers
# ---------------------------------------------------------------------------

_VALID_PRESETS = frozenset({
    "today", "yesterday", "7d", "30d", "mtd", "ytd",
})


def get_latest_active_date(db: Session) -> Optional[date]:
    """Return the most-recent date that has at least one row with mention_count > 0.

    Used as the anchor for "today" so the dashboard always reflects the latest
    completed market day, not wall-clock CURRENT_DATE (which may have no data yet).
    """
    result = db.query(func.max(EntityTimeSeriesDaily.date)).filter(
        EntityTimeSeriesDaily.mention_count > 0
    ).scalar()
    return result


def resolve_date_range(
    preset: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    latest_active: Optional[date],
) -> Tuple[date, date, str, str]:
    """Resolve a preset or explicit range to (start_date, end_date, label, preset_key).

    Returns:
        start_date (inclusive)
        end_date   (inclusive)
        label      — human-readable label for UI header e.g. "Last 7 days"
        preset_key — normalised preset name ("today", "yesterday", "7d", …)
    """
    anchor: date = latest_active or date.today()

    if preset and preset.lower() in _VALID_PRESETS:
        p = preset.lower()
    elif start_date and end_date:
        p = "custom"
    else:
        p = "today"

    if p == "today":
        return anchor, anchor, "Today", "today"

    if p == "yesterday":
        d = anchor - timedelta(days=1)
        return d, d, "Yesterday", "yesterday"

    if p == "7d":
        return anchor - timedelta(days=6), anchor, "Last 7 days", "7d"

    if p == "30d":
        return anchor - timedelta(days=29), anchor, "Last 30 days", "30d"

    if p == "mtd":
        first = anchor.replace(day=1)
        return first, anchor, f"Month to date", "mtd"

    if p == "ytd":
        first = anchor.replace(month=1, day=1)
        return first, anchor, "Year to date", "ytd"

    # custom explicit range
    if start_date and end_date:
        label = f"{start_date.strftime('%b %-d')} – {end_date.strftime('%b %-d')}"
        return start_date, end_date, label, "custom"

    # fallback
    return anchor, anchor, "Today", "today"


def _fetch_rows_for_single_date(
    db: Session,
    target_date: date,
) -> List[Tuple]:
    """Return (EntityMarket, EntityTimeSeriesDaily|None) pairs for one specific date.

    For the Today / Yesterday presets — exact-date join semantics.
    """
    sub = (
        db.query(
            EntityTimeSeriesDaily.entity_id,
            EntityTimeSeriesDaily.date,
        )
        .filter(EntityTimeSeriesDaily.date == target_date)
        .subquery()
    )
    return (
        db.query(EntityMarket, EntityTimeSeriesDaily)
        .outerjoin(sub, EntityMarket.id == sub.c.entity_id)
        .outerjoin(
            EntityTimeSeriesDaily,
            (EntityTimeSeriesDaily.entity_id == sub.c.entity_id)
            & (EntityTimeSeriesDaily.date == sub.c.date),
        )
        .order_by(EntityTimeSeriesDaily.composite_market_score.desc())
        .all()
    )


def _fetch_rows_aggregated(
    db: Session,
    start: date,
    end: date,
) -> List[Tuple]:
    """Return (EntityMarket, RangedSnapshot|None) pairs aggregated over [start, end].

    SUM mention_count / engagement_sum / unique_authors.
    Latest-snapshot scalars (score, trend_state, …) taken from the most-recent
    date with real activity within the range (DISTINCT ON pattern).

    Falls back gracefully to empty list if executed against SQLite (no DISTINCT ON).
    """
    try:
        sql = text("""
            WITH agg AS (
                SELECT entity_id,
                       SUM(mention_count)                         AS mention_count,
                       SUM(COALESCE(unique_authors, 0))           AS unique_authors,
                       SUM(COALESCE(engagement_sum, 0.0))         AS engagement_sum,
                       AVG(confidence_avg)                        AS confidence_avg,
                       MAX(date)                                  AS max_date
                FROM entity_timeseries_daily
                WHERE date BETWEEN :start_date AND :end_date
                  AND mention_count > 0
                GROUP BY entity_id
                HAVING SUM(mention_count) > 0
            ),
            latest AS (
                SELECT DISTINCT ON (t.entity_id)
                       t.entity_id,
                       t.composite_market_score,
                       t.weighted_signal_score,
                       t.growth_rate,
                       t.momentum,
                       t.acceleration,
                       t.volatility,
                       t.trend_state
                FROM entity_timeseries_daily t
                INNER JOIN agg ON agg.entity_id = t.entity_id
                              AND agg.max_date   = t.date
                ORDER BY t.entity_id, t.date DESC
            )
            SELECT
                agg.entity_id,
                agg.mention_count,
                agg.unique_authors,
                agg.engagement_sum,
                agg.confidence_avg,
                agg.max_date,
                latest.composite_market_score,
                latest.weighted_signal_score,
                latest.growth_rate,
                latest.momentum,
                latest.acceleration,
                latest.volatility,
                latest.trend_state
            FROM agg
            LEFT JOIN latest ON latest.entity_id = agg.entity_id
        """)
        agg_rows = db.execute(sql, {"start_date": start, "end_date": end}).fetchall()
    except Exception:
        return []

    # Build lookup: entity_uuid → RangedSnapshot
    snap_map: Dict[uuid.UUID, RangedSnapshot] = {}
    for row in agg_rows:
        (eid, mention_count, unique_authors, engagement_sum,
         confidence_avg, max_date,
         composite_market_score, weighted_signal_score,
         growth_rate, momentum, acceleration, volatility, trend_state) = row
        snap_map[eid] = RangedSnapshot(
            date=max_date,
            mention_count=float(mention_count or 0),
            unique_authors=int(unique_authors or 0),
            engagement_sum=float(engagement_sum or 0),
            composite_market_score=float(composite_market_score or 0),
            weighted_signal_score=float(weighted_signal_score) if weighted_signal_score is not None else None,
            growth_rate=float(growth_rate) if growth_rate is not None else None,
            momentum=float(momentum) if momentum is not None else None,
            acceleration=float(acceleration) if acceleration is not None else None,
            volatility=float(volatility) if volatility is not None else None,
            confidence_avg=float(confidence_avg) if confidence_avg is not None else None,
            trend_state=trend_state,
        )

    # Join with EntityMarket rows
    entity_uuids = list(snap_map.keys())
    if not entity_uuids:
        return []

    em_rows = (
        db.query(EntityMarket)
        .filter(EntityMarket.id.in_(entity_uuids))
        .all()
    )
    result = [(em, snap_map.get(em.id)) for em in em_rows]
    # Also include EntityMarket rows that have no range activity (entity exists, no data in range)
    # We skip those — unlike fetch_latest_rows which includes all entities,
    # range queries only return entities active in the range.
    result.sort(key=lambda x: (x[1].composite_market_score if x[1] else 0), reverse=True)
    return result


def fetch_rows_for_range(
    db: Session,
    start: date,
    end: date,
    is_single_day: bool = False,
) -> List[Tuple]:
    """Unified rows fetch: single-date for today/yesterday, aggregated for multi-day.

    Returns (EntityMarket, EntityTimeSeriesDaily|RangedSnapshot|None) pairs.
    """
    if is_single_day or start == end:
        return _fetch_rows_for_single_date(db, end)
    return _fetch_rows_aggregated(db, start, end)


def fetch_dashboard_kpis_ranged(
    db: Session,
    rows: List,
    signal_rows: List,
    start: date,
    end: date,
    brand_name_map: Optional[Dict[str, str]] = None,
) -> dict:
    """Compute headline KPIs over a date range.

    Same shape as fetch_dashboard_kpis() — compatible with DashboardKPIs schema.
    Signal counts are counted across the entire range (not just latest date).
    avg_score / avg_confidence use the range-aggregated snapshots.
    """
    brand_name_map = brand_name_map or {}

    # as_of_date = the latest date with real activity in the provided rows
    active_dates = [
        snap.date
        for _, snap in rows
        if snap is not None and (snap.mention_count or 0) > 0
    ]
    latest_date: Optional[date] = max(active_dates) if active_dates else None

    tracked_perfumes = sum(1 for em, _ in rows if em.entity_type == "perfume")

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

    active_movers = sum(
        1 for _, snap in rows
        if snap is not None and (snap.composite_market_score or 0.0) > 0
    )

    # Count signals across the full range
    breakout_count = 0
    acceleration_count = 0
    total_count = 0
    for sig, _ in signal_rows:
        sig_date = (
            sig.detected_at.date()
            if isinstance(sig.detected_at, datetime)
            else sig.detected_at
        )
        if start <= sig_date <= end:
            total_count += 1
            if sig.signal_type == "breakout":
                breakout_count += 1
            elif sig.signal_type == "acceleration_spike":
                acceleration_count += 1

    snaps_with_score = [
        snap for _, snap in rows
        if snap is not None and snap.composite_market_score is not None
        and (snap.composite_market_score or 0) > 0
    ]
    scores = [s.composite_market_score for s in snaps_with_score]
    confs = [
        s.confidence_avg for s in snaps_with_score
        if s.confidence_avg is not None
    ]

    avg_score = round(sum(scores) / len(scores), 4) if scores else None
    avg_conf = round(sum(confs) / len(confs), 4) if confs else None

    return {
        "tracked_brands": tracked_brands,
        "tracked_perfumes": tracked_perfumes,
        "active_movers": active_movers,
        "breakout_signals_today": breakout_count,
        "acceleration_signals_today": acceleration_count,
        "total_signals_today": total_count,
        "avg_market_score_today": avg_score,
        "avg_confidence_today": avg_conf,
        "as_of_date": latest_date.isoformat() if latest_date else None,
    }
