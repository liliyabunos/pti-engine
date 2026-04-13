#!/usr/bin/env python3
"""
Step 5A — Seed brands and perfumes into the market engine database.

Reads from perfume_trend_sdk/data/fragrance_master/seed_master.csv and
populates the UUID-based `brands` and `perfumes` tables.

Idempotent: re-running is safe. Uses `slug` as the stable lookup key so
existing records are never duplicated.

Usage:
    python scripts/seed_market_catalog.py
    python scripts/seed_market_catalog.py --db outputs/market_dev.db
    python scripts/seed_market_catalog.py --db outputs/market_dev.db --limit 50
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from perfume_trend_sdk.analysis.market_signals.aggregator import generate_ticker  # noqa: E402
from perfume_trend_sdk.db.market.base import Base  # noqa: E402
from perfume_trend_sdk.db.market.brand import Brand  # noqa: E402
from perfume_trend_sdk.db.market.perfume import Perfume  # noqa: E402
from perfume_trend_sdk.db.market.session import _make_engine  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_DB = PROJECT_ROOT / "outputs" / "market_dev.db"
DEFAULT_CSV = (
    PROJECT_ROOT / "perfume_trend_sdk" / "data" / "fragrance_master" / "seed_master.csv"
)

# Concentration suffixes stripped from the end of perfume names.
_CONCENTRATION_RE = re.compile(
    r"\s+(Eau\s+de\s+Parfum|Eau\s+de\s+Toilette|Eau\s+de\s+Cologne|"
    r"Eau\s+Fraic?he|Extrait\s+de\s+Parfum|Extrait|Parfum|EDP|EDT|EDC|"
    r"Cologne|Body\s+Mist|Body\s+Spray)\s*$",
    re.IGNORECASE,
)

_CONCENTRATION_CANONICAL = {
    "eau de parfum": "edp", "edp": "edp",
    "eau de toilette": "edt", "edt": "edt",
    "eau de cologne": "edc", "edc": "edc", "cologne": "edc",
    "extrait de parfum": "extrait", "extrait": "extrait",
    "parfum": "parfum",
    "body mist": "body_spray", "body spray": "body_spray",
}

_GENDER_MAP = {"women": "feminine", "men": "masculine", "unisex": "unisex"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(value: str) -> str:
    s = re.sub(r"[^\w\s-]", "", value.lower().strip())
    return re.sub(r"[\s_]+", "-", s).strip("-")


def _clean_name(raw: str):
    """Strip trailing concentration term. Return (clean_name, concentration|None)."""
    m = _CONCENTRATION_RE.search(raw)
    if m:
        concentration = _CONCENTRATION_CANONICAL.get(m.group(1).lower().strip())
        return raw[: m.start()].strip(), concentration
    return raw.strip(), None


def _unique_ticker(base: str, used: set, max_len: int = 8) -> str:
    t = base[:max_len]
    if t not in used:
        return t
    for i in range(2, 1000):
        candidate = (base[:max_len - len(str(i))] + str(i))[:max_len]
        if candidate not in used:
            return candidate
    return base[:max_len - 1] + "X"


# ---------------------------------------------------------------------------
# Core seed function
# ---------------------------------------------------------------------------

def seed(db_path: str, csv_path: str, limit: int | None = None) -> dict:
    """Populate brands and perfumes from the seed CSV.

    Args:
        db_path:  SQLite file path or SQLAlchemy URL.
        csv_path: Path to seed_master.csv.
        limit:    If set, only process the first N CSV rows (useful for testing).

    Returns:
        Summary dict with inserted/existing counts.
    """
    url = db_path if "://" in db_path else f"sqlite:///{db_path}"
    engine = _make_engine(url)
    Base.metadata.create_all(engine)  # creates all market engine tables
    Session = sessionmaker(bind=engine)

    now = datetime.now(timezone.utc)

    brand_cache: dict[str, Brand] = {}   # slug → Brand
    brand_tickers: set[str] = set()
    perfume_tickers: set[str] = set()

    brands_inserted = 0
    brands_existing = 0
    perfumes_inserted = 0
    perfumes_existing = 0

    with Session() as session:
        # ----------------------------------------------------------------
        # Load existing tickers so we don't collide on re-run
        # ----------------------------------------------------------------
        for b in session.query(Brand).all():
            brand_cache[b.slug] = b
            brand_tickers.add(b.ticker)
        for p in session.query(Perfume).all():
            perfume_tickers.add(p.ticker)

        # ----------------------------------------------------------------
        # Read CSV (needed for both repair pass and upsert passes)
        # ----------------------------------------------------------------
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if limit:
            rows = rows[:limit]

        # ----------------------------------------------------------------
        # Pass 1 — upsert brands
        # ----------------------------------------------------------------
        brand_names: dict[str, str] = {}  # slug → canonical name (first seen)
        for row in rows:
            bn = row["brand_name"].strip()
            if not bn:
                continue
            slug = _slugify(bn)
            if slug not in brand_names:
                brand_names[slug] = bn

        for slug, bn in brand_names.items():
            if slug in brand_cache:
                brands_existing += 1
                continue
            ticker = _unique_ticker(generate_ticker(bn), brand_tickers, max_len=6)
            brand_tickers.add(ticker)
            b = Brand(name=bn, slug=slug, ticker=ticker, created_at=now)
            session.add(b)
            session.flush()   # get .id before perfume pass
            brand_cache[slug] = b
            brands_inserted += 1

        session.flush()

        # ----------------------------------------------------------------
        # Pass 1b — repair brand_id links for existing perfumes
        # Corrects cases where the aggregation job heuristic created a wrong
        # brand link (e.g. "Tom Ford Black" instead of "Tom Ford").
        # Safe to run repeatedly: only updates rows that are actually wrong.
        # ----------------------------------------------------------------
        perfume_by_slug: dict[str, "Perfume"] = {
            p.slug: p for p in session.query(Perfume).all()
        }
        brands_repaired = 0
        for row in rows:
            bn = row["brand_name"].strip()
            raw_name = row["perfume_name"].strip()
            if not bn or not raw_name:
                continue
            clean_name, _ = _clean_name(raw_name)
            slug = _slugify(f"{bn}-{clean_name}")
            p = perfume_by_slug.get(slug)
            correct_brand = brand_cache.get(_slugify(bn))
            if p is None or correct_brand is None:
                continue
            if p.brand_id != correct_brand.id:
                p.brand_id = correct_brand.id
                brands_repaired += 1
        if brands_repaired:
            session.flush()
            logger.info("Repaired %d perfume brand links", brands_repaired)

        # ----------------------------------------------------------------
        # Pass 2 — upsert perfumes
        # ----------------------------------------------------------------
        for row in rows:
            bn = row["brand_name"].strip()
            raw_name = row["perfume_name"].strip()
            if not bn or not raw_name:
                continue

            clean_name, concentration = _clean_name(raw_name)
            # Slug includes brand to avoid cross-brand conflicts
            slug = _slugify(f"{bn}-{clean_name}")

            existing = session.query(Perfume).filter_by(slug=slug).first()
            if existing:
                if existing.ticker not in perfume_tickers:
                    perfume_tickers.add(existing.ticker)
                perfumes_existing += 1
                continue

            brand_obj = brand_cache.get(_slugify(bn))
            ticker = _unique_ticker(
                generate_ticker(f"{bn} {clean_name}"), perfume_tickers, max_len=7
            )
            perfume_tickers.add(ticker)

            launch_year: int | None = None
            if row.get("release_year"):
                try:
                    launch_year = int(row["release_year"])
                except ValueError:
                    pass

            gender_position = _GENDER_MAP.get(row.get("gender", "").strip().lower())

            session.add(Perfume(
                brand_id=brand_obj.id if brand_obj else None,
                name=clean_name,
                slug=slug,
                ticker=ticker,
                launch_year=launch_year,
                gender_position=gender_position,
                concentration=concentration,
                created_at=now,
            ))
            perfumes_inserted += 1

            if perfumes_inserted % 200 == 0:
                session.flush()
                logger.info("Seeded %d perfumes so far…", perfumes_inserted)

        session.commit()

    return {
        "db_path": str(db_path),
        "brands_inserted": brands_inserted,
        "brands_existing": brands_existing,
        "total_brands": brands_inserted + brands_existing,
        "perfumes_inserted": perfumes_inserted,
        "perfumes_existing": perfumes_existing,
        "total_perfumes": perfumes_inserted + perfumes_existing,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Seed market catalog (brands + perfumes).")
    p.add_argument("--db", default=str(DEFAULT_DB), help="DB path (default: outputs/market_dev.db)")
    p.add_argument("--csv", default=str(DEFAULT_CSV), help="Seed CSV path")
    p.add_argument(
        "--limit", type=int, default=None,
        help="Process only first N rows (useful for a quick smoke test)",
    )
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args()

    result = seed(args.db, args.csv, args.limit)
    print(f"\nSeed complete:")
    print(f"  Brands:   inserted={result['brands_inserted']:>4}  existing={result['brands_existing']:>4}  total={result['total_brands']:>4}")
    print(f"  Perfumes: inserted={result['perfumes_inserted']:>4}  existing={result['perfumes_existing']:>4}  total={result['total_perfumes']:>4}")
    print(f"  DB: {result['db_path']}")


if __name__ == "__main__":
    main()
