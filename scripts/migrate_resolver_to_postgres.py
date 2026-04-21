"""
Phase R1 — Migrate resolver/catalog data from SQLite → Postgres resolver_* tables.

Uses psycopg2.extras.execute_values for true bulk batch inserts (one SQL
statement per 500-row batch, not one statement per row). Fast enough for
56k rows over a public internet connection in under 2 minutes.

Idempotent: ON CONFLICT DO NOTHING — safe to re-run any number of times.

Usage:
    DATABASE_URL=... python3 scripts/migrate_resolver_to_postgres.py
    DATABASE_URL=... python3 scripts/migrate_resolver_to_postgres.py --dry-run
    DATABASE_URL=... python3 scripts/migrate_resolver_to_postgres.py --sqlite data/resolver/pti.db

Migration order (respects FK constraints):
  1. brands           → resolver_brands
  2. perfumes         → resolver_perfumes  (brand_id FK → resolver_brands)
  3. aliases          → resolver_aliases   (entity_id plain int, no FK)
  4. fragrance_master → resolver_fragrance_master
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BATCH = 2_000  # rows per execute_values call — larger = fewer roundtrips
DEFAULT_SQLITE = str(Path(__file__).resolve().parent.parent / "data" / "resolver" / "pti.db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_sqlite(path: str) -> sqlite3.Connection:
    if not Path(path).exists():
        print(f"[migrate] ERROR: SQLite file not found: {path}")
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _open_pg(database_url: str):
    """Return a psycopg2 connection using the DATABASE_URL."""
    import psycopg2
    parsed = urlparse(database_url)
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        dbname=parsed.path.lstrip("/"),
        user=parsed.username,
        password=parsed.password,
        sslmode="require",
        connect_timeout=30,
    )
    conn.autocommit = False
    return conn


def _execute_values(pg_cur, sql: str, rows: list[tuple], page_size: int = 2_000) -> int:
    """Bulk-insert rows using psycopg2.extras.execute_values.

    Returns number of rows passed (not necessarily inserted — ON CONFLICT
    DO NOTHING means some may be skipped silently).
    """
    from psycopg2.extras import execute_values
    if not rows:
        return 0
    execute_values(pg_cur, sql, rows, page_size=page_size)
    return len(rows)


def _log_sqlite_counts(sqlite_con: sqlite3.Connection) -> None:
    tables = ["brands", "perfumes", "aliases", "fragrance_master"]
    print("[migrate] SQLite source counts:")
    for t in tables:
        n = sqlite_con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n:,}")


def _log_pg_counts(pg_cur) -> None:
    tables = ["resolver_brands", "resolver_perfumes", "resolver_aliases", "resolver_fragrance_master"]
    print("[migrate] Postgres resolver_* counts:")
    for t in tables:
        pg_cur.execute(f"SELECT COUNT(*) FROM {t}")
        n = pg_cur.fetchone()[0]
        print(f"  {t}: {n:,}")


# ---------------------------------------------------------------------------
# Main migration
# ---------------------------------------------------------------------------

def migrate(sqlite_path: str, dry_run: bool) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("[migrate] ERROR: DATABASE_URL is not set.")
        sys.exit(1)

    safe_url = database_url.split("@")[-1] if "@" in database_url else database_url
    print(f"[migrate] SQLite source : {sqlite_path}")
    print(f"[migrate] Postgres      : {safe_url}")
    print(f"[migrate] Mode          : {'DRY-RUN (no writes)' if dry_run else 'LIVE'}")
    print()

    sqlite_con = _open_sqlite(sqlite_path)
    _log_sqlite_counts(sqlite_con)
    print()

    if dry_run:
        print("[migrate] DRY-RUN complete — no writes performed.")
        sqlite_con.close()
        return

    pg_conn = _open_pg(database_url)
    pg_cur = pg_conn.cursor()

    # ── 1. Brands ────────────────────────────────────────────────────────────
    print("[migrate] Step 1/4 — brands → resolver_brands")
    brand_rows = sqlite_con.execute(
        "SELECT id, canonical_name, normalized_name FROM brands ORDER BY id"
    ).fetchall()
    total = len(brand_rows)
    sql = """
        INSERT INTO resolver_brands (canonical_name, normalized_name)
        VALUES %s
        ON CONFLICT (normalized_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
    """
    for i in range(0, total, BATCH):
        chunk = brand_rows[i : i + BATCH]
        _execute_values(pg_cur, sql, [(r["canonical_name"], r["normalized_name"]) for r in chunk])
        pg_conn.commit()
        print(f"  {min(i + BATCH, total):,}/{total:,}", end="\r")
    print(f"  {total:,}/{total:,} — done")

    # Build SQLite-id → Postgres-id brand map
    pg_cur.execute("SELECT id, normalized_name FROM resolver_brands")
    pg_brand_by_norm = {row[1]: row[0] for row in pg_cur.fetchall()}
    brand_id_map = {int(r["id"]): pg_brand_by_norm[r["normalized_name"]]
                    for r in brand_rows if r["normalized_name"] in pg_brand_by_norm}
    print(f"  brand id map: {len(brand_id_map):,}/{total:,}")

    # ── 2. Perfumes ──────────────────────────────────────────────────────────
    print("\n[migrate] Step 2/4 — perfumes → resolver_perfumes")
    perf_rows = sqlite_con.execute(
        "SELECT id, brand_id, canonical_name, normalized_name, default_concentration "
        "FROM perfumes ORDER BY id"
    ).fetchall()
    total = len(perf_rows)
    sql = """
        INSERT INTO resolver_perfumes
            (brand_id, canonical_name, normalized_name, default_concentration)
        VALUES %s
        ON CONFLICT (normalized_name) DO UPDATE SET
            brand_id              = EXCLUDED.brand_id,
            canonical_name        = EXCLUDED.canonical_name,
            default_concentration = EXCLUDED.default_concentration
    """
    for i in range(0, total, BATCH):
        chunk = perf_rows[i : i + BATCH]
        _execute_values(pg_cur, sql, [
            (
                brand_id_map.get(int(r["brand_id"])) if r["brand_id"] else None,
                r["canonical_name"],
                r["normalized_name"],
                r["default_concentration"],
            )
            for r in chunk
        ])
        pg_conn.commit()
        print(f"  {min(i + BATCH, total):,}/{total:,}", end="\r")
    print(f"  {total:,}/{total:,} — done")

    # Build perfume id map
    pg_cur.execute("SELECT id, normalized_name FROM resolver_perfumes")
    pg_perf_by_norm = {row[1]: row[0] for row in pg_cur.fetchall()}
    perfume_id_map = {int(r["id"]): pg_perf_by_norm[r["normalized_name"]]
                     for r in perf_rows if r["normalized_name"] in pg_perf_by_norm}
    print(f"  perfume id map: {len(perfume_id_map):,}/{total:,}")

    # ── 3. Aliases ───────────────────────────────────────────────────────────
    print("\n[migrate] Step 3/4 — aliases → resolver_aliases")
    alias_rows = sqlite_con.execute(
        "SELECT alias_text, normalized_alias_text, entity_type, entity_id, "
        "match_type, confidence FROM aliases ORDER BY id"
    ).fetchall()
    total = len(alias_rows)
    sql = """
        INSERT INTO resolver_aliases
            (alias_text, normalized_alias_text, entity_type, entity_id,
             match_type, confidence)
        VALUES %s
        ON CONFLICT (normalized_alias_text, entity_type, entity_id) DO UPDATE SET
            alias_text = EXCLUDED.alias_text,
            match_type = EXCLUDED.match_type,
            confidence = EXCLUDED.confidence
    """
    inserted = 0
    for i in range(0, total, BATCH):
        chunk = alias_rows[i : i + BATCH]
        rows = []
        for r in chunk:
            etype = r["entity_type"]
            sid = int(r["entity_id"])
            if etype == "perfume":
                pgid = perfume_id_map.get(sid, sid)
            elif etype == "brand":
                pgid = brand_id_map.get(sid, sid)
            else:
                pgid = sid
            rows.append((r["alias_text"], r["normalized_alias_text"], etype, pgid,
                         r["match_type"], float(r["confidence"])))
        _execute_values(pg_cur, sql, rows)
        pg_conn.commit()
        inserted += len(chunk)
        print(f"  {inserted:,}/{total:,}", end="\r")
    print(f"  {total:,}/{total:,} — done")

    # ── 4. Fragrance master ──────────────────────────────────────────────────
    print("\n[migrate] Step 4/4 — fragrance_master → resolver_fragrance_master")
    fm_rows = sqlite_con.execute(
        "SELECT fragrance_id, brand_name, perfume_name, canonical_name, "
        "normalized_name, release_year, gender, source, brand_id, perfume_id "
        "FROM fragrance_master ORDER BY rowid"
    ).fetchall()
    total = len(fm_rows)
    sql = """
        INSERT INTO resolver_fragrance_master
            (fragrance_id, brand_name, perfume_name, canonical_name,
             normalized_name, release_year, gender, source, brand_id, perfume_id)
        VALUES %s
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
    inserted = 0
    for i in range(0, total, BATCH):
        chunk = fm_rows[i : i + BATCH]
        _execute_values(pg_cur, sql, [
            (
                r["fragrance_id"],
                r["brand_name"],
                r["perfume_name"],
                r["canonical_name"],
                r["normalized_name"],
                r["release_year"],
                r["gender"],
                r["source"],
                brand_id_map.get(int(r["brand_id"])) if r["brand_id"] else None,
                perfume_id_map.get(int(r["perfume_id"])) if r["perfume_id"] else None,
            )
            for r in chunk
        ])
        pg_conn.commit()
        inserted += len(chunk)
        print(f"  {inserted:,}/{total:,}", end="\r")
    print(f"  {total:,}/{total:,} — done")

    # ── Final counts ─────────────────────────────────────────────────────────
    print()
    _log_pg_counts(pg_cur)
    print("\n[migrate] Done.")

    pg_cur.close()
    pg_conn.close()
    sqlite_con.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Migrate SQLite resolver KB → Postgres resolver_* tables (idempotent, batched)."
    )
    p.add_argument(
        "--sqlite",
        default=DEFAULT_SQLITE,
        help="SQLite resolver DB path (default: data/resolver/pti.db)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Count source rows only — no Postgres writes.",
    )
    args = p.parse_args()
    migrate(args.sqlite, args.dry_run)


if __name__ == "__main__":
    main()
