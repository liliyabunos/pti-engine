from __future__ import annotations

import argparse
import csv
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


@dataclass
class SeedRow:
    fragrance_id: str
    brand_name: str
    perfume_name: str
    release_year: int | None
    gender: str | None
    source: str


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
            brand_name = (row.get("brand_name") or "").strip()
            perfume_name = (row.get("perfume_name") or "").strip()
            source = (row.get("source") or "").strip()

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


def _make_store(db_path: str | None, database_url: str | None):
    """Return the appropriate store for the current environment."""
    if database_url:
        from perfume_trend_sdk.storage.entities.pg_fragrance_master_store import (
            PgFragranceMasterStore,
        )
        return PgFragranceMasterStore(database_url)
    if db_path:
        return FragranceMasterStore(db_path)
    raise RuntimeError(
        "No database configured. Set DATABASE_URL (Postgres) or pass --db (SQLite)."
    )


def ingest_seed_csv(csv_path: Path, store) -> dict:
    """
    Load seed CSV into the given store (SQLite or Postgres).

    Returns a summary dict with row counts.
    """
    store.init_schema()
    rows = load_seed_rows(csv_path)

    brands_upserted = 0
    perfumes_upserted = 0
    aliases_upserted = 0

    for row in rows:
        normalized_brand = normalize_text(row.brand_name)
        canonical_perfume_name = row.perfume_name.strip()
        canonical_brand_name = row.brand_name.strip()
        canonical_full_name = f"{canonical_brand_name} {canonical_perfume_name}".strip()
        normalized_full_name = normalize_text(canonical_full_name)

        brand_id = store.upsert_brand(
            BrandRecord(
                canonical_name=canonical_brand_name,
                normalized_name=normalized_brand,
            )
        )
        brands_upserted += 1

        perfume_id = store.upsert_perfume(
            PerfumeRecord(
                brand_id=brand_id,
                canonical_name=canonical_full_name,
                normalized_name=normalized_full_name,
                default_concentration=None,
            )
        )
        perfumes_upserted += 1

        brand_aliases = [
            AliasRecord(
                alias_text=alias,
                normalized_alias_text=normalize_text(alias),
                entity_type="brand",
                entity_id=brand_id,
                match_type="exact",
                confidence=1.0,
            )
            for alias in generate_brand_aliases(canonical_brand_name)
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
            for alias in generate_perfume_aliases(canonical_brand_name, canonical_perfume_name)
        ]

        store.upsert_aliases(brand_aliases)
        store.upsert_aliases(perfume_aliases)
        aliases_upserted += len(brand_aliases) + len(perfume_aliases)

        store.upsert_fragrance_master_row(
            fragrance_id=row.fragrance_id,
            brand_name=canonical_brand_name,
            perfume_name=canonical_perfume_name,
            canonical_name=canonical_full_name,
            normalized_name=normalized_full_name,
            release_year=row.release_year,
            gender=row.gender,
            source=row.source,
            brand_id=brand_id,
            perfume_id=perfume_id,
        )

    return {
        "seed_rows": len(rows),
        "brands_upserted": brands_upserted,
        "perfumes_upserted": perfumes_upserted,
        "aliases_upserted": aliases_upserted,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Load fragrance master seed CSV into SQLite or Postgres.\n\n"
            "Backend selection (in priority order):\n"
            "  1. DATABASE_URL env var → Postgres (Railway / production)\n"
            "  2. --db flag            → SQLite (local development)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--csv", required=True, help="Path to seed CSV")
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "Path to SQLite DB for local development. "
            "Not required when DATABASE_URL is set."
        ),
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    db_path = args.db

    if not database_url and not db_path:
        print(
            "ERROR: no database configured.\n"
            "  For Postgres: set DATABASE_URL in your environment.\n"
            "  For SQLite:   pass --db <path>.",
            file=sys.stderr,
        )
        sys.exit(1)

    store = _make_store(db_path, database_url)
    backend = f"postgres ({database_url.split('@')[-1]})" if database_url else f"sqlite ({db_path})"
    print(f"[load_fragrance_master] backend = {backend}")
    print(f"[load_fragrance_master] csv     = {args.csv}")
    print()

    summary = ingest_seed_csv(Path(args.csv), store)

    print("[load_fragrance_master] Done.")
    print(f"  seed rows processed : {summary['seed_rows']}")
    print(f"  brands upserted     : {summary['brands_upserted']}")
    print(f"  perfumes upserted   : {summary['perfumes_upserted']}")
    print(f"  aliases upserted    : {summary['aliases_upserted']}")


if __name__ == "__main__":
    main()
