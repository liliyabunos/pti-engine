from __future__ import annotations

"""
Postgres-backed resolver store.

Mirrors the interface of FragranceMasterStore but writes to the
resolver_* tables created by Alembic migration 014.

Hot read path: get_perfume_by_alias() hits ix_resolver_aliases_lookup
(normalized_alias_text, entity_type) which is the covering index for
the most frequent query pattern in PerfumeResolver.resolve_text().

All writes are idempotent (ON CONFLICT DO NOTHING / DO UPDATE).
Schema is owned by Alembic — init_schema() is a no-op here.
"""

import logging
from typing import Iterable

from sqlalchemy import text

from perfume_trend_sdk.storage.entities.fragrance_master_store import (
    AliasRecord,
    BrandRecord,
    PerfumeRecord,
)
from perfume_trend_sdk.storage.postgres.db import get_engine

_log = logging.getLogger(__name__)

_ALLOWED_TABLES = {
    "brands": "resolver_brands",
    "perfumes": "resolver_perfumes",
    "aliases": "resolver_aliases",
    "fragrance_master": "resolver_fragrance_master",
}

_BATCH = 500


class PgResolverStore:
    """
    Postgres resolver store backed by resolver_* tables.

    Implements the same public interface as FragranceMasterStore so
    PerfumeResolver can swap stores without any logic changes.
    """

    def __init__(self) -> None:
        self._engine = get_engine()

    # ------------------------------------------------------------------
    # Schema — no-op: Alembic manages this
    # ------------------------------------------------------------------

    def init_schema(self) -> None:  # noqa: D401
        """No-op. Postgres schema is managed by Alembic migrations."""

    # ------------------------------------------------------------------
    # Hot read path — called for every token window in resolve_text()
    # ------------------------------------------------------------------

    def get_perfume_by_alias(self, normalized_alias: str) -> dict | None:
        """Return resolver hit for normalized_alias or None."""
        sql = text(
            """
            SELECT p.id, p.canonical_name
            FROM   resolver_aliases  a
            JOIN   resolver_perfumes p
              ON   a.entity_type = 'perfume'
             AND   a.entity_id   = p.id
            WHERE  a.normalized_alias_text = :alias
            LIMIT  1
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"alias": normalized_alias}).fetchone()

        if row is None:
            return None

        return {
            "perfume_id": int(row[0]),
            "canonical_name": str(row[1]),
            "confidence": 1.0,
            "match_type": "exact",
        }

    # ------------------------------------------------------------------
    # Writes — used by migration script, not by live ingest
    # ------------------------------------------------------------------

    def upsert_brand(self, brand: BrandRecord) -> int:
        sql_upsert = text(
            """
            INSERT INTO resolver_brands (canonical_name, normalized_name)
            VALUES (:canonical, :normalized)
            ON CONFLICT (normalized_name) DO UPDATE
                SET canonical_name = EXCLUDED.canonical_name
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            row = conn.execute(
                sql_upsert,
                {"canonical": brand.canonical_name, "normalized": brand.normalized_name},
            ).fetchone()
        return int(row[0])

    def upsert_perfume(self, perfume: PerfumeRecord) -> int:
        sql_upsert = text(
            """
            INSERT INTO resolver_perfumes
                (brand_id, canonical_name, normalized_name, default_concentration)
            VALUES (:brand_id, :canonical, :normalized, :concentration)
            ON CONFLICT (normalized_name) DO UPDATE
                SET brand_id              = EXCLUDED.brand_id,
                    canonical_name        = EXCLUDED.canonical_name,
                    default_concentration = EXCLUDED.default_concentration
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            row = conn.execute(
                sql_upsert,
                {
                    "brand_id": perfume.brand_id,
                    "canonical": perfume.canonical_name,
                    "normalized": perfume.normalized_name,
                    "concentration": perfume.default_concentration,
                },
            ).fetchone()
        return int(row[0])

    def upsert_aliases(self, aliases: Iterable[AliasRecord]) -> None:
        sql = text(
            """
            INSERT INTO resolver_aliases
                (alias_text, normalized_alias_text, entity_type, entity_id,
                 match_type, confidence)
            VALUES
                (:alias_text, :normalized_alias_text, :entity_type, :entity_id,
                 :match_type, :confidence)
            ON CONFLICT (normalized_alias_text, entity_type, entity_id)
            DO UPDATE SET
                alias_text  = EXCLUDED.alias_text,
                match_type  = EXCLUDED.match_type,
                confidence  = EXCLUDED.confidence
            """
        )
        rows = [
            {
                "alias_text": a.alias_text,
                "normalized_alias_text": a.normalized_alias_text,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "match_type": a.match_type,
                "confidence": a.confidence,
            }
            for a in aliases
        ]
        if not rows:
            return
        with self._engine.begin() as conn:
            for i in range(0, len(rows), _BATCH):
                conn.execute(sql, rows[i : i + _BATCH])

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
        sql = text(
            """
            INSERT INTO resolver_fragrance_master
                (fragrance_id, brand_name, perfume_name, canonical_name,
                 normalized_name, release_year, gender, source, brand_id, perfume_id)
            VALUES
                (:fragrance_id, :brand_name, :perfume_name, :canonical_name,
                 :normalized_name, :release_year, :gender, :source,
                 :brand_id, :perfume_id)
            ON CONFLICT (fragrance_id) DO UPDATE SET
                brand_name      = EXCLUDED.brand_name,
                perfume_name    = EXCLUDED.perfume_name,
                canonical_name  = EXCLUDED.canonical_name,
                normalized_name = EXCLUDED.normalized_name,
                release_year    = EXCLUDED.release_year,
                gender          = EXCLUDED.gender,
                source          = EXCLUDED.source,
                brand_id        = EXCLUDED.brand_id,
                perfume_id      = EXCLUDED.perfume_id
            """
        )
        with self._engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "fragrance_id": fragrance_id,
                    "brand_name": brand_name,
                    "perfume_name": perfume_name,
                    "canonical_name": canonical_name,
                    "normalized_name": normalized_name,
                    "release_year": release_year,
                    "gender": gender,
                    "source": source,
                    "brand_id": brand_id,
                    "perfume_id": perfume_id,
                },
            )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def count_rows(self, table_name: str) -> int:
        pg_table = _ALLOWED_TABLES.get(table_name)
        if pg_table is None:
            raise ValueError(
                f"Unsupported table: {table_name!r}. "
                f"Allowed: {list(_ALLOWED_TABLES)}"
            )
        sql = text(f"SELECT COUNT(*) FROM {pg_table}")  # noqa: S608 — table name is allowlisted
        with self._engine.connect() as conn:
            row = conn.execute(sql).fetchone()
        return int(row[0])
