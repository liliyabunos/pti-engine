from __future__ import annotations

"""Job: promote_candidates — Phase 4b Safe Promotion to Knowledge Base.

Promotes approved fragrance candidates into the resolver Knowledge Base
(fragrance_master, aliases, brands, perfumes in RESOLVER_DB_PATH).

Phase 4b rules
--------------
  - Only processes candidates with review_status = 'approved_for_promotion'
  - Operates on TWO databases:
      market_db (PTI_DB_PATH)    — fragrance_candidates source
      kb_db    (RESOLVER_DB_PATH) — KB write target (fragrance_master, aliases, etc.)
  - NEVER overwrites existing canonical entities
  - create_new_entity is gated behind --allow-create flag (off by default)
  - dry_run is the default — must pass --no-dry-run to write

Decisions
---------
  exact_existing_entity  — already in KB; no write needed
  merge_into_existing    — add new alias for existing entity
  create_new_entity      — create brand/perfume/FM rows + alias
  reject_promotion       — fails safeguards; no write

Run
---
  # Preview (safe — no DB writes)
  python -m perfume_trend_sdk.jobs.promote_candidates --dry-run

  # Bounded real run (perfume + brand, creates allowed)
  python -m perfume_trend_sdk.jobs.promote_candidates --no-dry-run --limit 25 --allow-create

  # Perfume only, no new entity creation
  python -m perfume_trend_sdk.jobs.promote_candidates --no-dry-run --limit 25 --type perfume
"""

import argparse
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB paths
# ---------------------------------------------------------------------------

_DEFAULT_MARKET_DB = os.environ.get("PTI_DB_PATH", "outputs/market_dev.db")
_DEFAULT_KB_DB = os.environ.get("RESOLVER_DB_PATH", "outputs/pti.db")


# ---------------------------------------------------------------------------
# Candidate loader (from market DB)
# ---------------------------------------------------------------------------

def _load_approved_candidates(
    market_cur: sqlite3.Cursor,
    *,
    candidate_types: Optional[List[str]] = None,
    min_occurrences: int = 1,
    limit: int = 200,
    already_promoted: bool = False,
) -> List[Dict[str, Any]]:
    """Load approved_for_promotion candidates from market DB."""
    conditions = ["review_status = 'approved_for_promotion'"]
    params: List[Any] = []

    if candidate_types:
        placeholders = ",".join("?" * len(candidate_types))
        conditions.append(f"(approved_entity_type IN ({placeholders}) OR candidate_type IN ({placeholders}))")
        params.extend(candidate_types)
        params.extend(candidate_types)

    conditions.append("occurrences >= ?")
    params.append(min_occurrences)

    if not already_promoted:
        conditions.append("(promotion_decision IS NULL)")

    where = " AND ".join(conditions)
    sql = (
        f"SELECT id, normalized_text, normalized_candidate_text, candidate_type, "
        f"  approved_entity_type, occurrences, source_platform, promotion_decision "
        f"FROM fragrance_candidates "
        f"WHERE {where} "
        f"ORDER BY occurrences DESC, id "
        f"LIMIT ?"
    )
    params.append(limit)

    market_cur.execute(sql, params)
    rows = market_cur.fetchall()
    keys = [
        "id", "normalized_text", "normalized_candidate_text", "candidate_type",
        "approved_entity_type", "occurrences", "source_platform", "promotion_decision",
    ]
    return [dict(zip(keys, r)) for r in rows]


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _fmt_candidate(c: Dict[str, Any]) -> str:
    etype = c.get("approved_entity_type") or c.get("candidate_type") or "?"
    norm_cand = c.get("normalized_candidate_text") or ""
    norm_cand_str = f"  →  \"{norm_cand}\"" if norm_cand and norm_cand != c["normalized_text"] else ""
    return (
        f"  id={c['id']:6d}  occ={c['occurrences']:3d}  [{c.get('source_platform') or '?':7s}]"
        f"  [{etype:10s}]  \"{c['normalized_text']}\"{norm_cand_str}"
    )


def _fmt_check(check, show_reason: bool = True) -> str:
    reason_str = f"  ({check.reason})" if show_reason else ""
    target_str = ""
    if check.matched_canonical_name:
        target_str = f"  →  \"{check.matched_canonical_name}\""
    elif check.canonical_name_to_create:
        target_str = f"  →  create \"{check.canonical_name_to_create}\""
    return (
        f"  id={check.candidate_id:6d}  [{check.entity_type:10s}]"
        f"  \"{check.promotion_text}\"{target_str}{reason_str}"
    )


def _print_bucket(label: str, checks, limit: int = 10, show_reason: bool = True) -> None:
    print(f"\n  --- {label} ({len(checks)}) ---")
    for ch in checks[:limit]:
        print(_fmt_check(ch, show_reason=show_reason))
    if len(checks) > limit:
        print(f"  ... and {len(checks) - limit} more")


# ---------------------------------------------------------------------------
# Dry-run report
# ---------------------------------------------------------------------------

def run_dry_run(
    candidates: List[Dict[str, Any]],
    checks,
    allow_create: bool,
) -> None:
    from perfume_trend_sdk.analysis.candidate_validation.promoter import (
        DECISION_CREATE, DECISION_EXACT, DECISION_MERGE, DECISION_REJECT,
    )

    buckets = defaultdict(list)
    for ch in checks:
        buckets[ch.decision].append(ch)

    total = len(checks)
    n_exact = len(buckets[DECISION_EXACT])
    n_merge = len(buckets[DECISION_MERGE])
    n_create = len(buckets[DECISION_CREATE])
    n_reject = len(buckets[DECISION_REJECT])

    print()
    print("=== Phase 4b Dry-Run Preview ===")
    print(f"  Candidates evaluated        : {total}")
    print(f"  exact_existing_entity       : {n_exact} (already in KB — no write needed)")
    print(f"  merge_into_existing         : {n_merge} (will add alias to existing entity)")
    print(f"  create_new_entity           : {n_create}"
          + (" [GATED — needs --allow-create]" if not allow_create else " [will create new KB rows]"))
    print(f"  reject_promotion            : {n_reject} (safeguard rejections)")

    _print_bucket("EXACT (already in KB)", buckets[DECISION_EXACT], limit=8, show_reason=False)
    _print_bucket("MERGE (add alias)", buckets[DECISION_MERGE], limit=8)
    _print_bucket("CREATE (new entity)", buckets[DECISION_CREATE], limit=8)
    _print_bucket("REJECT (safeguards)", buckets[DECISION_REJECT], limit=12)

    print()
    print("  [DRY RUN] — no DB writes.")
    if n_create > 0 and not allow_create:
        print(f"  {n_create} create_new_entity candidates are gated.")
        print("  Re-run with --allow-create to enable entity creation.")


# ---------------------------------------------------------------------------
# Real promotion run
# ---------------------------------------------------------------------------

def run_real_promotion(
    checks,
    kb_conn: sqlite3.Connection,
    market_conn: sqlite3.Connection,
    allow_create: bool,
) -> Dict[str, Any]:
    from perfume_trend_sdk.analysis.candidate_validation.promoter import (
        DECISION_CREATE, DECISION_EXACT, DECISION_MERGE, DECISION_REJECT,
        execute_create_brand, execute_create_perfume, execute_merge,
        record_promotion_outcome,
    )

    kb_cur = kb_conn.cursor()
    market_cur = market_conn.cursor()

    results = {
        "exact": [],
        "merged": [],
        "created": [],
        "rejected": [],
        "skipped_create_gated": [],
        "errors": [],
    }

    for check in checks:
        try:
            if check.decision == DECISION_EXACT:
                record_promotion_outcome(
                    market_cur,
                    check.candidate_id,
                    decision=DECISION_EXACT,
                    canonical_name=check.matched_canonical_name,
                    promoted_as=check.entity_type,
                    rejection_reason=None,
                )
                results["exact"].append(check)

            elif check.decision == DECISION_MERGE:
                alias_result = execute_merge(check, kb_cur)
                record_promotion_outcome(
                    market_cur,
                    check.candidate_id,
                    decision=DECISION_MERGE,
                    canonical_name=check.matched_canonical_name,
                    promoted_as=check.entity_type,
                    rejection_reason=None,
                )
                results["merged"].append((check, alias_result))

            elif check.decision == DECISION_CREATE:
                if not allow_create:
                    results["skipped_create_gated"].append(check)
                    continue

                if check.entity_type == "perfume":
                    new_id, canonical = execute_create_perfume(check, kb_cur, check.candidate_id)
                    promoted_as = "perfume"
                else:
                    new_id, canonical = execute_create_brand(check, kb_cur)
                    promoted_as = "brand"

                record_promotion_outcome(
                    market_cur,
                    check.candidate_id,
                    decision=DECISION_CREATE,
                    canonical_name=canonical,
                    promoted_as=promoted_as,
                    rejection_reason=None,
                )
                results["created"].append((check, new_id, canonical))

            elif check.decision == DECISION_REJECT:
                record_promotion_outcome(
                    market_cur,
                    check.candidate_id,
                    decision=DECISION_REJECT,
                    canonical_name=None,
                    promoted_as=None,
                    rejection_reason=check.rejection_reason,
                )
                results["rejected"].append(check)

        except Exception as exc:  # noqa: BLE001
            logger.error("Error processing candidate %s: %s", check.candidate_id, exc)
            results["errors"].append((check, str(exc)))

    kb_conn.commit()
    market_conn.commit()
    return results


# ---------------------------------------------------------------------------
# Real-run report
# ---------------------------------------------------------------------------

def print_real_results(results: Dict[str, Any]) -> None:
    print()
    print("=== Phase 4b Promotion Results ===")
    print(f"  exact_existing_entity       : {len(results['exact'])}")
    print(f"  merge_into_existing         : {len(results['merged'])}")
    print(f"  create_new_entity           : {len(results['created'])}")
    print(f"  reject_promotion            : {len(results['rejected'])}")
    print(f"  skipped (create gated)      : {len(results['skipped_create_gated'])}")
    print(f"  errors                      : {len(results['errors'])}")

    if results["merged"]:
        print(f"\n  --- Aliases added ({len(results['merged'])}) ---")
        for check, alias_result in results["merged"][:10]:
            print(f"  id={check.candidate_id:6d}  \"{check.promotion_text}\"  →  "
                  f"\"{check.matched_canonical_name}\"  alias={alias_result}")

    if results["created"]:
        print(f"\n  --- Created ({len(results['created'])}) ---")
        for check, new_id, canonical in results["created"][:10]:
            print(f"  id={check.candidate_id:6d}  \"{check.promotion_text}\"  →  "
                  f"\"{canonical}\" (new_id={new_id})")

    if results["rejected"]:
        print(f"\n  --- Rejected ({len(results['rejected'])}) ---")
        for check in results["rejected"][:10]:
            print(f"  id={check.candidate_id:6d}  \"{check.promotion_text}\"  reason={check.rejection_reason}")

    if results["skipped_create_gated"]:
        print(f"\n  --- Skipped (create gated — {len(results['skipped_create_gated'])}) ---")
        print("  Re-run with --allow-create to promote these candidates.")
        for check in results["skipped_create_gated"][:5]:
            print(f"  id={check.candidate_id:6d}  \"{check.promotion_text}\"  →  "
                  f"would create \"{check.canonical_name_to_create}\"")

    if results["errors"]:
        print(f"\n  --- ERRORS ({len(results['errors'])}) ---")
        for check, err in results["errors"]:
            print(f"  id={check.candidate_id:6d}  \"{check.promotion_text}\"  error={err}")


# ---------------------------------------------------------------------------
# KB count summary
# ---------------------------------------------------------------------------

def _print_kb_counts(kb_cur: sqlite3.Cursor) -> None:
    tables = [("fragrance_master", "fragrance_master"), ("aliases", "aliases"),
              ("brands", "brands"), ("perfumes", "perfumes")]
    print()
    print("  KB row counts:")
    for label, table in tables:
        kb_cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        cnt = kb_cur.fetchone()[0]
        print(f"    {label:20s}: {cnt:,}")

    kb_cur.execute("SELECT COUNT(*) FROM fragrance_master WHERE source = 'discovery'")
    disc = kb_cur.fetchone()[0]
    kb_cur.execute("SELECT COUNT(*) FROM aliases WHERE match_type = 'discovery_generated'")
    disc_aliases = kb_cur.fetchone()[0]
    print(f"    discovery FM rows          : {disc}")
    print(f"    discovery_generated aliases: {disc_aliases}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 4b: promote approved candidates to Knowledge Base"
    )

    # Mode
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Preview decisions without any DB writes (safe)"
    )
    mode_group.add_argument(
        "--no-dry-run", action="store_false", dest="dry_run",
        help="Execute promotions (writes to KB and market DB)"
    )

    # Filters
    parser.add_argument("--limit", type=int, default=50,
                        help="Max candidates to process (default: 50)")
    parser.add_argument("--min-occurrences", type=int, default=1,
                        help="Minimum occurrence count (default: 1)")
    parser.add_argument("--type", metavar="TYPE",
                        help="Candidate type filter: perfume | brand | all (default: perfume,brand)")

    # Execution flags
    parser.add_argument("--allow-create", action="store_true",
                        help="Enable create_new_entity decisions (off by default)")
    parser.add_argument("--show-kb-counts", action="store_true",
                        help="Print KB row counts before and after")

    # DB overrides
    parser.add_argument("--market-db", metavar="PATH",
                        default=_DEFAULT_MARKET_DB,
                        help=f"Market DB path (default: {_DEFAULT_MARKET_DB})")
    parser.add_argument("--kb-db", metavar="PATH",
                        default=_DEFAULT_KB_DB,
                        help=f"Resolver KB DB path (default: {_DEFAULT_KB_DB})")

    args = parser.parse_args()

    # Candidate type filter
    if args.type is None or args.type == "all":
        candidate_types = ["perfume", "brand"]
    elif args.type == "perfume":
        candidate_types = ["perfume"]
    elif args.type == "brand":
        candidate_types = ["brand"]
    else:
        print(f"ERROR: unknown --type value: {args.type!r}")
        sys.exit(1)

    # Open connections
    market_path = args.market_db
    kb_path = args.kb_db

    if not os.path.exists(market_path):
        print(f"ERROR: market DB not found: {market_path}")
        sys.exit(1)
    if not os.path.exists(kb_path):
        print(f"ERROR: KB DB not found: {kb_path}")
        sys.exit(1)

    market_conn = sqlite3.connect(market_path)
    kb_conn = sqlite3.connect(kb_path)

    market_cur = market_conn.cursor()
    kb_cur = kb_conn.cursor()

    # Check migration 013 is applied
    market_cur.execute("PRAGMA table_info(fragrance_candidates)")
    cols = {r[1] for r in market_cur.fetchall()}
    if "promotion_decision" not in cols:
        print("ERROR: migration 013 not applied. Run: alembic upgrade head")
        sys.exit(1)

    try:
        from perfume_trend_sdk.analysis.candidate_validation.promoter import (
            load_kb_snapshot, run_prechecks,
        )

        print()
        print(f"  Market DB : {market_path}")
        print(f"  KB DB     : {kb_path}")

        if args.show_kb_counts:
            print("\n  [BEFORE]")
            _print_kb_counts(kb_cur)

        # Load candidates
        candidates = _load_approved_candidates(
            market_cur,
            candidate_types=candidate_types,
            min_occurrences=args.min_occurrences,
            limit=args.limit,
        )

        total_approved = candidates  # alias for clarity
        print(f"\n  Candidates loaded           : {len(candidates)}")
        print(f"  Type filter                 : {candidate_types}")
        print(f"  Min occurrences             : {args.min_occurrences}")
        print(f"  Limit                       : {args.limit}")
        print(f"  Allow create                : {args.allow_create}")
        print(f"  Mode                        : {'DRY RUN' if args.dry_run else 'REAL'}")

        if not candidates:
            print("\n  No candidates to process.")
            return

        # Load KB snapshot
        logger.info("Loading KB snapshot...")
        kb = load_kb_snapshot(kb_conn)
        logger.info(
            "KB loaded: %d aliases, %d FM rows, %d brands",
            len(kb["alias_lookup"]), len(kb["fm_list"]), len(kb["brand_lookup"]),
        )

        # Run prechecks
        checks = run_prechecks(candidates, kb)

        if args.dry_run:
            run_dry_run(candidates, checks, allow_create=args.allow_create)
        else:
            results = run_real_promotion(
                checks,
                kb_conn=kb_conn,
                market_conn=market_conn,
                allow_create=args.allow_create,
            )
            print_real_results(results)

            if args.show_kb_counts:
                print("\n  [AFTER]")
                _print_kb_counts(kb_cur)

    finally:
        market_conn.close()
        kb_conn.close()


if __name__ == "__main__":
    main()
