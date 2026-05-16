#!/usr/bin/env python3
"""RES-AMB2 — Targeted False-Positive Entity Repair

Removes 6 confirmed false-positive perfume entities from production data.
These entities accumulated entity_mentions because ambiguous short aliases
(e.g. "so you", "you are", "en route", "one & only", etc.) matched common
English phrases in YouTube/Reddit text with no brand context.

Scope (deliberate narrow repair):
  - Strips the 6 false-positive entity_ids from resolved_signals.resolved_entities_json
    for content collected in the last `--days` days (default: 90)
  - Deletes entity_mentions for the 6 entity_ids (all time — these are 100% false)
  - Deletes entity_timeseries_daily rows for the 6 entity_ids (all time)
  - Deletes signals rows for the 6 entity_ids (all time)
  - Deletes signal_intelligence_snapshots rows for the 6 entity_ids (all time)
  - Reports orphaned brand entities with no remaining tracked perfumes

After running with --apply, re-run aggregation for recent dates to rebuild
entity_timeseries_daily from the cleaned resolved_signals.

Usage:
    # Dry run (default — show what would change, no writes):
    DATABASE_URL=<prod-url> python3 scripts/res_amb2_targeted_repair.py

    # Apply:
    DATABASE_URL=<prod-url> python3 scripts/res_amb2_targeted_repair.py --apply

    # Wider window (last 180 days of resolved_signals):
    DATABASE_URL=<prod-url> python3 scripts/res_amb2_targeted_repair.py --apply --days 180
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Set

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Confirmed false-positive entities (entity_market.id — production verified)
# Source: RES-AMB2 Phase A production audit (2026-05-16)
# ---------------------------------------------------------------------------

_FALSE_POSITIVE_ENTITY_IDS: List[str] = [
    "0bb5d31a-7563-43ec-8466-6550d4db45ef",  # So You (Alia Touch)
    "d9085447-d736-491a-a42c-7ab3c6013ea4",  # One & Only (One &)
    "9e952b6e-a8e8-4310-8f24-9f36fd5f8bb4",  # You Are (Geparlys)
    "e4f7168f-92cd-4c6a-bc8d-e2557a14f73d",  # En Route (Botanicae Expressions)
    "28656415-dba0-4563-8842-d59664edbc06",  # Fragrance of Summer (M. Asam)
    "3957f740-cc82-497c-bb47-b01dbdd6ffc6",  # Good Vibes (brand=None)
]

# Canonical names as they appear in resolved_signals.resolved_entities_json.
_FALSE_POSITIVE_CANONICAL_NAMES: Set[str] = {
    "So You",
    "One & Only",
    "You Are",
    "En Route",
    "Fragrance of Summer",
    "Good Vibes",
}

# Brands associated with these false-positive perfumes.
# Check for orphaned brand entities after repair.
_AFFECTED_BRANDS: List[str] = [
    "Alia Touch",
    "Alia Touch / عالية تاتش",
    "One &",          # DATA4 ghost brand from ampersand truncation
    "Geparlys",
    "Botanicae Expressions",
    "M. Asam",
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
    bar = "=" * 60
    print(f"\n{bar}\n  {title}\n{bar}")


def _print_section(title: str) -> None:
    print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# Step 1: Strip false-positive entities from resolved_signals
# ---------------------------------------------------------------------------

def _repair_resolved_signals(cur, days: int, dry_run: bool) -> Dict[str, int]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    cur.execute(
        """
        SELECT rs.id, rs.content_item_id, rs.resolved_entities_json
        FROM resolved_signals rs
        JOIN canonical_content_items cci ON cci.id = rs.content_item_id
        WHERE cci.collected_at >= %s
        """,
        (cutoff,),
    )
    rows = cur.fetchall()

    updated_count = 0
    skipped_clean = 0
    empty_after = 0

    for row in rows:
        try:
            entities: List[Dict[str, Any]] = json.loads(row["resolved_entities_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue

        original_names = {e.get("canonical_name") for e in entities}
        kept = [
            e for e in entities
            if e.get("canonical_name") not in _FALSE_POSITIVE_CANONICAL_NAMES
        ]

        if len(kept) == len(entities):
            skipped_clean += 1
            continue

        removed_names = original_names & _FALSE_POSITIVE_CANONICAL_NAMES
        updated_count += 1
        if not kept:
            empty_after += 1

        if not dry_run:
            new_json = json.dumps(kept)
            cur.execute(
                "UPDATE resolved_signals SET resolved_entities_json = %s WHERE id = %s",
                (new_json, row["id"]),
            )
        else:
            print(
                f"  [DRY RUN] Would strip {removed_names} from resolved_signals id={row['id']} "
                f"(content={str(row['content_item_id'])[:12]}...)"
            )

    return {
        "rows_checked": len(rows),
        "rows_updated": updated_count,
        "rows_already_clean": skipped_clean,
        "rows_empty_after": empty_after,
    }


# ---------------------------------------------------------------------------
# Step 2: Delete entity_mentions
# ---------------------------------------------------------------------------

def _delete_entity_mentions(cur, entity_ids: List[str], dry_run: bool) -> int:
    placeholders = ",".join(["%s"] * len(entity_ids))
    cur.execute(
        f"SELECT COUNT(*) AS cnt FROM entity_mentions WHERE entity_id::text IN ({placeholders})",
        entity_ids,
    )
    count = cur.fetchone()["cnt"]
    if not dry_run and count > 0:
        cur.execute(
            f"DELETE FROM entity_mentions WHERE entity_id::text IN ({placeholders})",
            entity_ids,
        )
    return count


# ---------------------------------------------------------------------------
# Step 3: Delete entity_timeseries_daily
# ---------------------------------------------------------------------------

def _delete_timeseries(cur, entity_ids: List[str], dry_run: bool) -> int:
    placeholders = ",".join(["%s"] * len(entity_ids))
    cur.execute(
        f"SELECT COUNT(*) AS cnt FROM entity_timeseries_daily WHERE entity_id::text IN ({placeholders})",
        entity_ids,
    )
    count = cur.fetchone()["cnt"]
    if not dry_run and count > 0:
        cur.execute(
            f"DELETE FROM entity_timeseries_daily WHERE entity_id::text IN ({placeholders})",
            entity_ids,
        )
    return count


# ---------------------------------------------------------------------------
# Step 4: Delete signals
# ---------------------------------------------------------------------------

def _delete_signals(cur, entity_ids: List[str], dry_run: bool) -> int:
    placeholders = ",".join(["%s"] * len(entity_ids))
    cur.execute(
        f"SELECT COUNT(*) AS cnt FROM signals WHERE entity_id::text IN ({placeholders})",
        entity_ids,
    )
    count = cur.fetchone()["cnt"]
    if not dry_run and count > 0:
        cur.execute(
            f"DELETE FROM signals WHERE entity_id::text IN ({placeholders})",
            entity_ids,
        )
    return count


# ---------------------------------------------------------------------------
# Step 5: Delete signal_intelligence_snapshots
# ---------------------------------------------------------------------------

def _delete_snapshots(cur, entity_ids: List[str], dry_run: bool) -> int:
    placeholders = ",".join(["%s"] * len(entity_ids))
    cur.execute(
        f"""SELECT COUNT(*) AS cnt FROM signal_intelligence_snapshots
            WHERE entity_id::text IN ({placeholders})""",
        entity_ids,
    )
    count = cur.fetchone()["cnt"]
    if not dry_run and count > 0:
        cur.execute(
            f"DELETE FROM signal_intelligence_snapshots WHERE entity_id::text IN ({placeholders})",
            entity_ids,
        )
    return count


# ---------------------------------------------------------------------------
# Step 6: Report orphaned brand entities
# ---------------------------------------------------------------------------

def _report_orphaned_brands(cur) -> None:
    _print_section("Orphaned brand entity check (after repair)")

    for brand_name in _AFFECTED_BRANDS:
        cur.execute(
            """
            SELECT em.id, em.canonical_name, em.entity_type
            FROM entity_market em
            WHERE em.entity_type = 'brand'
              AND LOWER(em.canonical_name) = LOWER(%s)
            """,
            (brand_name,),
        )
        brand_row = cur.fetchone()
        if not brand_row:
            print(f"  {brand_name}: no brand entity in entity_market")
            continue

        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM entity_market em
            WHERE em.entity_type = 'perfume'
              AND LOWER(em.brand_name) = LOWER(%s)
            """,
            (brand_name,),
        )
        perfume_count = cur.fetchone()["cnt"]

        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM entity_timeseries_daily
            WHERE entity_id = %s
            """,
            (str(brand_row["id"]),),
        )
        ts_count = cur.fetchone()["cnt"]

        status = "ORPHANED" if perfume_count == 0 and ts_count == 0 else "has data"
        print(
            f"  {brand_name}: brand_entity_id={brand_row['id']} | "
            f"tracked_perfumes={perfume_count} | timeseries_rows={ts_count} → {status}"
        )
        if status == "ORPHANED":
            print(
                f"    ↳ Manual action recommended: DELETE FROM entity_market WHERE id='{brand_row['id']}';"
            )


# ---------------------------------------------------------------------------
# Step 7: Verify entity_market still has the 6 entities (for audit trail)
# ---------------------------------------------------------------------------

def _verify_entities(cur) -> None:
    _print_section("Entity_market confirmation (entities still exist for audit)")
    placeholders = ",".join(["%s"] * len(_FALSE_POSITIVE_ENTITY_IDS))
    cur.execute(
        f"""
        SELECT id, canonical_name, entity_type, brand_name
        FROM entity_market
        WHERE id::text IN ({placeholders})
        ORDER BY canonical_name
        """,
        _FALSE_POSITIVE_ENTITY_IDS,
    )
    rows = cur.fetchall()
    for r in rows:
        print(f"  ✓ {r['canonical_name']} ({r['brand_name']}) — id={r['id']}")
    missing = len(_FALSE_POSITIVE_ENTITY_IDS) - len(rows)
    if missing > 0:
        print(f"  WARNING: {missing} entity IDs not found in entity_market")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="RES-AMB2 targeted false-positive repair")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to DB. Default is dry-run (read-only).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Repair resolved_signals for content collected in last N days (default: 90)",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    mode = "DRY RUN" if dry_run else "APPLY"

    _print_header(f"RES-AMB2 Targeted Repair — {mode}")
    print(f"  Entities targeted: {len(_FALSE_POSITIVE_ENTITY_IDS)}")
    print(f"  Resolved signals window: last {args.days} days")
    print(f"  Mode: {mode}")
    print()

    conn = _connect()
    try:
        cur = conn.cursor()

        # Verify entities exist
        _verify_entities(cur)

        # Step 1: Resolved signals
        _print_section("Step 1: resolved_signals — strip false-positive entities from JSON")
        rs_stats = _repair_resolved_signals(cur, args.days, dry_run)
        print(f"  rows_checked:        {rs_stats['rows_checked']}")
        print(f"  rows_updated:        {rs_stats['rows_updated']}")
        print(f"  rows_already_clean:  {rs_stats['rows_already_clean']}")
        print(f"  rows_empty_after:    {rs_stats['rows_empty_after']}  (will have empty JSON after repair)")

        # Step 2: entity_mentions
        _print_section("Step 2: entity_mentions — delete all rows for false-positive entity IDs")
        em_count = _delete_entity_mentions(cur, _FALSE_POSITIVE_ENTITY_IDS, dry_run)
        action = "Would delete" if dry_run else "Deleted"
        print(f"  {action}: {em_count} entity_mentions rows")

        # Step 3: entity_timeseries_daily
        _print_section("Step 3: entity_timeseries_daily — delete all rows for false-positive entity IDs")
        ts_count = _delete_timeseries(cur, _FALSE_POSITIVE_ENTITY_IDS, dry_run)
        print(f"  {action}: {ts_count} entity_timeseries_daily rows")

        # Step 4: signals
        _print_section("Step 4: signals — delete all rows for false-positive entity IDs")
        sig_count = _delete_signals(cur, _FALSE_POSITIVE_ENTITY_IDS, dry_run)
        print(f"  {action}: {sig_count} signals rows")

        # Step 5: signal_intelligence_snapshots
        _print_section("Step 5: signal_intelligence_snapshots — delete false-positive snapshots")
        snap_count = _delete_snapshots(cur, _FALSE_POSITIVE_ENTITY_IDS, dry_run)
        print(f"  {action}: {snap_count} signal_intelligence_snapshots rows")

        # Step 6: Orphaned brand report
        _report_orphaned_brands(cur)

        if dry_run:
            conn.rollback()
            _print_header("DRY RUN COMPLETE — no changes written")
            print("  Run with --apply to execute.")
        else:
            conn.commit()
            _print_header("REPAIR COMPLETE — changes committed")
            print(f"  resolved_signals updated:              {rs_stats['rows_updated']}")
            print(f"  entity_mentions deleted:               {em_count}")
            print(f"  entity_timeseries_daily deleted:       {ts_count}")
            print(f"  signals deleted:                       {sig_count}")
            print(f"  signal_intelligence_snapshots deleted: {snap_count}")
            print()
            print("  NEXT STEP: Re-run aggregation for recent dates to rebuild timeseries from")
            print("  the cleaned resolved_signals:")
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
