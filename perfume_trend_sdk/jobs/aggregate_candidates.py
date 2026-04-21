from __future__ import annotations

"""Job: aggregate_candidates

Re-computes confidence_score = log(occurrences + 1) for every candidate
in fragrance_candidates and marks them status='aggregated'.

Run after ingestion to propagate occurrence counts from all sources into
a single ranked list of unresolved mentions.

Usage:
    python -m perfume_trend_sdk.jobs.aggregate_candidates

Output summary dict (returned from run() and printed by __main__):
    {
        "total_candidates": int,
        "updated": int,
        "top_10": [ {normalized_text, occurrences, confidence_score, source_platform}, ... ]
    }
"""

import argparse
import logging
import math
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def run(db: Session) -> Dict[str, Any]:
    """Recompute confidence_score for all candidates and return a summary."""

    # Count total
    total = db.execute(text("SELECT COUNT(*) FROM fragrance_candidates")).scalar() or 0
    logger.info("[aggregate_candidates] total candidates: %d", total)

    if total == 0:
        return {"total_candidates": 0, "updated": 0, "top_10": []}

    # Load all rows that need updating
    rows = db.execute(
        text("SELECT id, occurrences FROM fragrance_candidates")
    ).fetchall()

    updated = 0
    for row_id, occurrences in rows:
        new_score = round(math.log(occurrences + 1), 4)
        db.execute(
            text(
                "UPDATE fragrance_candidates "
                "SET confidence_score = :score, status = 'aggregated' "
                "WHERE id = :id"
            ),
            {"score": new_score, "id": row_id},
        )
        updated += 1

    db.flush()
    logger.info("[aggregate_candidates] updated %d rows", updated)

    # Top 10 by occurrences
    top_rows = db.execute(
        text(
            "SELECT normalized_text, occurrences, confidence_score, source_platform "
            "FROM fragrance_candidates "
            "ORDER BY occurrences DESC, confidence_score DESC "
            "LIMIT 10"
        )
    ).fetchall()

    top_10: List[Dict[str, Any]] = [
        {
            "normalized_text": r[0],
            "occurrences": r[1],
            "confidence_score": r[2],
            "source_platform": r[3],
        }
        for r in top_rows
    ]

    # Distribution stats
    dist_rows = db.execute(
        text(
            "SELECT "
            "  SUM(CASE WHEN occurrences = 1 THEN 1 ELSE 0 END) AS singles, "
            "  SUM(CASE WHEN occurrences BETWEEN 2 AND 4 THEN 1 ELSE 0 END) AS low, "
            "  SUM(CASE WHEN occurrences BETWEEN 5 AND 9 THEN 1 ELSE 0 END) AS medium, "
            "  SUM(CASE WHEN occurrences >= 10 THEN 1 ELSE 0 END) AS high "
            "FROM fragrance_candidates"
        )
    ).fetchone()

    distribution = {
        "singles (1)": dist_rows[0] or 0,
        "low (2-4)": dist_rows[1] or 0,
        "medium (5-9)": dist_rows[2] or 0,
        "high (10+)": dist_rows[3] or 0,
    }

    summary = {
        "total_candidates": total,
        "updated": updated,
        "top_10": top_10,
        "distribution": distribution,
    }
    logger.info("[aggregate_candidates] complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    from perfume_trend_sdk.storage.postgres.db import session_scope

    parser = argparse.ArgumentParser(description="Aggregate fragrance_candidates confidence scores")
    parser.parse_args()

    with session_scope() as db:
        summary = run(db)

    print("\n=== Candidate Aggregation Summary ===")
    print(f"  Total candidates : {summary['total_candidates']}")
    print(f"  Updated rows     : {summary['updated']}")

    print("\n  Confidence distribution:")
    for label, count in summary.get("distribution", {}).items():
        print(f"    {label:20s}: {count}")

    print("\n  Top 10 candidates (by occurrences):")
    print(f"  {'Rank':<5} {'Occurrences':<12} {'Confidence':<10} {'Platform':<10} {'Text'}")
    print("  " + "-" * 80)
    for i, row in enumerate(summary["top_10"], 1):
        print(
            f"  {i:<5} {row['occurrences']:<12} {row['confidence_score']:<10.4f} "
            f"{(row['source_platform'] or 'unknown'):<10} {row['normalized_text']}"
        )


if __name__ == "__main__":
    main()
