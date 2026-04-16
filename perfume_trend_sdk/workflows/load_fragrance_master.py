from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

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


def ingest_seed_csv(csv_path: Path, db_path: Path) -> None:
    store = FragranceMasterStore(str(db_path))
    store.init_schema()

    rows = load_seed_rows(csv_path)

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

        perfume_id = store.upsert_perfume(
            PerfumeRecord(
                brand_id=brand_id,
                canonical_name=canonical_full_name,
                normalized_name=normalized_full_name,
                default_concentration=None,
            )
        )

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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Load fragrance master seed CSV into the resolver SQLite DB.\n\n"
            "This populates brands, perfumes, and aliases in the local resolver\n"
            "catalog (pti.db). After running this, run sync_identity_map.py to\n"
            "link resolver Integer IDs to market engine UUIDs in Postgres."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--csv", required=True, help="Path to seed CSV")
    parser.add_argument("--db", required=True, help="Path to resolver SQLite DB (e.g. outputs/pti.db)")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    ingest_seed_csv(Path(args.csv), Path(args.db))
    print("fragrance_master seed load completed")


if __name__ == "__main__":
    main()
