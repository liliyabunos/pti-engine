"""SIG-QA1 Batch 2 Repair — 12 False-Positive Entities

All 12 confirmed false positives via full RS inspection (2026-05-19).
RS evidence brand context rate: 0% across all rows for every entity.

Entities:
  White Musk (W.Dressroom)              — Type B note/ingredient collision
  Black Pepper (Demeter)                — Type B note/ingredient collision
  Apple Blossom (Auric Blends)          — Type B note/ingredient collision
  Bitter Orange (Zara)                  — Type B note/ingredient collision
  Earl Grey (Teone Reinthal)            — Type B note/ingredient collision
  Earl Grey Tea (Demeter)               — Type B note/ingredient collision
  Black Jeans (Versace)                 — Type C ordinary noun collision
  Black Suit (Ramon Monegal)            — Type C ordinary noun collision
  Green Tea (Coty)                      — Type D generic descriptor
  Hair Perfume (Balmain)                — Type D generic descriptor
  Bath & Body (Marbert)                 — Type D generic descriptor (category)
  Be Cool (Avon)                        — Type D generic descriptor

Repair scope (OPS-PV1 Repair Scope Compatibility Rule — full-history strip):
  1. Strip all RS rows for each canonical name (no --days window)
  2. Delete entity_mentions for each entity_id
  3. Delete entity_timeseries_daily for each entity_id
  4. Delete signals for each entity_id
  5. Delete signal_intelligence_snapshots for each entity_id
  6. Brand cleanup (OPS-EE1: delete brand ts/signals where all or majority of tracked
     perfumes were false-positive entities; let pipeline recompute from legitimate ones)

Usage:
    python3 scripts/sig_qa1_batch2_repair.py            # dry-run (default)
    python3 scripts/sig_qa1_batch2_repair.py --apply    # execute repair
"""

import argparse
import os
import sys

import psycopg2
import psycopg2.extras


# ---------------------------------------------------------------------------
# Entities to repair — queried at runtime by canonical_name
# ---------------------------------------------------------------------------

ENTITIES = [
    {"canonical_name": "White Musk",     "brand_name": "W.Dressroom"},
    {"canonical_name": "Black Pepper",   "brand_name": "Demeter"},
    {"canonical_name": "Apple Blossom",  "brand_name": "Auric Blends"},
    {"canonical_name": "Bitter Orange",  "brand_name": "Zara"},
    {"canonical_name": "Earl Grey",      "brand_name": "Teone Reinthal Natural Perfume"},
    {"canonical_name": "Earl Grey Tea",  "brand_name": "Demeter"},
    {"canonical_name": "Black Jeans",    "brand_name": "Versace"},
    {"canonical_name": "Black Suit",     "brand_name": "Ramon Monegal"},
    {"canonical_name": "Green Tea",      "brand_name": "Coty"},
    {"canonical_name": "Hair Perfume",   "brand_name": "Balmain"},
    {"canonical_name": "Bath & Body",    "brand_name": "Marbert"},
    {"canonical_name": "Be Cool",        "brand_name": "Avon"},
]

# ---------------------------------------------------------------------------
# Brand cleanup rules
# OPS-EE1: DELETE ALL brand ts/signals — pipeline recomputes from remaining
# legitimate perfumes. Only applied if brand entity exists.
# ---------------------------------------------------------------------------
# Note: brands with many other legitimate tracked perfumes (Versace, Coty, Zara,
# Balmain, Avon, Demeter) will have their ts/signals deleted too — the false-positive
# perfume may have been the only or dominant contributor to false brand scores.
# The pipeline will recompute correct brand scores from surviving legitimate perfumes
# on the next run.
#
# Brands with only 1–2 tracked perfumes where ALL are false-positive:
#   Auric Blends, Teone Reinthal Natural Perfume, Marbert, W.Dressroom, Ramon Monegal
# Brands with multiple legitimate perfumes (false-positive was one of many):
#   Versace, Coty, Zara, Balmain, Avon, Demeter (×2 entities)
#
# Per OPS-EE1: delete all brand ts/signals for ALL affected brands regardless of
# size. The pipeline will recompute from legitimate perfumes within hours.
# ---------------------------------------------------------------------------

BRAND_NAMES_TO_CLEAN = [
    "W.Dressroom",
    "Demeter",               # covers both Black Pepper + Earl Grey Tea
    "Auric Blends",
    "Zara",
    "Teone Reinthal Natural Perfume",
    "Versace",
    "Ramon Monegal",
    "Coty",
    "Balmain",
    "Marbert",
    "Avon",
]


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    return url


def _fetch_entity_id(cur, canonical_name: str, brand_name: str):
    """Fetch entity_id from entity_market for a perfume by canonical_name + brand_name."""
    cur.execute(
        """
        SELECT id FROM entity_market
        WHERE canonical_name = %s
          AND brand_name = %s
          AND entity_type = 'perfume'
        LIMIT 1
        """,
        (canonical_name, brand_name),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def _fetch_brand_entity_id(cur, brand_name: str):
    """Fetch entity_id for a brand entity by brand_name."""
    cur.execute(
        """
        SELECT id FROM entity_market
        WHERE brand_name = %s
          AND entity_type = 'brand'
        LIMIT 1
        """,
        (brand_name,),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


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
    cur.execute(
        f"SELECT COUNT(*) FROM {table} WHERE entity_id = %s",
        (entity_id,),
    )
    return cur.fetchone()[0]


def _delete_rows(cur, table: str, entity_id: str) -> int:
    cur.execute(
        f"DELETE FROM {table} WHERE entity_id = %s",
        (entity_id,),
    )
    return cur.rowcount


def run(dry_run: bool) -> None:
    conn = psycopg2.connect(_get_db_url())
    conn.autocommit = False

    try:
        mode = "DRY-RUN" if dry_run else "APPLY"
        print(f"\n[sig-qa1-batch2] {mode} — repairing {len(ENTITIES)} Batch 2 false-positive entities\n")

        # Fetch entity_ids at runtime
        with conn.cursor() as cur:
            for entity in ENTITIES:
                eid = _fetch_entity_id(cur, entity["canonical_name"], entity["brand_name"])
                entity["entity_id"] = eid
                if not eid:
                    print(f"  WARNING: {entity['canonical_name']} ({entity['brand_name']}) — entity_id not found in entity_market")

        # Perfume-level repair
        total_rs = total_mentions = total_ts = total_signals = total_snaps = 0

        with conn.cursor() as cur:
            for entity in ENTITIES:
                name = entity["canonical_name"]
                eid = entity.get("entity_id")
                brand = entity["brand_name"]

                rs_count = _strip_rs_rows(cur, name, dry_run)

                if eid:
                    mentions = _count_rows(cur, "entity_mentions", eid)
                    ts       = _count_rows(cur, "entity_timeseries_daily", eid)
                    sigs     = _count_rows(cur, "signals", eid)
                    snaps    = _count_rows(cur, "signal_intelligence_snapshots", eid)
                else:
                    mentions = ts = sigs = snaps = 0

                print(
                    f"  {name} ({brand}): RS={rs_count} mentions={mentions} "
                    f"ts={ts} signals={sigs} snaps={snaps}"
                    + ("  [entity_id not found — skip downstream]" if not eid else "")
                )

                if not dry_run and eid:
                    _delete_rows(cur, "entity_mentions", eid)
                    _delete_rows(cur, "entity_timeseries_daily", eid)
                    _delete_rows(cur, "signals", eid)
                    _delete_rows(cur, "signal_intelligence_snapshots", eid)

                total_rs       += rs_count
                total_mentions += mentions
                total_ts       += ts
                total_signals  += sigs
                total_snaps    += snaps

        print(
            f"\n  Perfume totals: RS={total_rs} mentions={total_mentions} "
            f"ts={total_ts} signals={total_signals} snaps={total_snaps}"
        )

        # Brand-level repair (OPS-EE1)
        print("\n[sig-qa1-batch2] Brand cleanup (OPS-EE1 — delete all, pipeline recomputes):")
        brand_ts_total = brand_sigs_total = 0

        with conn.cursor() as cur:
            for brand_name in BRAND_NAMES_TO_CLEAN:
                eid = _fetch_brand_entity_id(cur, brand_name)
                if not eid:
                    print(f"  {brand_name}: SKIPPED (brand entity not found)")
                    continue

                ts   = _count_rows(cur, "entity_timeseries_daily", eid)
                sigs = _count_rows(cur, "signals", eid)
                print(f"  {brand_name}: ts={ts} signals={sigs}")

                if not dry_run:
                    _delete_rows(cur, "entity_timeseries_daily", eid)
                    _delete_rows(cur, "signals", eid)

                brand_ts_total   += ts
                brand_sigs_total += sigs

        print(f"\n  Brand totals: ts={brand_ts_total} signals={brand_sigs_total}")

        if dry_run:
            conn.rollback()
            print("\n[sig-qa1-batch2] DRY-RUN complete — no changes written.")
            print("  Run with --apply to execute repair.")
        else:
            conn.commit()
            print("\n[sig-qa1-batch2] APPLY complete — all changes committed.")
            print(
                "\nPost-repair verification SQL:\n"
                "  SELECT canonical_name, COUNT(*) FROM entity_mentions em\n"
                "  JOIN entity_market eml ON eml.id = em.entity_id\n"
                "  WHERE eml.canonical_name IN (\n"
                "    'White Musk','Black Pepper','Apple Blossom','Bitter Orange',\n"
                "    'Earl Grey','Earl Grey Tea','Black Jeans','Black Suit',\n"
                "    'Green Tea','Hair Perfume','Bath & Body','Be Cool'\n"
                "  ) GROUP BY canonical_name;  -- expect 0 rows\n"
            )

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIG-QA1 Batch 2 false-positive repair")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Execute repair (default is dry-run)",
    )
    args = parser.parse_args()
    run(dry_run=not args.apply)
