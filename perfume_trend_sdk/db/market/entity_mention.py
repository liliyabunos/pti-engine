from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Float, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


class EntityMention(Base):
    __tablename__ = "entity_mentions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    source_platform: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    author_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    author_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    mention_count: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    influence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    engagement: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    region: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    channel: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
