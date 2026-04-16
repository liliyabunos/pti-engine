#!/usr/bin/env python3
"""
Migrate real data from local SQLite (market_dev.db) to Railway PostgreSQL.

Strategy:
  - Transfer source/catalog layers only (content, resolution, entity catalog)
  - Skip derived/computed tables (entity_timeseries_daily, signals)
  - Rerun aggregation + detect_signals on Railway after migration

Usage:
    DATABASE_URL="postgresql://..." python3 scripts/migrate_to_production.py

Optional dry run (print counts only, no writes):
    DATABASE_URL="..." python3 scripts/migrate_to_production.py --dry-run
"""

import argparse
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = "outputs/market_dev.db"

# Tables to migrate in dependency order.
# Each entry: (sqlite_table, postgres_table, conflict_column)
MIGRATION_PLAN = [
    # Entity catalog
    ("brands",                  "brands",                  "id"),
    ("perfumes",                "perfumes",                "id"),
    ("entity_market",           "entity_market",           "id"),
    # Content pipeline source layer (created by migration 007)
    ("canonical_content_items", "canonical_content_items", "id"),
    ("resolved_signals",        "resolved_signals",        "content_item_id"),
    ("entity_mentions",         "entity_mentions",         "id"),
]

# Tables intentionally skipped:
#   brand_identity_map / perfume_identity_map — local SQLite bridge tables, not in Railway schema
#   entity_timeseries_daily / signals         — rebuilt on Railway by aggregation + detect_signals jobs
#   alerts / watchlists / alert_events        — empty, skip
SKIP_TABLES = ["brand_identity_map", "perfume_identity_map",
               "entity_timeseries_daily", "signals", "alerts", "watchlists",
               "watchlist_items", "alert_events"]


def _fmt_uuid(val: str) -> str:
    """Normalize a hex UUID string to hyphenated format expected by Postgres."""
    if val is None:
        return val
    s = str(val).replace("-", "")
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return val  # already hyphenated or not a UUID — return as-is


# Columns that contain UUID values and must be normalized before insert
_UUID_COLS = {"id", "entity_id", "brand_id", "perfume_id"}


def get_sqlite_rows(conn: sqlite3.Connection, table: str):
    cursor = conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cursor.description]
    raw_rows = cursor.fetchall()

    # Normalize UUID columns: SQLite stores them as plain hex, Postgres needs hyphens
    uuid_col_idxs = [i for i, c in enumerate(cols) if c in _UUID_COLS]
    if not uuid_col_idxs:
        return cols, raw_rows

    rows = []
    for row in raw_rows:
        row = list(row)
        for i in uuid_col_idxs:
            if row[i] is not None:
                row[i] = _fmt_uuid(row[i])
        rows.append(tuple(row))
    return cols, rows


def pg_upsert(pg_conn, table: str, cols: list, rows: list, conflict_col: str,
              dry_run: bool) -> int:
    if not rows:
        return 0

    import psycopg2.extras

    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(f'"{c}"' for c in cols)
    update_clause = ", ".join(
        f'"{c}" = EXCLUDED."{c}"'
        for c in cols
        if c != conflict_col
    )

    sql = (
        f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT ("{conflict_col}") DO UPDATE SET {update_clause}'
    )

    if dry_run:
        print(f"  [DRY RUN] would upsert {len(rows)} rows into {table}")
        return len(rows)

    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)
    pg_conn.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be migrated without writing")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        sys.exit("ERROR: DATABASE_URL env var is not set.")

    if not os.path.exists(SQLITE_PATH):
        sys.exit(f"ERROR: SQLite source not found at {SQLITE_PATH}")

    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {database_url.split('@')[-1] if '@' in database_url else database_url}")
    print(f"Dry run: {args.dry_run}")
    print()

    try:
        import psycopg2
        pg_conn = psycopg2.connect(database_url)
    except Exception as e:
        sys.exit(f"ERROR: Cannot connect to PostgreSQL: {e}")

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = None  # keep as tuples

    total_written = 0
    for sqlite_table, pg_table, conflict_col in MIGRATION_PLAN:
        try:
            cols, rows = get_sqlite_rows(sqlite_conn, sqlite_table)
        except Exception as e:
            print(f"  SKIP {sqlite_table}: not found in SQLite ({e})")
            continue

        print(f"  {sqlite_table} → {pg_table}: {len(rows)} rows", end="")
        try:
            n = pg_upsert(pg_conn, pg_table, cols, rows, conflict_col, args.dry_run)
            total_written += n
            print(f"  ✓")
        except Exception as e:
            pg_conn.rollback()
            print(f"\n  ERROR on {pg_table}: {e}")
            print("  Skipping this table and continuing...")

    sqlite_conn.close()
    pg_conn.close()

    print()
    print(f"Done. Total rows {'(dry run)' if args.dry_run else 'written'}: {total_written}")
    print()
    if not args.dry_run:
        print("Next steps — run on Railway (or via DATABASE_URL locally):")
        print()
        print("  # 1. Rebuild daily aggregates for all dates with real content")
        print("  for DATE in 2026-03-30 2026-03-31 2026-04-01 2026-04-02 2026-04-03 \\")
        print("              2026-04-04 2026-04-05 2026-04-06 2026-04-07 2026-04-08 \\")
        print("              2026-04-09 2026-04-10 2026-04-11 2026-04-12 2026-04-13; do")
        print("    DATABASE_URL=... python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date $DATE")
        print("  done")
        print()
        print("  # 2. Detect signals for all dates")
        print("  for DATE in 2026-03-30 ... 2026-04-13; do")
        print("    DATABASE_URL=... python3 -m perfume_trend_sdk.jobs.detect_signals --date $DATE")
        print("  done")


if __name__ == "__main__":
    main()
