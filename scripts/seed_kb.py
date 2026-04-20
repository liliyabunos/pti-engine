#!/usr/bin/env python3
"""
Unified Knowledge Base (KB) seed script.

Runs all three KB initialization steps in order:

  Step 1 — Resolver seed
    Load seed_master.csv + seed_placeholder.csv into the resolver DB
    (SQLite: data/resolver/pti.db, or Postgres via RESOLVER_DATABASE_URL).
    Writes: fragrance_master, brands (int PK), perfumes (int PK), aliases.

  Step 2 — Market catalog seed
    Seed UUID-keyed brands and perfumes into the market engine DB
    (SQLite: outputs/market_dev.db, or Postgres via DATABASE_URL).
    Reads: seed_master.csv directly.

  Step 3 — Identity map sync
    Link resolver integer IDs to market engine UUIDs in brand_identity_map
    and perfume_identity_map.
    Reads: resolver SQLite pti.db + market DB (SQLite or Postgres).

All steps are idempotent — re-running is safe.

Usage:

  # Local dev (both DBs are SQLite):
  python scripts/seed_kb.py

  # Production Postgres (market engine):
  DATABASE_URL="postgresql://..." python scripts/seed_kb.py

  # Production with separate Postgres resolver DB:
  DATABASE_URL="postgresql://..." RESOLVER_DATABASE_URL="postgresql://..." \\
      python scripts/seed_kb.py

  # Skip individual steps:
  python scripts/seed_kb.py --skip-resolver --skip-sync

  # Dry-run: check what would run without executing:
  python scripts/seed_kb.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("seed_kb")

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

DEFAULT_RESOLVER_DB  = PROJECT_ROOT / "data" / "resolver" / "pti.db"
DEFAULT_MARKET_DB    = PROJECT_ROOT / "outputs" / "market_dev.db"
DEFAULT_SEED_MASTER  = PROJECT_ROOT / "perfume_trend_sdk" / "data" / "fragrance_master" / "seed_master.csv"
DEFAULT_SEED_PLACEHOLDER = (
    PROJECT_ROOT / "perfume_trend_sdk" / "data" / "fragrance_master" / "seed_placeholder.csv"
)


# ---------------------------------------------------------------------------
# Step 1 — Resolver seed (fragrance_master, aliases, brands/perfumes int PK)
# ---------------------------------------------------------------------------

def step_resolver_seed(
    resolver_db: Path,
    seed_csvs: list[Path],
    pg_url: str | None,
    dry_run: bool,
) -> bool:
    """Load seed CSVs into the resolver DB (SQLite or Postgres)."""
    logger.info("=== Step 1: Resolver seed ===")

    if dry_run:
        logger.info("[dry-run] Would load %d CSV(s) into resolver DB=%s pg_url=%s",
                    len(seed_csvs), resolver_db, pg_url or "(none)")
        return True

    try:
        from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv

        total_errors = 0
        for csv_path in seed_csvs:
            if not csv_path.exists():
                logger.warning("Seed CSV not found, skipping: %s", csv_path)
                continue
            logger.info("Loading %s …", csv_path.name)
            result = ingest_seed_csv(
                csv_path=csv_path,
                db_path=resolver_db if not pg_url else None,
                pg_url=pg_url,
            )
            logger.info(
                "  brands=%d  perfumes=%d  aliases=%d  fm=%d  errors=%d",
                result.get("db_brands", result["brands_written"]),
                result.get("db_perfumes", result["perfumes_written"]),
                result.get("db_aliases", result["aliases_written"]),
                result.get("db_fragrance_master", 0),
                result["error_count"],
            )
            total_errors += result["error_count"]

        if total_errors:
            logger.warning("Step 1 completed with %d total errors", total_errors)
        else:
            logger.info("Step 1 completed successfully")
        return True

    except Exception as exc:
        logger.error("Step 1 FAILED: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Step 2 — Market catalog seed (brands/perfumes UUID PK)
# ---------------------------------------------------------------------------

def step_market_seed(
    market_db: Path,
    database_url: str | None,
    seed_csv: Path,
    dry_run: bool,
) -> bool:
    """Seed UUID-keyed brands and perfumes into the market engine DB."""
    logger.info("=== Step 2: Market catalog seed ===")

    db_target = database_url or str(market_db)

    if dry_run:
        logger.info("[dry-run] Would seed market catalog: %s (csv=%s)", db_target, seed_csv)
        return True

    try:
        from scripts.seed_market_catalog import seed

        if not seed_csv.exists():
            logger.error("seed_master.csv not found at %s — skipping market seed", seed_csv)
            return False

        result = seed(
            db_path=database_url or str(market_db),
            csv_path=str(seed_csv),
        )
        logger.info(
            "Market seed: brands inserted=%d existing=%d  perfumes inserted=%d existing=%d",
            result["brands_inserted"], result["brands_existing"],
            result["perfumes_inserted"], result["perfumes_existing"],
        )
        logger.info("Step 2 completed successfully")
        return True

    except Exception as exc:
        logger.error("Step 2 FAILED: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Step 3 — Identity map sync
# ---------------------------------------------------------------------------

def step_identity_sync(
    resolver_db: Path,
    market_db: Path,
    database_url: str | None,
    verbose: bool,
    dry_run: bool,
) -> bool:
    """Sync resolver integer IDs ↔ market engine UUIDs."""
    logger.info("=== Step 3: Identity map sync ===")

    if dry_run:
        logger.info(
            "[dry-run] Would sync identity maps: resolver=%s market=%s",
            resolver_db, database_url or market_db,
        )
        return True

    try:
        from scripts.sync_identity_map import sync, _resolve_market_url

        if not resolver_db.exists():
            logger.error(
                "Resolver DB not found at %s — cannot sync identity maps. "
                "Run Step 1 first.", resolver_db,
            )
            return False

        market_url = _resolve_market_url(
            str(market_db) if not database_url else None,
            database_url,
        )
        result = sync(str(resolver_db), market_url, verbose=verbose)

        logger.info(
            "Identity sync: brands mapped=%d unmatched=%d | perfumes mapped=%d unmatched=%d",
            result["brand_mapped"],    result["brand_unmatched"],
            result["perfume_mapped"],  result["perfume_unmatched"],
        )
        if result["brand_unmatched_examples"]:
            logger.info("  Unmatched brand examples: %s", result["brand_unmatched_examples"])
        if result["perfume_unmatched_examples"]:
            logger.info("  Unmatched perfume examples: %s", result["perfume_unmatched_examples"])

        logger.info("Step 3 completed successfully")
        return True

    except Exception as exc:
        logger.error("Step 3 FAILED: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--resolver-db",
        default=str(DEFAULT_RESOLVER_DB),
        help=f"Resolver SQLite DB path (default: {DEFAULT_RESOLVER_DB})",
    )
    p.add_argument(
        "--market-db",
        default=str(DEFAULT_MARKET_DB),
        help=f"Market engine SQLite DB path for local dev (default: {DEFAULT_MARKET_DB}). "
             "Not required when DATABASE_URL is set.",
    )
    p.add_argument(
        "--pg-url",
        default=None,
        metavar="URL",
        help="Postgres URL for the *resolver* DB. Overrides RESOLVER_DATABASE_URL. "
             "Must be a dedicated resolver DB — NOT the market engine DATABASE_URL.",
    )
    p.add_argument(
        "--skip-resolver",
        action="store_true",
        help="Skip Step 1 (resolver seed). Use if resolver DB is already seeded.",
    )
    p.add_argument(
        "--skip-market",
        action="store_true",
        help="Skip Step 2 (market catalog seed).",
    )
    p.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip Step 3 (identity map sync).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print unmatched examples from identity sync.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without executing anything.",
    )
    return p


def main() -> int:
    args = _parser().parse_args()

    database_url  = os.environ.get("DATABASE_URL", "").strip() or None
    resolver_db   = Path(args.resolver_db)
    market_db     = Path(args.market_db)
    pg_url        = args.pg_url or os.environ.get("RESOLVER_DATABASE_URL", "").strip() or None
    seed_csvs     = [p for p in [DEFAULT_SEED_MASTER, DEFAULT_SEED_PLACEHOLDER] if p.exists()]

    logger.info("KB seed starting")
    logger.info("  Resolver DB  : %s", pg_url.split("@")[-1] if pg_url else resolver_db)
    logger.info("  Market DB    : %s", database_url.split("@")[-1] if database_url else market_db)
    logger.info("  Seed CSVs    : %s", [p.name for p in seed_csvs])
    if args.dry_run:
        logger.info("  DRY RUN — no changes will be made")

    failures: list[str] = []

    # Step 1 — Resolver seed
    if not args.skip_resolver:
        ok = step_resolver_seed(resolver_db, seed_csvs, pg_url, args.dry_run)
        if not ok:
            failures.append("resolver_seed")
    else:
        logger.info("=== Step 1: Resolver seed — SKIPPED ===")

    # Step 2 — Market catalog seed
    if not args.skip_market:
        ok = step_market_seed(market_db, database_url, DEFAULT_SEED_MASTER, args.dry_run)
        if not ok:
            failures.append("market_seed")
    else:
        logger.info("=== Step 2: Market catalog seed — SKIPPED ===")

    # Step 3 — Identity map sync (requires resolver DB to exist)
    if not args.skip_sync:
        ok = step_identity_sync(
            resolver_db=resolver_db,
            market_db=market_db,
            database_url=database_url,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
        if not ok:
            failures.append("identity_sync")
    else:
        logger.info("=== Step 3: Identity map sync — SKIPPED ===")

    if failures:
        logger.error("KB seed FAILED in: %s", ", ".join(failures))
        return 1

    logger.info("KB seed COMPLETE — all steps succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
