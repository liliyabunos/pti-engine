from __future__ import annotations

"""Job: validate_candidates — Phase 3B Candidate Validation & Noise Filtering.

Classifies every row in fragrance_candidates using deterministic rules.
No AI, no external calls, no DB writes to any table other than
fragrance_candidates.

Idempotent: re-running overwrites previous classification with the same result.

Run:
    python -m perfume_trend_sdk.jobs.validate_candidates

Flags:
    --dry-run     Print summary without writing to DB
    --batch-size  Rows per DB transaction (default: 500)
"""

import argparse
import logging
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# Batch size for DB UPDATE operations
DEFAULT_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

def run(
    db: Session,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Dict[str, Any]:
    """Load, classify, and optionally update all fragrance_candidates rows.

    Returns a summary dict with counts and example rows.
    """
    from perfume_trend_sdk.analysis.candidate_validation.rules import (
        load_brand_tokens,
        load_note_names,
    )
    from perfume_trend_sdk.analysis.candidate_validation.classifier import classify

    # -----------------------------------------------------------------------
    # Load rule assets from DB (done once per run)
    # -----------------------------------------------------------------------
    logger.info("[validate_candidates] loading brand tokens...")
    brand_tokens = load_brand_tokens(db)
    logger.info("[validate_candidates] brand tokens loaded: %d", len(brand_tokens))

    logger.info("[validate_candidates] loading note names from notes_canonical...")
    note_names = load_note_names(db)
    logger.info("[validate_candidates] note names loaded: %d", len(note_names))

    # -----------------------------------------------------------------------
    # Load all candidates
    # -----------------------------------------------------------------------
    rows = db.execute(
        text(
            "SELECT id, normalized_text, occurrences, source_platform "
            "FROM fragrance_candidates "
            "ORDER BY occurrences DESC"
        )
    ).fetchall()

    total = len(rows)
    logger.info("[validate_candidates] classifying %d candidates...", total)

    # -----------------------------------------------------------------------
    # Classify each row
    # -----------------------------------------------------------------------
    updates: List[Dict[str, Any]] = []
    counts: Dict[str, int] = defaultdict(int)
    # For report examples
    examples: Dict[str, List[Dict]] = defaultdict(list)

    for row_id, normalized_text, occurrences, source_platform in rows:
        result = classify(normalized_text, brand_tokens, note_names)

        token_count = len(normalized_text.strip().split())
        update = {
            "id": row_id,
            "candidate_type": result.candidate_type,
            "validation_status": result.validation_status,
            "rejection_reason": result.rejection_reason,
            "token_count": result.token_count,
            "contains_brand_keyword": 1 if result.contains_brand_keyword else 0,
            "contains_perfume_keyword": 1 if result.contains_perfume_keyword else 0,
        }
        updates.append(update)

        key = result.validation_status
        counts[key] += 1

        # Collect up to 30 examples per bucket
        if len(examples[key]) < 30:
            examples[key].append({
                "text": normalized_text,
                "type": result.candidate_type,
                "status": result.validation_status,
                "reason": result.rejection_reason,
                "occurrences": occurrences,
                "source": source_platform,
            })

    logger.info("[validate_candidates] classification complete: %s", dict(counts))

    # -----------------------------------------------------------------------
    # Write to DB (skip if dry_run)
    # -----------------------------------------------------------------------
    if not dry_run:
        _batch_update(db, updates, batch_size)
        logger.info("[validate_candidates] DB updated.")
    else:
        logger.info("[validate_candidates] dry-run mode — no DB writes.")

    # -----------------------------------------------------------------------
    # Build summary
    # -----------------------------------------------------------------------
    summary = {
        "total": total,
        "counts": dict(counts),
        "accepted_rule_based": counts.get("accepted_rule_based", 0),
        "rejected_noise": counts.get("rejected_noise", 0),
        "review": counts.get("review", 0),
        "pending": counts.get("pending", 0),
        "examples": dict(examples),
        "brand_tokens_loaded": len(brand_tokens),
        "note_names_loaded": len(note_names),
        "dry_run": dry_run,
    }

    logger.info("[validate_candidates] complete: %s", {k: v for k, v in summary.items() if k != "examples"})
    return summary


def _batch_update(
    db: Session, updates: List[Dict[str, Any]], batch_size: int
) -> None:
    """Write classification results to fragrance_candidates in batches."""
    total_written = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i : i + batch_size]
        for u in batch:
            db.execute(
                text(
                    "UPDATE fragrance_candidates SET "
                    "  candidate_type = :ct, "
                    "  validation_status = :vs, "
                    "  rejection_reason = :rr, "
                    "  token_count = :tc, "
                    "  contains_brand_keyword = :cbk, "
                    "  contains_perfume_keyword = :cpk "
                    "WHERE id = :id"
                ),
                {
                    "ct": u["candidate_type"],
                    "vs": u["validation_status"],
                    "rr": u["rejection_reason"],
                    "tc": u["token_count"],
                    "cbk": u["contains_brand_keyword"],
                    "cpk": u["contains_perfume_keyword"],
                    "id": u["id"],
                },
            )
        db.flush()
        total_written += len(batch)
        logger.info("[validate_candidates] wrote %d / %d rows", total_written, len(updates))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 3B: classify fragrance_candidates with deterministic rules"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and report without writing to DB",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"DB update batch size (default: {DEFAULT_BATCH_SIZE})",
    )
    args = parser.parse_args()

    from perfume_trend_sdk.storage.postgres.db import session_scope

    with session_scope() as db:
        summary = run(db, dry_run=args.dry_run, batch_size=args.batch_size)

    _print_summary(summary)


def _print_summary(summary: Dict[str, Any]) -> None:
    total = summary["total"]
    counts = summary["counts"]
    examples = summary["examples"]

    print()
    print("=== Phase 3B Candidate Validation Summary ===")
    print(f"  Total candidates          : {total:,}")
    print(f"  accepted_rule_based       : {counts.get('accepted_rule_based', 0):,}")
    print(f"  rejected_noise            : {counts.get('rejected_noise', 0):,}")
    print(f"  review                    : {counts.get('review', 0):,}")
    if counts.get("pending"):
        print(f"  pending                   : {counts['pending']:,}")
    print(f"  brand tokens loaded       : {summary['brand_tokens_loaded']:,}")
    print(f"  note names loaded         : {summary['note_names_loaded']:,}")
    if summary["dry_run"]:
        print("  [DRY RUN — no DB writes]")

    print()
    _print_examples(
        "Top accepted perfume/brand candidates",
        [r for r in examples.get("accepted_rule_based", [])],
        20,
    )

    print()
    _print_examples(
        "Top review candidates (ambiguous — needs human review)",
        [r for r in examples.get("review", []) if r["type"] != "noise"],
        20,
    )

    print()
    _print_examples(
        "Top rejected noise phrases",
        examples.get("rejected_noise", []),
        20,
        show_reason=True,
    )


def _print_examples(
    header: str,
    rows: List[Dict],
    limit: int,
    show_reason: bool = False,
) -> None:
    print(f"  --- {header} ---")
    if not rows:
        print("  (none)")
        return
    for row in rows[:limit]:
        reason_str = f"  [{row['reason']}]" if show_reason and row.get("reason") else ""
        print(
            f"  occ={row['occurrences']:3d}  [{row['source'] or 'unknown':7s}]"
            f"  type={row['type']:10s}  {row['text']}{reason_str}"
        )


if __name__ == "__main__":
    main()
