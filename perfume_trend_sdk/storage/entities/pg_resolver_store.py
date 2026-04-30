from __future__ import annotations

"""
Postgres-backed resolver store.

Mirrors the interface of FragranceMasterStore but writes to the
resolver_* tables created by Alembic migration 014.

Hot read path: get_perfume_by_alias() uses an in-memory alias cache loaded
at __init__ time.  Loading all ~13k aliases in one bulk SELECT (~0.5s) and
doing dict lookups avoids the O(N²) network round-trips that would otherwise
be required — one query per token window per content item — which degrades
to minutes over remote Postgres connections.

All writes are idempotent (ON CONFLICT DO NOTHING / DO UPDATE).
Schema is owned by Alembic — init_schema() is a no-op here.
"""

import logging
import os
from typing import Dict, Iterable, Optional

from sqlalchemy import text

from perfume_trend_sdk.storage.entities.fragrance_master_store import (
    AliasRecord,
    BrandRecord,
    PerfumeRecord,
)
from perfume_trend_sdk.storage.postgres.db import get_engine

_log = logging.getLogger(__name__)

# Minimum alias count required to trust the Postgres resolver in production.
# If resolver_aliases has fewer rows, the store is considered "empty" —
# migration has not run yet, so production should fail fast rather than
# silently resolving nothing.
_MIN_ALIAS_ROWS_PRODUCTION = 5_000

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

    Alias resolution is in-memory: all resolver_aliases rows are loaded
    once at construction time into self._alias_cache (dict keyed by
    normalized_alias_text).  get_perfume_by_alias() is then an O(1)
    dict lookup — no per-call DB roundtrip.
    """

    def __init__(self) -> None:
        self._engine = get_engine()
        self._alias_cache: Dict[str, dict] = {}
        self._load_alias_cache()

    def _load_alias_cache(self) -> None:
        """Bulk-load all perfume aliases into memory.

        One query at startup replaces per-call DB lookups in resolve_text().
        With ~13k aliases this takes ~0.5s and uses ~3MB RAM.
        """
        sql = text(
            """
            SELECT a.normalized_alias_text, p.id, p.canonical_name
            FROM   resolver_aliases  a
            JOIN   resolver_perfumes p
              ON   a.entity_type = 'perfume'
             AND   a.entity_id   = p.id
            """
        )
        cache: Dict[str, dict] = {}
        with self._engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        for row in rows:
            norm_alias = str(row[0])
            if norm_alias not in cache:  # keep first hit (lowest entity_id wins)
                cache[norm_alias] = {
                    "perfume_id": int(row[1]),
                    "canonical_name": str(row[2]),
                    "confidence": 1.0,
                    "match_type": "exact",
                }
        self._alias_cache = cache
        _log.info("[resolver] alias cache loaded: %d entries", len(cache))

    # ------------------------------------------------------------------
    # Schema — no-op: Alembic manages this
    # ------------------------------------------------------------------

    def init_schema(self) -> None:  # noqa: D401
        """No-op. Postgres schema is managed by Alembic migrations."""

    def check_has_data(self) -> None:
        """
        Fail-fast guard: raise RuntimeError if resolver_aliases is empty.

        Called by make_resolver() in production so that a missing migration
        causes an immediate, visible error instead of silent 'no matches'.

        Not called in dev/test environments.
        """
        count = len(self._alias_cache) if self._alias_cache else self.count_rows("aliases")
        if count < _MIN_ALIAS_ROWS_PRODUCTION:
            raise RuntimeError(
                f"Postgres resolver_aliases has only {count} rows "
                f"(minimum expected: {_MIN_ALIAS_ROWS_PRODUCTION}). "
                "Migration has not run yet. "
                "Run: python3 scripts/migrate_resolver_to_postgres.py"
            )

    # ------------------------------------------------------------------
    # Hot read path — O(1) in-memory dict lookup
    # ------------------------------------------------------------------

    def get_perfume_by_alias(self, normalized_alias: str) -> Optional[dict]:
        """Return resolver hit for normalized_alias or None (in-memory lookup)."""
        return self._alias_cache.get(normalized_alias)

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
