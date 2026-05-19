"""SIG-QA1 Type D Repair — Feel Good / Come Together / Bride To Be / Day to Day

Confirmed false-positive entities where the perfume name is a generic English
phrase and 0% of RS evidence contains any brand context token.

All 4 entities confirmed via full RS inspection (2026-05-19):
  Feel Good   (Esprit)          — 0/6 RS rows contain "esprit"
  Come Together (Vintner's Reserve) — 0/5 RS rows contain "vintner"
  Bride To Be (Primark)         — 0/3 RS rows contain "primark"
  Day to Day  (Primark)         — 0/4 RS rows contain "primark"

Repair scope (OPS-PV1 Repair Scope Compatibility Rule — full-history strip):
  1. Strip all RS rows for each canonical name (no --days window)
  2. Delete entity_mentions for each entity_id
  3. Delete entity_timeseries_daily for each entity_id
  4. Delete signals for each entity_id
  5. Delete signal_intelligence_snapshots for each entity_id
  6. Brand cleanup:
     - Esprit (374bb03d): DELETE ALL ts/signals — Feel Good is only tracked perfume
     - Vintner's Reserve (9a01b6f4): DELETE ALL ts/signals — pipeline recomputes
       from Banana Pudding (1 mention) + Blackberry Wine (1 mention)
     - Primark brand (15f87cfa): DELETE ALL ts/signals (3 rows) — pipeline
       recomputes from 12 other legitimate tracked perfumes

Usage:
    python3 scripts/sig_qa1_type_d_repair.py            # dry-run (default)
    python3 scripts/sig_qa1_type_d_repair.py --apply    # execute repair
"""

import argparse
import json
import os
import sys

import psycopg2
import psycopg2.extras


# ---------------------------------------------------------------------------
# Entities to repair
# ---------------------------------------------------------------------------

ENTITIES = [
    {
        "canonical_name": "Feel Good",
        "brand_name": "Esprit",
        "entity_id": "c2caa332-c9fa-4eef-9887-52b0ee448436",
    },
    {
        "canonical_name": "Come Together",
        "brand_name": "Vintner's Reserve",
        "entity_id": "b13d928a-849d-43c3-abc8-1317ad81e7ee",
    },
    {
        "canonical_name": "Bride To Be",
        "brand_name": "Primark",
        "entity_id": "a12020a5-f3c5-4a47-9d66-5f0de0a754a7",
    },
    {
        "canonical_name": "Day to Day",
        "brand_name": "Primark",
        "entity_id": "a76e080a-fb15-4311-bcaf-cf155c8ce091",
    },
]

# Brand entities to clean up after perfume-level repair.
# All are deleted entirely; pipeline recomputes from remaining legitimate perfumes.
BRAND_CLEANUPS = [
    {
        "brand_name": "Esprit",
        "entity_id": "374bb03d-618e-4e3e-aff2-2cd2511e83f4",
        "note": "Only tracked perfume was Feel Good (false) — full delete",
    },
    {
        "brand_name": "Vintner's Reserve",
        "entity_id": "9a01b6f4-46cf-4356-80d1-6bd7f329809f",
        "note": "Come Together (false, 5 mentions) was dominant; 2 small legit perfumes; pipeline recomputes",
    },
    {
        "brand_name": "Primark",
        "entity_id": "15f87cfa-0000-0000-0000-000000000000",  # placeholder — fetched at runtime
        "note": "3 brand ts rows; 12 other legit perfumes; pipeline recomputes",
    },
]


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    return url


def _strip_rs_rows(cur, canonical_name: str, dry_run: bool) -> int:
    """Remove canonical_name from resolved_entities_json in all RS rows.
    Returns number of rows updated."""
    cur.execute(
        """
        SELECT COUNT(*) FROM resolved_signals
        WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements(resolved_entities_json::jsonb) AS elem
            WHERE elem->>'canonical_name' = %s
        )
        """,
        (canonical_name,),
    )
    total = cur.fetchone()[0]
    if total == 0:
        return 0

    if dry_run:
        return total

    cur.execute(
        """
        UPDATE resolved_signals
        SET resolved_entities_json = (
            SELECT COALESCE(
                jsonb_agg(elem ORDER BY (elem->>'canonical_name')),
                '[]'::jsonb
            )::text
            FROM jsonb_array_elements(resolved_entities_json::jsonb) AS elem
            WHERE elem->>'canonical_name' != %s
        )
        WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements(resolved_entities_json::jsonb) AS elem
            WHERE elem->>'canonical_name' = %s
        )
        """,
        (canonical_name, canonical_name),
    )
    return cur.rowcount


def _count_rows(cur, table: str, entity_id: str) -> int:
    id_col = "entity_id"
    cur.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {id_col} = %s",
        (entity_id,),
    )
    return cur.fetchone()[0]


def _delete_rows(cur, table: str, entity_id: str) -> int:
    id_col = "entity_id"
    cur.execute(
        f"DELETE FROM {table} WHERE {id_col} = %s",
        (entity_id,),
    )
    return cur.rowcount


def run(dry_run: bool) -> None:
    conn = psycopg2.connect(_get_db_url())
    conn.autocommit = False

    try:
        # --- Fetch Primark brand entity_id at runtime ---
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM entity_market WHERE brand_name = 'Primark' AND entity_type = 'brand'",
            )
            row = cur.fetchone()
            if row:
                BRAND_CLEANUPS[2]["entity_id"] = str(row[0])
            else:
                print("WARNING: Primark brand entity not found — skipping brand cleanup")
                BRAND_CLEANUPS[2]["entity_id"] = None

        mode = "DRY-RUN" if dry_run else "APPLY"
        print(f"\n[sig-qa1-type-d] {mode} — repairing {len(ENTITIES)} Type D false-positive entities\n")

        total_rs = 0
        total_mentions = 0
        total_ts = 0
        total_signals = 0
        total_snaps = 0

        # --- Perfume-level repair ---
        with conn.cursor() as cur:
            for entity in ENTITIES:
                name = entity["canonical_name"]
                eid = entity["entity_id"]
                brand = entity["brand_name"]

                rs_count = _strip_rs_rows(cur, name, dry_run)
                mentions = _count_rows(cur, "entity_mentions", eid)
                ts = _count_rows(cur, "entity_timeseries_daily", eid)
                sigs = _count_rows(cur, "signals", eid)
                snaps = _count_rows(cur, "signal_intelligence_snapshots", eid)

                print(
                    f"  {name} ({brand}): RS={rs_count} mentions={mentions} "
                    f"ts={ts} signals={sigs} snaps={snaps}"
                )

                if not dry_run:
                    _delete_rows(cur, "entity_mentions", eid)
                    _delete_rows(cur, "entity_timeseries_daily", eid)
                    _delete_rows(cur, "signals", eid)
                    _delete_rows(cur, "signal_intelligence_snapshots", eid)

                total_rs += rs_count
                total_mentions += mentions
                total_ts += ts
                total_signals += sigs
                total_snaps += snaps

        print(f"\n  Perfume totals: RS={total_rs} mentions={total_mentions} "
              f"ts={total_ts} signals={total_signals} snaps={total_snaps}")

        # --- Brand-level repair ---
        print("\n[sig-qa1-type-d] Brand cleanup:")
        brand_ts_deleted = 0
        brand_sigs_deleted = 0

        with conn.cursor() as cur:
            for bc in BRAND_CLEANUPS:
                if bc["entity_id"] is None:
                    print(f"  {bc['brand_name']}: SKIPPED (entity not found)")
                    continue

                eid = bc["entity_id"]
                ts = _count_rows(cur, "entity_timeseries_daily", eid)
                sigs = _count_rows(cur, "signals", eid)
                print(f"  {bc['brand_name']}: ts={ts} signals={sigs} — {bc['note']}")

                if not dry_run:
                    _delete_rows(cur, "entity_timeseries_daily", eid)
                    _delete_rows(cur, "signals", eid)

                brand_ts_deleted += ts
                brand_sigs_deleted += sigs

        print(f"\n  Brand totals: ts={brand_ts_deleted} signals={brand_sigs_deleted}")

        if dry_run:
            conn.rollback()
            print("\n[sig-qa1-type-d] DRY-RUN complete — no changes written.")
            print("  Run with --apply to execute repair.")
        else:
            conn.commit()
            print("\n[sig-qa1-type-d] APPLY complete — all changes committed.")
            print(
                "\nPost-repair verification SQL:\n"
                "  SELECT COUNT(*) FROM entity_mentions WHERE entity_id IN (\n"
                "    'c2caa332-c9fa-4eef-9887-52b0ee448436',\n"
                "    'b13d928a-849d-43c3-abc8-1317ad81e7ee',\n"
                "    'a12020a5-f3c5-4a47-9d66-5f0de0a754a7',\n"
                "    'a76e080a-fb15-4311-bcaf-cf155c8ce091'\n"
                "  );  -- expect 0\n"
            )

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIG-QA1 Type D false-positive repair")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Execute repair (default is dry-run)",
    )
    args = parser.parse_args()
    run(dry_run=not args.apply)
