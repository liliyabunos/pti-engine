from __future__ import annotations

"""Job: detect_metadata_gaps — Phase 5 Coverage Maintenance

Scans for perfume entities in entity_market with missing or empty metadata:
  - missing_fragrantica  : no fragrantica_records row for this entity
  - missing_notes        : fragrantica_records row exists but all note lists are empty
  - missing_accords      : fragrantica_records row exists but accords_json is empty

Writes candidates into metadata_gap_queue (idempotent via ON CONFLICT on entity_id + gap_type).

Usage:
    python -m perfume_trend_sdk.jobs.detect_metadata_gaps
    python -m perfume_trend_sdk.jobs.detect_metadata_gaps --dry-run
    python -m perfume_trend_sdk.jobs.detect_metadata_gaps --gap-types missing_fragrantica
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

VALID_GAP_TYPES = {"missing_fragrantica", "missing_notes", "missing_accords"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_missing_fragrantica(db: Session) -> List[Dict[str, Any]]:
    """Perfumes in entity_market with no fragrantica_records row."""
    rows = db.execute(text("""
        SELECT e.id, e.entity_type, e.canonical_name
        FROM entity_market e
        LEFT JOIN fragrantica_records fr ON fr.perfume_id = e.id
        WHERE e.entity_type = 'perfume'
          AND fr.id IS NULL
        ORDER BY e.canonical_name
    """)).fetchall()

    return [
        {
            "entity_id": str(r[0]),
            "entity_type": str(r[1]),
            "canonical_name": str(r[2]) if r[2] else None,
            "gap_type": "missing_fragrantica",
            "reason": "no_fragrantica_record",
            "priority": 7,
            "fragrance_id": None,
        }
        for r in rows
    ]


def _detect_missing_notes(db: Session) -> List[Dict[str, Any]]:
    """Perfumes with a fragrantica_records row but all note lists empty."""
    rows = db.execute(text("""
        SELECT e.id, e.entity_type, e.canonical_name, fr.fragrance_id
        FROM entity_market e
        JOIN fragrantica_records fr ON fr.perfume_id = e.id
        WHERE e.entity_type = 'perfume'
          AND (fr.notes_top_json IS NULL OR fr.notes_top_json = '[]')
          AND (fr.notes_middle_json IS NULL OR fr.notes_middle_json = '[]')
          AND (fr.notes_base_json IS NULL OR fr.notes_base_json = '[]')
        ORDER BY e.canonical_name
    """)).fetchall()

    return [
        {
            "entity_id": str(r[0]),
            "entity_type": str(r[1]),
            "canonical_name": str(r[2]) if r[2] else None,
            "gap_type": "missing_notes",
            "reason": "fragrantica_record_has_no_notes",
            "priority": 5,
            "fragrance_id": str(r[3]) if r[3] else None,
        }
        for r in rows
    ]


def _detect_missing_accords(db: Session) -> List[Dict[str, Any]]:
    """Perfumes with a fragrantica_records row but empty accords_json."""
    rows = db.execute(text("""
        SELECT e.id, e.entity_type, e.canonical_name, fr.fragrance_id
        FROM entity_market e
        JOIN fragrantica_records fr ON fr.perfume_id = e.id
        WHERE e.entity_type = 'perfume'
          AND (fr.accords_json IS NULL OR fr.accords_json = '[]')
        ORDER BY e.canonical_name
    """)).fetchall()

    return [
        {
            "entity_id": str(r[0]),
            "entity_type": str(r[1]),
            "canonical_name": str(r[2]) if r[2] else None,
            "gap_type": "missing_accords",
            "reason": "fragrantica_record_has_no_accords",
            "priority": 6,
            "fragrance_id": str(r[3]) if r[3] else None,
        }
        for r in rows
    ]


def _upsert_metadata_gap_queue(
    db: Session, gaps: List[Dict[str, Any]], dry_run: bool
) -> int:
    if not gaps or dry_run:
        return 0

    now = _now_iso()
    written = 0
    for item in gaps:
        db.execute(text("""
            INSERT INTO metadata_gap_queue
              (entity_id, entity_type, canonical_name, gap_type, reason,
               priority, status, fragrance_id, created_at, updated_at)
            VALUES
              (:entity_id, :entity_type, :canonical_name, :gap_type, :reason,
               :priority, 'pending', :fragrance_id, :now, :now)
            ON CONFLICT (entity_id, gap_type) DO UPDATE SET
              reason       = EXCLUDED.reason,
              priority     = EXCLUDED.priority,
              fragrance_id = COALESCE(EXCLUDED.fragrance_id, metadata_gap_queue.fragrance_id),
              updated_at   = EXCLUDED.updated_at,
              status       = CASE
                               WHEN metadata_gap_queue.status IN ('done', 'failed')
                               THEN 'pending'
                               ELSE metadata_gap_queue.status
                             END
        """), {**item, "now": now})
        written += 1

    db.flush()
    return written


def run(
    db: Session,
    gap_types: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    active_types = gap_types if gap_types else list(VALID_GAP_TYPES)
    all_gaps: List[Dict[str, Any]] = []

    if "missing_fragrantica" in active_types:
        found = _detect_missing_fragrantica(db)
        logger.info("[detect_metadata_gaps] missing_fragrantica: %d entities", len(found))
        all_gaps.extend(found)

    if "missing_notes" in active_types:
        found = _detect_missing_notes(db)
        logger.info("[detect_metadata_gaps] missing_notes: %d entities", len(found))
        all_gaps.extend(found)

    if "missing_accords" in active_types:
        found = _detect_missing_accords(db)
        logger.info("[detect_metadata_gaps] missing_accords: %d entities", len(found))
        all_gaps.extend(found)

    written = _upsert_metadata_gap_queue(db, all_gaps, dry_run)

    by_type: Dict[str, int] = {}
    for g in all_gaps:
        by_type[g["gap_type"]] = by_type.get(g["gap_type"], 0) + 1

    return {
        "gaps_found": len(all_gaps),
        "written_to_queue": written,
        "by_gap_type": by_type,
        "dry_run": dry_run,
        "top_10": all_gaps[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5: detect metadata gaps")
    parser.add_argument("--gap-types", nargs="+", choices=list(VALID_GAP_TYPES),
                        help="Gap types to detect (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect but do not write to queue")
    args = parser.parse_args()

    from perfume_trend_sdk.storage.postgres.db import session_scope

    with session_scope() as db:
        summary = run(db, gap_types=args.gap_types, dry_run=args.dry_run)

    print()
    print("=== Metadata Gap Detection ===")
    print(f"  Total gaps found          : {summary['gaps_found']}")
    print(f"  Written to queue          : {summary['written_to_queue']}")
    for gap_type, count in summary["by_gap_type"].items():
        print(f"    {gap_type:<28}: {count}")
    print(f"  Dry run                   : {summary['dry_run']}")

    if summary["top_10"]:
        print(f"\n  Sample gaps detected:")
        for item in summary["top_10"]:
            print(f"    [{item['priority']}] {item['gap_type']:<25}  "
                  f"{item['canonical_name'] or item['entity_id'][:16]}")


if __name__ == "__main__":
    main()
