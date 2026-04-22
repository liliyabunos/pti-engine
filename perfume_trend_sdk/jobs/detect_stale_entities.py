from __future__ import annotations

"""Job: detect_stale_entities — Phase 5 Coverage Maintenance

Scans entity_market for entities with no recent market activity and writes
them into stale_entity_queue for follow-up.

Stale definition:
  - Last timeseries row with mention_count > 0 is older than --stale-days (default: 14)
  - OR entity is in entity_market but has zero timeseries rows at all

Idempotency:
  - Uses ON CONFLICT (entity_id) DO UPDATE so re-running is always safe
  - Entities that have since become active are moved back to status='pending'
    (detection refreshes the row)

Usage:
    python -m perfume_trend_sdk.jobs.detect_stale_entities
    python -m perfume_trend_sdk.jobs.detect_stale_entities --stale-days 30
    python -m perfume_trend_sdk.jobs.detect_stale_entities --dry-run
"""

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_STALE_DAYS = 14


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_stale(db: Session, stale_days: int) -> List[Dict[str, Any]]:
    """Return list of stale entity dicts."""
    rows = db.execute(text("""
        SELECT
            e.id            AS entity_id,
            e.entity_type,
            e.canonical_name,
            MAX(CASE WHEN t.mention_count > 0 THEN t.date ELSE NULL END) AS last_active_date
        FROM entity_market e
        LEFT JOIN entity_timeseries_daily t ON t.entity_id = e.id
        GROUP BY e.id, e.entity_type, e.canonical_name
        HAVING
            MAX(CASE WHEN t.mention_count > 0 THEN t.date ELSE NULL END) IS NULL
            OR MAX(CASE WHEN t.mention_count > 0 THEN t.date ELSE NULL END) <
               (CURRENT_DATE - CAST(:stale_days AS INTEGER))
        ORDER BY last_active_date ASC NULLS FIRST
    """), {"stale_days": stale_days}).fetchall()

    result = []
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for r in rows:
        entity_id, entity_type, canonical_name, last_active_date = (
            str(r[0]), str(r[1]), str(r[2]) if r[2] else None, r[3]
        )
        last_seen = str(last_active_date) if last_active_date else None
        if last_seen is None:
            days_inactive = None
            reason = "no_timeseries_rows"
        else:
            from datetime import date
            last_date = date.fromisoformat(str(last_seen))
            today = date.fromisoformat(today_str)
            days_inactive = (today - last_date).days
            reason = f"inactive_{days_inactive}d"

        priority = 1 if last_seen is None else (3 if days_inactive and days_inactive > 30 else 5)

        result.append({
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "reason": reason,
            "priority": priority,
            "last_seen_date": last_seen,
            "days_inactive": days_inactive,
        })

    return result


def _upsert_stale_queue(db: Session, stale: List[Dict[str, Any]], dry_run: bool) -> int:
    """Insert or update rows in stale_entity_queue. Returns count written."""
    if not stale or dry_run:
        return 0

    now = _now_iso()
    written = 0
    for item in stale:
        db.execute(text("""
            INSERT INTO stale_entity_queue
              (entity_id, entity_type, canonical_name, reason, priority,
               status, last_seen_date, days_inactive, created_at, updated_at)
            VALUES
              (:entity_id, :entity_type, :canonical_name, :reason, :priority,
               'pending', :last_seen_date, :days_inactive, :now, :now)
            ON CONFLICT (entity_id) DO UPDATE SET
              reason          = EXCLUDED.reason,
              priority        = EXCLUDED.priority,
              last_seen_date  = EXCLUDED.last_seen_date,
              days_inactive   = EXCLUDED.days_inactive,
              updated_at      = EXCLUDED.updated_at,
              status          = CASE
                                  WHEN stale_entity_queue.status IN ('done', 'failed')
                                  THEN 'pending'
                                  ELSE stale_entity_queue.status
                                END
        """), {**item, "now": now})
        written += 1

    db.flush()
    return written


def run(db: Session, stale_days: int = _DEFAULT_STALE_DAYS, dry_run: bool = False) -> Dict[str, Any]:
    logger.info("[detect_stale] Scanning for entities inactive for >%d days", stale_days)

    stale = _detect_stale(db, stale_days)
    logger.info("[detect_stale] Found %d stale entities", len(stale))

    written = _upsert_stale_queue(db, stale, dry_run)

    no_ts = sum(1 for s in stale if s["reason"] == "no_timeseries_rows")
    very_stale = sum(1 for s in stale if s["days_inactive"] and s["days_inactive"] > 30)

    return {
        "stale_found": len(stale),
        "written_to_queue": written,
        "no_timeseries": no_ts,
        "inactive_over_30d": very_stale,
        "dry_run": dry_run,
        "top_10": stale[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5: detect stale entities")
    parser.add_argument("--stale-days", type=int, default=_DEFAULT_STALE_DAYS,
                        help=f"Days of inactivity threshold (default: {_DEFAULT_STALE_DAYS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect but do not write to queue")
    args = parser.parse_args()

    from perfume_trend_sdk.storage.postgres.db import session_scope

    with session_scope() as db:
        summary = run(db, stale_days=args.stale_days, dry_run=args.dry_run)

    print()
    print("=== Stale Entity Detection ===")
    print(f"  Stale entities found      : {summary['stale_found']}")
    print(f"  Written to queue          : {summary['written_to_queue']}")
    print(f"  No timeseries at all      : {summary['no_timeseries']}")
    print(f"  Inactive > 30 days        : {summary['inactive_over_30d']}")
    print(f"  Dry run                   : {summary['dry_run']}")

    if summary["top_10"]:
        print(f"\n  Top 10 stale entities:")
        for item in summary["top_10"]:
            days_str = f"{item['days_inactive']}d" if item["days_inactive"] is not None else "no data"
            print(f"    [{item['priority']}] {item['canonical_name'] or item['entity_id'][:12]}  "
                  f"reason={item['reason']}  last_seen={item['last_seen_date'] or 'never'}  ({days_str})")


if __name__ == "__main__":
    main()
