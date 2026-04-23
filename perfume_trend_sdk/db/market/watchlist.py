from __future__ import annotations

"""
Watchlist and WatchlistItem ORM models.

V1 owner strategy:
  There is no auth layer yet. All watchlists and items share a single dev
  owner identified by `owner_key = "dev"`. When auth is introduced, replace
  `owner_key` with a proper user FK and filter by the authenticated user.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base

DEV_OWNER_KEY = "dev"


class Watchlist(Base):
    """Named collection of tracked entities owned by a single user (or 'dev')."""

    __tablename__ = "watchlists"

    # id stored as varchar(36) UUID string — matches migration 004 column type
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_key: Mapped[str] = mapped_column(
        String(128), nullable=False, default=DEV_OWNER_KEY, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WatchlistItem(Base):
    """A single entity pinned to a watchlist."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "entity_id", "entity_type", name="uq_watchlist_entity"),
    )

    # id and watchlist_id stored as varchar(36) UUID strings — matches migration 004 column type
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    watchlist_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("watchlists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # entity_id is the canonical string id (EntityMarket.entity_id), not the UUID
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
