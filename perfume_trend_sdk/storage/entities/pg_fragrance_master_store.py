from __future__ import annotations

"""
PostgreSQL backend for the fragrance knowledge base (brands, perfumes, aliases,
fragrance_master).

Drop-in replacement for FragranceMasterStore when a Postgres resolver URL is
configured.  Shares the same dataclass records (BrandRecord, PerfumeRecord,
AliasRecord) defined in fragrance_master_store.py.

Uses SQLAlchemy core (text()) — consistent with the rest of the codebase.
Does NOT use psycopg2 directly.

IMPORTANT: This store writes the *resolver* schema (integer PKs).
           It must NOT be pointed at the market engine DATABASE_URL, which uses
           UUID PKs in a different brands/perfumes schema.
           Use a dedicated RESOLVER_DATABASE_URL for this store.
"""

import logging
from typing import Iterable

from sqlalchemy import create_engine, text

from perfume_trend_sdk.storage.entities.fragrance_master_store import (
    AliasRecord,
    BrandRecord,
    PerfumeRecord,
)

logger = logging.getLogger(__name__)


class PgFragranceMasterStore:
    """
    Postgres-backed entity store for the seed fragrance knowledge base.

    Interface is identical to FragranceMasterStore so load_fragrance_master
    can use either store transparently.

    Schema created by init_schema() uses SERIAL (integer) PKs — the same
    resolver schema as the SQLite store — NOT the UUID market engine schema.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._engine = create_engine(database_url, future=True)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create resolver tables in Postgres if they do not already exist."""
        statements = [
            """
            CREATE TABLE IF NOT EXISTS brands (
                id SERIAL PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS perfumes (
                id SERIAL PRIMARY KEY,
                brand_id INTEGER NULL REFERENCES brands(id),
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                default_concentration TEXT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS aliases (
                id SERIAL PRIMARY KEY,
                alias_text TEXT NOT NULL,
                normalized_alias_text TEXT NOT NULL,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('brand', 'perfume')),
                entity_id INTEGER NOT NULL,
                match_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(normalized_alias_text, entity_type, entity_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_pg_aliases_lookup
                ON aliases(normalized_alias_text, entity_type)
            """,
            """
            CREATE TABLE IF NOT EXISTS fragrance_master (
                fragrance_id TEXT PRIMARY KEY,
                brand_name TEXT NOT NULL,
                perfume_name TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                release_year INTEGER NULL,
                gender TEXT NULL,
                source TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                brand_id INTEGER NULL REFERENCES brands(id),
                perfume_id INTEGER NULL REFERENCES perfumes(id)
            )
            """,
        ]
        with self._engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        logger.info("[PgFragranceMasterStore] Schema initialized")

    # ------------------------------------------------------------------
    # Upsert helpers
    # ------------------------------------------------------------------

    def upsert_brand(self, brand: BrandRecord) -> int:
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO brands (canonical_name, normalized_name)
                    VALUES (:canonical_name, :normalized_name)
                    ON CONFLICT(normalized_name)
                    DO UPDATE SET canonical_name = EXCLUDED.canonical_name
                """),
                {"canonical_name": brand.canonical_name, "normalized_name": brand.normalized_name},
            )
            row = conn.execute(
                text("SELECT id FROM brands WHERE normalized_name = :nname"),
                {"nname": brand.normalized_name},
            ).fetchone()
        if row is None:
            raise RuntimeError(f"upsert_brand: failed for {brand.canonical_name!r}")
        return int(row[0])

    def upsert_perfume(self, perfume: PerfumeRecord) -> int:
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO perfumes (brand_id, canonical_name, normalized_name, default_concentration)
                    VALUES (:brand_id, :canonical_name, :normalized_name, :default_concentration)
                    ON CONFLICT(normalized_name)
                    DO UPDATE SET
                        brand_id               = EXCLUDED.brand_id,
                        canonical_name         = EXCLUDED.canonical_name,
                        default_concentration  = EXCLUDED.default_concentration
                """),
                {
                    "brand_id":              perfume.brand_id,
                    "canonical_name":        perfume.canonical_name,
                    "normalized_name":       perfume.normalized_name,
                    "default_concentration": perfume.default_concentration,
                },
            )
            row = conn.execute(
                text("SELECT id FROM perfumes WHERE normalized_name = :nname"),
                {"nname": perfume.normalized_name},
            ).fetchone()
        if row is None:
            raise RuntimeError(f"upsert_perfume: failed for {perfume.canonical_name!r}")
        return int(row[0])

    def upsert_aliases(self, aliases: Iterable[AliasRecord]) -> None:
        rows = [
            {
                "alias_text":            a.alias_text,
                "normalized_alias_text": a.normalized_alias_text,
                "entity_type":           a.entity_type,
                "entity_id":             a.entity_id,
                "match_type":            a.match_type,
                "confidence":            a.confidence,
            }
            for a in aliases
        ]
        if not rows:
            return
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO aliases (
                        alias_text, normalized_alias_text, entity_type,
                        entity_id, match_type, confidence
                    )
                    VALUES (
                        :alias_text, :normalized_alias_text, :entity_type,
                        :entity_id, :match_type, :confidence
                    )
                    ON CONFLICT(normalized_alias_text, entity_type, entity_id)
                    DO UPDATE SET
                        alias_text  = EXCLUDED.alias_text,
                        match_type  = EXCLUDED.match_type,
                        confidence  = EXCLUDED.confidence,
                        updated_at  = NOW()
                """),
                rows,
            )

    def upsert_fragrance_master_row(
        self,
        *,
        fragrance_id: str,
        brand_name: str,
        perfume_name: str,
        canonical_name: str,
        normalized_name: str,
        release_year: int | None,
        gender: str | None,
        source: str,
        brand_id: int | None,
        perfume_id: int | None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO fragrance_master (
                        fragrance_id, brand_name, perfume_name, canonical_name,
                        normalized_name, release_year, gender, source,
                        brand_id, perfume_id
                    )
                    VALUES (
                        :fragrance_id, :brand_name, :perfume_name, :canonical_name,
                        :normalized_name, :release_year, :gender, :source,
                        :brand_id, :perfume_id
                    )
                    ON CONFLICT(fragrance_id) DO UPDATE SET
                        brand_name      = EXCLUDED.brand_name,
                        perfume_name    = EXCLUDED.perfume_name,
                        canonical_name  = EXCLUDED.canonical_name,
                        normalized_name = EXCLUDED.normalized_name,
                        release_year    = EXCLUDED.release_year,
                        gender          = EXCLUDED.gender,
                        source          = EXCLUDED.source,
                        brand_id        = EXCLUDED.brand_id,
                        perfume_id      = EXCLUDED.perfume_id
                """),
                {
                    "fragrance_id":   fragrance_id,
                    "brand_name":     brand_name,
                    "perfume_name":   perfume_name,
                    "canonical_name": canonical_name,
                    "normalized_name": normalized_name,
                    "release_year":   release_year,
                    "gender":         gender,
                    "source":         source,
                    "brand_id":       brand_id,
                    "perfume_id":     perfume_id,
                },
            )

    # ------------------------------------------------------------------
    # Read helpers (mirror FragranceMasterStore interface)
    # ------------------------------------------------------------------

    def count_rows(self, table_name: str) -> int:
        allowed = {"brands", "perfumes", "aliases", "fragrance_master"}
        if table_name not in allowed:
            raise ValueError(f"Unsupported table: {table_name!r}")
        with self._engine.connect() as conn:
            row = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
        return int(row[0])

    def get_perfume_aliases(self, normalized_perfume_name: str) -> list[str]:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM perfumes WHERE normalized_name = :nname"),
                {"nname": normalized_perfume_name},
            ).fetchone()
            if row is None:
                return []
            perfume_id = int(row[0])
            rows = conn.execute(
                text("""
                    SELECT alias_text FROM aliases
                    WHERE entity_type = 'perfume' AND entity_id = :pid
                    ORDER BY alias_text
                """),
                {"pid": perfume_id},
            ).fetchall()
        return [str(r[0]) for r in rows]

    def get_perfume_by_alias(self, normalized_alias: str) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT p.id, p.canonical_name
                    FROM aliases a
                    JOIN perfumes p ON a.entity_type = 'perfume' AND a.entity_id = p.id
                    WHERE a.entity_type = 'perfume'
                      AND a.normalized_alias_text = :alias
                    LIMIT 1
                """),
                {"alias": normalized_alias},
            ).fetchone()
        if row is None:
            return None
        return {
            "perfume_id":     int(row[0]),
            "canonical_name": str(row[1]),
            "confidence":     1.0,
            "match_type":     "exact",
        }
