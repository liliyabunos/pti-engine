#!/usr/bin/env python3
"""Phase 2b — Production Enrichment Data Bridge.

Reads enrichment data from a local SQLite market DB and upserts it into a
production PostgreSQL database — without altering any business logic or
creating new canonical entities.

Tables synced (in order):
  1. notes            — by normalized_name (upsert)
  2. accords          — by normalized_name (upsert)
  3. fragrantica_records — by fragrance_id (upsert)
  4. perfume_notes    — by (perfume_id, note_id, note_position) (upsert)
  5. perfume_accords  — by (perfume_id, accord_id) (upsert)

Identity safety:
  Perfume UUIDs in local SQLite and production PostgreSQL originate from the
  same seed catalog and are therefore identical in value (SQLite stores them
  without hyphens; PostgreSQL stores with hyphens but the same bit-value).
  The script normalises all UUIDs to the standard hyphenated form before
  writing to production.

CLI:
    # Dry run (inspect what would be synced, no writes)
    python3 scripts/sync_enrichment_to_production.py --dry-run

    # Real run targeting production
    DATABASE_URL="postgresql://..." python3 scripts/sync_enrichment_to_production.py

    # Override local SQLite path
    python3 scripts/sync_enrichment_to_production.py --source outputs/market_dev.db
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import sqlalchemy
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_uuid(raw: Optional[str]) -> Optional[str]:
    """Normalise a UUID string to standard hyphenated form.

    Handles:
      - already-hyphenated: "a0b21187-7234-42a6-acd9-ef7712c67589"
      - unhyphenated (SQLite):  "a0b21187723442a6acd9ef7712c67589"
      - None → None
    """
    if not raw:
        return None
    raw = raw.strip()
    if "-" in raw:
        return raw.lower()
    if len(raw) == 32:
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}".lower()
    return raw.lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Local SQLite reader
# ---------------------------------------------------------------------------

class LocalReader:
    def __init__(self, db_path: str) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def fetch(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------------------
# Production writer
# ---------------------------------------------------------------------------

class ProdWriter:
    def __init__(self, db_url: str, dry_run: bool = False) -> None:
        self.engine = sqlalchemy.create_engine(db_url, connect_args={"connect_timeout": 15})
        self.dry_run = dry_run

    def execute(self, conn, sql: str, params: dict) -> None:
        if self.dry_run:
            return
        conn.execute(text(sql), params)

    def count(self, conn, table: str) -> int:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0


# ---------------------------------------------------------------------------
# Bulk insert helper
# ---------------------------------------------------------------------------

def _bulk_insert(writer: ProdWriter, conn, table: str, columns: List[str], rows_data: List[Dict[str, Any]]) -> None:
    """Execute a single INSERT ... VALUES (...), (...) ON CONFLICT DO NOTHING.

    All rows are sent in one round-trip, which is critical for high-latency
    remote connections. In dry-run mode, no write is performed.
    """
    if not rows_data or writer.dry_run:
        return

    # Build: VALUES (:col0_0, :col1_0), (:col0_1, :col1_1), ...
    value_clauses = []
    params: Dict[str, Any] = {}
    for i, row in enumerate(rows_data):
        clause = "(" + ", ".join(f":{col}_{i}" for col in columns) + ")"
        value_clauses.append(clause)
        for col in columns:
            params[f"{col}_{i}"] = row[col]

    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES {', '.join(value_clauses)} "
        f"ON CONFLICT DO NOTHING"
    )
    conn.execute(text(sql), params)


# ---------------------------------------------------------------------------
# Sync functions
# ---------------------------------------------------------------------------

def sync_notes(reader: LocalReader, writer: ProdWriter, conn) -> Dict[str, int]:
    rows = reader.fetch("SELECT id, name, normalized_name, created_at FROM notes")

    # Pre-load all existing normalized_names in one query (avoids N round-trips)
    existing_names: set = {
        r[0] for r in conn.execute(text("SELECT normalized_name FROM notes")).fetchall()
    }

    to_insert: List[Dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if row["normalized_name"] in existing_names:
            skipped += 1
            continue
        to_insert.append({
            "id": _norm_uuid(row["id"]),
            "name": row["name"],
            "normalized_name": row["normalized_name"],
            "created_at": row["created_at"] or _now(),
        })

    _bulk_insert(writer, conn, "notes", ["id", "name", "normalized_name", "created_at"], to_insert)
    return {"inserted": len(to_insert), "skipped": skipped, "total_source": len(rows)}


def sync_accords(reader: LocalReader, writer: ProdWriter, conn) -> Dict[str, int]:
    rows = reader.fetch("SELECT id, name, normalized_name, created_at FROM accords")

    existing_names: set = {
        r[0] for r in conn.execute(text("SELECT normalized_name FROM accords")).fetchall()
    }

    to_insert: List[Dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if row["normalized_name"] in existing_names:
            skipped += 1
            continue
        to_insert.append({
            "id": _norm_uuid(row["id"]),
            "name": row["name"],
            "normalized_name": row["normalized_name"],
            "created_at": row["created_at"] or _now(),
        })

    _bulk_insert(writer, conn, "accords", ["id", "name", "normalized_name", "created_at"], to_insert)
    return {"inserted": len(to_insert), "skipped": skipped, "total_source": len(rows)}


def _build_perfume_uuid_set(conn) -> set:
    """Return set of all production perfume UUIDs (as normalised strings)."""
    rows = conn.execute(text("SELECT CAST(id AS text) FROM perfumes")).fetchall()
    return {_norm_uuid(r[0]) for r in rows}


def sync_fragrantica_records(
    reader: LocalReader, writer: ProdWriter, conn, prod_perfume_uuids: set
) -> Dict[str, int]:
    rows = reader.fetch(
        "SELECT id, fragrance_id, perfume_id, source_url, raw_payload_ref, "
        "brand_name, perfume_name, accords_json, notes_top_json, notes_middle_json, "
        "notes_base_json, rating_value, rating_count, release_year, perfumer, gender, "
        "similar_perfumes_json, fetched_at, created_at "
        "FROM fragrantica_records"
    )

    # Pre-load existing fragrance_ids in one query
    existing_fids: set = {
        r[0] for r in conn.execute(text("SELECT fragrance_id FROM fragrantica_records")).fetchall()
    }

    _FR_COLS = [
        "id", "fragrance_id", "perfume_id", "source_url", "raw_payload_ref",
        "brand_name", "perfume_name", "accords_json", "notes_top_json",
        "notes_middle_json", "notes_base_json", "rating_value", "rating_count",
        "release_year", "perfumer", "gender", "similar_perfumes_json",
        "fetched_at", "created_at",
    ]

    to_insert: List[Dict[str, Any]] = []
    skipped = no_perfume_match = 0

    for row in rows:
        local_perfume_id = _norm_uuid(row["perfume_id"])

        if local_perfume_id and local_perfume_id not in prod_perfume_uuids:
            logger.warning(
                "fragrantica_records: perfume_id %s not in production — skipping %s",
                local_perfume_id, row["fragrance_id"],
            )
            no_perfume_match += 1
            continue

        if row["fragrance_id"] in existing_fids:
            skipped += 1
            continue

        to_insert.append({
            "id": _norm_uuid(row["id"]),
            "fragrance_id": row["fragrance_id"],
            "perfume_id": local_perfume_id,
            "source_url": row["source_url"],
            "raw_payload_ref": row["raw_payload_ref"],
            "brand_name": row["brand_name"],
            "perfume_name": row["perfume_name"],
            "accords_json": row["accords_json"],
            "notes_top_json": row["notes_top_json"],
            "notes_middle_json": row["notes_middle_json"],
            "notes_base_json": row["notes_base_json"],
            "rating_value": row["rating_value"],
            "rating_count": row["rating_count"],
            "release_year": row["release_year"],
            "perfumer": row["perfumer"],
            "gender": row["gender"],
            "similar_perfumes_json": row["similar_perfumes_json"],
            "fetched_at": row["fetched_at"] or _now(),
            "created_at": row["created_at"] or _now(),
        })

    _bulk_insert(writer, conn, "fragrantica_records", _FR_COLS, to_insert)
    return {
        "inserted": len(to_insert),
        "skipped": skipped,
        "no_perfume_match": no_perfume_match,
        "total_source": len(rows),
    }


def sync_perfume_notes(
    reader: LocalReader,
    writer: ProdWriter,
    conn,
    prod_perfume_uuids: set,
    prod_note_norm_to_id: Dict[str, str],
) -> Dict[str, int]:
    rows = reader.fetch(
        "SELECT pn.id, pn.perfume_id, n.normalized_name, pn.note_position, pn.source, pn.created_at "
        "FROM perfume_notes pn "
        "JOIN notes n ON n.id = pn.note_id"
    )

    # Pre-load existing (perfume_id, note_id, note_position) triples in one query
    existing_keys: set = {
        (r[0], r[1], r[2])
        for r in conn.execute(
            text("SELECT perfume_id, note_id, note_position FROM perfume_notes")
        ).fetchall()
    }

    to_insert: List[Dict[str, Any]] = []
    skipped = no_match = 0

    for row in rows:
        local_perfume_id = _norm_uuid(row["perfume_id"])
        if local_perfume_id not in prod_perfume_uuids:
            no_match += 1
            continue

        prod_note_id = prod_note_norm_to_id.get(row["normalized_name"])
        if not prod_note_id:
            logger.warning("perfume_notes: note '%s' not in production — skipping", row["normalized_name"])
            no_match += 1
            continue

        if (local_perfume_id, prod_note_id, row["note_position"]) in existing_keys:
            skipped += 1
            continue

        to_insert.append({
            "id": str(uuid.uuid4()),
            "perfume_id": local_perfume_id,
            "note_id": prod_note_id,
            "note_position": row["note_position"],
            "source": row["source"] or "fragrantica",
            "created_at": row["created_at"] or _now(),
        })

    _bulk_insert(writer, conn, "perfume_notes",
                 ["id", "perfume_id", "note_id", "note_position", "source", "created_at"],
                 to_insert)
    return {
        "inserted": len(to_insert),
        "skipped": skipped,
        "no_match": no_match,
        "total_source": len(rows),
    }


def sync_perfume_accords(
    reader: LocalReader,
    writer: ProdWriter,
    conn,
    prod_perfume_uuids: set,
    prod_accord_norm_to_id: Dict[str, str],
) -> Dict[str, int]:
    rows = reader.fetch(
        "SELECT pa.id, pa.perfume_id, a.normalized_name, pa.source, pa.created_at "
        "FROM perfume_accords pa "
        "JOIN accords a ON a.id = pa.accord_id"
    )

    # Pre-load existing (perfume_id, accord_id) pairs in one query
    existing_keys: set = {
        (r[0], r[1])
        for r in conn.execute(
            text("SELECT perfume_id, accord_id FROM perfume_accords")
        ).fetchall()
    }

    to_insert: List[Dict[str, Any]] = []
    skipped = no_match = 0

    for row in rows:
        local_perfume_id = _norm_uuid(row["perfume_id"])
        if local_perfume_id not in prod_perfume_uuids:
            no_match += 1
            continue

        prod_accord_id = prod_accord_norm_to_id.get(row["normalized_name"])
        if not prod_accord_id:
            no_match += 1
            continue

        if (local_perfume_id, prod_accord_id) in existing_keys:
            skipped += 1
            continue

        to_insert.append({
            "id": str(uuid.uuid4()),
            "perfume_id": local_perfume_id,
            "accord_id": prod_accord_id,
            "source": row["source"] or "fragrantica",
            "created_at": row["created_at"] or _now(),
        })

    _bulk_insert(writer, conn, "perfume_accords",
                 ["id", "perfume_id", "accord_id", "source", "created_at"],
                 to_insert)
    return {
        "inserted": len(to_insert),
        "skipped": skipped,
        "no_match": no_match,
        "total_source": len(rows),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2b — sync enrichment data to production")
    parser.add_argument(
        "--source",
        default="outputs/market_dev.db",
        help="Local SQLite market DB path (default: outputs/market_dev.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Read source data, log what would be synced, but write nothing",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        raise SystemExit("DATABASE_URL is required — set it to the production PostgreSQL URL")
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    logger.info("Source SQLite  : %s", args.source)
    logger.info("Target DB      : %s", db_url.split("@")[-1])
    logger.info("Mode           : %s", "DRY RUN" if args.dry_run else "LIVE")

    reader = LocalReader(args.source)
    writer = ProdWriter(db_url, dry_run=args.dry_run)

    with writer.engine.begin() as conn:
        # Pre-sync counts
        pre = {t: writer.count(conn, t) for t in
               ["notes", "accords", "fragrantica_records", "perfume_notes", "perfume_accords"]}
        logger.info("Pre-sync production counts: %s", pre)

        prod_perfume_uuids = _build_perfume_uuid_set(conn)
        logger.info("Production perfumes available for mapping: %d", len(prod_perfume_uuids))

        # --- notes ---
        logger.info("--- Syncing notes ---")
        notes_result = sync_notes(reader, writer, conn)
        logger.info("notes: %s", notes_result)

        # --- accords ---
        logger.info("--- Syncing accords ---")
        accords_result = sync_accords(reader, writer, conn)
        logger.info("accords: %s", accords_result)

        # Build production note_id lookup (after syncing notes)
        prod_note_rows = conn.execute(
            text("SELECT id, normalized_name FROM notes")
        ).fetchall()
        prod_note_norm_to_id = {r[1]: str(r[0]) for r in prod_note_rows}
        logger.info("Production notes available after sync: %d", len(prod_note_norm_to_id))

        # Build production accord_id lookup
        prod_accord_rows = conn.execute(
            text("SELECT id, normalized_name FROM accords")
        ).fetchall()
        prod_accord_norm_to_id = {r[1]: str(r[0]) for r in prod_accord_rows}
        logger.info("Production accords available after sync: %d", len(prod_accord_norm_to_id))

        # --- fragrantica_records ---
        logger.info("--- Syncing fragrantica_records ---")
        fr_result = sync_fragrantica_records(reader, writer, conn, prod_perfume_uuids)
        logger.info("fragrantica_records: %s", fr_result)

        # --- perfume_notes ---
        logger.info("--- Syncing perfume_notes ---")
        pn_result = sync_perfume_notes(reader, writer, conn, prod_perfume_uuids, prod_note_norm_to_id)
        logger.info("perfume_notes: %s", pn_result)

        # --- perfume_accords ---
        logger.info("--- Syncing perfume_accords ---")
        pa_result = sync_perfume_accords(reader, writer, conn, prod_perfume_uuids, prod_accord_norm_to_id)
        logger.info("perfume_accords: %s", pa_result)

        # Post-sync counts
        post = {t: writer.count(conn, t) for t in
                ["notes", "accords", "fragrantica_records", "perfume_notes", "perfume_accords"]}

    reader.close()

    print("\n=== Phase 2b Sync Summary ===")
    print(f"  Mode          : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"\n  Pre-sync  → Post-sync:")
    for t in ["notes", "accords", "fragrantica_records", "perfume_notes", "perfume_accords"]:
        print(f"    {t:<25} : {pre[t]} → {post[t]}")
    print(f"\n  notes            : {notes_result}")
    print(f"  accords          : {accords_result}")
    print(f"  fragrantica_recs : {fr_result}")
    print(f"  perfume_notes    : {pn_result}")
    print(f"  perfume_accords  : {pa_result}")
    print("==============================\n")

    if args.dry_run:
        print("DRY RUN — no data was written. Run without --dry-run to apply.")


if __name__ == "__main__":
    main()
