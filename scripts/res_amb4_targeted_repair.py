"""RES-AMB4 — Production Repair Script.

Strips 8 confirmed false-positive perfume entities from all data layers:
  - resolved_signals (full-history, per OPS-PV1 Repair Scope Compatibility Rule)
  - entity_mentions
  - entity_timeseries_daily
  - signals
  - signal_intelligence_snapshots
  - Brand rollup cleanup: delete brand ts + signals for all 8 brands
    (let next pipeline recompute legitimate brand data — OPS-EE1 efficient path)

False-positive entities (confirmed via production RS inspection — all 0% brand hit rate):
  1. I will           (Femascu)           b52d1e87-...
  2. Very Pretty      (Michael Kors)      5866c340-...
  3. So Sexy!         (Fiorucci)          3838b920-...
  4. Day One          (Smell Bent)        24e0124e-...
  5. Best Man         (Helena Rubinstein) ae5efdbb-...
  6. You & You        (Puig)              2c64976b-...
  7. Jasmine & Rose   (Primark)           bbc44c51-...
  8. Cedar Wood       (Monotheme)         8c92d0a9-...

Brand rollup cleanup (delete all ts + signals — let pipeline recompute):
  Femascu             7127bbbd-...   (100% FP)
  Michael Kors        28297982-...   (mixed)
  Fiorucci            b4232de3-...   (mixed)
  Smell Bent          0936963a-...   (100% FP)
  Helena Rubinstein   533655b8-...   (mixed)
  Puig                191a8317-...   (100% FP)
  Primark             15f87cfa-...   (mixed)
  Monotheme           18fae14a-...   (mixed)

OPS-EE1 choice: delete ALL brand ts + signals for all 8 brands. Next pipeline
run will recompute legitimate brand data from clean RS rows.

Usage:
    DATABASE_URL=<prod-url> python3 scripts/res_amb4_targeted_repair.py --dry-run
    DATABASE_URL=<prod-url> python3 scripts/res_amb4_targeted_repair.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

import psycopg2

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Config — canonical names verified from production entity_market (2026-05-17)
# ---------------------------------------------------------------------------

FALSE_POSITIVE_PERFUMES: List[Dict[str, Any]] = [
    {
        "canonical_name": "I will",          # lowercase 'w' — confirmed in entity_market
        "brand": "Femascu",
        "reason": "future-tense sentence construction; 140 false mentions; 0% RS brand hit",
    },
    {
        "canonical_name": "Very Pretty",
        "brand": "Michael Kors",
        "reason": "adjective descriptor; 0% MK brand hit in RS",
    },
    {
        "canonical_name": "So Sexy!",
        "brand": "Fiorucci",
        "reason": "exclamation phrase; 0% Fiorucci brand hit in RS",
    },
    {
        "canonical_name": "Day One",
        "brand": "Smell Bent",
        "reason": "temporal phrase; wedding/fragrance Reddit + YouTube",
    },
    {
        "canonical_name": "Best Man",
        "brand": "Helena Rubinstein",
        "reason": "wedding speech + fragrance phrase; 0% HR brand hit in RS",
    },
    {
        "canonical_name": "You & You",
        "brand": "Puig",
        "reason": "conversational phrase; 0% Puig brand hit in RS",
    },
    {
        "canonical_name": "Jasmine & Rose",
        "brand": "Primark",
        "reason": "note/ingredient description; 0% Primark brand hit in RS",
    },
    {
        "canonical_name": "Cedar Wood",
        "brand": "Monotheme",
        "reason": "note name; 0% Monotheme brand hit in RS",
    },
]

FP_BRAND_ENTITIES: List[Dict[str, Any]] = [
    {"brand_name": "Femascu",           "pct_fp": "100%"},
    {"brand_name": "Michael Kors",      "pct_fp": "mixed"},
    {"brand_name": "Fiorucci",          "pct_fp": "mixed"},
    {"brand_name": "Smell Bent",        "pct_fp": "100%"},
    {"brand_name": "Helena Rubinstein", "pct_fp": "mixed"},
    {"brand_name": "Puig",              "pct_fp": "100%"},
    {"brand_name": "Primark",           "pct_fp": "mixed"},
    {"brand_name": "Monotheme",         "pct_fp": "mixed"},
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("ERROR: DATABASE_URL env var not set")
    return psycopg2.connect(url)


def _fetchone(conn, sql: str, params: tuple = ()) -> Optional[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _count(conn, sql: str, params: tuple = ()) -> int:
    row = _fetchone(conn, sql, params)
    return row[0] if row else 0


def _execute(conn, sql: str, params: tuple = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _resolve_entity_id(conn, canonical_name: str, entity_type: str) -> Optional[str]:
    row = _fetchone(
        conn,
        "SELECT id::text FROM entity_market WHERE entity_type=%s AND canonical_name=%s LIMIT 1",
        (entity_type, canonical_name),
    )
    return row[0] if row else None


def _brand_entity_id(conn, brand_name: str) -> Optional[str]:
    return _resolve_entity_id(conn, brand_name, "brand")


# ---------------------------------------------------------------------------
# Count queries for dry-run
# ---------------------------------------------------------------------------

def _count_rs_affected(conn, canonical_name: str) -> int:
    return _count(
        conn,
        """SELECT COUNT(*) FROM resolved_signals
           WHERE resolved_entities_json::jsonb @> jsonb_build_array(
               jsonb_build_object('canonical_name', %s)
           )""",
        (canonical_name,),
    )


def _count_mentions(conn, entity_id: str) -> int:
    return _count(conn, "SELECT COUNT(*) FROM entity_mentions WHERE entity_id=%s::uuid", (entity_id,))


def _count_timeseries(conn, entity_id: str) -> int:
    return _count(conn, "SELECT COUNT(*) FROM entity_timeseries_daily WHERE entity_id=%s::uuid", (entity_id,))


def _count_signals(conn, entity_id: str) -> int:
    return _count(conn, "SELECT COUNT(*) FROM signals WHERE entity_id=%s::uuid", (entity_id,))


def _count_snapshots(conn, entity_id: str) -> int:
    return _count(conn, "SELECT COUNT(*) FROM signal_intelligence_snapshots WHERE entity_id=%s::uuid", (entity_id,))


# ---------------------------------------------------------------------------
# Repair operations (apply mode)
# ---------------------------------------------------------------------------

def _strip_rs(conn, canonical_name: str) -> int:
    # COALESCE handles the case where the entity was the only one in the array
    # (jsonb_agg returns NULL for empty input → '[]' is the correct empty result).
    return _execute(
        conn,
        """UPDATE resolved_signals
           SET resolved_entities_json = COALESCE(
               (
                   SELECT jsonb_agg(elem)::text
                   FROM jsonb_array_elements(resolved_entities_json::jsonb) AS elem
                   WHERE elem->>'canonical_name' != %s
               ),
               '[]'
           )
           WHERE resolved_entities_json::jsonb @> jsonb_build_array(
               jsonb_build_object('canonical_name', %s)
           )""",
        (canonical_name, canonical_name),
    )


def _del_mentions(conn, eid: str) -> int:
    return _execute(conn, "DELETE FROM entity_mentions WHERE entity_id=%s::uuid", (eid,))


def _del_timeseries(conn, eid: str) -> int:
    return _execute(conn, "DELETE FROM entity_timeseries_daily WHERE entity_id=%s::uuid", (eid,))


def _del_signals(conn, eid: str) -> int:
    return _execute(conn, "DELETE FROM signals WHERE entity_id=%s::uuid", (eid,))


def _del_snapshots(conn, eid: str) -> int:
    return _execute(conn, "DELETE FROM signal_intelligence_snapshots WHERE entity_id=%s::uuid", (eid,))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n=== RES-AMB4 Repair ({mode}) ===\n")

    conn = _connect()

    # -----------------------------------------------------------------------
    # Phase 1 — Perfume entity cleanup
    # -----------------------------------------------------------------------
    print("--- Phase 1: Perfume entity cleanup ---\n")

    total_rs = 0
    total_mentions = 0
    total_ts = 0
    total_sigs = 0
    total_snaps = 0

    for ent in FALSE_POSITIVE_PERFUMES:
        cname = ent["canonical_name"]
        print(f"  [{cname}] ({ent['brand']})")

        entity_id = _resolve_entity_id(conn, cname, "perfume")
        if entity_id:
            print(f"    entity_id: {entity_id}")
        else:
            print(f"    WARNING: not found in entity_market — will still strip RS rows")

        if dry_run:
            rs_c = _count_rs_affected(conn, cname)
            men_c = _count_mentions(conn, entity_id) if entity_id else 0
            ts_c = _count_timeseries(conn, entity_id) if entity_id else 0
            sig_c = _count_signals(conn, entity_id) if entity_id else 0
            snap_c = _count_snapshots(conn, entity_id) if entity_id else 0
            print(f"    would update RS rows:        {rs_c}")
            print(f"    would delete mentions:       {men_c}")
            print(f"    would delete ts:             {ts_c}")
            print(f"    would delete signals:        {sig_c}")
            print(f"    would delete snapshots:      {snap_c}")
        else:
            rs_c = _strip_rs(conn, cname)
            men_c = _del_mentions(conn, entity_id) if entity_id else 0
            ts_c = _del_timeseries(conn, entity_id) if entity_id else 0
            sig_c = _del_signals(conn, entity_id) if entity_id else 0
            snap_c = _del_snapshots(conn, entity_id) if entity_id else 0
            conn.commit()

            # Verify RS residuals
            residuals = _count_rs_affected(conn, cname)
            status = "✓ CLEAN" if residuals == 0 else f"✗ {residuals} REMAINING"
            print(f"    RS strip:                    {rs_c} updated  — {status}")
            print(f"    mentions deleted:            {men_c}")
            print(f"    ts deleted:                  {ts_c}")
            print(f"    signals deleted:             {sig_c}")
            print(f"    snapshots deleted:           {snap_c}")

        total_rs += rs_c
        total_mentions += men_c
        total_ts += ts_c
        total_sigs += sig_c
        total_snaps += snap_c
        print()

    verb = "would" if dry_run else "DONE"
    print(f"  Phase 1 totals ({verb}):")
    print(f"    RS rows:    {total_rs}")
    print(f"    mentions:   {total_mentions}")
    print(f"    ts:         {total_ts}")
    print(f"    signals:    {total_sigs}")
    print(f"    snapshots:  {total_snaps}")

    # -----------------------------------------------------------------------
    # Phase 2 — Brand entity cleanup
    # -----------------------------------------------------------------------
    print("\n--- Phase 2: Brand entity cleanup ---\n")

    btotal_ts = 0
    btotal_sigs = 0

    for brand in FP_BRAND_ENTITIES:
        bname = brand["brand_name"]
        eid = _brand_entity_id(conn, bname)

        if not eid:
            print(f"  [{bname}] — not found in entity_market (clean or never created)")
            continue

        if dry_run:
            ts_c = _count_timeseries(conn, eid)
            sig_c = _count_signals(conn, eid)
            snap_c = _count_snapshots(conn, eid)
            print(f"  [{bname}] ({brand['pct_fp']} FP) entity_id={eid}")
            print(f"    would delete ts:      {ts_c}")
            print(f"    would delete signals: {sig_c}")
            print(f"    would delete snaps:   {snap_c}")
        else:
            ts_c = _del_timeseries(conn, eid)
            sig_c = _del_signals(conn, eid)
            snap_c = _del_snapshots(conn, eid)
            conn.commit()
            print(f"  [{bname}] ({brand['pct_fp']} FP) entity_id={eid}")
            print(f"    ts deleted:      {ts_c}")
            print(f"    signals deleted: {sig_c}")
            print(f"    snaps deleted:   {snap_c}")

        btotal_ts += ts_c
        btotal_sigs += sig_c

    print(f"\n  Phase 2 totals ({verb}):")
    print(f"    brand ts:       {btotal_ts}")
    print(f"    brand signals:  {btotal_sigs}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n=== {mode} COMPLETE ===")
    if dry_run:
        print("Run with --apply to execute against production.")
    else:
        print("Repair applied. Next pipeline run recomputes brand data from clean RS rows.")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RES-AMB4 production repair")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
