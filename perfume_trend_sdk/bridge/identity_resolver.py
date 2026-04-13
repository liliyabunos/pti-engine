from __future__ import annotations

"""
Step 6C — Identity resolver: translate between resolver IDs and market UUIDs.

This module provides a single importable utility for any pipeline code that
needs to cross the resolver ↔ market engine boundary.

Usage:
    from perfume_trend_sdk.bridge.identity_resolver import IdentityResolver

    resolver = IdentityResolver("outputs/market_dev.db")

    # resolver integer id → market UUID string
    uuid_str = resolver.brand_uuid(legacy_brand_id=42)
    uuid_str = resolver.perfume_uuid(legacy_perfume_id=7)

    # market UUID → resolver integer id (reverse lookup)
    legacy_id = resolver.resolver_brand_id(market_brand_uuid="abc123...")
    legacy_id = resolver.resolver_perfume_id(market_perfume_uuid="abc123...")

    # Batch lookups (returns only the successfully mapped entries)
    uuid_map = resolver.brand_uuids_for([1, 2, 3, 42])
    uuid_map = resolver.perfume_uuids_for([10, 20, 99])

Architecture contract
---------------------
The mapping tables (`brand_identity_map`, `perfume_identity_map`) live in
the market engine database. They are the single source of truth for cross-
system identity translation. See docs/architecture/identity_contract.md.
"""

from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from perfume_trend_sdk.db.market.base import Base
from perfume_trend_sdk.db.market.identity_map import BrandIdentityMap, PerfumeIdentityMap


class IdentityResolver:
    """Translates between resolver catalog IDs and market engine UUIDs.

    Backed by brand_identity_map and perfume_identity_map in the market DB.
    All lookups are O(1) point queries against indexed columns.

    Args:
        market_db: Path to market engine SQLite file, or any SQLAlchemy URL.
    """

    def __init__(self, market_db: str) -> None:
        url = market_db if "://" in market_db else f"sqlite:///{market_db}"
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self._engine = create_engine(url, connect_args=connect_args)
        self._Session = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)

    def ensure_tables(self) -> None:
        """Create mapping tables if they don't exist yet."""
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # Forward lookups: resolver id → market UUID
    # ------------------------------------------------------------------

    def brand_uuid(self, legacy_brand_id: int) -> Optional[str]:
        """Return market UUID string for a resolver brand integer id, or None."""
        with self._Session() as session:
            row = session.query(BrandIdentityMap).filter_by(
                resolver_brand_id=legacy_brand_id
            ).first()
            return row.market_brand_uuid if row else None

    def perfume_uuid(self, legacy_perfume_id: int) -> Optional[str]:
        """Return market UUID string for a resolver perfume integer id, or None."""
        with self._Session() as session:
            row = session.query(PerfumeIdentityMap).filter_by(
                resolver_perfume_id=legacy_perfume_id
            ).first()
            return row.market_perfume_uuid if row else None

    # ------------------------------------------------------------------
    # Reverse lookups: market UUID → resolver id
    # ------------------------------------------------------------------

    def resolver_brand_id(self, market_brand_uuid: str) -> Optional[int]:
        """Return resolver integer brand id for a market UUID string, or None."""
        with self._Session() as session:
            row = session.query(BrandIdentityMap).filter_by(
                market_brand_uuid=str(market_brand_uuid)
            ).first()
            return row.resolver_brand_id if row else None

    def resolver_perfume_id(self, market_perfume_uuid: str) -> Optional[int]:
        """Return resolver integer perfume id for a market UUID string, or None."""
        with self._Session() as session:
            row = session.query(PerfumeIdentityMap).filter_by(
                market_perfume_uuid=str(market_perfume_uuid)
            ).first()
            return row.resolver_perfume_id if row else None

    # ------------------------------------------------------------------
    # Batch lookups (efficiency for pipeline jobs)
    # ------------------------------------------------------------------

    def brand_uuids_for(self, legacy_brand_ids: list[int]) -> dict[int, str]:
        """Return {resolver_id: market_uuid} for every matched id in the list."""
        if not legacy_brand_ids:
            return {}
        with self._Session() as session:
            rows = (
                session.query(BrandIdentityMap)
                .filter(BrandIdentityMap.resolver_brand_id.in_(legacy_brand_ids))
                .all()
            )
            return {r.resolver_brand_id: r.market_brand_uuid for r in rows}

    def perfume_uuids_for(self, legacy_perfume_ids: list[int]) -> dict[int, str]:
        """Return {resolver_id: market_uuid} for every matched id in the list."""
        if not legacy_perfume_ids:
            return {}
        with self._Session() as session:
            rows = (
                session.query(PerfumeIdentityMap)
                .filter(PerfumeIdentityMap.resolver_perfume_id.in_(legacy_perfume_ids))
                .all()
            )
            return {r.resolver_perfume_id: r.market_perfume_uuid for r in rows}

    # ------------------------------------------------------------------
    # Coverage stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return row counts for both mapping tables."""
        with self._Session() as session:
            brand_count   = session.query(BrandIdentityMap).count()
            perfume_count = session.query(PerfumeIdentityMap).count()
        return {
            "brand_mappings":   brand_count,
            "perfume_mappings": perfume_count,
        }
