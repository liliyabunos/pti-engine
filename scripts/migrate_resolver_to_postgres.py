"""
Phase R1 — Migrate resolver/catalog data from SQLite → Postgres resolver_* tables.

Idempotent: all inserts use ON CONFLICT DO NOTHING (via PgResolverStore upserts).
Safe to re-run; rows already present are skipped.

Usage:
    # requires DATABASE_URL in environment (or .env)
    python3 scripts/migrate_resolver_to_postgres.py

    # override SQLite source path:
    python3 scripts/migrate_resolver_to_postgres.py --sqlite data/resolver/pti.db

    # dry-run (count rows only, no writes):
    python3 scripts/migrate_resolver_to_postgres.py --dry-run

Migration order (respects FKs):
  1. brands   → resolver_brands
  2. perfumes → resolver_perfumes   (brand_id FK)
  3. aliases  → resolver_aliases    (entity_id is plain int, no FK)
  4. fragrance_master → resolver_fragrance_master  (brand_id + perfume_id FKs)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BATCH = 500
DEFAULT_SQLITE = str(Path(__file__).resolve().parent.parent / "data" / "resolver" / "pti.db")


def _open_sqlite(path: str) -> sqlite3.Connection:
    if not Path(path).exists():
        print(f"[migrate] ERROR: SQLite file not found: {path}")
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _log_counts(label: str, sqlite_con: sqlite3.Connection) -> None:
    tables = ["brands", "perfumes", "aliases", "fragrance_master"]
    print(f"\n[migrate] {label} counts (SQLite source):")
    for t in tables:
        n = sqlite_con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n:,}")


def _log_pg_counts(store) -> None:
    tables = ["brands", "perfumes", "aliases", "fragrance_master"]
    print("\n[migrate] Postgres resolver_* counts:")
    for t in tables:
        n = store.count_rows(t)
        print(f"  resolver_{t}: {n:,}")


def migrate(sqlite_path: str, dry_run: bool) -> None:
    from perfume_trend_sdk.storage.entities.fragrance_master_store import (
        AliasRecord,
        BrandRecord,
        PerfumeRecord,
    )
    from perfume_trend_sdk.storage.entities.pg_resolver_store import PgResolverStore

    if not os.environ.get("DATABASE_URL"):
        print("[migrate] ERROR: DATABASE_URL is not set. Export it before running.")
        sys.exit(1)

    print(f"[migrate] SQLite source : {sqlite_path}")
    print(f"[migrate] Postgres      : {os.environ['DATABASE_URL'].split('@')[-1]}")
    print(f"[migrate] Mode          : {'DRY-RUN (no writes)' if dry_run else 'LIVE'}")

    sqlite_con = _open_sqlite(sqlite_path)
    _log_counts("source", sqlite_con)

    if dry_run:
        print("\n[migrate] DRY-RUN complete — no writes performed.")
        sqlite_con.close()
        return

    store = PgResolverStore()

    # ── 1. Brands ────────────────────────────────────────────────────────────
    print("\n[migrate] Step 1/4 — brands → resolver_brands")
    brand_rows = sqlite_con.execute(
        "SELECT id, canonical_name, normalized_name FROM brands ORDER BY id"
    ).fetchall()
    brand_id_map: dict[int, int] = {}  # sqlite_id → postgres_id
    inserted = 0
    for i, row in enumerate(brand_rows):
        pg_id = store.upsert_brand(
            BrandRecord(
                canonical_name=row["canonical_name"],
                normalized_name=row["normalized_name"],
            )
        )
        brand_id_map[int(row["id"])] = pg_id
        inserted += 1
        if inserted % BATCH == 0 or inserted == len(brand_rows):
            print(f"  brands: {inserted:,}/{len(brand_rows):,}", end="\r")
    print(f"\n  brands done: {inserted:,}")

    # ── 2. Perfumes ──────────────────────────────────────────────────────────
    print("\n[migrate] Step 2/4 — perfumes → resolver_perfumes")
    perf_rows = sqlite_con.execute(
        "SELECT id, brand_id, canonical_name, normalized_name, default_concentration "
        "FROM perfumes ORDER BY id"
    ).fetchall()
    perfume_id_map: dict[int, int] = {}  # sqlite_id → postgres_id
    inserted = 0
    for row in perf_rows:
        sqlite_brand_id = row["brand_id"]
        pg_brand_id = brand_id_map.get(int(sqlite_brand_id)) if sqlite_brand_id else None
        pg_id = store.upsert_perfume(
            PerfumeRecord(
                brand_id=pg_brand_id,
                canonical_name=row["canonical_name"],
                normalized_name=row["normalized_name"],
                default_concentration=row["default_concentration"],
            )
        )
        perfume_id_map[int(row["id"])] = pg_id
        inserted += 1
        if inserted % BATCH == 0 or inserted == len(perf_rows):
            print(f"  perfumes: {inserted:,}/{len(perf_rows):,}", end="\r")
    print(f"\n  perfumes done: {inserted:,}")

    # ── 3. Aliases ───────────────────────────────────────────────────────────
    print("\n[migrate] Step 3/4 — aliases → resolver_aliases")
    alias_rows = sqlite_con.execute(
        "SELECT alias_text, normalized_alias_text, entity_type, entity_id, "
        "match_type, confidence FROM aliases ORDER BY id"
    ).fetchall()
    total_aliases = len(alias_rows)
    inserted = 0
    for i in range(0, total_aliases, BATCH):
        chunk = alias_rows[i : i + BATCH]
        records = []
        for row in chunk:
            entity_type = row["entity_type"]
            sqlite_entity_id = int(row["entity_id"])
            if entity_type == "perfume":
                pg_entity_id = perfume_id_map.get(sqlite_entity_id, sqlite_entity_id)
            elif entity_type == "brand":
                pg_entity_id = brand_id_map.get(sqlite_entity_id, sqlite_entity_id)
            else:
                pg_entity_id = sqlite_entity_id
            records.append(
                AliasRecord(
                    alias_text=row["alias_text"],
                    normalized_alias_text=row["normalized_alias_text"],
                    entity_type=entity_type,
                    entity_id=pg_entity_id,
                    match_type=row["match_type"],
                    confidence=float(row["confidence"]),
                )
            )
        store.upsert_aliases(records)
        inserted += len(chunk)
        print(f"  aliases: {inserted:,}/{total_aliases:,}", end="\r")
    print(f"\n  aliases done: {inserted:,}")

    # ── 4. Fragrance master ──────────────────────────────────────────────────
    print("\n[migrate] Step 4/4 — fragrance_master → resolver_fragrance_master")
    fm_rows = sqlite_con.execute(
        "SELECT fragrance_id, brand_name, perfume_name, canonical_name, "
        "normalized_name, release_year, gender, source, brand_id, perfume_id "
        "FROM fragrance_master ORDER BY rowid"
    ).fetchall()
    total_fm = len(fm_rows)
    inserted = 0
    for row in fm_rows:
        sqlite_brand_id = row["brand_id"]
        sqlite_perf_id = row["perfume_id"]
        pg_brand_id = brand_id_map.get(int(sqlite_brand_id)) if sqlite_brand_id else None
        pg_perf_id = perfume_id_map.get(int(sqlite_perf_id)) if sqlite_perf_id else None
        store.upsert_fragrance_master_row(
            fragrance_id=row["fragrance_id"],
            brand_name=row["brand_name"],
            perfume_name=row["perfume_name"],
            canonical_name=row["canonical_name"],
            normalized_name=row["normalized_name"],
            release_year=row["release_year"],
            gender=row["gender"],
            source=row["source"],
            brand_id=pg_brand_id,
            perfume_id=pg_perf_id,
        )
        inserted += 1
        if inserted % BATCH == 0 or inserted == total_fm:
            print(f"  fragrance_master: {inserted:,}/{total_fm:,}", end="\r")
    print(f"\n  fragrance_master done: {inserted:,}")

    # ── Final counts ─────────────────────────────────────────────────────────
    _log_pg_counts(store)
    print("\n[migrate] Done.")

    sqlite_con.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Migrate SQLite resolver KB → Postgres resolver_* tables (idempotent)."
    )
    p.add_argument(
        "--sqlite",
        default=DEFAULT_SQLITE,
        help="Path to SQLite resolver DB (default: data/resolver/pti.db)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows and exit without writing to Postgres.",
    )
    args = p.parse_args()
    migrate(args.sqlite, args.dry_run)


if __name__ == "__main__":
    main()
