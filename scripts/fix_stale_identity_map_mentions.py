#!/usr/bin/env python3
"""
Fix stale entity_mentions caused by perfume_identity_map resolver_perfume_id corruption.

Root cause:
  perfume_identity_map.resolver_perfume_id has a systematic +6 offset error.
  Old aggregator path `identity_resolver.perfume_uuid(int(raw_eid))` looked up
  market_perfume_uuid via resolver_perfume_id — which due to the offset returns
  the UUID of the wrong entity. This wrote entity_mentions to stale UUIDs (not in
  entity_market) ALONGSIDE the correct mentions already written via the entity_uuid_map path.

Fix strategy:
  Delete entity_mentions where:
    1. entity_id is NOT in entity_market (stale — no market row to join)
    2. AND the same source_url has at least one entity_mention where entity_id IS in
       entity_market (the correct mention already exists — the stale one is a duplicate)

  Preserve entity_mentions where:
    - entity_id is stale AND source_url has NO correct sibling
    (These may be genuine mentions of niche entities not yet in entity_market;
    deleting them would lose real data without any confirmed duplicate existing.)

Usage:
  # Dry-run (default — no writes):
  DATABASE_URL=<url> python3 scripts/fix_stale_identity_map_mentions.py

  # Apply deletes:
  DATABASE_URL=<url> python3 scripts/fix_stale_identity_map_mentions.py --apply

  # Also re-run aggregation for affected dates after --apply:
  DATABASE_URL=<url> python3 scripts/fix_stale_identity_map_mentions.py --apply --reaggregate
"""

import argparse
import os
import subprocess
import sys
from datetime import date

import psycopg2
import psycopg2.extras


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit("ERROR: DATABASE_URL environment variable is required.")
    return url


def audit(cur) -> tuple[int, int, list[date], list[dict]]:
    """Return (delete_count, keep_count, affected_dates, stale_summary)."""

    cur.execute("""
        SELECT COUNT(*)
        FROM entity_mentions em
        WHERE NOT EXISTS (SELECT 1 FROM entity_market mk WHERE mk.id = em.entity_id)
          AND EXISTS (
              SELECT 1 FROM entity_mentions em_ok
              JOIN entity_market mk2 ON mk2.id = em_ok.entity_id
              WHERE em_ok.source_url = em.source_url
          )
    """)
    delete_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM entity_mentions em
        WHERE NOT EXISTS (SELECT 1 FROM entity_market mk WHERE mk.id = em.entity_id)
          AND NOT EXISTS (
              SELECT 1 FROM entity_mentions em_ok
              JOIN entity_market mk2 ON mk2.id = em_ok.entity_id
              WHERE em_ok.source_url = em.source_url
          )
    """)
    keep_count = cur.fetchone()[0]

    cur.execute("""
        SELECT DISTINCT DATE(em.occurred_at) AS dt
        FROM entity_mentions em
        WHERE NOT EXISTS (SELECT 1 FROM entity_market mk WHERE mk.id = em.entity_id)
          AND EXISTS (
              SELECT 1 FROM entity_mentions em_ok
              JOIN entity_market mk2 ON mk2.id = em_ok.entity_id
              WHERE em_ok.source_url = em.source_url
          )
        ORDER BY dt
    """)
    affected_dates = [r[0] for r in cur.fetchall()]

    # Per-stale-UUID breakdown (DISTINCT ON to avoid duplicate PIM rows for same UUID)
    cur.execute("""
        SELECT
            em.entity_id::text,
            COUNT(*) AS total_mentions,
            SUM(CASE
                WHEN EXISTS (
                    SELECT 1 FROM entity_mentions em_ok
                    JOIN entity_market mk2 ON mk2.id = em_ok.entity_id
                    WHERE em_ok.source_url = em.source_url
                ) THEN 1 ELSE 0
            END) AS would_delete,
            (
                SELECT pim2.canonical_name FROM perfume_identity_map pim2
                WHERE pim2.market_perfume_uuid = em.entity_id::text
                LIMIT 1
            ) AS canonical_name
        FROM entity_mentions em
        WHERE NOT EXISTS (SELECT 1 FROM entity_market mk WHERE mk.id = em.entity_id)
        GROUP BY em.entity_id
        ORDER BY total_mentions DESC
    """)
    stale_summary = [
        {
            "entity_id": r[0],
            "total_mentions": r[1],
            "would_delete": r[2],
            "would_keep": r[1] - r[2],
            "pim_name": r[3] or "NOT IN PIM",
        }
        for r in cur.fetchall()
    ]

    return delete_count, keep_count, affected_dates, stale_summary


def print_audit(delete_count: int, keep_count: int, affected_dates: list, stale_summary: list):
    total = delete_count + keep_count
    print(f"\n{'='*70}")
    print("STALE IDENTITY MAP MENTIONS AUDIT")
    print(f"{'='*70}")
    print(f"Total stale entity_mentions:         {total}")
    print(f"  → Would DELETE (false positives):  {delete_count}")
    print(f"  → Would KEEP   (isolated niche):   {keep_count}")
    print(f"\nAffected dates for re-aggregation: {[str(d) for d in affected_dates]}")
    print(f"\nPer-UUID breakdown ({len(stale_summary)} unique stale entity_ids):")
    print(f"  {'UUID':10s}  {'total':>6s}  {'delete':>7s}  {'keep':>6s}  PIM canonical")
    print(f"  {'-'*8}  {'------':>6s}  {'-------':>7s}  {'------':>6s}  {'-'*30}")
    for row in stale_summary:
        action = "ALL_DELETE" if row["would_keep"] == 0 else (
            "ALL_KEEP" if row["would_delete"] == 0 else "PARTIAL"
        )
        print(
            f"  {row['entity_id'][:8]}  {row['total_mentions']:>6d}  "
            f"{row['would_delete']:>7d}  {row['would_keep']:>6d}  "
            f"{row['pim_name'][:45]}"
        )
    print()


def apply_deletes(cur) -> int:
    cur.execute("""
        DELETE FROM entity_mentions em
        WHERE NOT EXISTS (SELECT 1 FROM entity_market mk WHERE mk.id = em.entity_id)
          AND EXISTS (
              SELECT 1 FROM entity_mentions em_ok
              JOIN entity_market mk2 ON mk2.id = em_ok.entity_id
              WHERE em_ok.source_url = em.source_url
          )
    """)
    return cur.rowcount


def run_reaggregate(affected_dates: list[date]):
    """Re-run aggregation + signal detection for all affected dates."""
    print("\nRe-aggregating affected dates...")
    for dt in sorted(affected_dates):
        date_str = str(dt)
        print(f"  {date_str} → aggregate...", end=" ", flush=True)
        r = subprocess.run(
            [sys.executable, "-m", "perfume_trend_sdk.jobs.aggregate_daily_market_metrics",
             "--date", date_str],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"FAILED\n{r.stderr[-500:]}")
        else:
            print("OK", end="  ")

        print(f"signals...", end=" ", flush=True)
        r = subprocess.run(
            [sys.executable, "-m", "perfume_trend_sdk.jobs.detect_breakout_signals",
             "--date", date_str],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"FAILED\n{r.stderr[-500:]}")
        else:
            print("OK")


def main():
    parser = argparse.ArgumentParser(description="Fix stale identity_map entity_mentions")
    parser.add_argument("--apply", action="store_true",
                        help="Execute deletes (default: dry-run only)")
    parser.add_argument("--reaggregate", action="store_true",
                        help="Re-run aggregation+signals for affected dates after --apply")
    args = parser.parse_args()

    db_url = get_db_url()

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Always audit first
    delete_count, keep_count, affected_dates, stale_summary = audit(cur)
    print_audit(delete_count, keep_count, affected_dates, stale_summary)

    if not args.apply:
        print("[DRY-RUN] No changes made. Pass --apply to execute.")
        conn.close()
        return

    if delete_count == 0:
        print("Nothing to delete. Already clean.")
        conn.close()
        return

    print(f"Deleting {delete_count} false-positive stale entity_mentions...")
    deleted = apply_deletes(cur)
    conn.commit()
    print(f"Deleted: {deleted} rows")

    # Verify
    cur.execute("""
        SELECT COUNT(*)
        FROM entity_mentions em
        WHERE NOT EXISTS (SELECT 1 FROM entity_market mk WHERE mk.id = em.entity_id)
          AND EXISTS (
              SELECT 1 FROM entity_mentions em_ok
              JOIN entity_market mk2 ON mk2.id = em_ok.entity_id
              WHERE em_ok.source_url = em.source_url
          )
    """)
    remaining = cur.fetchone()[0]
    print(f"Remaining false-positive stale mentions: {remaining} (expected 0)")

    cur.execute("""
        SELECT COUNT(*)
        FROM entity_mentions em
        WHERE NOT EXISTS (SELECT 1 FROM entity_market mk WHERE mk.id = em.entity_id)
    """)
    all_stale = cur.fetchone()[0]
    print(f"Remaining isolated stale mentions (preserved): {all_stale}")

    conn.close()

    if args.reaggregate:
        run_reaggregate(affected_dates)
    else:
        print(f"\nRun with --reaggregate to re-aggregate these dates:")
        for dt in affected_dates:
            print(f"  {dt}")


if __name__ == "__main__":
    main()
