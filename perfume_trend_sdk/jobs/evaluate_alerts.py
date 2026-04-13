#!/usr/bin/env python3
"""
Alert Evaluation Job — PTI Market Terminal v1

Evaluates all active alerts against the latest entity market data.
Respects cooldown windows to keep the system low-noise.

Usage:
    python -m perfume_trend_sdk.jobs.evaluate_alerts

Exit codes:
    0 — success (any number of alerts, including zero triggered)
    1 — fatal error

Cooldown rule (from CLAUDE.md §19):
    If the condition is true but the alert fired within cooldown_hours,
    do not create a "triggered" event. Optionally records a "suppressed"
    event for diagnostics.

Condition types (V1):
    breakout_detected    — signal of type "breakout" in the last 24 h
    acceleration_detected — signal of type "acceleration_spike" in last 24 h
    any_new_signal        — any signal in the last 24 h
    score_above           — latest composite_market_score > threshold_value
    growth_above          — latest growth_rate > threshold_value
    confidence_below      — latest confidence_avg < threshold_value
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from perfume_trend_sdk.db.market.alert import Alert, AlertEvent
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily
from perfume_trend_sdk.db.market.models import EntityMarket
from perfume_trend_sdk.db.market.session import get_session_factory
from perfume_trend_sdk.db.market.signal import Signal
from sqlalchemy import func

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# How far back to look for signals when evaluating signal-based conditions
SIGNAL_WINDOW_HOURS = 24


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _get_latest_snapshot(
    db: Session, entity_market_uuid: uuid.UUID
) -> Optional[EntityTimeSeriesDaily]:
    """Return the most recent snapshot row for an entity UUID."""
    return (
        db.query(EntityTimeSeriesDaily)
        .filter_by(entity_id=entity_market_uuid)
        .order_by(EntityTimeSeriesDaily.date.desc())
        .first()
    )


def _get_recent_signals(
    db: Session,
    entity_market_uuid: uuid.UUID,
    hours: int = SIGNAL_WINDOW_HOURS,
) -> list[Signal]:
    """Return signals detected within the last `hours` hours for an entity."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    return (
        db.query(Signal)
        .filter(
            Signal.entity_id == entity_market_uuid,
            Signal.detected_at >= cutoff,
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Condition evaluators
# ---------------------------------------------------------------------------

def _evaluate_condition(
    alert: Alert,
    snap: Optional[EntityTimeSeriesDaily],
    recent_signals: list[Signal],
) -> tuple[bool, dict]:
    """Return (condition_met, reason_dict).

    reason_dict is stored in alert_events.reason_json for diagnostics.
    """
    ct = alert.condition_type
    threshold = alert.threshold_value

    if ct == "breakout_detected":
        matched = [s for s in recent_signals if s.signal_type == "breakout"]
        met = len(matched) > 0
        reason = {
            "condition": ct,
            "matched_signals": len(matched),
            "window_hours": SIGNAL_WINDOW_HOURS,
        }

    elif ct == "acceleration_detected":
        matched = [s for s in recent_signals if s.signal_type == "acceleration_spike"]
        met = len(matched) > 0
        reason = {
            "condition": ct,
            "matched_signals": len(matched),
            "window_hours": SIGNAL_WINDOW_HOURS,
        }

    elif ct == "any_new_signal":
        met = len(recent_signals) > 0
        reason = {
            "condition": ct,
            "total_recent_signals": len(recent_signals),
            "window_hours": SIGNAL_WINDOW_HOURS,
        }

    elif ct == "score_above":
        value = snap.composite_market_score if snap else None
        met = value is not None and value > threshold
        reason = {
            "condition": ct,
            "current_value": value,
            "threshold": threshold,
        }

    elif ct == "growth_above":
        value = snap.growth_rate if snap else None
        met = value is not None and value > threshold
        reason = {
            "condition": ct,
            "current_value": value,
            "threshold": threshold,
        }

    elif ct == "confidence_below":
        value = snap.confidence_avg if snap else None
        met = value is not None and value < threshold
        reason = {
            "condition": ct,
            "current_value": value,
            "threshold": threshold,
        }

    else:
        log.warning("Unknown condition_type '%s' for alert %s — skipping.", ct, alert.id)
        met = False
        reason = {"condition": ct, "error": "unknown_condition_type"}

    return met, reason


def _is_in_cooldown(alert: Alert) -> bool:
    """Return True if the alert fired within its cooldown window."""
    if alert.last_triggered_at is None:
        return False
    last = alert.last_triggered_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    cooldown_end = last + timedelta(hours=alert.cooldown_hours)
    return datetime.now(tz=timezone.utc) < cooldown_end


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def evaluate_alerts(db: Session, record_suppressed: bool = True) -> dict:
    """Evaluate all active alerts and create AlertEvents as needed.

    Args:
        db: live SQLAlchemy session
        record_suppressed: if True, write a "suppressed" event when condition
            is true but inside cooldown (useful for diagnostics).

    Returns:
        dict with counts: evaluated, triggered, suppressed, skipped_no_data
    """
    now = datetime.now(tz=timezone.utc)

    active_alerts = db.query(Alert).filter_by(is_active=True).all()
    log.info("Active alerts to evaluate: %d", len(active_alerts))

    # Batch-load EntityMarket rows for all alert entity_ids
    entity_ids = list({a.entity_id for a in active_alerts})
    em_rows = db.query(EntityMarket).filter(EntityMarket.entity_id.in_(entity_ids)).all()
    em_map: dict[str, EntityMarket] = {em.entity_id: em for em in em_rows}

    counts = {"evaluated": 0, "triggered": 0, "suppressed": 0, "skipped_no_data": 0}

    for alert in active_alerts:
        counts["evaluated"] += 1
        em = em_map.get(alert.entity_id)

        if em is None:
            log.warning(
                "Alert %s references unknown entity '%s' — skipping.",
                alert.id, alert.entity_id,
            )
            counts["skipped_no_data"] += 1
            continue

        snap = _get_latest_snapshot(db, em.id)
        recent_signals = _get_recent_signals(db, em.id)

        condition_met, reason = _evaluate_condition(alert, snap, recent_signals)

        if not condition_met:
            continue

        in_cooldown = _is_in_cooldown(alert)

        if in_cooldown:
            # Condition true but cooldown active — optionally record suppressed
            if record_suppressed:
                ev = AlertEvent(
                    id=uuid.uuid4(),
                    alert_id=alert.id,
                    entity_id=alert.entity_id,
                    entity_type=alert.entity_type,
                    triggered_at=now,
                    status="suppressed",
                    reason_json=json.dumps({**reason, "suppressed_reason": "in_cooldown"}),
                )
                db.add(ev)
            counts["suppressed"] += 1
            log.info(
                "Alert %s [%s] SUPPRESSED (cooldown active, last=%s, window=%dh).",
                alert.id, alert.condition_type,
                alert.last_triggered_at, alert.cooldown_hours,
            )
        else:
            # Real trigger
            ev = AlertEvent(
                id=uuid.uuid4(),
                alert_id=alert.id,
                entity_id=alert.entity_id,
                entity_type=alert.entity_type,
                triggered_at=now,
                status="triggered",
                reason_json=json.dumps(reason),
            )
            db.add(ev)
            alert.last_triggered_at = now
            counts["triggered"] += 1
            log.info(
                "Alert %s [%s] TRIGGERED for entity '%s'. Reason: %s",
                alert.id, alert.condition_type, alert.entity_id, reason,
            )

    db.flush()
    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== PTI Alert Evaluation Job starting ===")
    factory = get_session_factory()
    session: Session = factory()

    # Ensure watchlist/alert tables exist (safe no-op if already created)
    from perfume_trend_sdk.db.market.models import Base
    from perfume_trend_sdk.db.market.session import _make_engine, get_database_url
    engine = _make_engine(get_database_url())
    Base.metadata.create_all(engine)

    try:
        counts = evaluate_alerts(session)
        session.commit()
        log.info(
            "=== Evaluation complete — evaluated=%d triggered=%d suppressed=%d skipped=%d ===",
            counts["evaluated"],
            counts["triggered"],
            counts["suppressed"],
            counts["skipped_no_data"],
        )
    except Exception as exc:
        session.rollback()
        log.exception("Fatal error during alert evaluation: %s", exc)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
