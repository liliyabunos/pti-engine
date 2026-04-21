from __future__ import annotations

"""Job: review_candidates — Phase 4a Review & Approval Pipeline.

Provides a CLI interface to inspect, approve, reject, and normalize
fragrance candidates before promotion to the Knowledge Base.

Phase 4a NEVER writes to:
  - fragrance_master
  - aliases
  - brands

All writes go to fragrance_candidates.review_status and related fields only.

Commands
--------
  --list              List candidates awaiting review
  --summary           Print current review state counts
  --auto-approve-accepted
                      Auto-approve accepted_rule_based candidates above
                      --min-occurrences threshold (requires explicit flag)
  --approve <ID>      Approve a single candidate by ID
  --reject <ID>       Reject a single candidate by ID
  --normalize <ID>    Mark a candidate as needs_normalization with proposed text

Flags
-----
  --validation-status accepted_rule_based | review
  --review-status     pending_review | approved_for_promotion | rejected_final | needs_normalization
  --type              perfume | brand | note | unknown
  --min-occurrences   Minimum occurrence count (default: 1)
  --limit             Max rows to return in --list (default: 50)
  --entity-type       Used with --approve: intended KB type
  --normalized-text   Explicit normalized form (with --approve or --normalize)
  --notes             Review annotation (any action)
  --dry-run           Preview without writing (--auto-approve-accepted)

Run
---
  python -m perfume_trend_sdk.jobs.review_candidates --summary
  python -m perfume_trend_sdk.jobs.review_candidates --list --type perfume --min-occurrences 2
  python -m perfume_trend_sdk.jobs.review_candidates --auto-approve-accepted --min-occurrences 2 --dry-run
  python -m perfume_trend_sdk.jobs.review_candidates --auto-approve-accepted --min-occurrences 2
  python -m perfume_trend_sdk.jobs.review_candidates --approve 1234 --entity-type perfume
  python -m perfume_trend_sdk.jobs.review_candidates --reject 1234 --notes "generic phrase"
"""

import argparse
import logging
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_row(row: Dict[str, Any], *, show_normalized: bool = False) -> str:
    norm = row.get("normalized_candidate_text")
    norm_str = f"  →  \"{norm}\"" if norm and show_normalized else ""
    rtype = row.get("approved_entity_type") or row.get("candidate_type") or "?"
    return (
        f"  id={row['id']:6d}  occ={row['occurrences']:3d}  [{row['source_platform'] or '?':7s}]"
        f"  type={rtype:10s}  {row['normalized_text']}{norm_str}"
    )


def _print_section(header: str, rows: List[Dict], limit: int, show_normalized: bool = False) -> None:
    print(f"\n  --- {header} ---")
    if not rows:
        print("  (none)")
        return
    for row in rows[:limit]:
        print(_fmt_row(row, show_normalized=show_normalized))


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_summary(db) -> None:
    from perfume_trend_sdk.analysis.candidate_validation.reviewer import review_summary
    s = review_summary(db)
    print()
    print("=== Phase 4a Review Summary ===")
    print(f"  Total candidates          : {s['total']:,}")
    print(f"  pending_review            : {s['pending_review']:,}")
    print(f"  approved_for_promotion    : {s['approved_for_promotion']:,}")
    print(f"  rejected_final            : {s['rejected_final']:,}")
    print(f"  needs_normalization       : {s['needs_normalization']:,}")
    if s["approved_by_type"]:
        print()
        print("  Approved by entity type:")
        for etype, cnt in sorted(s["approved_by_type"].items(), key=lambda x: -x[1]):
            print(f"    {etype:12s}: {cnt:,}")


def cmd_list(db, args) -> None:
    from perfume_trend_sdk.analysis.candidate_validation.reviewer import get_candidates_for_review
    rows = get_candidates_for_review(
        db,
        validation_status=args.validation_status or None,
        review_status=args.review_status or None,
        candidate_type=args.type or None,
        min_occurrences=args.min_occurrences,
        limit=args.limit,
        order_by="occurrences",
    )
    review_status_label = args.review_status or "pending_review"
    print(f"\n  --- Top candidates (review_status={review_status_label}) ---")
    if not rows:
        print("  (none matching filters)")
        return
    for row in rows:
        print(_fmt_row(row, show_normalized=True))
    print(f"\n  Showing {len(rows)} rows.")


def cmd_auto_approve(db, args) -> None:
    from perfume_trend_sdk.analysis.candidate_validation.reviewer import bulk_approve_accepted
    dry = args.dry_run
    result = bulk_approve_accepted(
        db,
        min_occurrences=args.min_occurrences,
        dry_run=dry,
    )
    mode = "[DRY RUN]" if dry else "[APPLIED]"
    print(f"\n  {mode} auto-approve accepted_rule_based candidates")
    print(f"  min_occurrences: {result['min_occurrences']}")
    print(f"  types: {result['candidate_types']}")
    print(f"  total matched: {result['total_approved']}")
    print()
    if result["approved"]:
        print("  Approved candidates:")
        for r in result["approved"]:
            norm_str = f"  →  \"{r['normalized']}\"" if r["normalized"] else ""
            print(
                f"    id={r['id']:6d}  occ={r['occurrences']:3d}  [{r['source'] or '?':7s}]"
                f"  type={r['type']:10s}  {r['text']}{norm_str}"
            )
    if result["normalized_examples"]:
        print()
        print("  Normalization examples applied:")
        for ex in result["normalized_examples"][:10]:
            print(f"    \"{ex['original']}\" → \"{ex['normalized']}\"")

    if dry:
        print()
        print("  [DRY RUN] — no DB writes. Re-run without --dry-run to apply.")


def cmd_approve(db, args) -> None:
    from perfume_trend_sdk.analysis.candidate_validation.reviewer import approve_candidate
    cid = args.approve
    ok = approve_candidate(
        db,
        cid,
        entity_type=args.entity_type or None,
        normalized_text=args.normalized_text or None,
        notes=args.notes or None,
    )
    if ok:
        print(f"  Approved candidate id={cid}")
    else:
        print(f"  ERROR: candidate id={cid} not found.")
        sys.exit(1)


def cmd_reject(db, args) -> None:
    from perfume_trend_sdk.analysis.candidate_validation.reviewer import reject_candidate
    cid = args.reject
    ok = reject_candidate(db, cid, notes=args.notes or None)
    if ok:
        print(f"  Rejected candidate id={cid}")
    else:
        print(f"  ERROR: candidate id={cid} not found.")
        sys.exit(1)


def cmd_normalize(db, args) -> None:
    from perfume_trend_sdk.analysis.candidate_validation.reviewer import (
        mark_candidate_normalized,
        propose_normalized_form,
    )
    from sqlalchemy import text as sa_text
    cid = args.normalize

    # If no explicit text, auto-propose
    norm_text = args.normalized_text
    if not norm_text:
        row = db.execute(
            sa_text("SELECT normalized_text FROM fragrance_candidates WHERE id = :id"),
            {"id": cid},
        ).fetchone()
        if not row:
            print(f"  ERROR: candidate id={cid} not found.")
            sys.exit(1)
        proposed, changed = propose_normalized_form(row[0])
        if not changed:
            print(f"  No normalization needed for id={cid}: \"{row[0]}\"")
            return
        norm_text = proposed

    ok = mark_candidate_normalized(db, cid, norm_text, notes=args.notes or None)
    if ok:
        print(f"  Marked id={cid} as needs_normalization → \"{norm_text}\"")
    else:
        print(f"  ERROR: candidate id={cid} not found.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 4a: review and approve fragrance candidates for KB promotion"
    )

    # Command group (mutually exclusive)
    cmd_group = parser.add_mutually_exclusive_group(required=True)
    cmd_group.add_argument("--summary", action="store_true", help="Print review state counts")
    cmd_group.add_argument("--list", action="store_true", dest="do_list", help="List candidates")
    cmd_group.add_argument(
        "--auto-approve-accepted",
        action="store_true",
        dest="auto_approve",
        help="Auto-approve accepted_rule_based candidates above threshold",
    )
    cmd_group.add_argument("--approve", type=int, metavar="ID", help="Approve candidate by ID")
    cmd_group.add_argument("--reject", type=int, metavar="ID", help="Reject candidate by ID")
    cmd_group.add_argument(
        "--normalize", type=int, metavar="ID",
        help="Mark candidate as needs_normalization"
    )

    # Filter flags
    parser.add_argument("--validation-status", metavar="STATUS",
                        help="Filter by Phase 3B status (accepted_rule_based | review)")
    parser.add_argument("--review-status", metavar="STATUS",
                        help="Filter by Phase 4a status")
    parser.add_argument("--type", metavar="TYPE",
                        help="Filter by candidate_type (perfume | brand | note | unknown)")
    parser.add_argument("--min-occurrences", type=int, default=1,
                        metavar="N", help="Minimum occurrence count (default: 1)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max rows for --list (default: 50)")

    # Action flags
    parser.add_argument("--entity-type", metavar="TYPE",
                        help="Intended KB type for --approve (perfume | brand | note | unknown)")
    parser.add_argument("--normalized-text", metavar="TEXT",
                        help="Explicit normalized form for --approve or --normalize")
    parser.add_argument("--notes", metavar="TEXT", help="Reviewer annotation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without DB writes (used with --auto-approve-accepted)")

    args = parser.parse_args()

    from perfume_trend_sdk.storage.postgres.db import session_scope

    with session_scope() as db:
        if args.summary:
            cmd_summary(db)
        elif args.do_list:
            cmd_list(db, args)
        elif args.auto_approve:
            cmd_auto_approve(db, args)
        elif args.approve:
            cmd_approve(db, args)
        elif args.reject:
            cmd_reject(db, args)
        elif args.normalize:
            cmd_normalize(db, args)


if __name__ == "__main__":
    main()
