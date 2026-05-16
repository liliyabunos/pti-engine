#!/usr/bin/env python3
"""DATA4-B — Ghost Brand Entity Repair

Fixes upstream entity_market.perfume.brand_name for Type 1-3 ghost brand cases
(ampersand truncation, pipe-delimiter fragments, word-fragment brands) where the
correct brand_name can be resolved from resolver_brands via the perfume's
canonical_name.

Then deletes downstream ghost brand entity_market rows and their timeseries/signals.

Scope (deliberate narrow repair — DATA4-B only):
  - Type 1: Ampersand-truncated brand_names (e.g. "Oud &" from "Oud & Roses")
  - Type 2: Pipe-delimiter fragments (e.g. "Lattafa / لطافة" → wrong brand_name on perfume)
  - Type 3: Word-fragment brands confirmed ghost (no resolver match, 0 catalog perfumes
    after repair)

Explicit EXCLUSIONS (separate phases):
  - TOM FORD Private Blend (DATA4-C — collection-as-brand, needs architectural decision)
  - Encoding mismatches like "Comme des Garcons" → "Comme des Garçons" (DATA4-D)

Repair-Complete Rule applies:
  1. Fix upstream (entity_market.perfume.brand_name) FIRST
  2. Then delete downstream ghost brand rows (entity_market.brand, entity_timeseries_daily,
     signals, signal_intelligence_snapshots for those brands)

Usage:
    # Dry run (default):
    DATABASE_URL=<prod-url> python3 scripts/data4b_ghost_brand_repair.py

    # Apply:
    DATABASE_URL=<prod-url> python3 scripts/data4b_ghost_brand_repair.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Set, Tuple

import psycopg2
import psycopg2.extras


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


# ---------------------------------------------------------------------------
# Step 1: Identify ghost brand entities (no catalog perfumes from resolver)
# ---------------------------------------------------------------------------

def _find_ghost_brands(cur) -> List[dict]:
    """Find brand entities in entity_market that have 0 resolver-matched perfumes.

    A brand entity is a ghost if:
    - entity_type = 'brand'
    - No resolver_brands row matches its canonical_name (case-insensitive)
    - No brand_profiles row matches its brand_name_normalized

    Exclusions:
    - TOM FORD Private Blend (DATA4-C scope)
    - Brands that match resolver_brands (they are legitimate)
    """
    cur.execute("""
        SELECT
            em.id::text AS id,
            em.entity_id,
            em.canonical_name,
            -- Check how many perfume entity_market rows use this brand_name
            (
                SELECT COUNT(*)
                FROM entity_market ep
                WHERE ep.entity_type = 'perfume'
                  AND LOWER(ep.brand_name) = LOWER(em.canonical_name)
            ) AS perfume_em_count,
            -- Check if there's a resolver_brands match
            (
                SELECT rb.canonical_name
                FROM resolver_brands rb
                WHERE LOWER(rb.canonical_name) = LOWER(em.canonical_name)
                LIMIT 1
            ) AS resolver_match,
            -- Check if there's a brand_profiles match
            (
                SELECT bp.brand_name_normalized
                FROM brand_profiles bp
                WHERE LOWER(bp.brand_name_normalized) = LOWER(em.canonical_name)
                LIMIT 1
            ) AS profile_match,
            -- Count timeseries rows
            (
                SELECT COUNT(*)
                FROM entity_timeseries_daily etd
                WHERE etd.entity_id = em.id
            ) AS ts_count,
            -- Count signal rows
            (
                SELECT COUNT(*)
                FROM signals s
                WHERE s.entity_id = em.id
            ) AS signal_count
        FROM entity_market em
        WHERE em.entity_type = 'brand'
          AND em.canonical_name != 'TOM FORD Private Blend'
        ORDER BY ts_count DESC, em.canonical_name
    """)
    rows = cur.fetchall()

    ghosts = []
    for row in rows:
        if row["resolver_match"] is None and row["profile_match"] is None:
            ghosts.append(dict(row))
    return ghosts


# ---------------------------------------------------------------------------
# Step 2: For each ghost brand, find the correct brand_name via resolver
# ---------------------------------------------------------------------------

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

    # Try suffix-normalized form (DATA2 pattern)
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


# ---------------------------------------------------------------------------
# Step 3: Find perfume entity_market rows with bad brand_names (ghost origins)
# ---------------------------------------------------------------------------

def _find_perfumes_with_ghost_brand(cur, ghost_brand_name: str) -> List[dict]:
    """Find perfume rows in entity_market using this ghost brand_name."""
    cur.execute("""
        SELECT id::text, entity_id, canonical_name, brand_name
        FROM entity_market
        WHERE entity_type = 'perfume'
          AND LOWER(brand_name) = LOWER(%s)
        ORDER BY canonical_name
    """, (ghost_brand_name,))
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Step 4: Fix upstream — update entity_market.perfume.brand_name
# ---------------------------------------------------------------------------

def _fix_perfume_brand_name(cur, perfume_id: str, correct_brand: str, dry_run: bool) -> None:
    if dry_run:
        print(f"      [DRY RUN] Would UPDATE entity_market id={perfume_id[:8]}... brand_name → {correct_brand!r}")
    else:
        cur.execute(
            "UPDATE entity_market SET brand_name = %s WHERE id::text = %s",
            (correct_brand, perfume_id),
        )


# ---------------------------------------------------------------------------
# Step 5: Delete ghost brand downstream rows
# ---------------------------------------------------------------------------

def _delete_ghost_brand_rows(cur, brand_entity_id: str, dry_run: bool) -> Dict[str, int]:
    """Delete entity_market brand row + all downstream timeseries/signals/snapshots."""
    counts = {}

    # Get the UUID id for this brand entity_id slug
    cur.execute(
        "SELECT id::text FROM entity_market WHERE entity_id = %s AND entity_type = 'brand'",
        (brand_entity_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"not_found": 1}

    brand_uuid = row["id"]

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

    # Delete the brand entity_market row itself
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
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="DATA4-B ghost brand repair")
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()

    dry_run = not args.apply
    mode = "DRY RUN" if dry_run else "APPLY"

    _print_header(f"DATA4-B Ghost Brand Repair — {mode}")
    print("  Scope: Type 1 (ampersand), Type 2 (pipe), Type 3 (word-fragment) ghost brands")
    print("  Exclusions: TOM FORD Private Blend (DATA4-C), encoding mismatches (DATA4-D)")
    print(f"  Mode: {mode}")

    conn = _connect()
    try:
        cur = conn.cursor()

        # Step 1: Find ghost brands
        _print_section("Step 1: Ghost brand discovery")
        ghosts = _find_ghost_brands(cur)
        print(f"  Ghost brand entities found: {len(ghosts)}")
        print()

        total_upstream_fixed = 0
        total_upstream_unfixable = 0
        brands_deleted = 0
        brands_skipped_has_perfumes = 0

        for ghost in ghosts:
            brand_name = ghost["canonical_name"]
            entity_id = ghost["entity_id"]
            ts_count = ghost["ts_count"]
            signal_count = ghost["signal_count"]
            perfume_em_count = ghost["perfume_em_count"]

            print(f"\n  Ghost: {brand_name!r}  (entity_id={entity_id})")
            print(f"    ts_rows={ts_count}  signals={signal_count}  "
                  f"perfumes_using_this_brand={perfume_em_count}")

            # Find perfume rows using this ghost brand_name
            perfumes = _find_perfumes_with_ghost_brand(cur, brand_name)
            if perfumes:
                print(f"    Perfume rows with this brand_name: {len(perfumes)}")

            # Try to resolve correct brand for each perfume
            brand_resolutions: Dict[str, Optional[str]] = {}
            for p in perfumes:
                correct = _resolve_correct_brand(cur, p["canonical_name"])
                brand_resolutions[p["id"]] = correct
                status = f"→ {correct!r}" if correct else "→ UNRESOLVABLE"
                print(f"      {p['canonical_name']!r} {status}")

            # Fix upstream brand_names for resolvable perfumes
            fixed_this_brand = 0
            unfixed_this_brand = 0
            for p in perfumes:
                correct = brand_resolutions[p["id"]]
                if correct and correct.lower() != brand_name.lower():
                    _fix_perfume_brand_name(cur, p["id"], correct, dry_run)
                    fixed_this_brand += 1
                elif correct and correct.lower() == brand_name.lower():
                    # Brand name is actually correct — not a ghost, skip deletion
                    print(f"      SKIP: resolver confirms {brand_name!r} is correct for {p['canonical_name']!r}")
                    unfixed_this_brand += 1
                else:
                    unfixed_this_brand += 1

            total_upstream_fixed += fixed_this_brand
            total_upstream_unfixable += unfixed_this_brand

            # After upstream fix: re-check if any perfumes still use this brand_name
            # If unfixable perfumes remain, we cannot safely delete the brand entity
            if unfixed_this_brand > 0:
                print(f"    SKIP ghost brand deletion: {unfixed_this_brand} perfume(s) unresolvable "
                      f"— cannot safely remove brand entity")
                brands_skipped_has_perfumes += 1
                continue

            # Safe to delete: all perfumes have been re-pointed to correct brand
            # (or there were no perfumes using this brand at all)
            print(f"    Deleting ghost brand entity + downstream rows...")
            deletion_counts = _delete_ghost_brand_rows(cur, entity_id, dry_run)
            for table, count in deletion_counts.items():
                action = "Would delete" if dry_run else "Deleted"
                print(f"      {action} {count} rows from {table}")
            brands_deleted += 1

        _print_header(f"{mode} SUMMARY")
        print(f"  Ghost brands found:              {len(ghosts)}")
        print(f"  Upstream brand_names fixed:      {total_upstream_fixed}")
        print(f"  Upstream unresolvable (skipped): {total_upstream_unfixable}")
        print(f"  Ghost brand entities deleted:    {brands_deleted}")
        print(f"  Ghost brands skipped (unresolvable perfumes): {brands_skipped_has_perfumes}")

        if dry_run:
            conn.rollback()
            print("\n  DRY RUN COMPLETE — no changes written. Run with --apply to execute.")
        else:
            conn.commit()
            print("\n  REPAIR COMMITTED.")
            print()
            print("  NEXT STEP: Re-run aggregation for recent dates to rebuild brand timeseries")
            print("  from the corrected entity_market.perfume.brand_name values:")
            print()
            print("    for D in $(seq 0 6); do")
            print("      DATE=$(date -u -d \"-$D days\" +%Y-%m-%d 2>/dev/null || date -u -v-${D}d +%Y-%m-%d)")
            print("      python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date $DATE")
            print("    done")

    except Exception as exc:
        conn.rollback()
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
