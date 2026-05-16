from __future__ import annotations

"""
Job: detect_breakout_signals

Reads the latest entity snapshots from entity_timeseries_daily, runs
BreakoutDetector, and writes detected signal events to signals via ORM.

Signal entity_id is the UUID from entity_timeseries_daily.entity_id
(which references entity_market.id).

Usage (standalone):
    python -m perfume_trend_sdk.jobs.detect_breakout_signals \
        --date 2026-04-10

Usage (programmatic):
    from perfume_trend_sdk.jobs.detect_breakout_signals import run
    summary = run(db=session, detected_at="2026-04-10")
"""

import argparse
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from perfume_trend_sdk.analysis.market_signals.detector import BreakoutDetector
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import Base, EntityMarket
from perfume_trend_sdk.db.market.signal import Signal
from perfume_trend_sdk.db.market.signal_intelligence_snapshot import write_signal_snapshot
from perfume_trend_sdk.db.market.session import _make_engine, get_database_url, make_session_factory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DATA0 — Signal threshold version
#
# Increment this constant when breakout detection thresholds change.
# Every signal row written by this job carries this version, making historical
# signals methodologically comparable and citable with footnotes in reports.
# Existing rows were backfilled to version 1 via migration 043 server_default.
# ---------------------------------------------------------------------------
SIGNAL_THRESHOLD_VERSION = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_latest_snapshots(db: Session, target_date: date) -> List[Dict[str, Any]]:
    """Return all snapshots for target_date as dicts (entity_id is UUID)."""
    rows = (
        db.query(EntityTimeSeriesDaily)
        .filter(EntityTimeSeriesDaily.date == target_date)
        .all()
    )
    return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows]


def _load_prev_snapshots(
    db: Session, entity_uuids: List[uuid.UUID], before_date: date
) -> Dict[uuid.UUID, Dict[str, Any]]:
    prev: Dict[uuid.UUID, Dict[str, Any]] = {}
    for uid in entity_uuids:
        row = (
            db.query(EntityTimeSeriesDaily)
            .filter(
                EntityTimeSeriesDaily.entity_id == uid,
                EntityTimeSeriesDaily.date < before_date,
            )
            .order_by(EntityTimeSeriesDaily.date.desc())
            .first()
        )
        if row:
            prev[uid] = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    return prev


def _get_entity_type(db: Session, entity_uuid: uuid.UUID) -> str:
    """Look up entity_type from entity_market. Falls back to 'perfume'."""
    em = db.query(EntityMarket).filter_by(id=entity_uuid).first()
    return em.entity_type if em else "perfume"


def _sanitize_metadata(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Replace non-finite floats (inf, -inf, nan) before JSON storage.

    PostgreSQL JSON rejects Python's float("inf") / float("nan").
    Cap infinite values at 9999.9; replace nan with None.
    """
    if not meta:
        return meta
    import math
    cleaned = {}
    for k, v in meta.items():
        if isinstance(v, float):
            if math.isinf(v):
                v = 9999.9 if v > 0 else -9999.9
            elif math.isnan(v):
                v = None
        cleaned[k] = v
    return cleaned


def _upsert_signal(db: Session, sig: Dict[str, Any], entity_type: str) -> bool:
    """Insert or update a signal. Returns True if new."""
    existing = (
        db.query(Signal)
        .filter_by(
            entity_id=sig["entity_id"],
            entity_type=entity_type,
            signal_type=sig["signal_type"],
            detected_at=sig["detected_at"],
        )
        .first()
    )
    metadata = _sanitize_metadata(sig.get("metadata"))
    if existing:
        existing.strength = sig.get("strength", 0.0)
        existing.metadata_json = metadata
        return False
    db.add(Signal(
        entity_id=sig["entity_id"],
        entity_type=entity_type,
        signal_type=sig["signal_type"],
        strength=sig.get("strength", 0.0),
        metadata_json=metadata,
        detected_at=sig["detected_at"],
        signal_threshold_version=SIGNAL_THRESHOLD_VERSION,  # DATA0
        created_at=datetime.now(timezone.utc),
    ))
    return True


# ---------------------------------------------------------------------------
# Main job function
# ---------------------------------------------------------------------------

def run(
    db: Session,
    detected_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Detect breakout signals for all entities on detected_at.

    Args:
        db:          Active SQLAlchemy session.
        detected_at: ISO date string. Defaults to today.

    Returns:
        Summary dict: {detected_at, signals_detected, new_signals, signal_types}.
    """
    if detected_at is None:
        detected_at = date.today().isoformat()

    target_date_obj = date.fromisoformat(detected_at)
    detected_at_dt = datetime.combine(target_date_obj, datetime.min.time()).replace(tzinfo=timezone.utc)

    logger.info("detect_breakout_signals_started date=%s", detected_at)

    # Wipe existing signals for this date so reruns are fully idempotent.
    # Threshold changes or re-aggregation should produce a clean signal set,
    # not accumulate stale signals from previous runs.
    deleted = db.query(Signal).filter(Signal.detected_at == detected_at_dt).delete()
    if deleted:
        logger.info("detect_breakout_signals_cleared_stale count=%d date=%s", deleted, detected_at)
    db.flush()

    current_snaps = _load_latest_snapshots(db, target_date_obj)
    entity_uuids = [s["entity_id"] for s in current_snaps]
    prev_snaps = _load_prev_snapshots(db, entity_uuids, before_date=target_date_obj)

    # Cache entity types to avoid N+1 on signal upsert
    entity_type_cache: Dict[uuid.UUID, str] = {}
    for snap in current_snaps:
        uid = snap["entity_id"]
        if uid not in entity_type_cache:
            entity_type_cache[uid] = snap.get("entity_type") or _get_entity_type(db, uid)

    # FTG-5 / SN1-A — Build caches for snapshot writing
    # snap_by_entity_id: entity UUID → EntityTimeSeriesDaily dict (metrics at detection time)
    snap_by_entity_id: Dict[uuid.UUID, Dict[str, Any]] = {
        s["entity_id"]: s for s in current_snaps
    }
    # entity_market_cache: entity UUID → (canonical_name, brand_name) for denormalization
    entity_market_cache: Dict[uuid.UUID, tuple] = {}
    if entity_uuids:
        em_rows = db.query(EntityMarket).filter(EntityMarket.id.in_(entity_uuids)).all()
        for em in em_rows:
            entity_market_cache[em.id] = (em.canonical_name, em.brand_name)

    detector = BreakoutDetector()
    signals = detector.detect_batch(
        snapshots=current_snaps,
        prev_snapshots=prev_snaps,
        detected_at=detected_at_dt,    # pass datetime object; detector stores as-is
    )

    # Patch detected_at to datetime in each signal dict (detector may return str)
    for sig in signals:
        if not isinstance(sig["detected_at"], datetime):
            sig["detected_at"] = detected_at_dt

    new_count = 0
    snapshots_written = 0
    for sig in signals:
        entity_type = entity_type_cache.get(sig["entity_id"], "perfume")
        if _upsert_signal(db, sig, entity_type):
            new_count += 1
        # FTG-5 / SN1-A — Write immutable first-capture intelligence snapshot.
        # Non-fatal: snapshot failure never blocks signal generation.
        em_info = entity_market_cache.get(sig["entity_id"], ("", None))
        wrote = write_signal_snapshot(
            db=db,
            sig=sig,
            snap=snap_by_entity_id.get(sig["entity_id"], {}),
            entity_type=entity_type,
            entity_canonical_name=em_info[0],
            entity_brand_name=em_info[1],
            signal_threshold_version=SIGNAL_THRESHOLD_VERSION,
        )
        if wrote:
            snapshots_written += 1

    db.flush()

    signal_types = list({s["signal_type"] for s in signals})
    logger.info(
        "detect_breakout_signals_completed date=%s total=%d new=%d snapshots_written=%d types=%s",
        detected_at, len(signals), new_count, snapshots_written, signal_types,
    )

    return {
        "detected_at": detected_at,
        "signals_detected": len(signals),
        "new_signals": new_count,
        "snapshots_written": snapshots_written,
        "signal_types": signal_types,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Detect breakout signals from daily snapshots.")
    p.add_argument("--date", default=None, help="ISO date YYYY-MM-DD (default: today)")
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    url = get_database_url()
    Session_ = make_session_factory(url)
    with Session_() as session:
        summary = run(session, detected_at=args.date)
        session.commit()
    print(summary)


if __name__ == "__main__":
    main()
