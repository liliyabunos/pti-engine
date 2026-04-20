from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.utils.alias_generator import (
    generate_brand_aliases,
    generate_perfume_aliases,
    normalize_text,
)
from perfume_trend_sdk.storage.entities.fragrance_master_store import (
    AliasRecord,
    BrandRecord,
    FragranceMasterStore,
    PerfumeRecord,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SeedRow:
    fragrance_id: str
    brand_name: str
    perfume_name: str
    release_year: int | None
    gender: str | None
    source: str


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped)


def parse_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def load_seed_rows(csv_path: Path) -> list[SeedRow]:
    rows: list[SeedRow] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"fragrance_id", "brand_name", "perfume_name", "source"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required CSV columns: {sorted(missing)}")

        for line_no, row in enumerate(reader, start=2):
            fragrance_id = (row.get("fragrance_id") or "").strip()
            brand_name   = (row.get("brand_name")   or "").strip()
            perfume_name = (row.get("perfume_name")  or "").strip()
            source       = (row.get("source")        or "").strip()

            if not fragrance_id or not brand_name or not perfume_name or not source:
                raise ValueError(f"Invalid required values on line {line_no}")

            rows.append(
                SeedRow(
                    fragrance_id=fragrance_id,
                    brand_name=brand_name,
                    perfume_name=perfume_name,
                    release_year=parse_int_or_none(row.get("release_year")),
                    gender=parse_optional(row.get("gender")),
                    source=source,
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Store factory — selects SQLite or Postgres backend
# ---------------------------------------------------------------------------

def _make_store(db_path: Path | None, pg_url: str | None):
    """
    Return the appropriate store for the given backend.

    Priority:
      1. pg_url explicitly passed (--pg-url CLI flag)
      2. RESOLVER_DATABASE_URL env var
      3. db_path (SQLite)

    IMPORTANT: pg_url / RESOLVER_DATABASE_URL must point to a dedicated
    *resolver* Postgres DB — NOT the market engine DATABASE_URL (which uses
    UUID-keyed brands/perfumes).
    """
    resolver_url = pg_url or os.environ.get("RESOLVER_DATABASE_URL", "").strip()
    if resolver_url:
        logger.info("[load_fragrance_master] Backend: Postgres (%s)", resolver_url.split("@")[-1])
        try:
            from perfume_trend_sdk.storage.entities.pg_fragrance_master_store import (
                PgFragranceMasterStore,
            )
            return PgFragranceMasterStore(resolver_url)
        except ImportError as exc:
            logger.error(
                "[load_fragrance_master] PgFragranceMasterStore import failed: %s — "
                "falling back to SQLite (db_path=%s)",
                exc,
                db_path,
            )

    if db_path is None:
        raise ValueError(
            "No db_path and no RESOLVER_DATABASE_URL / --pg-url provided. "
            "Cannot initialize a store."
        )
    logger.info("[load_fragrance_master] Backend: SQLite (%s)", db_path)
    return FragranceMasterStore(str(db_path))


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------

def ingest_seed_csv(
    csv_path: Path,
    db_path: Path | None = None,
    *,
    pg_url: str | None = None,
) -> dict:
    """
    Load seed CSV rows into the fragrance knowledge base.

    Args:
        csv_path: Path to the seed CSV file.
        db_path:  SQLite resolver DB path (required when Postgres is not configured).
        pg_url:   Optional explicit Postgres resolver URL (overrides RESOLVER_DATABASE_URL).

    Returns:
        Summary dict with row counts for brands, perfumes, aliases, fragrance_master.
    """
    store = _make_store(db_path, pg_url)

    logger.info("[load_fragrance_master] Initializing schema …")
    store.init_schema()

    rows = load_seed_rows(csv_path)
    logger.info("[load_fragrance_master] Loaded %d seed rows from %s", len(rows), csv_path)

    brands_written = 0
    perfumes_written = 0
    aliases_written = 0
    errors: list[str] = []

    for i, row in enumerate(rows):
        try:
            normalized_brand   = normalize_text(row.brand_name)
            canonical_brand    = row.brand_name.strip()
            canonical_perfume  = row.perfume_name.strip()
            canonical_full     = f"{canonical_brand} {canonical_perfume}".strip()
            normalized_full    = normalize_text(canonical_full)

            brand_id = store.upsert_brand(
                BrandRecord(
                    canonical_name=canonical_brand,
                    normalized_name=normalized_brand,
                )
            )
            brands_written += 1

            perfume_id = store.upsert_perfume(
                PerfumeRecord(
                    brand_id=brand_id,
                    canonical_name=canonical_full,
                    normalized_name=normalized_full,
                    default_concentration=None,
                )
            )
            perfumes_written += 1

            brand_aliases = [
                AliasRecord(
                    alias_text=alias,
                    normalized_alias_text=normalize_text(alias),
                    entity_type="brand",
                    entity_id=brand_id,
                    match_type="exact",
                    confidence=1.0,
                )
                for alias in generate_brand_aliases(canonical_brand)
            ]
            perfume_aliases = [
                AliasRecord(
                    alias_text=alias,
                    normalized_alias_text=normalize_text(alias),
                    entity_type="perfume",
                    entity_id=perfume_id,
                    match_type="exact",
                    confidence=1.0,
                )
                for alias in generate_perfume_aliases(canonical_brand, canonical_perfume)
            ]
            store.upsert_aliases(brand_aliases)
            store.upsert_aliases(perfume_aliases)
            aliases_written += len(brand_aliases) + len(perfume_aliases)

            store.upsert_fragrance_master_row(
                fragrance_id=row.fragrance_id,
                brand_name=canonical_brand,
                perfume_name=canonical_perfume,
                canonical_name=canonical_full,
                normalized_name=normalized_full,
                release_year=row.release_year,
                gender=row.gender,
                source=row.source,
                brand_id=brand_id,
                perfume_id=perfume_id,
            )

            if (i + 1) % 500 == 0:
                logger.info(
                    "[load_fragrance_master] Progress: %d/%d rows processed …",
                    i + 1, len(rows),
                )

        except Exception as exc:
            msg = f"Row {i + 2} ({row.fragrance_id!r}): {exc}"
            logger.error("[load_fragrance_master] ERROR %s", msg)
            errors.append(msg)

    summary = {
        "csv_path":          str(csv_path),
        "seed_rows":         len(rows),
        "brands_written":    brands_written,
        "perfumes_written":  perfumes_written,
        "aliases_written":   aliases_written,
        "error_count":       len(errors),
        "errors":            errors[:20],   # cap to first 20 for logs
    }

    # DB counts (best-effort — don't fail if count_rows isn't available)
    try:
        summary["db_brands"]            = store.count_rows("brands")
        summary["db_perfumes"]          = store.count_rows("perfumes")
        summary["db_aliases"]           = store.count_rows("aliases")
        summary["db_fragrance_master"]  = store.count_rows("fragrance_master")
    except Exception as exc:
        logger.warning("[load_fragrance_master] count_rows failed: %s", exc)

    if errors:
        logger.warning(
            "[load_fragrance_master] Completed with %d errors (first: %s)",
            len(errors), errors[0],
        )
    else:
        logger.info("[load_fragrance_master] Completed with no errors")

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Load fragrance master seed CSV into the resolver knowledge base.\n\n"
            "Backend selection (in priority order):\n"
            "  1. --pg-url flag         → Postgres resolver DB\n"
            "  2. RESOLVER_DATABASE_URL → Postgres resolver DB\n"
            "  3. --db flag             → SQLite resolver DB (outputs/pti.db)\n\n"
            "NOTE: Postgres resolver URL must NOT be the market engine DATABASE_URL.\n"
            "      These are separate databases with different schemas."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to seed CSV (e.g. perfume_trend_sdk/data/fragrance_master/seed_master.csv)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to resolver SQLite DB (e.g. outputs/pti.db or data/resolver/pti.db)",
    )
    parser.add_argument(
        "--pg-url",
        default=None,
        metavar="URL",
        help=(
            "Postgres URL for resolver DB. Overrides RESOLVER_DATABASE_URL. "
            "Must be a dedicated resolver DB, not the market engine DB."
        ),
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    parser = build_arg_parser()
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None

    result = ingest_seed_csv(
        csv_path=Path(args.csv),
        db_path=db_path,
        pg_url=args.pg_url,
    )

    print("\nfragrance_master seed load complete:")
    print(f"  CSV rows processed : {result['seed_rows']}")
    print(f"  Brands written     : {result['brands_written']}")
    print(f"  Perfumes written   : {result['perfumes_written']}")
    print(f"  Aliases written    : {result['aliases_written']}")
    print(f"  Errors             : {result['error_count']}")
    if result.get("db_brands") is not None:
        print(f"\n  DB counts (post-load):")
        print(f"    brands           : {result['db_brands']}")
        print(f"    perfumes         : {result['db_perfumes']}")
        print(f"    aliases          : {result['db_aliases']}")
        print(f"    fragrance_master : {result['db_fragrance_master']}")
    if result["errors"]:
        print(f"\n  First error: {result['errors'][0]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
