from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


class SourceProfile(Base):
    """Channel / author profile data — one row per (platform, source_id)."""

    __tablename__ = "source_profiles"
    __table_args__ = (
        UniqueConstraint("platform", "source_id", name="uq_source_profiles_platform_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # YouTube: subscriberCount; Reddit: None
    subscribers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Rolling average from seen videos/posts
    avg_views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_videos: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class MentionSource(Base):
    """Raw engagement data for each entity mention — one row per entity_mention."""

    __tablename__ = "mention_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # FK to entity_mentions.id (no ORM relationship — keep coupling loose)
    mention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # (likes + comments) / views — None when views == 0
    engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Placeholder for future weighting (I2)
    source_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
