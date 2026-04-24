from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


class EntityTimeSeriesDaily(Base):
    __tablename__ = "entity_timeseries_daily"
    __table_args__ = (
        UniqueConstraint("entity_id", "entity_type", "date", name="uq_entity_timeseries_daily"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    mention_count: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unique_authors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engagement_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    sentiment_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    search_index: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retailer_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    growth_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    composite_market_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    momentum: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    acceleration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volatility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Phase I2 — source-quality-weighted score (non-destructive, raw score preserved above)
    # Formula: MIN(100, composite_market_score × (1.0 + avg_source_quality))
    # avg_source_quality = AVG(mention_sources.source_score) for entity's mentions on this date
    # NULL when no mentions have been written yet for this date (e.g. carry-forward rows)
    weighted_signal_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
