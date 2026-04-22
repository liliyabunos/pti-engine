#!/usr/bin/env python3
"""Phase 1B — Bulk notes/accords backfill from Parfumo dataset.

Downloads parfumo_data_clean.csv (TidyTuesday 2024-12-10) and imports
Top Notes, Middle Notes, Base Notes, and Main_Accords into:
  - resolver_perfume_notes
  - resolver_perfume_accords

These tables use integer FKs to resolver_perfumes.id, covering the full
56k catalog regardless of market ingestion activity.

Matching strategy (in order):
  1. Exact normalized match: LOWER(brand_name) + LOWER(perfume_name)
  2. Normalized-only match on combined canonical_name

Rules:
  - DO NOT duplicate existing notes (UNIQUE index on perfume_id + norm_name + position)
  - DO NOT overwrite fragrantica_records data — these tables are the fallback layer
  - Fragrantica-enriched perfumes remain preferred in the entity API

Usage:
    # Dry-run (no DB writes):
    python3 scripts/import_dataset_notes.py --dry-run

    # Real run against production PostgreSQL:
    DATABASE_URL="<prod-url>" python3 scripts/import_dataset_notes.py

    # Bounded test run:
    DATABASE_URL="<prod-url>" python3 scripts/import_dataset_notes.py --limit 1000

    # Skip download (use cached file):
    python3 scripts/import_dataset_notes.py --csv-path /tmp/parfumo_data_clean.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

PARFUMO_URL = (
    "https://raw.githubusercontent.com/rfordatascience/tidytuesday"
    "/main/data/2024/2024-12-10/parfumo_data_clean.csv"
)

# Concentration suffixes — same list as aggregator uses
_CONC_SUFFIXES = [
    "extrait de parfum",
    "eau de parfum",
    "eau de toilette",
    "eau de cologne",
    "eau fraiche",
    "extrait",
    "parfum",
]

_NOISE_NOTE_WORDS = {
    "", "none", "n/a", "unknown", "other", "various", "several",
}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, unicode-normalize, collapse whitespace, strip."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _strip_concentration(name: str) -> str:
    """Strip trailing concentration suffix from a normalized perfume name."""
    result = name.strip()
    changed = True
    while changed:
        changed = False
        for suffix in _CONC_SUFFIXES:
            if result.endswith(" " + suffix):
                result = result[: -(len(suffix) + 1)].rstrip()
                changed = True
                break
            if result == suffix:
                break
    return result or name


def _parse_list(raw: str) -> List[str]:
    """Parse a comma/semicolon-separated note list, return cleaned names."""
    if not raw or raw.strip().lower() in ("", "none", "n/a", "na"):
        return []
    # Split on comma or semicolon
    parts = re.split(r"[,;]", raw)
    result = []
    for part in parts:
        cleaned = part.strip().strip('"').strip("'").strip()
        if cleaned and _normalize(cleaned) not in _NOISE_NOTE_WORDS:
            result.append(cleaned)
    return result


# ---------------------------------------------------------------------------
# Dataset download
# ---------------------------------------------------------------------------

def _download_csv(url: str, cache_path: Optional[Path] = None) -> str:
    if cache_path and cache_path.exists():
        logger.info("[import] Using cached CSV: %s", cache_path)
        return cache_path.read_text(encoding="utf-8")
    logger.info("[import] Downloading Parfumo dataset from %s …", url)
    req = urllib.request.Request(url, headers={"User-Agent": "PTI-SDK/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    logger.info("[import] Downloaded %d bytes", len(raw))
    if cache_path:
        cache_path.write_text(raw, encoding="utf-8")
        logger.info("[import] Cached to %s", cache_path)
    return raw


def _parse_csv(raw: str) -> List[Dict]:
    reader = csv.DictReader(io.StringIO(raw))
    return list(reader)


# ---------------------------------------------------------------------------
# Resolver lookup
# ---------------------------------------------------------------------------

def _detect_table_names(engine) -> Tuple[str, str, str, str]:
    """Return (perfumes_table, brands_table, notes_table, accords_table) based on what exists."""
    with engine.connect() as conn:
        # Check Postgres resolver tables first
        try:
            conn.execute(text("SELECT 1 FROM resolver_perfumes LIMIT 1"))
            return "resolver_perfumes", "resolver_brands", "resolver_perfume_notes", "resolver_perfume_accords"
        except Exception:
            pass
        # Fall back to legacy SQLite tables
        try:
            conn.execute(text("SELECT 1 FROM perfumes LIMIT 1"))
            return "perfumes", "brands", "resolver_perfume_notes", "resolver_perfume_accords"
        except Exception:
            pass
    raise RuntimeError(
        "No resolver table found (resolver_perfumes or perfumes). "
        "Point DATABASE_URL at production PostgreSQL or PTI_DB_PATH at a resolver SQLite DB."
    )


def _build_resolver_lookup(engine, perfumes_table: str = "resolver_perfumes", brands_table: str = "resolver_brands") -> Dict[str, int]:
    """
    Build lookup: normalized_key -> perfumes.id

    Key = _normalize(brand_name) + "||" + _normalize(perfume_name_stripped)
    Also register key with just canonical_name for fallback matching.
    """
    logger.info("[import] Loading %s lookup …", perfumes_table)
    lookup: Dict[str, int] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
            SELECT rp.id, rp.canonical_name, rp.normalized_name, rb.canonical_name AS brand_name
            FROM {perfumes_table} rp
            LEFT JOIN {brands_table} rb ON rp.brand_id = rb.id
            """)
        ).fetchall()

    for row in rows:
        rid, canonical, normalized, brand_name = row
        rid = int(rid)

        # Key 1: normalized canonical_name (e.g. "dior sauvage")
        k1 = _normalize(normalized or canonical or "")
        if k1 and k1 not in lookup:
            lookup[k1] = rid

        # Key 2: brand + stripped perfume name
        if brand_name:
            brand_norm = _normalize(brand_name)
            # strip concentration from canonical name to get perfume part
            perfume_norm = _strip_concentration(_normalize(canonical or ""))
            # remove brand prefix from canonical if present
            if perfume_norm.startswith(brand_norm + " "):
                perfume_norm = perfume_norm[len(brand_norm) + 1:].strip()
            k2 = brand_norm + "||" + perfume_norm
            if k2 and k2 not in lookup:
                lookup[k2] = rid

    logger.info("[import] Resolver lookup built: %d keys for %d perfumes", len(lookup), len(rows))
    return lookup


def _match_row(
    brand: str,
    name: str,
    lookup: Dict[str, int],
) -> Optional[int]:
    """Return resolver_perfume_id or None."""
    brand_norm = _normalize(brand)
    name_norm = _strip_concentration(_normalize(name))

    # Strategy 1: brand + perfume key
    k1 = brand_norm + "||" + name_norm
    if k1 in lookup:
        return lookup[k1]

    # Strategy 2: full canonical name "brand perfume"
    full_norm = _normalize(brand + " " + name)
    full_stripped = _strip_concentration(full_norm)
    if full_stripped in lookup:
        return lookup[full_stripped]
    if full_norm in lookup:
        return lookup[full_norm]

    # Strategy 3: just stripped perfume name (risky — only if unique)
    # Skip — too many false positives for common names like "Noir", "Bleu"
    return None


# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_batch(
    engine,
    notes_batch: List[Dict],
    accords_batch: List[Dict],
    dry_run: bool,
    notes_table: str = "resolver_perfume_notes",
    accords_table: str = "resolver_perfume_accords",
) -> Tuple[int, int]:
    """Bulk-insert a batch of notes + accords using executemany.

    Uses a single transaction with one executemany call per table —
    far fewer roundtrips than row-by-row inserts.
    Returns (notes_attempted, accords_attempted).
    """
    if dry_run or (not notes_batch and not accords_batch):
        return len(notes_batch), len(accords_batch)

    now = _now_iso()
    notes_ok = 0
    accords_ok = 0

    # Build parameter lists
    note_params = [
        {
            "pid": item["resolver_perfume_id"],
            "name": item["note_name"],
            "norm": item["normalized_name"],
            "pos": item["position"],
            "src": item.get("source", "parfumo_v1"),
            "ts": now,
        }
        for item in notes_batch
    ]
    accord_params = [
        {
            "pid": item["resolver_perfume_id"],
            "name": item["accord_name"],
            "norm": item["normalized_name"],
            "src": item.get("source", "parfumo_v1"),
            "ts": now,
        }
        for item in accords_batch
    ]

    with engine.begin() as conn:
        if note_params:
            try:
                conn.execute(
                    text(f"""
                    INSERT INTO {notes_table}
                      (resolver_perfume_id, note_name, normalized_name, position, source, created_at)
                    VALUES
                      (:pid, :name, :norm, :pos, :src, :ts)
                    ON CONFLICT (resolver_perfume_id, normalized_name, position) DO NOTHING
                    """),
                    note_params,
                )
                notes_ok = len(note_params)
            except Exception as exc:
                logger.warning("[import] Notes bulk insert error: %s", exc)

        if accord_params:
            try:
                conn.execute(
                    text(f"""
                    INSERT INTO {accords_table}
                      (resolver_perfume_id, accord_name, normalized_name, source, created_at)
                    VALUES
                      (:pid, :name, :norm, :src, :ts)
                    ON CONFLICT (resolver_perfume_id, normalized_name) DO NOTHING
                    """),
                    accord_params,
                )
                accords_ok = len(accord_params)
            except Exception as exc:
                logger.warning("[import] Accords bulk insert error: %s", exc)

    return notes_ok, accords_ok


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def _get_engine():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return create_engine(db_url)
    db_path = os.environ.get("PTI_DB_PATH", "outputs/pti.db")
    return create_engine(f"sqlite:///{db_path}")


def run(
    csv_raw: str,
    dry_run: bool = False,
    limit: Optional[int] = None,
    batch_size: int = 5000,
    source: str = "parfumo_v1",
) -> Dict:
    rows = _parse_csv(csv_raw)
    total_rows = len(rows)
    logger.info("[import] Parsed %d dataset rows", total_rows)

    if limit:
        rows = rows[:limit]
        logger.info("[import] Limiting to first %d rows", limit)

    engine = _get_engine()

    # Auto-detect table names (Postgres resolver_* vs SQLite legacy)
    perfumes_table, brands_table, notes_table, accords_table = _detect_table_names(engine)
    logger.info("[import] Using tables: %s, %s → %s, %s", perfumes_table, brands_table, notes_table, accords_table)

    # Build resolver lookup
    lookup = _build_resolver_lookup(engine, perfumes_table, brands_table)

    stats = {
        "total_dataset_rows": total_rows,
        "processed_rows": len(rows),
        "matched": 0,
        "unmatched": 0,
        "notes_inserted": 0,
        "accords_inserted": 0,
        "notes_prepared": 0,
        "accords_prepared": 0,
        "batches": 0,
    }

    notes_batch: List[Dict] = []
    accords_batch: List[Dict] = []
    unmatched_sample: List[str] = []
    matched_sample: List[Tuple[str, str, int]] = []

    for i, row in enumerate(rows):
        brand = (row.get("Brand") or "").strip()
        name = (row.get("Name") or "").strip()

        if not brand or not name:
            stats["unmatched"] += 1
            continue

        resolver_id = _match_row(brand, name, lookup)

        if resolver_id is None:
            stats["unmatched"] += 1
            if len(unmatched_sample) < 10:
                unmatched_sample.append(f"{brand} — {name}")
            continue

        stats["matched"] += 1
        if len(matched_sample) < 5:
            matched_sample.append((brand, name, resolver_id))

        # Parse notes (Parfumo CSV uses underscore column names: Top_Notes, Middle_Notes, Base_Notes)
        for pos, col in [("top", "Top_Notes"), ("middle", "Middle_Notes"), ("base", "Base_Notes")]:
            for note in _parse_list(row.get(col, "") or ""):
                norm = _normalize(note)
                if norm and norm not in _NOISE_NOTE_WORDS:
                    notes_batch.append({
                        "resolver_perfume_id": resolver_id,
                        "note_name": note[:200],
                        "normalized_name": norm[:200],
                        "position": pos,
                        "source": source,
                    })
                    stats["notes_prepared"] += 1

        # Parse accords
        for accord in _parse_list(row.get("Main_Accords", "") or ""):
            norm = _normalize(accord)
            if norm and norm not in _NOISE_NOTE_WORDS:
                accords_batch.append({
                    "resolver_perfume_id": resolver_id,
                    "accord_name": accord[:200],
                    "normalized_name": norm[:200],
                    "source": source,
                })
                stats["accords_prepared"] += 1

        # Flush batch
        if len(notes_batch) + len(accords_batch) >= batch_size:
            n_ok, a_ok = _insert_batch(engine, notes_batch, accords_batch, dry_run, notes_table, accords_table)
            stats["notes_inserted"] += n_ok
            stats["accords_inserted"] += a_ok
            stats["batches"] += 1
            notes_batch = []
            accords_batch = []
            if stats["batches"] % 10 == 0:
                logger.info(
                    "[import] Batch %d: matched=%d unmatched=%d notes=%d accords=%d",
                    stats["batches"],
                    stats["matched"],
                    stats["unmatched"],
                    stats["notes_inserted"],
                    stats["accords_inserted"],
                )

    # Final flush
    if notes_batch or accords_batch:
        n_ok, a_ok = _insert_batch(engine, notes_batch, accords_batch, dry_run, notes_table, accords_table)
        stats["notes_inserted"] += n_ok
        stats["accords_inserted"] += a_ok
        stats["batches"] += 1

    stats["unmatched_sample"] = unmatched_sample
    stats["matched_sample"] = [(b, n, rid) for b, n, rid in matched_sample]

    return stats


def _verify_counts(engine, notes_table: str = "resolver_perfume_notes", accords_table: str = "resolver_perfume_accords"):
    with engine.connect() as conn:
        notes_count = conn.execute(
            text(f"SELECT COUNT(*) FROM {notes_table}")
        ).scalar()
        accords_count = conn.execute(
            text(f"SELECT COUNT(*) FROM {accords_table}")
        ).scalar()
        perfumes_with_notes = conn.execute(
            text(f"SELECT COUNT(DISTINCT resolver_perfume_id) FROM {notes_table}")
        ).scalar()
        perfumes_with_accords = conn.execute(
            text(f"SELECT COUNT(DISTINCT resolver_perfume_id) FROM {accords_table}")
        ).scalar()
    return {
        "total_notes": notes_count,
        "total_accords": accords_count,
        "perfumes_with_notes": perfumes_with_notes,
        "perfumes_with_accords": perfumes_with_accords,
    }


def _spot_check(engine, perfumes_table: str = "resolver_perfumes", notes_table: str = "resolver_perfume_notes", n: int = 5):
    """Spot-check: show sample perfumes with their notes."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
            SELECT rp.canonical_name, rpn.position, rpn.note_name
            FROM {notes_table} rpn
            JOIN {perfumes_table} rp ON rp.id = rpn.resolver_perfume_id
            ORDER BY rp.canonical_name, rpn.position, rpn.note_name
            LIMIT :n
            """),
            {"n": n * 5},
        ).fetchall()
    return rows


def main():
    parser = argparse.ArgumentParser(description="Phase 1B: Bulk notes backfill from Parfumo dataset")
    parser.add_argument("--dry-run", action="store_true", help="Parse and match but do not write to DB")
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N dataset rows")
    parser.add_argument("--batch-size", type=int, default=5000, help="Insert batch size (default: 5000)")
    parser.add_argument("--csv-path", type=str, default=None, help="Path to local Parfumo CSV (skip download)")
    parser.add_argument("--verify-only", action="store_true", help="Only run verification queries, no import")
    parser.add_argument("--source", type=str, default="parfumo_v1", help="Source tag for imported rows")
    args = parser.parse_args()

    engine = _get_engine()
    perfumes_table, brands_table, notes_table, accords_table = _detect_table_names(engine)

    if args.verify_only:
        counts = _verify_counts(engine, notes_table, accords_table)
        print("\n=== Verification ===")
        for k, v in counts.items():
            print(f"  {k:<30}: {v:,}")
        rows = _spot_check(engine, perfumes_table, notes_table)
        print("\n  Sample notes:")
        for r in rows:
            print(f"    [{r[1]}] {r[0]}: {r[2]}")
        return

    # Ensure notes table exists (fail fast with a clear message)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {notes_table} LIMIT 1"))
    except Exception:
        print(
            f"\nERROR: {notes_table} table not found.\n"
            "Run: alembic upgrade head\n"
            "(Migration 017 adds this table.)\n"
        )
        sys.exit(1)

    # Load CSV
    if args.csv_path:
        csv_path = Path(args.csv_path)
        csv_raw = csv_path.read_text(encoding="utf-8")
        logger.info("[import] Loaded CSV from %s (%d bytes)", csv_path, len(csv_raw))
    else:
        # Cache in /tmp
        cache_path = Path("/tmp/parfumo_data_clean.csv")
        csv_raw = _download_csv(PARFUMO_URL, cache_path=cache_path)

    if args.dry_run:
        logger.info("[import] DRY-RUN MODE — no DB writes")

    stats = run(
        csv_raw,
        dry_run=args.dry_run,
        limit=args.limit,
        batch_size=args.batch_size,
        source=args.source,
    )

    print()
    print("=== Phase 1B — Notes Backfill Results ===")
    print(f"  Dataset rows total        : {stats['total_dataset_rows']:,}")
    print(f"  Rows processed            : {stats['processed_rows']:,}")
    print(f"  Matched to resolver       : {stats['matched']:,}")
    print(f"  Unmatched                 : {stats['unmatched']:,}")
    match_rate = stats['matched'] / max(stats['processed_rows'], 1) * 100
    print(f"  Match rate                : {match_rate:.1f}%")
    print()
    print(f"  Notes prepared            : {stats['notes_prepared']:,}")
    print(f"  Accords prepared          : {stats['accords_prepared']:,}")
    if not args.dry_run:
        print(f"  Notes inserted            : {stats['notes_inserted']:,}")
        print(f"  Accords inserted          : {stats['accords_inserted']:,}")
        print(f"  Insert batches            : {stats['batches']}")
    else:
        print(f"  [DRY-RUN] Would insert ~  : {stats['notes_prepared']:,} notes, {stats['accords_prepared']:,} accords")

    if stats.get("matched_sample"):
        print(f"\n  Sample matched:")
        for brand, name, rid in stats["matched_sample"]:
            print(f"    resolver_id={rid}: {brand} — {name}")

    if stats.get("unmatched_sample"):
        print(f"\n  Sample unmatched (first 10):")
        for item in stats["unmatched_sample"]:
            print(f"    {item}")

    if not args.dry_run:
        print()
        counts = _verify_counts(engine, notes_table, accords_table)
        print("=== Post-Import Verification ===")
        for k, v in counts.items():
            print(f"  {k:<30}: {v:,}")

        print("\n  Sample notes (spot-check):")
        for r in _spot_check(engine, perfumes_table, notes_table, n=10):
            print(f"    [{r[1]}] {r[0]}: {r[2]}")


if __name__ == "__main__":
    main()
