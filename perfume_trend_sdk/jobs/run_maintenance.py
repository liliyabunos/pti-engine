from __future__ import annotations

"""Job: run_maintenance — Phase 5 Coverage Maintenance Runner

Processes bounded pending items from stale_entity_queue and metadata_gap_queue.

Execution model (conservative — Phase 5 initial version):
  - stale_entity_queue:
      No automated refresh path exists yet (targeted re-ingestion requires
      per-entity search queries which are outside the current pipeline scope).
      Items are marked status='detected_only' with a note explaining the
      limitation. This records the maintenance concern without risky fallback.

  - metadata_gap_queue (missing_fragrantica, missing_notes, missing_accords):
      Fragrantica enrichment requires CDP browser access — not available in
      automated production context. Items are marked status='pending_enrichment'
      so they surface in future enrichment batch runs (local CDP or future
      remote browser infrastructure).

Usage:
    python -m perfume_trend_sdk.jobs.run_maintenance
    python -m perfume_trend_sdk.jobs.run_maintenance --limit 20
    python -m perfume_trend_sdk.jobs.run_maintenance --dry-run
    python -m perfume_trend_sdk.jobs.run_maintenance --queue stale
    python -m perfume_trend_sdk.jobs.run_maintenance --queue metadata
"""

import argparse
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Queue readers
# ---------------------------------------------------------------------------

def _load_pending_stale(db: Session, limit: int) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT id, entity_id, entity_type, canonical_name, reason,
               priority, last_seen_date, days_inactive
        FROM stale_entity_queue
        WHERE status = 'pending'
        ORDER BY priority ASC, days_inactive DESC NULLS FIRST
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    return [
        {
            "id": r[0],
            "entity_id": str(r[1]),
            "entity_type": str(r[2]),
            "canonical_name": str(r[3]) if r[3] else None,
            "reason": str(r[4]),
            "priority": r[5],
            "last_seen_date": r[6],
            "days_inactive": r[7],
        }
        for r in rows
    ]


def _load_pending_metadata(db: Session, limit: int) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT id, entity_id, entity_type, canonical_name, gap_type,
               reason, priority, fragrance_id
        FROM metadata_gap_queue
        WHERE status = 'pending'
        ORDER BY priority ASC, gap_type
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    return [
        {
            "id": r[0],
            "entity_id": str(r[1]),
            "entity_type": str(r[2]),
            "canonical_name": str(r[3]) if r[3] else None,
            "gap_type": str(r[4]),
            "reason": str(r[5]),
            "priority": r[6],
            "fragrance_id": str(r[7]) if r[7] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Queue processors
# ---------------------------------------------------------------------------

def _process_stale_item(db: Session, item: Dict[str, Any], dry_run: bool) -> str:
    """
    No automated refresh path exists yet.
    Mark as detected_only — the maintenance concern is recorded.
    A future targeted re-ingestion feature will pick these up.
    """
    new_status = "detected_only"
    note = (
        "No automated refresh path available in current pipeline. "
        "Entity will be re-evaluated next maintenance cycle. "
        f"Last active: {item.get('last_seen_date') or 'never'}."
    )
    if not dry_run:
        db.execute(text("""
            UPDATE stale_entity_queue
            SET status = :status,
                updated_at = :now,
                last_attempted_at = :now,
                notes_json = :note
            WHERE id = :id
        """), {"status": new_status, "now": _now_iso(), "note": note, "id": item["id"]})
    return new_status


def _process_metadata_gap_item(db: Session, item: Dict[str, Any], dry_run: bool) -> str:
    """
    Fragrantica enrichment requires CDP browser — not automated in production.
    Mark as pending_enrichment so the item surfaces in future local CDP runs.
    """
    new_status = "pending_enrichment"
    fragrance_id_str = item.get("fragrance_id") or "unknown"
    note = (
        f"gap_type={item['gap_type']}. "
        f"Fragrantica enrichment requires CDP browser access (not available in automated prod). "
        f"fragrance_id={fragrance_id_str}. "
        "Will be resolved when local CDP enrichment batch runs."
    )
    if not dry_run:
        db.execute(text("""
            UPDATE metadata_gap_queue
            SET status = :status,
                updated_at = :now,
                last_attempted_at = :now,
                notes_json = :note
            WHERE id = :id
        """), {"status": new_status, "now": _now_iso(), "note": note, "id": item["id"]})
    return new_status


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(
    db: Session,
    limit: int = _DEFAULT_LIMIT,
    queue: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {
        "stale_processed": 0,
        "stale_outcomes": {},
        "metadata_processed": 0,
        "metadata_outcomes": {},
        "dry_run": dry_run,
    }

    per_queue = limit  # each queue gets the full limit budget independently

    # --- stale_entity_queue ---
    if queue in (None, "stale"):
        stale_items = _load_pending_stale(db, per_queue)
        logger.info("[run_maintenance] stale queue: %d pending items (limit=%d)",
                    len(stale_items), per_queue)
        for item in stale_items:
            outcome = _process_stale_item(db, item, dry_run)
            results["stale_outcomes"][outcome] = results["stale_outcomes"].get(outcome, 0) + 1
            results["stale_processed"] += 1
            logger.debug("[run_maintenance] stale id=%d %s → %s",
                         item["id"], item.get("canonical_name") or item["entity_id"][:12], outcome)

    # --- metadata_gap_queue ---
    if queue in (None, "metadata"):
        meta_items = _load_pending_metadata(db, per_queue)
        logger.info("[run_maintenance] metadata queue: %d pending items (limit=%d)",
                    len(meta_items), per_queue)
        for item in meta_items:
            outcome = _process_metadata_gap_item(db, item, dry_run)
            results["metadata_outcomes"][outcome] = results["metadata_outcomes"].get(outcome, 0) + 1
            results["metadata_processed"] += 1
            logger.debug("[run_maintenance] metadata id=%d gap=%s %s → %s",
                         item["id"], item["gap_type"],
                         item.get("canonical_name") or item["entity_id"][:12], outcome)

    if not dry_run:
        db.flush()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5: maintenance runner")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                        help=f"Max items to process per queue (default: {_DEFAULT_LIMIT})")
    parser.add_argument("--queue", choices=["stale", "metadata"],
                        help="Process only one queue (default: both)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read queues and compute outcomes but do not write status updates")
    args = parser.parse_args()

    from perfume_trend_sdk.storage.postgres.db import session_scope

    with session_scope() as db:
        results = run(db, limit=args.limit, queue=args.queue, dry_run=args.dry_run)

    print()
    print("=== Maintenance Runner ===")
    print(f"  Dry run                   : {results['dry_run']}")
    print(f"  Stale items processed     : {results['stale_processed']}")
    for outcome, count in results["stale_outcomes"].items():
        print(f"    → {outcome:<28}: {count}")
    print(f"  Metadata items processed  : {results['metadata_processed']}")
    for outcome, count in results["metadata_outcomes"].items():
        print(f"    → {outcome:<28}: {count}")


if __name__ == "__main__":
    main()
