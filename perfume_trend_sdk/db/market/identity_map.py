from __future__ import annotations

"""
Identity mapping models — bridge between resolver/catalog layer and market engine.

Tables:
  brand_identity_map    — resolver Integer brand id  ↔  market UUID brand id
  perfume_identity_map  — resolver Integer perfume id ↔  market UUID perfume id

Both tables use Integer autoincrement PKs (cross-DB compatible) and store
the market UUID as a String(36) so they work on SQLite and PostgreSQL without
requiring the postgresql.UUID dialect type.

These tables live in the market engine database. They are populated by the
sync job (scripts/sync_identity_map.py) and queried by the bridge utility
(perfume_trend_sdk.bridge.identity_resolver).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from perfume_trend_sdk.db.market.base import Base


class BrandIdentityMap(Base):
    """One-to-one mapping between resolver brand Integer id and market UUID.

    resolver_brand_id  — brands.id from the resolver/catalog DB (Integer PK)
    market_brand_uuid  — brands.id from the market engine DB (UUID stored as str)
    canonical_name     — the canonical brand name at time of mapping (for audit)
    slug               — the slug used to match (stable key)
    """

    __tablename__ = "brand_identity_map"
    __table_args__ = (
        UniqueConstraint("resolver_brand_id", name="uq_bim_resolver_id"),
        UniqueConstraint("market_brand_uuid", name="uq_bim_market_uuid"),
        Index("ix_bim_market_uuid", "market_brand_uuid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resolver_brand_id: Mapped[int] = mapped_column(Integer, nullable=False)
    market_brand_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )


class PerfumeIdentityMap(Base):
    """Mapping between resolver perfume Integer id and market UUID.

    Cardinality: many-to-one is intentional. The legacy resolver catalog
    stores concentration variants (EDP, EDT, Extrait) as separate integer
    records. The market engine strips concentrations and treats all variants
    as a single entity (one UUID). Multiple resolver_perfume_ids therefore
    map to the same market_perfume_uuid.

    resolver_perfume_id — perfumes.id from the resolver/catalog DB (Integer PK)
    market_perfume_uuid — perfumes.id from the market engine DB (UUID stored as str)
    canonical_name      — full canonical name at time of mapping (for audit)
    slug                — the slug used to match (stable key)
    """

    __tablename__ = "perfume_identity_map"
    __table_args__ = (
        # Each resolver id maps to exactly one market UUID (one-to-one from resolver side).
        # Multiple resolver ids can share a market UUID (concentration variants collapse).
        UniqueConstraint("resolver_perfume_id", name="uq_pim_resolver_id"),
        Index("ix_pim_market_uuid", "market_perfume_uuid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resolver_perfume_id: Mapped[int] = mapped_column(Integer, nullable=False)
    market_perfume_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )
