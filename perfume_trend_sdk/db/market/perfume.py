from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from perfume_trend_sdk.db.market.base import Base


class Perfume(Base):
    __tablename__ = "perfumes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    launch_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gender_position: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    olfactive_family: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    price_band: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    concentration: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    brand = relationship("Brand", backref="perfumes", lazy="joined")
