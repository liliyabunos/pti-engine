from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import sqlite3


@dataclass
class BrandRecord:
    canonical_name: str
    normalized_name: str


@dataclass
class PerfumeRecord:
    brand_id: int | None
    canonical_name: str
    normalized_name: str
    default_concentration: str | None = None


@dataclass
class AliasRecord:
    alias_text: str
    normalized_alias_text: str
    entity_type: str  # "brand" | "perfume"
    entity_id: int
    match_type: str   # "manual" | "exact" | "fuzzy" | "ai_confirmed"
    confidence: float


class FragranceMasterStore:
    """
    SQLite-backed entity store for the seed fragrance knowledge base.

    This store is intentionally narrow for Phase 1:
    - creates required tables if they do not exist
    - upserts brands, perfumes, and aliases
    - provides simple lookup helpers for loader/tests
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS brands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS perfumes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand_id INTEGER NULL,
                    canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    default_concentration TEXT NULL,
                    FOREIGN KEY (brand_id) REFERENCES brands(id)
                );

                CREATE TABLE IF NOT EXISTS aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias_text TEXT NOT NULL,
                    normalized_alias_text TEXT NOT NULL,
                    entity_type TEXT NOT NULL CHECK(entity_type IN ('brand', 'perfume')),
                    entity_id INTEGER NOT NULL,
                    match_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    brand_id INTEGER NULL,
                    perfume_id INTEGER NULL,
                    FOREIGN KEY (brand_id) REFERENCES brands(id),
                    FOREIGN KEY (perfume_id) REFERENCES perfumes(id)
                );
                """
            )

    def upsert_brand(self, brand: BrandRecord) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO brands (canonical_name, normalized_name)
                VALUES (?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                    canonical_name = excluded.canonical_name
                """,
                (brand.canonical_name, brand.normalized_name),
            )
            row = conn.execute(
                "SELECT id FROM brands WHERE normalized_name = ?",
                (brand.normalized_name,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to upsert brand")
            return int(row["id"])

    def upsert_perfume(self, perfume: PerfumeRecord) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO perfumes (brand_id, canonical_name, normalized_name, default_concentration)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                    brand_id = excluded.brand_id,
                    canonical_name = excluded.canonical_name,
                    default_concentration = excluded.default_concentration
                """,
                (
                    perfume.brand_id,
                    perfume.canonical_name,
                    perfume.normalized_name,
                    perfume.default_concentration,
                ),
            )
            row = conn.execute(
                "SELECT id FROM perfumes WHERE normalized_name = ?",
                (perfume.normalized_name,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to upsert perfume")
            return int(row["id"])

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

        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO aliases (
                    alias_text,
                    normalized_alias_text,
                    entity_type,
                    entity_id,
                    match_type,
                    confidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_alias_text, entity_type, entity_id)
                DO UPDATE SET
                    alias_text = excluded.alias_text,
                    match_type = excluded.match_type,
                    confidence = excluded.confidence,
                    updated_at = CURRENT_TIMESTAMP
                """,
                alias_rows,
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
        with self.connect() as conn:
            conn.execute(
                """
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fragrance_id) DO UPDATE SET
                    brand_name = excluded.brand_name,
                    perfume_name = excluded.perfume_name,
                    canonical_name = excluded.canonical_name,
                    normalized_name = excluded.normalized_name,
                    release_year = excluded.release_year,
                    gender = excluded.gender,
                    source = excluded.source,
                    brand_id = excluded.brand_id,
                    perfume_id = excluded.perfume_id
                """,
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

    def count_rows(self, table_name: str) -> int:
        allowed = {"brands", "perfumes", "aliases", "fragrance_master"}
        if table_name not in allowed:
            raise ValueError(f"Unsupported table: {table_name}")
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table_name}").fetchone()
            return int(row["n"])

    def get_perfume_aliases(self, normalized_perfume_name: str) -> list[str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM perfumes WHERE normalized_name = ?",
                (normalized_perfume_name,),
            ).fetchone()
            if row is None:
                return []
            perfume_id = int(row["id"])
            rows = conn.execute(
                """
                SELECT alias_text
                FROM aliases
                WHERE entity_type = 'perfume' AND entity_id = ?
                ORDER BY alias_text
                """,
                (perfume_id,),
            ).fetchall()
            return [str(r["alias_text"]) for r in rows]

    def get_perfume_by_alias(self, normalized_alias: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.id, p.canonical_name
                FROM aliases a
                JOIN perfumes p
                  ON a.entity_type = 'perfume'
                 AND a.entity_id = p.id
                WHERE a.entity_type = 'perfume'
                  AND a.normalized_alias_text = ?
                LIMIT 1
                """,
                (normalized_alias,),
            ).fetchone()

            if row is None:
                return None

            return {
                "perfume_id": int(row["id"]),
                "canonical_name": str(row["canonical_name"]),
                "confidence": 1.0,
                "match_type": "exact",
            }
