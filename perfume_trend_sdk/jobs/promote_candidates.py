from __future__ import annotations

"""Job: promote_candidates — Phase 4b Safe Promotion to Knowledge Base.

Promotes approved fragrance candidates into the Postgres resolver Knowledge Base
(resolver_fragrance_master, resolver_aliases, resolver_brands, resolver_perfumes).

Phase 4b rules
--------------
  - Only processes candidates with review_status = 'approved_for_promotion'
  - Reads fragrance_candidates from the market Postgres DB via session_scope()
  - Writes all KB changes to resolver_* Postgres tables via PgResolverStore
  - NEVER overwrites existing canonical entities
  - create_new_entity is gated behind --allow-create flag (off by default)
  - dry_run is the default — must pass --no-dry-run to write

Decisions
---------
  exact_existing_entity  — already in KB; no write needed
  merge_into_existing    — add new alias in resolver_aliases
  create_new_entity      — create rows in resolver_brands/perfumes/fm + alias
  reject_promotion       — fails safeguards; no write

PRODUCTION GUARD
----------------
If PTI_ENV=production and DATABASE_URL is not set, startup fails immediately.
SQLite is never used as the KB write target in this job.

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
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Production guard — fail fast if SQLite would be used as KB target
# ---------------------------------------------------------------------------

def _assert_postgres_available() -> None:
    """Raise RuntimeError if DATABASE_URL is unset in production.

    This guard prevents any accidental SQLite fallback for KB writes.
    In dev, DATABASE_URL can point at the Postgres instance for testing.
    """
    pti_env = os.environ.get("PTI_ENV", "dev").strip().lower()
    if pti_env == "production" and not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "promote_candidates: DATABASE_URL is required when PTI_ENV=production. "
            "This job writes to Postgres resolver_* tables and does not support SQLite."
        )


# ---------------------------------------------------------------------------
# Candidate loader — reads from market Postgres DB via SQLAlchemy session
# ---------------------------------------------------------------------------

def _load_approved_candidates(
    db: Session,
    *,
    candidate_types: Optional[List[str]] = None,
    min_occurrences: int = 1,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Load approved_for_promotion candidates from fragrance_candidates."""
    conditions = ["review_status = 'approved_for_promotion'"]
    params: Dict[str, Any] = {}

    if candidate_types:
        # Build an IN clause using named params
        placeholders = ", ".join(f":ct{i}" for i in range(len(candidate_types)))
        conditions.append(
            f"(approved_entity_type IN ({placeholders}) "
            f"OR candidate_type IN ({placeholders}))"
        )
        for i, ct in enumerate(candidate_types):
            params[f"ct{i}"] = ct

    conditions.append("occurrences >= :min_occ")
    params["min_occ"] = min_occurrences

    conditions.append("promotion_decision IS NULL")

    params["limit"] = limit
    where = " AND ".join(conditions)
    sql = text(
        f"SELECT id, normalized_text, normalized_candidate_text, candidate_type, "  # noqa: S608
        f"  approved_entity_type, occurrences, source_platform, promotion_decision "
        f"FROM fragrance_candidates "
        f"WHERE {where} "
        f"ORDER BY occurrences DESC, id "
        f"LIMIT :limit"
    )
    rows = db.execute(sql, params).fetchall()
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
    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import (
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
    print(f"  merge_into_existing         : {n_merge} (will add alias in resolver_aliases)")
    print(f"  create_new_entity           : {n_create}"
          + (" [GATED — needs --allow-create]" if not allow_create else " [will create Postgres resolver rows]"))
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
# Real promotion run — writes to Postgres resolver_* tables
# ---------------------------------------------------------------------------

def run_real_promotion(
    checks,
    store,           # PgResolverStore
    db: Session,     # market DB session (fragrance_candidates)
    allow_create: bool,
) -> Dict[str, Any]:
    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import (
        DECISION_CREATE,
        DECISION_EXACT,
        DECISION_MERGE,
        DECISION_REJECT,
        execute_create_brand_pg,
        execute_create_perfume_pg,
        execute_merge_pg,
        record_promotion_outcome_pg,
    )

    results: Dict[str, Any] = {
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
                record_promotion_outcome_pg(
                    db,
                    check.candidate_id,
                    decision=DECISION_EXACT,
                    canonical_name=check.matched_canonical_name,
                    promoted_as=check.entity_type,
                    rejection_reason=None,
                )
                results["exact"].append(check)

            elif check.decision == DECISION_MERGE:
                alias_result = execute_merge_pg(check, store)
                record_promotion_outcome_pg(
                    db,
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
                    new_id, canonical = execute_create_perfume_pg(check, store, check.candidate_id)
                    promoted_as = "perfume"
                else:
                    new_id, canonical = execute_create_brand_pg(check, store)
                    promoted_as = "brand"

                record_promotion_outcome_pg(
                    db,
                    check.candidate_id,
                    decision=DECISION_CREATE,
                    canonical_name=canonical,
                    promoted_as=promoted_as,
                    rejection_reason=None,
                )
                results["created"].append((check, new_id, canonical))

            elif check.decision == DECISION_REJECT:
                record_promotion_outcome_pg(
                    db,
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

    # Flush market DB changes (session_scope commits on context exit)
    db.flush()
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
        print(f"\n  --- Aliases added to resolver_aliases ({len(results['merged'])}) ---")
        for check, alias_result in results["merged"][:10]:
            print(f"  id={check.candidate_id:6d}  \"{check.promotion_text}\"  →  "
                  f"\"{check.matched_canonical_name}\"  alias={alias_result}")

    if results["created"]:
        print(f"\n  --- Created in resolver_* tables ({len(results['created'])}) ---")
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
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _assert_postgres_available()

    parser = argparse.ArgumentParser(
        description="Phase 4b: promote approved candidates to Postgres resolver KB"
    )

    # Mode
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Preview decisions without any DB writes (safe)"
    )
    mode_group.add_argument(
        "--no-dry-run", action="store_false", dest="dry_run",
        help="Execute promotions (writes to resolver_* tables and fragrance_candidates)"
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
                        help="Print resolver_* row counts before and after")

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

    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import (
        load_kb_snapshot_pg,
        print_kb_counts_pg,
        run_prechecks,
    )
    from perfume_trend_sdk.storage.entities.pg_resolver_store import PgResolverStore
    from perfume_trend_sdk.storage.postgres.db import session_scope

    store = PgResolverStore()

    print()
    print("  KB target   : Postgres resolver_* tables")
    print(f"  Type filter : {candidate_types}")
    print(f"  Limit       : {args.limit}")
    print(f"  Allow create: {args.allow_create}")
    print(f"  Mode        : {'DRY RUN' if args.dry_run else 'REAL'}")

    if args.show_kb_counts:
        print_kb_counts_pg(store, "BEFORE")

    with session_scope() as db:
        # Load candidates from market Postgres DB
        candidates = _load_approved_candidates(
            db,
            candidate_types=candidate_types,
            min_occurrences=args.min_occurrences,
            limit=args.limit,
        )

        print(f"\n  Candidates loaded           : {len(candidates)}")
        print(f"  Min occurrences             : {args.min_occurrences}")

        if not candidates:
            print("\n  No candidates to process.")
            return

        # Load KB snapshot from Postgres resolver_* tables
        logger.info("Loading KB snapshot from Postgres...")
        kb = load_kb_snapshot_pg(store)
        logger.info(
            "KB loaded: %d aliases, %d FM rows, %d brands",
            len(kb["alias_lookup"]), len(kb["fm_list"]), len(kb["brand_lookup"]),
        )

        # Run prechecks (pure in-memory logic — no DB calls)
        checks = run_prechecks(candidates, kb)

        if args.dry_run:
            run_dry_run(candidates, checks, allow_create=args.allow_create)
        else:
            results = run_real_promotion(
                checks,
                store=store,
                db=db,
                allow_create=args.allow_create,
            )
            print_real_results(results)

    if args.show_kb_counts:
        print_kb_counts_pg(store, "AFTER")


if __name__ == "__main__":
    main()
