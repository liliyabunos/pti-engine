#!/usr/bin/env python3
"""DATA4-D — Encoding Mismatch Repair + Orphan Brand Name Fix

Two repair phases:

PHASE 1 — Structural Fragment Orphan Repair
  Perfume entity_market rows where brand_name is a structural fragment
  (ends in & or | or &amp;) but no ghost brand entity was created (DATA4-B
  guard blocked entity creation after the fact, but the perfume row still
  carries the malformed brand_name).

  Strategy: resolve correct brand via resolver_fragrance_master, then UPDATE
  entity_market.brand_name for the perfume row only.

PHASE 2 — DATA4-D Encoding Mismatch Repair
  Perfume entity_market rows where brand_name is an encoding variant that
  doesn't match the canonical resolver_brands entry:
    - Accented forms vs ASCII  (Comme des Garçons vs Garcons)
    - Multilingual variants    (Khadlaj vs Khadlaj / خدلج)

  Strategy:
    1. UPDATE perfume rows: brand_name → correct canonical form
    2. DELETE ghost brand entity + downstream (etd, signals, snapshots)
    3. Print date range that needs aggregation recompute (run manually after)

Explicit EXCLUSIONS (same as DATA4-B):
  - TOM FORD Private Blend (DATA4-C scope)
  - Brands already fixed by DATA4-B (structural fragments already repaired)

Repair-Complete Rule applies:
  1. Fix upstream (entity_market.perfume.brand_name) FIRST
  2. Then delete downstream ghost brand entity + timeseries/signals/snapshots
  3. Then re-run aggregation for affected dates (operator runs manually after)

Usage:
    # Dry run (default):
    DATABASE_URL=<prod-url> python3 scripts/data4d_encoding_repair.py

    # Apply:
    DATABASE_URL=<prod-url> python3 scripts/data4d_encoding_repair.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras


# ---------------------------------------------------------------------------
# DATA4-D encoding correction registry
# Format: (wrong_brand_name_on_perfume_rows, correct_brand_name)
# The ghost entity to delete has canonical_name == wrong_brand_name
# ---------------------------------------------------------------------------

ENCODING_CORRECTIONS: List[Tuple[str, str]] = [
    # Accented ghost brand entity; perfumes use accented form → fix to ASCII
    ("Comme des Garçons", "Comme des Garcons"),
    ("Areej Le Doré", "Areej Le Dore"),
    ("Ramón Monegal", "Ramon Monegal"),
    # Multilingual ghost brand entity; perfumes use simplified form → fix to multilingual
    ("Khadlaj", "Khadlaj / خدلج"),
    ("Al Haramain", "Al Haramain / الحرمين"),
    # Ghost entity has multilingual form; perfumes use simplified form
    ("Lattafa / لطافة", "Lattafa"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("ERROR: DATABASE_URL environment variable not set.")
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def _print_header(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")


def _print_section(title: str) -> None:
    print(f"\n--- {title} ---")


def _resolve_correct_brand(cur, canonical_name: str) -> Optional[str]:
    """Look up the correct brand_name for a perfume via resolver_fragrance_master."""
    norm = canonical_name.lower().strip()
    cur.execute("""
        SELECT rfm.brand_name
        FROM resolver_fragrance_master rfm
        JOIN resolver_perfumes rp ON rp.id = rfm.perfume_id
        WHERE LOWER(rp.canonical_name) = %s
        LIMIT 1
    """, (norm,))
    row = cur.fetchone()
    if row:
        return row["brand_name"]

    # Suffix-normalized form (DATA2 pattern)
    cur.execute("""
        SELECT rfm.brand_name
        FROM resolver_fragrance_master rfm
        JOIN resolver_perfumes rp ON rp.id = rfm.perfume_id
        WHERE LOWER(TRIM(REGEXP_REPLACE(
            REGEXP_REPLACE(rp.canonical_name,
                '\\s+(Extrait de Parfum|Eau de Parfum|Eau de Toilette|Eau de Cologne|Eau Fraiche|Extrait|Parfum)\\s*$',
                '', 'i'),
            '\\s+(Extrait de Parfum|Eau de Parfum|Eau de Toilette|Eau de Cologne|Eau Fraiche|Extrait|Parfum)\\s*$',
            '', 'i'
        ))) = %s
        LIMIT 1
    """, (norm,))
    row = cur.fetchone()
    if row:
        return row["brand_name"]

    return None


def _get_ghost_brand_entity(cur, canonical_name: str) -> Optional[Dict]:
    """Find a brand entity_market row for the given canonical_name."""
    cur.execute("""
        SELECT
            em.id::text AS uuid,
            em.entity_id,
            em.canonical_name,
            (SELECT COUNT(*) FROM entity_timeseries_daily etd WHERE etd.entity_id = em.id) AS ts_count,
            (SELECT COUNT(*) FROM signals s WHERE s.entity_id = em.id) AS signal_count,
            (SELECT COUNT(*) FROM signal_intelligence_snapshots sis WHERE sis.entity_id = em.id) AS snapshot_count,
            (SELECT MIN(etd.date) FROM entity_timeseries_daily etd WHERE etd.entity_id = em.id) AS first_date,
            (SELECT MAX(etd.date) FROM entity_timeseries_daily etd WHERE etd.entity_id = em.id) AS last_date
        FROM entity_market em
        WHERE em.entity_type = 'brand'
          AND em.canonical_name = %s
    """, (canonical_name,))
    row = cur.fetchone()
    return dict(row) if row else None


def _delete_ghost_brand_rows(cur, brand_uuid: str, dry_run: bool) -> Dict[str, int]:
    """Delete brand entity + all downstream timeseries/signals/snapshots."""
    counts: Dict[str, int] = {}

    for table, col in [
        ("entity_timeseries_daily", "entity_id"),
        ("signals", "entity_id"),
        ("signal_intelligence_snapshots", "entity_id"),
    ]:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE {col}::text = %s", (brand_uuid,))
        count = cur.fetchone()["cnt"]
        counts[table] = count
        if not dry_run and count > 0:
            cur.execute(f"DELETE FROM {table} WHERE {col}::text = %s", (brand_uuid,))

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM entity_market WHERE id::text = %s AND entity_type = 'brand'",
        (brand_uuid,),
    )
    em_count = cur.fetchone()["cnt"]
    counts["entity_market_brand_row"] = em_count
    if not dry_run and em_count > 0:
        cur.execute(
            "DELETE FROM entity_market WHERE id::text = %s AND entity_type = 'brand'",
            (brand_uuid,),
        )

    return counts


# ---------------------------------------------------------------------------
# Phase 1 — Structural Fragment Orphan Repair
# ---------------------------------------------------------------------------

def _find_structural_fragment_perfumes(cur) -> List[Dict]:
    """Find perfume rows where brand_name is a structural fragment (ends in & or |)."""
    cur.execute("""
        SELECT
            em.id::text AS id,
            em.entity_id,
            em.canonical_name,
            em.brand_name,
            -- Check if a ghost brand entity exists
            (
                SELECT em2.id::text
                FROM entity_market em2
                WHERE em2.entity_type = 'brand'
                  AND LOWER(em2.canonical_name) = LOWER(em.brand_name)
                LIMIT 1
            ) AS ghost_brand_uuid
        FROM entity_market em
        WHERE em.entity_type = 'perfume'
          AND em.brand_name IS NOT NULL
          AND (
            em.brand_name LIKE '%&'
            OR em.brand_name LIKE '%|'
            OR em.brand_name LIKE '%&amp;'
          )
          AND em.canonical_name != 'TOM FORD Private Blend'
        ORDER BY em.brand_name, em.canonical_name
    """)
    return [dict(r) for r in cur.fetchall()]


def run_phase1_structural_fragment(cur, dry_run: bool) -> Dict[str, int]:
    """Fix orphan perfume rows with structural fragment brand_names."""
    _print_section("PHASE 1 — Structural Fragment Orphan Repair")
    perfumes = _find_structural_fragment_perfumes(cur)
    print(f"  Perfume rows with structural fragment brand_name: {len(perfumes)}")

    fixed = 0
    unfixable = 0

    for p in perfumes:
        canonical = p["canonical_name"]
        wrong_brand = p["brand_name"]
        ghost_uuid = p["ghost_brand_uuid"]

        correct = _resolve_correct_brand(cur, canonical)
        status = f"→ {correct!r}" if correct else "→ UNRESOLVABLE"
        print(f"\n  Perfume: {canonical!r}")
        print(f"    Current brand_name: {wrong_brand!r}")
        print(f"    Resolver lookup: {status}")
        if ghost_uuid:
            print(f"    Ghost brand entity UUID: {ghost_uuid} (NOT deleted — handled by DATA4-B or Phase 2)")

        if correct and correct.lower() != wrong_brand.lower():
            if dry_run:
                print(f"    [DRY RUN] Would UPDATE brand_name → {correct!r}")
            else:
                cur.execute(
                    "UPDATE entity_market SET brand_name = %s WHERE id::text = %s",
                    (correct, p["id"]),
                )
                print(f"    UPDATED brand_name → {correct!r}")
            fixed += 1
        elif correct and correct.lower() == wrong_brand.lower():
            print(f"    SKIP: resolver confirms current brand_name is correct")
            unfixable += 1
        else:
            print(f"    SKIP: cannot resolve — leave for manual review")
            unfixable += 1

    print(f"\n  Phase 1 summary: fixed={fixed}  unresolvable/skipped={unfixable}")
    return {"fixed": fixed, "unfixable": unfixable}


# ---------------------------------------------------------------------------
# Phase 2 — DATA4-D Encoding Mismatch Repair
# ---------------------------------------------------------------------------

def run_phase2_encoding_mismatch(cur, dry_run: bool) -> List[Dict]:
    """Fix encoding mismatch cases; return list of date ranges needing recompute."""
    _print_section("PHASE 2 — DATA4-D Encoding Mismatch Repair")
    recompute_ranges: List[Dict] = []

    total_perfumes_fixed = 0
    total_ghosts_deleted = 0

    for wrong_brand, correct_brand in ENCODING_CORRECTIONS:
        print(f"\n  Correction: {wrong_brand!r} → {correct_brand!r}")

        # Find perfume rows with this wrong brand_name
        cur.execute("""
            SELECT id::text AS id, entity_id, canonical_name, brand_name
            FROM entity_market
            WHERE entity_type = 'perfume'
              AND brand_name = %s
            ORDER BY canonical_name
        """, (wrong_brand,))
        perfumes = [dict(r) for r in cur.fetchall()]
        print(f"    Perfume rows with brand_name={wrong_brand!r}: {len(perfumes)}")

        if perfumes:
            for p in perfumes:
                print(f"      {p['canonical_name']!r}")
            if dry_run:
                print(f"    [DRY RUN] Would UPDATE {len(perfumes)} rows: brand_name → {correct_brand!r}")
            else:
                cur.execute(
                    "UPDATE entity_market SET brand_name = %s WHERE entity_type = 'perfume' AND brand_name = %s",
                    (correct_brand, wrong_brand),
                )
                print(f"    UPDATED {len(perfumes)} rows: brand_name → {correct_brand!r}")
            total_perfumes_fixed += len(perfumes)

        # Check if ghost brand entity exists for the wrong form
        ghost = _get_ghost_brand_entity(cur, wrong_brand)
        if ghost:
            print(f"    Ghost brand entity: {wrong_brand!r} uuid={ghost['uuid'][:8]}")
            print(f"      ts_rows={ghost['ts_count']}  signals={ghost['signal_count']}  snapshots={ghost['snapshot_count']}")
            print(f"      date range: {ghost['first_date']} → {ghost['last_date']}")

            if ghost["ts_count"] > 0 or ghost["signal_count"] > 0:
                recompute_ranges.append({
                    "brand": correct_brand,
                    "first_date": ghost["first_date"],
                    "last_date": ghost["last_date"],
                    "ts_count": ghost["ts_count"],
                    "reason": f"Ghost {wrong_brand!r} deleted; rebuild under {correct_brand!r}",
                })

            counts = _delete_ghost_brand_rows(cur, ghost["uuid"], dry_run)
            for table, count in counts.items():
                action = "Would delete" if dry_run else "Deleted"
                print(f"      {action} {count} rows from {table}")
            if not dry_run:
                total_ghosts_deleted += 1
        else:
            # Check if correct brand entity exists already
            correct_entity = _get_ghost_brand_entity(cur, correct_brand)
            if correct_entity:
                print(f"    No ghost entity for {wrong_brand!r} — correct entity {correct_brand!r} already exists (ts={correct_entity['ts_count']})")
            else:
                print(f"    No ghost entity for {wrong_brand!r} — correct entity {correct_brand!r} will be created by aggregation recompute")

    print(f"\n  Phase 2 summary: perfume_rows_fixed={total_perfumes_fixed}  ghost_entities_deleted={total_ghosts_deleted}")
    return recompute_ranges


# ---------------------------------------------------------------------------
# Print aggregation recompute commands
# ---------------------------------------------------------------------------

def _print_recompute_plan(recompute_ranges: List[Dict]) -> None:
    if not recompute_ranges:
        print("\n  No aggregation recompute required.")
        return

    _print_section("AGGREGATION RECOMPUTE REQUIRED")
    print("  Run the following commands via Railway SSH after repair is applied:\n")
    print("  railway ssh --service generous-prosperity -- bash -c '")
    print("    cd /app")

    all_dates: set = set()
    for r in recompute_ranges:
        reason = r["reason"]
        print(f"\n    # {reason}")
        if r["first_date"] and r["last_date"]:
            d = r["first_date"]
            while d <= r["last_date"]:
                all_dates.add(d)
                d = d + timedelta(days=1) if isinstance(d, date) else date.fromisoformat(str(d)) + timedelta(days=1)

    sorted_dates = sorted(str(d) for d in all_dates)
    for d in sorted_dates:
        print(f"    python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date {d}")

    print("  '")
    print(f"\n  Total dates needing recompute: {len(sorted_dates)}")
    if sorted_dates:
        print(f"  Date range: {sorted_dates[0]} → {sorted_dates[-1]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="DATA4-D encoding mismatch + orphan brand_name repair")
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--phase", choices=["1", "2", "all"], default="all",
                        help="Which phase to run (default: all)")
    args = parser.parse_args()

    dry_run = not args.apply
    mode = "DRY RUN" if dry_run else "APPLY"

    _print_header(f"DATA4-D Encoding Mismatch + Orphan Brand Repair — {mode}")
    print(f"  Phase: {args.phase}")
    print(f"  Mode: {mode}")
    print(f"  Encoding corrections defined: {len(ENCODING_CORRECTIONS)}")

    conn = _connect()
    try:
        cur = conn.cursor()
        recompute_ranges: List[Dict] = []

        if args.phase in ("1", "all"):
            run_phase1_structural_fragment(cur, dry_run)

        if args.phase in ("2", "all"):
            recompute_ranges = run_phase2_encoding_mismatch(cur, dry_run)

        if dry_run:
            conn.rollback()
            _print_header("DRY RUN COMPLETE — no changes written")
            print("  Run with --apply to execute repairs.")
        else:
            conn.commit()
            _print_header("REPAIR COMMITTED")

        _print_recompute_plan(recompute_ranges)

        if not dry_run and recompute_ranges:
            print("\n  IMPORTANT: Run the aggregation recompute commands above to rebuild")
            print("  brand market state under the correct canonical brand names.")
            print("  Then verify production UI: ghost brands absent, correct brands visible.")

    except Exception as exc:
        conn.rollback()
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
