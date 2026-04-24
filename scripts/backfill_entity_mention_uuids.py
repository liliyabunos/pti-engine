from __future__ import annotations

"""
Backfill entity_mentions.entity_id to use entity_market.id.

Historical entity_mentions were written with perfume_identity_map.market_perfume_uuid
instead of entity_market.id. These two UUIDs are different for the same entity.

This script bridges via canonical_name:
    entity_mentions.entity_id → perfume_identity_map (market_perfume_uuid → canonical_name)
                              → entity_market (canonical_name → id)

Then updates entity_mentions.entity_id to the correct entity_market.id.

Idempotent: skips rows already using the correct UUID.
Safe: only updates rows where a confirmed canonical_name match exists.

Usage:
    python scripts/backfill_entity_mention_uuids.py --dry-run
    python scripts/backfill_entity_mention_uuids.py
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from perfume_trend_sdk.storage.postgres.db import session_scope


def backfill(dry_run: bool = True) -> dict:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[backfill_entity_mention_uuids] ERROR: DATABASE_URL not set.")
        sys.exit(1)

    print(f"[backfill_entity_mention_uuids] dry_run={dry_run}")

    with session_scope() as db:
        # Build mapping: old_uuid → new_uuid via canonical_name bridge.
        # Use DISTINCT ON to guard against duplicate canonical_names in entity_market
        # (e.g. "Alguien" has 2 rows — pick the highest-score one).
        # old_uuid = perfume_identity_map.market_perfume_uuid (what entity_mentions uses)
        # new_uuid = entity_market.id (what API queries use)
        mapping_rows = db.execute(text("""
            SELECT DISTINCT ON (pim.market_perfume_uuid)
                pim.market_perfume_uuid  AS old_uuid,
                em.id::text              AS new_uuid,
                pim.canonical_name
            FROM perfume_identity_map pim
            JOIN entity_market em ON em.canonical_name = pim.canonical_name
            WHERE pim.market_perfume_uuid::text != em.id::text
            ORDER BY pim.market_perfume_uuid, em.id
        """)).fetchall()

        mapping = {
            row[0]: (row[1], row[2])
            for row in mapping_rows
        }

        print(f"  UUID pairs needing fix (pim mismatch with entity_market): {len(mapping)}")

        # Also build brand mapping
        brand_mapping_rows = db.execute(text("""
            SELECT DISTINCT ON (bim.market_brand_uuid)
                bim.market_brand_uuid    AS old_uuid,
                em.id::text              AS new_uuid,
                bim.canonical_name
            FROM brand_identity_map bim
            JOIN entity_market em ON em.canonical_name = bim.canonical_name
            WHERE bim.market_brand_uuid::text != em.id::text
            ORDER BY bim.market_brand_uuid, em.id
        """)).fetchall()

        brand_mapping = {
            row[0]: (row[1], row[2])
            for row in brand_mapping_rows
        }
        print(f"  Brand UUID pairs needing fix: {len(brand_mapping)}")

        # Count affected entity_mentions rows (perfume)
        affected_perfume = db.execute(text("""
            SELECT COUNT(*) FROM entity_mentions
            WHERE entity_id::text = ANY(:old_uuids)
        """), {"old_uuids": list(mapping.keys())}).scalar()

        # Count affected entity_mentions rows (brand)
        affected_brand = db.execute(text("""
            SELECT COUNT(*) FROM entity_mentions
            WHERE entity_id::text = ANY(:old_uuids)
        """), {"old_uuids": list(brand_mapping.keys())}).scalar()

        print(f"  entity_mentions rows to fix (perfume): {affected_perfume}")
        print(f"  entity_mentions rows to fix (brand):   {affected_brand}")
        print(f"  entity_mentions rows to fix (total):   {affected_perfume + affected_brand}")

        if dry_run:
            print()
            print("  dry_run=True — no writes performed")
            print()
            print("  Sample mappings (first 5):")
            for old_uuid, (new_uuid, canonical) in list(mapping.items())[:5]:
                count = db.execute(text(
                    "SELECT COUNT(*) FROM entity_mentions WHERE entity_id::text = :uid"
                ), {"uid": old_uuid}).scalar()
                print(f"    [{canonical}]")
                print(f"      old: {old_uuid}")
                print(f"      new: {new_uuid}")
                print(f"      rows: {count}")
            return {
                "dry_run": True,
                "uuid_pairs": len(mapping) + len(brand_mapping),
                "rows_to_fix": affected_perfume + affected_brand,
            }

        # Execute updates in batches
        total_updated = 0

        # Update perfume entity_mentions
        for old_uuid, (new_uuid, canonical) in mapping.items():
            result = db.execute(text(
                f"UPDATE entity_mentions SET entity_id = '{new_uuid}'::uuid "
                f"WHERE entity_id::text = :old_uuid"
            ), {"old_uuid": old_uuid})
            total_updated += result.rowcount

        # Update brand entity_mentions
        for old_uuid, (new_uuid, canonical) in brand_mapping.items():
            result = db.execute(text(
                f"UPDATE entity_mentions SET entity_id = '{new_uuid}'::uuid "
                f"WHERE entity_id::text = :old_uuid"
            ), {"old_uuid": old_uuid})
            total_updated += result.rowcount

        db.commit()
        print(f"  Pass 1 updated: {total_updated} entity_mentions rows (exact canonical match)")

        # Pass 2: Concentration-suffix bridge
        # For pim entries like "Juliette Has a Gun Anyway Eau de Parfum" where stripping the
        # suffix matches an entity_market row "Juliette Has a Gun Anyway", re-link those mentions.
        _SUFFIX_PATTERN = (
            " (Extrait de Parfum|Eau de Parfum|Eau de Toilette|"
            "Eau de Cologne|Eau Fraiche|Extrait|Parfum)$"
        )
        conc_rows = db.execute(text(f"""
            SELECT DISTINCT ON (pim.market_perfume_uuid)
                pim.market_perfume_uuid::text  AS old_uuid,
                em.id::text                    AS new_uuid,
                pim.canonical_name             AS pim_name,
                em.canonical_name              AS em_name
            FROM perfume_identity_map pim
            JOIN entity_market em ON em.canonical_name = REGEXP_REPLACE(
                pim.canonical_name, '{_SUFFIX_PATTERN}', '', 'i'
            )
            WHERE pim.market_perfume_uuid::text != em.id::text
              AND em.entity_type = 'perfume'
              -- only fix rows not already on the correct UUID
              AND EXISTS (
                  SELECT 1 FROM entity_mentions ment
                  WHERE ment.entity_id::text = pim.market_perfume_uuid::text
                    AND NOT EXISTS (SELECT 1 FROM entity_market em2 WHERE em2.id = ment.entity_id)
              )
            ORDER BY pim.market_perfume_uuid, em.id
        """)).fetchall()

        print(f"  Pass 2: concentration-suffix UUID pairs to fix: {len(conc_rows)}")
        pass2_updated = 0
        for row in conc_rows:
            old_uuid, new_uuid = row[0], row[1]
            result = db.execute(text(
                f"UPDATE entity_mentions SET entity_id = '{new_uuid}'::uuid "
                f"WHERE entity_id::text = :old_uuid"
            ), {"old_uuid": old_uuid})
            pass2_updated += result.rowcount

        db.commit()
        total_updated += pass2_updated
        print(f"  Pass 2 updated: {pass2_updated} entity_mentions rows (concentration suffix bridge)")
        print(f"  Total updated: {total_updated}")

        # Verify: count how many still use old UUIDs
        still_wrong = db.execute(text("""
            SELECT COUNT(*) FROM entity_mentions
            WHERE entity_id::text = ANY(:old_uuids)
        """), {"old_uuids": list(mapping.keys()) + list(brand_mapping.keys())}).scalar()
        print(f"  Still wrong (pass-1 targets): {still_wrong}")

        # Count now correctly linked
        correct = db.execute(text("""
            SELECT COUNT(*) FROM entity_mentions ment
            WHERE EXISTS (SELECT 1 FROM entity_market em WHERE em.id = ment.entity_id)
        """)).scalar()
        total = db.execute(text("SELECT COUNT(*) FROM entity_mentions")).scalar()
        print(f"  Correctly linked (entity_market.id match): {correct}/{total}")

    return {
        "dry_run": False,
        "uuid_pairs": len(mapping) + len(brand_mapping),
        "rows_updated": total_updated,
        "still_wrong": still_wrong,
        "correctly_linked": correct,
        "total": total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix entity_mentions.entity_id to use entity_market.id"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Preview only — no writes"
    )
    args = parser.parse_args()

    result = backfill(dry_run=args.dry_run)
    print()
    print("[backfill_entity_mention_uuids] Done.", result)


if __name__ == "__main__":
    main()
