"""Phase I5 — Topic/Query Intelligence ORM models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


class ContentTopic(Base):
    """One extracted topic per (content_item, topic_type, topic_text).

    topic_type values:
      'query'     — YouTube search query that discovered the video
      'subreddit' — Reddit subreddit (r/fragrance, r/Colognes, …)
      'topic'     — deterministic regex match on title/text (e.g. "compliment getter")
    """
    __tablename__ = "content_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_item_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source_platform: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    topic_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    topic_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EntityTopicLink(Base):
    """Links an entity_market entity to a ContentTopic via content discovery.

    Denormalises topic_text and topic_type for efficient per-entity aggregation
    without a JOIN back to content_topics every query.
    """
    __tablename__ = "entity_topic_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_topic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("content_topics.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised for query speed
    topic_text: Mapped[str] = mapped_column(Text, nullable=False)
    topic_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Source quality score from mention_sources (Phase I2)
    source_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
