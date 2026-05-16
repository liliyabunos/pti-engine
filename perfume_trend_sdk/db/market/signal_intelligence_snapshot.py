"""FTG-5 / SN1-A — Signal Intelligence Snapshots.

Provides:
  SignalIntelligenceSnapshot — SQLAlchemy ORM model
  SNAPSHOT_SCHEMA_VERSION    — current snapshot schema version constant
  write_signal_snapshot()    — idempotent first-capture write helper

Architecture role:
  This module sits in the Intelligence Snapshot Layer (FTG-5).
  It persists the intelligence state that existed at the moment a market signal
  was first detected, creating an immutable historical record that future
  Deep Dive Reports and trend analyses can query.

Snapshot semantics — first-capture immutable (Option A):
  ON CONFLICT (entity_id, entity_type, signal_type, detected_at) DO NOTHING.
  The first pipeline run that detects a signal for a given (entity, type, date)
  captures the market metrics that existed at that moment and stores them forever.
  Subsequent reruns for the same date leave existing snapshots untouched.

  Rationale: The pipeline deletes and recreates signal rows on reruns (idempotent
  signal refresh), but the snapshot survives this. This decouples the historical
  intelligence record from signal table churn, which is the product intent:
  "Preserve the detection-time intelligence state as a historical record."

Fields captured at detection time (from EntityTimeSeriesDaily):
  market_score_at_detection   — composite_market_score (the headline metric)
  growth_rate_at_detection    — growth_rate vs previous snapshot
  momentum_at_detection       — momentum (rolling rate of change)
  acceleration_at_detection   — acceleration (momentum delta)
  mention_count_at_detection  — mention_count (raw activity volume)

Entity fields denormalized at capture time:
  entity_canonical_name — from entity_market.canonical_name
  entity_brand_name     — from entity_market.brand_name (nullable)

These are denormalized so the snapshot remains self-contained even if the
entity_market row is later renamed or reorganized.

No FK to signals table — signals are deleted and recreated on pipeline reruns,
making a FK constraint fragile. The composite (entity_id, entity_type,
signal_type, detected_at) is the stable natural key shared with signals.

No FK to entity_market — resilience against entity deletion.

SN1-B (follow-up): Add narrative / explanation text field once an explanation
layer exists in the pipeline. Currently no such field is generated.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from perfume_trend_sdk.db.market.base import Base


# ---------------------------------------------------------------------------
# Schema version constant
# Bump when snapshot schema or field semantics change.
# Allows future queries to filter/cite by schema version.
# ---------------------------------------------------------------------------
SNAPSHOT_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------

class SignalIntelligenceSnapshot(Base):
    """Immutable first-capture record of market intelligence at signal detection time.

    One row per (entity, signal_type, detected_at). Written when a signal is first
    generated; subsequent pipeline reruns for the same date leave this row untouched
    (ON CONFLICT DO NOTHING semantics in write_signal_snapshot).

    market_score_at_detection   — composite_market_score from entity_timeseries_daily
    growth_rate_at_detection    — growth_rate at detection (can be None for new_entry)
    momentum_at_detection       — momentum at detection (can be None)
    acceleration_at_detection   — acceleration at detection (can be None)
    mention_count_at_detection  — raw mention volume that day
    signal_strength             — strength from the signal (detector composite score)
    signal_metadata             — sanitized metadata_json from the signal dict
    signal_threshold_version    — version of the detection threshold set (DATA0)
    snapshot_schema_version     — version of this snapshot schema
    first_captured_at           — when the snapshot was first written (UTC)
    """

    __tablename__ = "signal_intelligence_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "entity_type",
            "signal_type",
            "detected_at",
            name="uq_sig_snapshot_entity_signal_detected",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # --- Entity identity ---
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Denormalized at capture time — self-contained for historical queries
    entity_canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_brand_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Signal identity ---
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    pipeline_run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # --- Market metrics at detection time (from EntityTimeSeriesDaily) ---
    market_score_at_detection: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    growth_rate_at_detection: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    momentum_at_detection: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    acceleration_at_detection: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    mention_count_at_detection: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # --- Signal data ---
    signal_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    signal_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # --- Versioning ---
    signal_threshold_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=SNAPSHOT_SCHEMA_VERSION
    )

    # --- Timestamps ---
    first_captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


# ---------------------------------------------------------------------------
# Write helper
# ---------------------------------------------------------------------------

def _safe_decimal(value: Any) -> Optional[Decimal]:
    """Convert a float/int to Decimal, returning None for None/NaN/inf."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return Decimal(str(round(f, 4)))
    except (TypeError, ValueError):
        return None


def write_signal_snapshot(
    db: Session,
    sig: Dict[str, Any],
    snap: Dict[str, Any],
    entity_type: str,
    entity_canonical_name: str,
    entity_brand_name: Optional[str],
    signal_threshold_version: int = 1,
) -> bool:
    """Write a first-capture immutable snapshot for a detected signal.

    Idempotent: ON CONFLICT (entity_id, entity_type, signal_type, detected_at)
    DO NOTHING — existing snapshots are never overwritten.

    Args:
        db:                     SQLAlchemy Session.
        sig:                    Signal dict from detector (entity_id, signal_type,
                                detected_at, strength, metadata).
        snap:                   EntityTimeSeriesDaily dict for the entity on the
                                same date. Pass {} if not available (metrics will
                                be NULL, which is acceptable).
        entity_type:            Entity type string (e.g. 'perfume', 'brand').
        entity_canonical_name:  Canonical name from entity_market (denormalized).
        entity_brand_name:      Brand name from entity_market (nullable).
        signal_threshold_version: DATA0 version constant from the calling job.

    Returns:
        True if snapshot was newly written; False if it already existed.
    """
    entity_id = sig["entity_id"]
    detected_at = sig["detected_at"]

    # Non-fatal resilience: skip rather than crash if data is missing
    if not entity_id or not detected_at or not entity_canonical_name:
        return False

    try:
        existing = db.execute(
            sa.text(
                "SELECT id FROM signal_intelligence_snapshots "
                "WHERE entity_id = :eid AND entity_type = :etype "
                "  AND signal_type = :stype AND detected_at = :dat LIMIT 1"
            ),
            {
                "eid": str(entity_id),
                "etype": entity_type,
                "stype": sig["signal_type"],
                "dat": detected_at,
            },
        ).fetchone()

        if existing:
            return False

        pipeline_run_date = (
            detected_at.date() if isinstance(detected_at, datetime) else detected_at
        )

        row = SignalIntelligenceSnapshot(
            entity_id=entity_id,
            entity_type=entity_type,
            entity_canonical_name=entity_canonical_name,
            entity_brand_name=entity_brand_name,
            signal_type=sig["signal_type"],
            detected_at=detected_at,
            pipeline_run_date=pipeline_run_date,
            market_score_at_detection=_safe_decimal(snap.get("composite_market_score")),
            growth_rate_at_detection=_safe_decimal(snap.get("growth_rate")),
            momentum_at_detection=_safe_decimal(snap.get("momentum")),
            acceleration_at_detection=_safe_decimal(snap.get("acceleration")),
            mention_count_at_detection=_safe_decimal(snap.get("mention_count")),
            signal_strength=float(sig.get("strength", 0.0)),
            signal_metadata=sig.get("metadata"),
            signal_threshold_version=signal_threshold_version,
            snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
            first_captured_at=datetime.now(timezone.utc),
        )
        db.add(row)
        return True

    except Exception:
        # Non-fatal: snapshot failure must never block signal generation
        return False
