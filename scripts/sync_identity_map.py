#!/usr/bin/env python3
"""
Step 6B — Sync identity maps: resolver catalog ↔ market engine.

Reads legacy Integer-PK brands/perfumes from the resolver DB (pti.db) and
UUID-PK brands/perfumes from the market engine DB (market_dev.db or Railway
Postgres), matches by slug, and writes mapping rows to brand_identity_map /
perfume_identity_map tables in the market engine DB.

Matching algorithm
------------------
Brands:
    slugify(legacy_brand.canonical_name) == market_brand.slug

Perfumes:
    slugify(strip_concentration(legacy_perfume.canonical_name)) == market_perfume.slug

The market engine slug for perfumes is built as:
    slugify("{brand_name}-{perfume_name_without_concentration}")
which is identical to slugify(full_legacy_canonical_name_stripped) because
both hyphens and spaces collapse to "-" in the slug.

Idempotent: re-running updates existing rows; it never creates duplicates.

Market DB selection (in priority order)
-----------------------------------------
  1. DATABASE_URL env var    → Railway / production Postgres
  2. --market-db flag        → local SQLite (dev)

Usage (local):
    python scripts/sync_identity_map.py \\
        --resolver-db outputs/pti.db \\
        --market-db outputs/market_dev.db \\
        --verbose

Usage (Railway Postgres):
    DATABASE_URL="postgresql://..." python scripts/sync_identity_map.py \\
        --resolver-db outputs/pti.db \\
        --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker      # noqa: E402

from perfume_trend_sdk.db.market.base import Base               # noqa: E402
from perfume_trend_sdk.db.market.identity_map import (           # noqa: E402
    BrandIdentityMap,
    PerfumeIdentityMap,
)

logger = logging.getLogger(__name__)

DEFAULT_RESOLVER_DB = PROJECT_ROOT / "outputs" / "pti.db"
DEFAULT_MARKET_DB   = PROJECT_ROOT / "outputs" / "market_dev.db"

# ---------------------------------------------------------------------------
# Slug / concentration helpers  (mirrors seed_market_catalog.py logic)
# ---------------------------------------------------------------------------

_CONCENTRATION_RE = re.compile(
    r"\s+(Eau\s+de\s+Parfum|Eau\s+de\s+Toilette|Eau\s+de\s+Cologne|"
    r"Eau\s+Fraic?he|Extrait\s+de\s+Parfum|Extrait|Parfum|EDP|EDT|EDC|"
    r"Cologne|Body\s+Mist|Body\s+Spray)\s*$",
    re.IGNORECASE,
)


def _slugify(value: str) -> str:
    s = re.sub(r"[^\w\s-]", "", value.lower().strip())
    return re.sub(r"[\s_]+", "-", s).strip("-")


def _strip_concentration(name: str) -> str:
    m = _CONCENTRATION_RE.search(name)
    return name[: m.start()].strip() if m else name.strip()


def _perfume_match_slug(canonical_name: str) -> str:
    """Derive the slug key used to match a legacy perfume to its market counterpart."""
    return _slugify(_strip_concentration(canonical_name))


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------

def _make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def _resolve_market_url(market_db_arg: str | None, database_url: str | None) -> str:
    """Return the SQLAlchemy URL for the market engine DB."""
    if database_url:
        return database_url
    path = market_db_arg or str(DEFAULT_MARKET_DB)
    return path if "://" in path else f"sqlite:///{path}"


# ---------------------------------------------------------------------------
# Loader helpers — resolver DB (always local SQLite)
# ---------------------------------------------------------------------------

def _load_legacy_brands(resolver_db: str) -> list[dict]:
    """Return all brands from the resolver catalog DB."""
    engine = create_engine(
        f"sqlite:///{resolver_db}", connect_args={"check_same_thread": False}
    )
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, canonical_name, normalized_name FROM brands ORDER BY id"
        )).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_legacy_perfumes(resolver_db: str) -> list[dict]:
    """Return all perfumes from the resolver catalog DB."""
    engine = create_engine(
        f"sqlite:///{resolver_db}", connect_args={"check_same_thread": False}
    )
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, brand_id, canonical_name, normalized_name FROM perfumes ORDER BY id"
        )).fetchall()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# Loader helpers — market DB (SQLite or Postgres)
# ---------------------------------------------------------------------------

def _load_market_brands(market_url: str) -> list[dict]:
    """Return all brands from the market engine DB (SQLite or Postgres)."""
    engine = _make_engine(market_url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT CAST(id AS TEXT) AS id, name, slug FROM brands"
        )).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_market_perfumes(market_url: str) -> list[dict]:
    """Return all perfumes from the market engine DB (SQLite or Postgres)."""
    engine = _make_engine(market_url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT CAST(id AS TEXT) AS id, name, slug FROM perfumes"
        )).fetchall()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# Upsert helpers (SQLAlchemy ORM on market DB)
# ---------------------------------------------------------------------------

def _upsert_brand_map(
    session,
    *,
    resolver_brand_id: int,
    market_brand_uuid: str,
    canonical_name: str,
    slug: str,
    now: datetime,
) -> bool:
    """Insert or update a BrandIdentityMap row. Returns True if new."""
    existing = session.query(BrandIdentityMap).filter_by(
        resolver_brand_id=resolver_brand_id
    ).first()
    if existing:
        existing.market_brand_uuid = market_brand_uuid
        existing.canonical_name = canonical_name
        existing.slug = slug
        existing.updated_at = now
        return False
    session.add(BrandIdentityMap(
        resolver_brand_id=resolver_brand_id,
        market_brand_uuid=market_brand_uuid,
        canonical_name=canonical_name,
        slug=slug,
        created_at=now,
        updated_at=now,
    ))
    return True


def _upsert_perfume_map(
    session,
    *,
    resolver_perfume_id: int,
    market_perfume_uuid: str,
    canonical_name: str,
    slug: str,
    now: datetime,
) -> bool:
    """Insert or update a PerfumeIdentityMap row. Returns True if new."""
    existing = session.query(PerfumeIdentityMap).filter_by(
        resolver_perfume_id=resolver_perfume_id
    ).first()
    if existing:
        existing.market_perfume_uuid = market_perfume_uuid
        existing.canonical_name = canonical_name
        existing.slug = slug
        existing.updated_at = now
        return False
    session.add(PerfumeIdentityMap(
        resolver_perfume_id=resolver_perfume_id,
        market_perfume_uuid=market_perfume_uuid,
        canonical_name=canonical_name,
        slug=slug,
        created_at=now,
        updated_at=now,
    ))
    return True


# ---------------------------------------------------------------------------
# Main sync function
# ---------------------------------------------------------------------------

def sync(
    resolver_db: str,
    market_url: str,
    verbose: bool = False,
) -> dict:
    """Match resolver catalog entities to market engine entities and write mappings.

    Args:
        resolver_db:  Path to resolver/catalog SQLite DB (pti.db).
        market_url:   SQLAlchemy URL for the market engine DB (SQLite or Postgres).
        verbose:      If True, print unmatched examples.

    Returns:
        Summary dict with counts for brands and perfumes.
    """
    now = datetime.now(timezone.utc)

    # Ensure mapping tables exist in market DB (create_all is idempotent)
    engine = _make_engine(market_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # ----------------------------------------------------------------
    # Load all entities from both sides
    # ----------------------------------------------------------------
    backend = "postgres" if not market_url.startswith("sqlite") else f"sqlite ({market_url})"
    logger.info("Loading resolver brands from %s", resolver_db)
    legacy_brands   = _load_legacy_brands(resolver_db)
    logger.info("Loading market brands from %s", backend)
    market_brands   = _load_market_brands(market_url)

    logger.info("Loading resolver perfumes from %s", resolver_db)
    legacy_perfumes = _load_legacy_perfumes(resolver_db)
    logger.info("Loading market perfumes from %s", backend)
    market_perfumes = _load_market_perfumes(market_url)

    # ----------------------------------------------------------------
    # Build slug-keyed lookup for market side
    # ----------------------------------------------------------------
    # slug → {id: uuid_str, name: str, slug: str}
    market_brand_by_slug:   dict[str, dict] = {r["slug"]: r for r in market_brands}
    market_perfume_by_slug: dict[str, dict] = {r["slug"]: r for r in market_perfumes}

    # ----------------------------------------------------------------
    # Match and write brands
    # ----------------------------------------------------------------
    brand_mapped   = 0
    brand_new      = 0
    brand_unmatched: list[dict] = []

    with Session() as session:
        for lb in legacy_brands:
            slug = _slugify(lb["canonical_name"])
            mb   = market_brand_by_slug.get(slug)
            if mb is None:
                brand_unmatched.append(lb)
                continue
            is_new = _upsert_brand_map(
                session,
                resolver_brand_id=int(lb["id"]),
                market_brand_uuid=mb["id"],
                canonical_name=lb["canonical_name"],
                slug=slug,
                now=now,
            )
            brand_mapped += 1
            if is_new:
                brand_new += 1

        session.commit()
        logger.info(
            "Brands: legacy=%d market=%d mapped=%d unmatched=%d",
            len(legacy_brands), len(market_brands),
            brand_mapped, len(brand_unmatched),
        )

    # ----------------------------------------------------------------
    # Match and write perfumes
    # ----------------------------------------------------------------
    perfume_mapped   = 0
    perfume_new      = 0
    perfume_unmatched: list[dict] = []

    with Session() as session:
        for lp in legacy_perfumes:
            slug = _perfume_match_slug(lp["canonical_name"])
            mp   = market_perfume_by_slug.get(slug)
            if mp is None:
                perfume_unmatched.append(lp)
                continue
            is_new = _upsert_perfume_map(
                session,
                resolver_perfume_id=int(lp["id"]),
                market_perfume_uuid=mp["id"],
                canonical_name=lp["canonical_name"],
                slug=slug,
                now=now,
            )
            perfume_mapped += 1
            if is_new:
                perfume_new += 1

            if perfume_mapped % 500 == 0:
                session.flush()
                logger.info("Mapped %d perfumes so far…", perfume_mapped)

        session.commit()
        logger.info(
            "Perfumes: legacy=%d market=%d mapped=%d unmatched=%d",
            len(legacy_perfumes), len(market_perfumes),
            perfume_mapped, len(perfume_unmatched),
        )

    if verbose and brand_unmatched:
        print("\nUnmatched legacy brands (no market counterpart):")
        for ub in brand_unmatched[:20]:
            slug = _slugify(ub["canonical_name"])
            print(f"  id={ub['id']:>4}  slug={slug!r:40}  name={ub['canonical_name']!r}")
        if len(brand_unmatched) > 20:
            print(f"  … and {len(brand_unmatched) - 20} more")

    if verbose and perfume_unmatched:
        print("\nUnmatched legacy perfumes (no market counterpart):")
        for up in perfume_unmatched[:20]:
            slug = _perfume_match_slug(up["canonical_name"])
            print(f"  id={up['id']:>4}  slug={slug!r:50}  name={up['canonical_name']!r}")
        if len(perfume_unmatched) > 20:
            print(f"  … and {len(perfume_unmatched) - 20} more")

    return {
        "resolver_db": str(resolver_db),
        "market_url":  market_url,
        # brands
        "legacy_brands":    len(legacy_brands),
        "market_brands":    len(market_brands),
        "brand_mapped":     brand_mapped,
        "brand_new":        brand_new,
        "brand_unmatched":  len(brand_unmatched),
        "brand_unmatched_examples": [u["canonical_name"] for u in brand_unmatched[:5]],
        # perfumes
        "legacy_perfumes":    len(legacy_perfumes),
        "market_perfumes":    len(market_perfumes),
        "perfume_mapped":     perfume_mapped,
        "perfume_new":        perfume_new,
        "perfume_unmatched":  len(perfume_unmatched),
        "perfume_unmatched_examples": [u["canonical_name"] for u in perfume_unmatched[:5]],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Sync identity maps: resolver catalog ↔ market engine.\n\n"
            "Market DB selection (in priority order):\n"
            "  1. DATABASE_URL env var  → Railway / production Postgres\n"
            "  2. --market-db flag      → local SQLite (dev)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--resolver-db", default=str(DEFAULT_RESOLVER_DB),
        help="Path to resolver/catalog SQLite DB (default: outputs/pti.db)",
    )
    p.add_argument(
        "--market-db", default=None,
        help=(
            "Path to market engine SQLite DB for local dev. "
            "Not required when DATABASE_URL is set."
        ),
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Print unmatched examples",
    )
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    market_url = _resolve_market_url(args.market_db, database_url)

    backend = (
        f"postgres ({database_url.split('@')[-1]})" if database_url
        else f"sqlite ({args.market_db or DEFAULT_MARKET_DB})"
    )
    print(f"[sync_identity_map] resolver_db = {args.resolver_db}")
    print(f"[sync_identity_map] market_db   = {backend}")
    print()

    result = sync(args.resolver_db, market_url, verbose=args.verbose)

    print("\nIdentity map sync complete:")
    print(f"  Resolver DB : {result['resolver_db']}")
    print(f"  Market DB   : {result['market_url']}")
    print()
    print(f"  Brands  — legacy={result['legacy_brands']:>4}  market={result['market_brands']:>4}  "
          f"mapped={result['brand_mapped']:>4}  new={result['brand_new']:>4}  "
          f"unmatched={result['brand_unmatched']:>4}")
    print(f"  Perfumes— legacy={result['legacy_perfumes']:>4}  market={result['market_perfumes']:>4}  "
          f"mapped={result['perfume_mapped']:>4}  new={result['perfume_new']:>4}  "
          f"unmatched={result['perfume_unmatched']:>4}")

    if result["brand_unmatched_examples"]:
        print(f"\n  Unmatched brand examples: {result['brand_unmatched_examples']}")
    if result["perfume_unmatched_examples"]:
        print(f"  Unmatched perfume examples: {result['perfume_unmatched_examples']}")


if __name__ == "__main__":
    main()
