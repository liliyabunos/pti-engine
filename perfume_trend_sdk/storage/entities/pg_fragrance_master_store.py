from __future__ import annotations

"""
Postgres backend for the fragrance knowledge base (brands, perfumes, aliases,
fragrance_master).

Drop-in replacement for FragranceMasterStore when DATABASE_URL is set.
Shares the same dataclass records (BrandRecord, PerfumeRecord, AliasRecord)
defined in fragrance_master_store.py.
"""

from typing import Iterable

from perfume_trend_sdk.storage.entities.fragrance_master_store import (
    AliasRecord,
    BrandRecord,
    PerfumeRecord,
)


class PgFragranceMasterStore:
    """
    Postgres-backed entity store for the seed fragrance knowledge base.

    Interface is identical to FragranceMasterStore so load_fragrance_master
    can use either store transparently.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self.database_url)

    def init_schema(self) -> None:
        """Create tables and indexes if they do not already exist."""
        sql = """
        CREATE TABLE IF NOT EXISTS brands (
            id SERIAL PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS perfumes (
            id SERIAL PRIMARY KEY,
            brand_id INTEGER NULL REFERENCES brands(id),
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            default_concentration TEXT NULL
        );

        CREATE TABLE IF NOT EXISTS aliases (
            id SERIAL PRIMARY KEY,
            alias_text TEXT NOT NULL,
            normalized_alias_text TEXT NOT NULL,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('brand', 'perfume')),
            entity_id INTEGER NOT NULL,
            match_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(normalized_alias_text, entity_type, entity_id)
        );

        CREATE INDEX IF NOT EXISTS idx_aliases_lookup
            ON aliases(normalized_alias_text, entity_type);

        CREATE TABLE IF NOT EXISTS fragrance_master (
            fragrance_id TEXT PRIMARY KEY,
            brand_name TEXT NOT NULL,
            perfume_name TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            release_year INTEGER NULL,
            gender TEXT NULL,
            source TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            brand_id INTEGER NULL REFERENCES brands(id),
            perfume_id INTEGER NULL REFERENCES perfumes(id)
        );
        """
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
        finally:
            conn.close()

    def upsert_brand(self, brand: BrandRecord) -> int:
        sql = """
        INSERT INTO brands (canonical_name, normalized_name)
        VALUES (%s, %s)
        ON CONFLICT(normalized_name) DO UPDATE SET
            canonical_name = EXCLUDED.canonical_name
        RETURNING id
        """
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (brand.canonical_name, brand.normalized_name))
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError(f"Failed to upsert brand: {brand.canonical_name!r}")
                    return int(row[0])
        finally:
            conn.close()

    def upsert_perfume(self, perfume: PerfumeRecord) -> int:
        sql = """
        INSERT INTO perfumes (brand_id, canonical_name, normalized_name, default_concentration)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT(normalized_name) DO UPDATE SET
            brand_id              = EXCLUDED.brand_id,
            canonical_name        = EXCLUDED.canonical_name,
            default_concentration = EXCLUDED.default_concentration
        RETURNING id
        """
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql,
                        (
                            perfume.brand_id,
                            perfume.canonical_name,
                            perfume.normalized_name,
                            perfume.default_concentration,
                        ),
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError(f"Failed to upsert perfume: {perfume.canonical_name!r}")
                    return int(row[0])
        finally:
            conn.close()

    def upsert_aliases(self, aliases: Iterable[AliasRecord]) -> None:
        alias_rows = [
            (
                a.alias_text,
                a.normalized_alias_text,
                a.entity_type,
                a.entity_id,
                a.match_type,
                a.confidence,
            )
            for a in aliases
        ]
        if not alias_rows:
            return

        sql = """
        INSERT INTO aliases (
            alias_text,
            normalized_alias_text,
            entity_type,
            entity_id,
            match_type,
            confidence
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(normalized_alias_text, entity_type, entity_id)
        DO UPDATE SET
            alias_text  = EXCLUDED.alias_text,
            match_type  = EXCLUDED.match_type,
            confidence  = EXCLUDED.confidence,
            updated_at  = CURRENT_TIMESTAMP
        """
        import psycopg2.extras
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_batch(cur, sql, alias_rows, page_size=200)
        finally:
            conn.close()

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
        sql = """
        INSERT INTO fragrance_master (
            fragrance_id,
            brand_name,
            perfume_name,
            canonical_name,
            normalized_name,
            release_year,
            gender,
            source,
            brand_id,
            perfume_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(fragrance_id) DO UPDATE SET
            brand_name     = EXCLUDED.brand_name,
            perfume_name   = EXCLUDED.perfume_name,
            canonical_name = EXCLUDED.canonical_name,
            normalized_name = EXCLUDED.normalized_name,
            release_year   = EXCLUDED.release_year,
            gender         = EXCLUDED.gender,
            source         = EXCLUDED.source,
            brand_id       = EXCLUDED.brand_id,
            perfume_id     = EXCLUDED.perfume_id
        """
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql,
                        (
                            fragrance_id,
                            brand_name,
                            perfume_name,
                            canonical_name,
                            normalized_name,
                            release_year,
                            gender,
                            source,
                            brand_id,
                            perfume_id,
                        ),
                    )
        finally:
            conn.close()

    def count_rows(self, table_name: str) -> int:
        allowed = {"brands", "perfumes", "aliases", "fragrance_master"}
        if table_name not in allowed:
            raise ValueError(f"Unsupported table: {table_name}")
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                    row = cur.fetchone()
                    return int(row[0]) if row else 0
        finally:
            conn.close()

    def get_perfume_by_alias(self, normalized_alias: str) -> dict | None:
        sql = """
        SELECT p.id, p.canonical_name
        FROM aliases a
        JOIN perfumes p
          ON a.entity_type = 'perfume'
         AND a.entity_id = p.id
        WHERE a.entity_type = 'perfume'
          AND a.normalized_alias_text = %s
        LIMIT 1
        """
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (normalized_alias,))
                    row = cur.fetchone()
        finally:
            conn.close()

        if row is None:
            return None
        return {
            "perfume_id": int(row[0]),
            "canonical_name": str(row[1]),
            "confidence": 1.0,
            "match_type": "exact",
        }
