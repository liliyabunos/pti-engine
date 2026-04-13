from __future__ import annotations

"""
Alert and AlertEvent ORM models.

V1 owner strategy:
  Same as watchlists — single dev owner via `owner_key = "dev"` until
  auth is introduced.

Allowed condition types (V1):
  breakout_detected    — signal of type "breakout" exists in last evaluation window
  acceleration_detected — signal of type "acceleration_spike" in last window
  any_new_signal        — any signal exists in last window
  score_above           — composite_market_score > threshold_value
  growth_above          — growth_rate > threshold_value
  confidence_below      — confidence_avg < threshold_value
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base

DEV_OWNER_KEY = "dev"

VALID_CONDITION_TYPES = frozenset({
    "breakout_detected",
    "acceleration_detected",
    "any_new_signal",
    "score_above",
    "growth_above",
    "confidence_below",
})

# Condition types that require a numeric threshold_value
THRESHOLD_REQUIRED = frozenset({
    "score_above",
    "growth_above",
    "confidence_below",
})


class Alert(Base):
    """Entity-based monitoring alert with cooldown support."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_key: Mapped[str] = mapped_column(
        String(128), nullable=False, default=DEV_OWNER_KEY, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # entity_id is the canonical string id (EntityMarket.entity_id)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)

    condition_type: Mapped[str] = mapped_column(String(64), nullable=False)
    threshold_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    cooldown_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delivery_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="in_app"
    )

    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AlertEvent(Base):
    """Audit record created each time an alert condition is evaluated and triggers."""

    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    # "triggered" | "suppressed" (suppressed = condition true but inside cooldown)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="triggered")
    reason_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
