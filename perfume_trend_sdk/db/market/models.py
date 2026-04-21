from __future__ import annotations

"""
Market Engine model registry — re-export hub.

All models live in their own files; this module re-exports them so that
existing imports (`from perfume_trend_sdk.db.market.models import ...`)
continue to work unchanged.

New code should import directly from the per-model files.
"""

import uuid
from datetime import datetime
from typing import Optional  # noqa: F401 — used by Mapped annotations

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.alert import Alert, AlertEvent  # noqa: F401
from perfume_trend_sdk.db.market.base import Base  # noqa: F401
from perfume_trend_sdk.db.market.brand import Brand  # noqa: F401
from perfume_trend_sdk.db.market.entity_mention import EntityMention  # noqa: F401
from perfume_trend_sdk.db.market.entity_timeseries_daily import EntityTimeSeriesDaily  # noqa: F401
from perfume_trend_sdk.db.market.notes_intelligence import (  # noqa: F401
    AccordStats,
    NoteCanonical,
    NoteCanonicalMap,
    NoteBrandStats,
    NoteStats,
)
from perfume_trend_sdk.db.market.perfume import Perfume  # noqa: F401
from perfume_trend_sdk.db.market.fragrance_candidates import FragranceCandidate  # noqa: F401
from perfume_trend_sdk.db.market.signal import Signal  # noqa: F401
from perfume_trend_sdk.db.market.watchlist import Watchlist, WatchlistItem  # noqa: F401


class EntityMarket(Base):
    """Master list of tracked market entities (perfumes, brands, notes).

    id         — UUID primary key, referenced by entity_timeseries_daily,
                 entity_mentions, and signals as their entity_id FK.
    entity_id  — stable human-readable string (canonical name), used by
                 API routes and URL paths.
    brand_name — denormalized brand name for fast display (populated from
                 the perfumes→brands catalog at aggregation time).
    """

    __tablename__ = "entity_market"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


__all__ = [
    "AccordStats",
    "Alert",
    "AlertEvent",
    "Base",
    "Brand",
    "EntityMarket",
    "EntityMention",
    "EntityTimeSeriesDaily",
    "FragranceCandidate",
    "NoteCanonical",
    "NoteCanonicalMap",
    "NoteBrandStats",
    "NoteStats",
    "Perfume",
    "Signal",
    "Watchlist",
    "WatchlistItem",
]
