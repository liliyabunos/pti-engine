#!/usr/bin/env python3
"""
Phase I3 — Trend State Backfill

Populates trend_state for all existing entity_timeseries_daily rows
that currently have trend_state IS NULL.

Uses the same compute_trend_state() logic as the aggregator so results
are 100% consistent with what new pipeline runs produce.

Strategy:
  1. Load all rows ordered by (entity_id, date ASC) — one pass.
  2. For each entity, track prev_score as we iterate chronologically.
  3. Call compute_trend_state() with the correct prev context.
  4. Batch UPDATE in chunks of 500.

Run locally against production:
    DATABASE_URL="<prod-url>" python3 scripts/backfill_trend_state.py

Run on Railway:
    railway run --service pipeline-daily python3 scripts/backfill_trend_state.py

Add --dry-run to preview without writing.
Add --limit N to process only the N most-recent dates (useful for spot-check).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------

def _make_engine():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Railway / production Postgres
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        from sqlalchemy import create_engine
        return create_engine(db_url, pool_pre_ping=True)
    # Local SQLite fallback
    db_path = os.environ.get("PTI_DB_PATH", "outputs/market_dev.db")
    from sqlalchemy import create_engine
    return create_engine(f"sqlite:///{db_path}")


def main():
    parser = argparse.ArgumentParser(description="Backfill trend_state for entity_timeseries_daily")
    parser.add_argument("--dry-run", action="store_true", help="Preview only — no DB writes")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only process the N most recent dates (0 = all)")
    parser.add_argument("--only-null", action="store_true", default=True,
                        help="Only update rows where trend_state IS NULL (default: true)")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from perfume_trend_sdk.analysis.market_signals.trend_state import compute_trend_state

    engine = _make_engine()
    from sqlalchemy import text

    with engine.connect() as conn:
        # Check column exists
        try:
            conn.execute(text("SELECT trend_state FROM entity_timeseries_daily LIMIT 1"))
        except Exception as e:
            print(f"ERROR: trend_state column not found — run alembic upgrade head first.\n{e}")
            sys.exit(1)

        # Load all rows (or only NULL ones)
        where = "WHERE trend_state IS NULL" if args.only_null else ""
        count_q = conn.execute(text(f"SELECT COUNT(*) FROM entity_timeseries_daily {where}")).scalar()
        print(f"Rows to process: {count_q:,}")

        if count_q == 0:
            print("Nothing to backfill — all rows already have trend_state.")
            return

        # Load rows ordered chronologically per entity
        # We need ALL rows per entity (including already-set ones) to get correct prev context.
        # So we load everything, then only update NULL rows.
        print("Loading timeseries rows...")
        rows = conn.execute(text("""
            SELECT id, entity_id, date, composite_market_score, growth_rate,
                   momentum, acceleration, mention_count, trend_state
            FROM entity_timeseries_daily
            ORDER BY entity_id, date ASC
        """)).fetchall()
        print(f"Total rows loaded: {len(rows):,}")

        # Group by entity_id and compute trend_state with rolling prev context
        # date filtering
        if args.limit > 0:
            all_dates = sorted(set(r[2] for r in rows), reverse=True)
            cutoff_dates = set(all_dates[:args.limit])
        else:
            cutoff_dates = None  # all dates

        updates: list[tuple] = []  # (trend_state, row_id)
        prev_score_by_entity: dict[str, Optional[float]] = {}
        skipped_already_set = 0

        for row in rows:
            row_id, entity_id, row_date, score, growth_rate, momentum, acceleration, mention_count, existing_trend = row

            entity_key = str(entity_id)
            prev_score = prev_score_by_entity.get(entity_key)

            # Compute trend state regardless (needed to track prev correctly)
            state = compute_trend_state(
                score=float(score or 0.0),
                prev_score=prev_score,
                growth_rate=growth_rate,
                momentum=momentum,
                acceleration=acceleration,
                mention_count=float(mention_count or 0.0),
            )

            # Only queue update if: trend_state is NULL AND (no date limit OR date in cutoff)
            if existing_trend is None:
                if cutoff_dates is None or row_date in cutoff_dates:
                    updates.append((state, row_id))
            else:
                skipped_already_set += 1

            # Update rolling prev for next row of this entity (only for rows with real activity)
            if mention_count and mention_count > 0:
                prev_score_by_entity[entity_key] = float(score or 0.0)

        print(f"Rows to update:       {len(updates):,}")
        print(f"Rows already set:     {skipped_already_set:,}")

        # Count state distribution
        from collections import Counter
        dist = Counter(state for state, _ in updates)
        print("\nPlanned trend_state distribution:")
        for state, cnt in sorted(dist.items(), key=lambda x: -x[1]):
            label = state or "None (carry-forward)"
            print(f"  {label:20}: {cnt:,}")

        if args.dry_run:
            print("\n[DRY RUN] No writes performed.")
            return

        # Batch UPDATE
        BATCH = 500
        written = 0
        with engine.begin() as wconn:
            for i in range(0, len(updates), BATCH):
                batch = updates[i:i + BATCH]
                # Use CASE WHEN for bulk update compatibility
                for state, row_id in batch:
                    wconn.execute(
                        text("UPDATE entity_timeseries_daily SET trend_state = :ts WHERE id = :rid"),
                        {"ts": state, "rid": row_id},
                    )
                written += len(batch)
                print(f"  Written {written:,}/{len(updates):,}...", end="\r")

        print(f"\nBackfill complete. Updated {written:,} rows.")

        # Verification
        print("\nVerification — post-backfill distribution:")
        result = conn.execute(text("""
            SELECT trend_state, COUNT(*) as cnt
            FROM entity_timeseries_daily
            GROUP BY trend_state
            ORDER BY cnt DESC
        """)).fetchall()
        for state, cnt in result:
            label = state or "NULL (carry-forward / inactive)"
            print(f"  {label:25}: {cnt:,}")

        # Show sample active rows with trend_state for latest date
        latest = conn.execute(text("""
            SELECT MAX(date) FROM entity_timeseries_daily
            WHERE mention_count > 0 AND trend_state IS NOT NULL
        """)).scalar()
        if latest:
            print(f"\nSample active rows for {latest}:")
            samples = conn.execute(text("""
                SELECT e.canonical_name, t.composite_market_score, t.trend_state
                FROM entity_timeseries_daily t
                JOIN entity_market e ON e.id = t.entity_id
                WHERE t.date = :d AND t.mention_count > 0 AND t.trend_state IS NOT NULL
                ORDER BY t.composite_market_score DESC
                LIMIT 10
            """), {"d": latest}).fetchall()
            print(f"  {'Name':35} {'Score':8} {'Trend':12}")
            print(f"  {'-'*35} {'-'*8} {'-'*12}")
            for name, score, ts in samples:
                print(f"  {name[:35]:35} {float(score or 0):8.2f} {ts or '—':12}")


if __name__ == "__main__":
    main()
