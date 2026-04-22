from __future__ import annotations

"""Job: review_create_bucket — Phase 4c Create Bucket Review & Controlled New Entity Creation.

Processes candidates left in the create_new_entity gated bucket from Phase 4b.
Applies stricter classification, seeds missing brand aliases, and executes a
bounded controlled create run.

All KB writes go to Postgres resolver_* tables via PgResolverStore.
Market DB reads/writes go to Postgres fragrance_candidates via session_scope().

Phase 4c decisions (per candidate)
------------------------------------
  reject_create_candidate  — fragment / generic / foreign / malformed; no KB write
  convert_to_merge         — better served as alias for existing entity
  keep_as_valid_create     — genuinely new entity; gated behind --allow-create
  defer_create             — uncertain; skipped this pass

Run order
---------
  # 1. Inspect full create bucket
  python -m perfume_trend_sdk.jobs.review_create_bucket --analyze

  # 2. Add missing brand short-form aliases (jovoy → Jovoy Paris, etc.)
  python -m perfume_trend_sdk.jobs.review_create_bucket --seed-brand-aliases --dry-run
  python -m perfume_trend_sdk.jobs.review_create_bucket --seed-brand-aliases

  # 3. Execute: reject, convert-to-merge, and create (dry-run first)
  python -m perfume_trend_sdk.jobs.review_create_bucket --execute --dry-run
  python -m perfume_trend_sdk.jobs.review_create_bucket --execute --allow-create --limit 10

  # 4. Integrity check
  python -m perfume_trend_sdk.jobs.review_create_bucket --integrity-check
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Production guard
# ---------------------------------------------------------------------------

def _assert_postgres_available() -> None:
    pti_env = os.environ.get("PTI_ENV", "dev").strip().lower()
    if pti_env == "production" and not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "review_create_bucket: DATABASE_URL is required when PTI_ENV=production. "
            "This job writes to Postgres resolver_* tables and does not support SQLite."
        )


# ---------------------------------------------------------------------------
# Phase 4c classification constants
# ---------------------------------------------------------------------------

_BRAND_PRODUCT_FRAGMENTS: frozenset = frozenset({
    "rouge", "baccarat", "libre", "pt", "blanc", "noir", "intense",
    "elixir", "absolute", "extreme", "pure",
})

_BRAND_GENERIC_WORDS: frozenset = frozenset({
    "different", "blend", "essential", "another", "therapy",
    "secret", "purchase", "join", "notes", "good", "nice",
    "amazing", "great", "love", "like", "want", "need",
})

_FOREIGN_FUNCTION_WORDS: frozenset = frozenset({
    "el", "en", "de", "del", "les", "du", "le", "la", "al",
    "un", "una", "por", "il", "gli", "lo", "los",
})

_PERFUME_CONTEXT_TOKENS: frozenset = frozenset({
    "and", "with", "from", "for", "what", "have", "actually",
    "very", "good", "awesome", "a", "all", "about",
    "samples", "sample", "i", "we", "is", "by",
    "if", "one", "then",
    "notes", "bottom", "top", "middle", "heart", "base",
})

_NOTE_BRAND_CONFUSERS: frozenset = frozenset({
    "vanille", "vanilla", "lilac", "ambrette", "sage",
    "amber", "musk", "oud",
})

_CONTENT_PHRASE_INDICATORS: frozenset = frozenset({
    "fucking", "bullshit", "actually can", "very good", "samples",
})

_LENIENT_FUZZY_THRESHOLD = 0.75

# Short brand alias seeds: (alias_text, normalized_alias_text, entity_type, entity_id, brand_canonical)
# entity_id refers to resolver_brands.id (integer PKs preserved from SQLite migration)
_BRAND_ALIAS_SEEDS: List[Tuple] = [
    # "jovoy" → Jovoy Paris (resolver_brands.id=634, verified post-migration)
    ("Jovoy", "jovoy", "brand", 634, "Jovoy Paris"),
]


# ---------------------------------------------------------------------------
# Candidate loader — reads from market Postgres DB (fragrance_candidates)
# ---------------------------------------------------------------------------

def _load_create_gated_candidates(
    db: Session,
    limit: int = 500,
    include_deferred: bool = True,
) -> List[Dict[str, Any]]:
    """Load candidates with promotion_decision = 'create_new_entity' (or deferred)."""
    if include_deferred:
        sql = text(
            "SELECT id, normalized_text, normalized_candidate_text, candidate_type, "
            "  approved_entity_type, occurrences, source_platform, promotion_decision "
            "FROM fragrance_candidates "
            "WHERE promotion_decision IN ('create_new_entity', 'deferred_create') "
            "  AND review_status = 'approved_for_promotion' "
            "ORDER BY occurrences DESC, id "
            "LIMIT :limit"
        )
    else:
        sql = text(
            "SELECT id, normalized_text, normalized_candidate_text, candidate_type, "
            "  approved_entity_type, occurrences, source_platform, promotion_decision "
            "FROM fragrance_candidates "
            "WHERE promotion_decision = 'create_new_entity' "
            "  AND review_status = 'approved_for_promotion' "
            "ORDER BY occurrences DESC, id "
            "LIMIT :limit"
        )
    rows = db.execute(sql, {"limit": limit}).fetchall()
    keys = [
        "id", "normalized_text", "normalized_candidate_text", "candidate_type",
        "approved_entity_type", "occurrences", "source_platform", "promotion_decision",
    ]
    return [dict(zip(keys, r)) for r in rows]


# ---------------------------------------------------------------------------
# Helper: promotion text selection
# ---------------------------------------------------------------------------

def _promotion_text(candidate: Dict[str, Any]) -> str:
    nc = (candidate.get("normalized_candidate_text") or "").strip()
    return nc if nc else candidate["normalized_text"]


# ---------------------------------------------------------------------------
# Phase 4c enhanced classification
# ---------------------------------------------------------------------------

def _resolve_brand(promo_text: str, kb: Dict) -> Optional[Dict]:
    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import resolve_brand
    return resolve_brand(promo_text, kb)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def enhanced_classify_4c(candidate: Dict[str, Any], kb: Dict) -> Tuple[str, str]:
    """Apply stricter Phase 4c classification to a create-gated candidate.

    Returns (decision, reason):
      "exact_now_in_kb"         — now resolves after KB seed expansion
      "reject_create_candidate" — fragment / noise / foreign / malformed
      "convert_to_merge"        — better served as alias for existing entity
      "keep_as_valid_create"    — genuinely new, brand resolvable, clean name
      "defer_create"            — uncertain, skip this pass
    """
    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import (
        check_exact,
        check_merge,
    )

    promo_text = _promotion_text(candidate)
    tokens = promo_text.split()
    entity_type = candidate.get("approved_entity_type") or candidate.get("candidate_type") or "unknown"

    # ── 1. Re-check exact match (KB may have grown since Phase 4b) ──────────
    if check_exact(promo_text, kb):
        return "exact_now_in_kb", "now_in_kb_after_seed"

    # ── 2. Strict rejection rules ─────────────────────────────────────────
    # Too short
    if len(promo_text) <= 3 or len(tokens) == 0:
        return "reject_create_candidate", "too_short"

    # Non-ASCII
    if not promo_text.isascii():
        return "reject_create_candidate", "non_ascii"

    # Foreign language function word present
    token_set = set(tokens)
    foreign_hits = token_set & _FOREIGN_FUNCTION_WORDS
    if foreign_hits:
        return "reject_create_candidate", f"foreign_function_word:{next(iter(foreign_hits))}"

    # Content phrase indicators
    for phrase in _CONTENT_PHRASE_INDICATORS:
        if phrase in promo_text:
            return "reject_create_candidate", f"content_phrase:{phrase}"

    if entity_type in ("perfume", "unknown"):
        # ── 3. Brand classification for perfume candidates ─────────────────
        brand_info = _resolve_brand(promo_text, kb)
        if brand_info is None:
            # Single-token perfume with no brand prefix
            if len(tokens) == 1:
                return "reject_create_candidate", "single_token_no_brand"
            return "defer_create", "brand_not_resolvable"

        # Brand part validation
        brand_part = (brand_info.get("brand_name") or "").lower()
        if brand_part in _BRAND_PRODUCT_FRAGMENTS:
            return "reject_create_candidate", f"brand_part_is_product_fragment:{brand_part}"
        if brand_part in _BRAND_GENERIC_WORDS:
            return "reject_create_candidate", f"brand_part_is_generic:{brand_part}"

        # Perfume part validation
        perf_tokens = brand_info.get("perfume_tokens") or []
        if not perf_tokens:
            return "reject_create_candidate", "no_perfume_part_after_brand"

        perf_token_set = set(perf_tokens)

        # Pyramid position words in perfume part
        pyramid_hits = perf_token_set & frozenset({"notes", "bottom", "top", "middle", "heart", "base"})
        if pyramid_hits:
            return "reject_create_candidate", f"perfume_part_is_pyramid_position:{next(iter(pyramid_hits))}"

        # Context tokens in perfume part
        context_hits = perf_token_set & _PERFUME_CONTEXT_TOKENS
        if context_hits:
            return "reject_create_candidate", f"perfume_part_context_token:{next(iter(context_hits))}"

        # Single note word in perfume part
        if len(perf_tokens) == 1 and perf_tokens[0] in _NOTE_BRAND_CONFUSERS:
            return "reject_create_candidate", f"single_note_word_perfume_part:{perf_tokens[0]}"

        # ── 4. Check if perfume part is already in aliases (convert to merge) ──
        perf_part_text = " ".join(perf_tokens)
        alias_hit = kb.get("alias_lookup", {}).get(perf_part_text)
        if alias_hit and isinstance(alias_hit, tuple):
            return "convert_to_merge", f"perfume_part_in_aliases:{perf_part_text}"

        # ── 5. Lenient fuzzy merge check ──────────────────────────────────
        merge = check_merge(promo_text, kb)
        if merge:
            return "convert_to_merge", f"fuzzy_merge:{merge.get('reason', '')}"

        proposed_norm = brand_info["normalized_name"]
        best_score = 0.0
        for fm_norm, _fid, _fcanon, _fpid in kb["fm_list"]:
            score = _similarity(proposed_norm, fm_norm)
            if score > best_score and score >= _LENIENT_FUZZY_THRESHOLD:
                best_score = score
                best_match_norm = fm_norm

        if best_score >= _LENIENT_FUZZY_THRESHOLD:
            return "convert_to_merge", f"lenient_fuzzy:{best_score:.2f}:{best_match_norm}"

        # ── 6. In-batch partial-name check is done by the caller ──────────
        return "keep_as_valid_create", f"new_perfume:brand={brand_info['brand_name']}"

    if entity_type == "brand":
        if len(tokens) == 1 and len(promo_text) < 4:
            return "reject_create_candidate", "single_short_token_brand"
        return "keep_as_valid_create", "new_brand"

    return "defer_create", f"unknown_entity_type:{entity_type}"


# ---------------------------------------------------------------------------
# KB snapshot — loads from Postgres resolver_* tables
# ---------------------------------------------------------------------------

def _load_kb_snapshot(store) -> Dict:
    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import load_kb_snapshot_pg
    return load_kb_snapshot_pg(store)


# ---------------------------------------------------------------------------
# Seed brand aliases — writes to resolver_aliases
# ---------------------------------------------------------------------------

def cmd_seed_brand_aliases(store, *, dry_run: bool) -> None:
    """Add missing short-form brand aliases to resolver_aliases in Postgres."""
    mode = "[DRY RUN]" if dry_run else "[APPLIED]"
    print(f"\n{mode} Seed brand short-form aliases (Postgres resolver_aliases)")
    print()

    added = 0
    for alias_text, norm_alias, entity_type, entity_id, brand_canonical in _BRAND_ALIAS_SEEDS:
        # Verify brand exists in resolver_brands
        with store._engine.connect() as conn:
            brand_row = conn.execute(text(
                "SELECT id, canonical_name FROM resolver_brands WHERE id = :id"
            ), {"id": entity_id}).fetchone()

        if not brand_row:
            print(f"  SKIP  \"{norm_alias}\" — resolver_brands.id={entity_id} not found")
            continue

        # Check if alias already exists
        with store._engine.connect() as conn:
            existing = conn.execute(text(
                "SELECT id FROM resolver_aliases "
                "WHERE normalized_alias_text = :norm AND entity_type = :etype AND entity_id = :eid"
            ), {"norm": norm_alias, "etype": entity_type, "eid": entity_id}).fetchone()

        if existing:
            print(f"  SKIP  \"{norm_alias}\" → \"{brand_canonical}\" — alias already exists")
            continue

        print(f"  ADD   \"{alias_text}\" / \"{norm_alias}\" → \"{brand_canonical}\" (id={entity_id})")
        if not dry_run:
            with store._engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO resolver_aliases "
                    "  (alias_text, normalized_alias_text, entity_type, entity_id, "
                    "   match_type, confidence) "
                    "VALUES (:alias_text, :norm, :etype, :eid, 'discovery_generated', 0.90) "
                    "ON CONFLICT ON CONSTRAINT uq_resolver_aliases_lookup DO NOTHING"
                ), {
                    "alias_text": alias_text,
                    "norm": norm_alias,
                    "etype": entity_type,
                    "eid": entity_id,
                })
            added += 1

    if not dry_run:
        print(f"\n  Added {added} alias(es) to resolver_aliases.")
    else:
        print(f"\n  Would add up to {len(_BRAND_ALIAS_SEEDS)} alias(es). Re-run without --dry-run to apply.")


# ---------------------------------------------------------------------------
# Analyze mode (no writes)
# ---------------------------------------------------------------------------

def cmd_analyze(candidates: List[Dict], kb: Dict) -> None:
    """Print full Phase 4c classification of all create-gated candidates."""
    buckets: Dict[str, List] = defaultdict(list)
    exact_now: List = []

    for c in candidates:
        decision, reason = enhanced_classify_4c(c, kb)
        if decision == "exact_now_in_kb":
            exact_now.append((c, reason))
        else:
            buckets[decision].append((c, reason))

    print()
    print("=== Phase 4c Create Bucket Analysis ===")
    print(f"  Total create-gated candidates : {len(candidates)}")
    if exact_now:
        print(f"  now in KB (after seed)        : {len(exact_now)}")
    print(f"  reject_create_candidate       : {len(buckets['reject_create_candidate'])}")
    print(f"  convert_to_merge              : {len(buckets['convert_to_merge'])}")
    print(f"  keep_as_valid_create          : {len(buckets['keep_as_valid_create'])}")
    print(f"  defer_create                  : {len(buckets['defer_create'])}")

    def _fmt(c, reason=""):
        promo = _promotion_text(c)
        etype = c.get("approved_entity_type") or c.get("candidate_type") or "?"
        occ = c.get("occurrences", 0)
        orig = c.get("normalized_text", "")
        nc = (c.get("normalized_candidate_text") or "").strip()
        nc_str = f"  →  \"{nc}\"" if nc and nc != orig else ""
        reason_str = f"  [{reason}]" if reason else ""
        return (
            f"  id={c['id']:6d}  occ={occ:3d}  [{etype:10s}]"
            f"  \"{orig}\"{nc_str}{reason_str}"
        )

    if exact_now:
        print(f"\n  --- Now exact in KB ({len(exact_now)}) ---")
        for c, r in exact_now[:5]:
            print(_fmt(c, r))

    if buckets["keep_as_valid_create"]:
        print(f"\n  --- KEEP AS VALID CREATE ({len(buckets['keep_as_valid_create'])}) ---")
        for c, r in buckets["keep_as_valid_create"]:
            print(_fmt(c, r))

    if buckets["convert_to_merge"]:
        print(f"\n  --- CONVERT TO MERGE ({len(buckets['convert_to_merge'])}) ---")
        for c, r in buckets["convert_to_merge"]:
            print(_fmt(c, r))

    if buckets["defer_create"]:
        print(f"\n  --- DEFER ({len(buckets['defer_create'])}) ---")
        for c, r in buckets["defer_create"][:15]:
            print(_fmt(c, r))
        if len(buckets["defer_create"]) > 15:
            print(f"  ... and {len(buckets['defer_create']) - 15} more deferred")

    if buckets["reject_create_candidate"]:
        print(f"\n  --- REJECT ({len(buckets['reject_create_candidate'])}) ---")
        for c, r in buckets["reject_create_candidate"][:15]:
            print(_fmt(c, r))
        if len(buckets["reject_create_candidate"]) > 15:
            print(f"  ... and {len(buckets['reject_create_candidate']) - 15} more rejected")


# ---------------------------------------------------------------------------
# Execute a single candidate's Phase 4c decision (Postgres-only KB writes)
# ---------------------------------------------------------------------------

def _execute_candidate_4c(
    candidate: Dict,
    decision: str,
    reason: str,
    kb: Dict,
    store,        # PgResolverStore
    db: Session,  # market Postgres session
    allow_create: bool,
) -> Tuple[str, str]:
    """Execute one candidate's Phase 4c decision. Returns (outcome, detail)."""
    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import (
        DECISION_CREATE,
        DECISION_EXACT,
        DECISION_MERGE,
        DECISION_REJECT,
        PromotionCheck,
        _now_iso,
        check_exact,
        check_merge,
        execute_create_brand_pg,
        execute_create_perfume_pg,
        execute_merge_pg,
        insert_alias_pg,
        record_promotion_outcome_pg,
    )

    cid = candidate["id"]
    promo_text = _promotion_text(candidate)
    entity_type = candidate.get("approved_entity_type") or candidate.get("candidate_type") or "unknown"

    if decision == "exact_now_in_kb":
        exact = check_exact(promo_text, kb)
        canonical = exact["canonical_name"] if exact else reason
        record_promotion_outcome_pg(db, cid, DECISION_EXACT, canonical, entity_type, None)
        return "exact", canonical

    if decision == "convert_to_merge":
        # Try standard merge path first
        merge = check_merge(promo_text, kb)
        if merge:
            check = PromotionCheck(
                candidate_id=cid,
                promotion_text=promo_text,
                original_text=candidate["normalized_text"],
                entity_type=entity_type,
                decision=DECISION_MERGE,
                reason=reason,
                matched_entity_id=merge["entity_id"],
                matched_canonical_name=merge["canonical_name"],
            )
            alias_result = execute_merge_pg(check, store)
            record_promotion_outcome_pg(
                db, cid, DECISION_MERGE, merge["canonical_name"], entity_type, None,
            )
            return "merged", f"{promo_text} → {merge['canonical_name']} (alias={alias_result})"

        # Perfume-part alias path
        brand_info = _resolve_brand(promo_text, kb)
        if brand_info and "perfume_part_in_aliases" in reason:
            perf_part_text = " ".join(brand_info.get("perfume_tokens", []))
            alias_hit = kb.get("alias_lookup", {}).get(perf_part_text)
            if alias_hit and isinstance(alias_hit, tuple):
                target_pid = alias_hit[0]
                canon_from_pid = kb.get("perfume_id_canon", {}).get(target_pid, perf_part_text)
                alias_text = " ".join(t.capitalize() for t in promo_text.split())
                alias_result = insert_alias_pg(
                    store,
                    alias_text=alias_text,
                    normalized_alias_text=promo_text,
                    entity_type="perfume",
                    entity_id=target_pid,
                    match_type="discovery_generated",
                    confidence=0.85,
                )
                record_promotion_outcome_pg(db, cid, DECISION_MERGE, canon_from_pid, entity_type, None)
                return "merged_alias_path", f"{promo_text} → {canon_from_pid} (alias={alias_result})"

        # Lenient fuzzy merge path
        if brand_info:
            proposed_norm = brand_info["normalized_name"]
            best_score = 0.0
            best_entity_id: Optional[int] = None
            best_canonical: Optional[str] = None
            for fm_norm, _fid, fm_canonical, fm_perfume_id in kb["fm_list"]:
                score = SequenceMatcher(None, proposed_norm, fm_norm).ratio()
                if score > best_score and score >= _LENIENT_FUZZY_THRESHOLD:
                    best_score = score
                    best_entity_id = fm_perfume_id
                    best_canonical = fm_canonical

            if best_entity_id is not None:
                alias_text = " ".join(t.capitalize() for t in promo_text.split())
                alias_result = insert_alias_pg(
                    store,
                    alias_text=alias_text,
                    normalized_alias_text=promo_text,
                    entity_type="perfume",
                    entity_id=best_entity_id,
                    match_type="discovery_generated",
                    confidence=0.80,
                )
                record_promotion_outcome_pg(db, cid, DECISION_MERGE, best_canonical, entity_type, None)
                return "merged_lenient", f"{promo_text} → {best_canonical} (alias={alias_result})"

        # No merge target found
        record_promotion_outcome_pg(
            db, cid, DECISION_REJECT, None, None, "phase4c:convert_to_merge_no_target",
        )
        return "rejected", "convert_to_merge_no_target"

    if decision == "reject_create_candidate":
        record_promotion_outcome_pg(
            db, cid, DECISION_REJECT, None, None, f"phase4c:{reason}",
        )
        return "rejected", reason

    if decision == "keep_as_valid_create":
        if not allow_create:
            db.execute(text(
                "UPDATE fragrance_candidates SET "
                "  promotion_decision = 'deferred_create', "
                "  promotion_rejection_reason = 'create_gated:allow_create_not_set', "
                "  promoted_at = :ts "
                "WHERE id = :id"
            ), {"ts": _now_iso(), "id": cid})
            return "deferred_create_gated", "allow_create_not_set"

        brand_info = _resolve_brand(promo_text, kb)
        if brand_info is None:
            record_promotion_outcome_pg(
                db, cid, DECISION_REJECT, None, None, "phase4c:brand_resolve_failed_at_execute",
            )
            return "rejected", "brand_resolve_failed_at_execute"

        try:
            check = PromotionCheck(
                candidate_id=cid,
                promotion_text=promo_text,
                original_text=candidate["normalized_text"],
                entity_type=entity_type,
                decision=DECISION_CREATE,
                reason=reason,
                brand_id=brand_info["brand_id"],
                brand_name=brand_info["brand_name"],
                canonical_name_to_create=brand_info["canonical_name"],
                normalized_name_to_create=brand_info["normalized_name"],
            )
            if entity_type == "perfume":
                new_id, canonical = execute_create_perfume_pg(check, store, cid)
            else:
                new_id, canonical = execute_create_brand_pg(check, store)

            record_promotion_outcome_pg(db, cid, DECISION_CREATE, canonical, entity_type, None)
            return "created", f"new_id={new_id} canonical=\"{canonical}\""

        except Exception as exc:  # noqa: BLE001
            record_promotion_outcome_pg(
                db, cid, DECISION_REJECT, None, None, f"phase4c:create_error:{exc}",
            )
            return "error", str(exc)

    if decision == "defer_create":
        db.execute(text(
            "UPDATE fragrance_candidates SET "
            "  promotion_decision = 'deferred_create', "
            "  promotion_rejection_reason = :reason, "
            "  promoted_at = :ts "
            "WHERE id = :id "
            "  AND (promotion_decision IS NULL OR promotion_decision = 'deferred_create')"
        ), {"reason": f"phase4c_deferred:{reason}", "ts": _now_iso(), "id": cid})
        return "deferred", reason

    return "skipped", decision


# ---------------------------------------------------------------------------
# Execute mode
# ---------------------------------------------------------------------------

def cmd_execute(
    candidates: List[Dict],
    kb: Dict,
    store,        # PgResolverStore
    db: Session,  # market Postgres session
    *,
    dry_run: bool,
    allow_create: bool,
    limit: int,
) -> None:
    """Execute Phase 4c decisions for create-gated candidates."""
    mode = "[DRY RUN]" if dry_run else "[REAL]"
    print(f"\n{mode} Phase 4c Execute")
    print(f"  Processing up to {limit} candidates  allow_create={allow_create}")

    results: Dict[str, List] = defaultdict(list)

    # Pre-classify all candidates
    classified = []
    for candidate in candidates:
        decision, reason = enhanced_classify_4c(candidate, kb)
        classified.append((candidate, decision, reason))

    # Build proposed canonical set to detect in-batch partial-name duplicates
    create_canonicals: List[str] = []
    for candidate, decision, reason in classified:
        if decision == "keep_as_valid_create":
            bi = _resolve_brand(_promotion_text(candidate), kb)
            if bi:
                create_canonicals.append(bi["normalized_name"])

    def _is_prefix_of_longer_create(proposed_norm: str) -> bool:
        prefix_with_space = proposed_norm + " "
        return any(
            other.startswith(prefix_with_space)
            for other in create_canonicals
            if other != proposed_norm
        )

    created_this_batch: set = set()
    processed = 0

    for candidate, decision, reason in classified:
        if processed >= limit:
            break

        promo_text = _promotion_text(candidate)

        # Detect in-batch partial-name creates
        if decision == "keep_as_valid_create":
            bi = _resolve_brand(promo_text, kb)
            if bi and _is_prefix_of_longer_create(bi["normalized_name"]):
                decision = "defer_create"
                reason = "partial_name:longer_canonical_in_batch"
            elif bi and bi["normalized_name"] in created_this_batch:
                decision = "defer_create"
                reason = "duplicate_canonical_this_batch"
            elif bi:
                created_this_batch.add(bi["normalized_name"])

        if dry_run:
            results[decision].append((candidate, reason))
            processed += 1
            continue

        outcome, detail = _execute_candidate_4c(
            candidate, decision, reason, kb, store, db, allow_create,
        )
        results[outcome].append((candidate, detail))
        processed += 1

    if not dry_run:
        db.flush()

    # Print results
    print()
    if dry_run:
        print("  === Dry-Run Classification ===")
        for bucket, items in sorted(results.items()):
            print(f"  {bucket:35s}: {len(items)}")
        print()
        if results.get("keep_as_valid_create"):
            print("  --- WOULD CREATE ---")
            for c, r in results["keep_as_valid_create"]:
                bi = _resolve_brand(_promotion_text(c), kb)
                canon = bi["canonical_name"] if bi else "?"
                print(f"  id={c['id']:6d}  \"{_promotion_text(c)}\"  →  create \"{canon}\"")
        if results.get("convert_to_merge"):
            print("  --- WOULD MERGE ---")
            for c, r in results["convert_to_merge"]:
                print(f"  id={c['id']:6d}  \"{_promotion_text(c)}\"  [{r}]")
        if not allow_create and results.get("keep_as_valid_create"):
            print()
            print(f"  {len(results['keep_as_valid_create'])} creates gated behind --allow-create.")
    else:
        print("  === Real Run Results ===")
        for outcome, items in sorted(results.items()):
            print(f"  {outcome:35s}: {len(items)}")
        print()
        if results.get("created"):
            print("  --- CREATED in resolver_* tables ---")
            for c, detail in results["created"]:
                print(f"  id={c['id']:6d}  \"{_promotion_text(c)}\"  →  {detail}")
        for key in ("merged", "merged_alias_path", "merged_lenient"):
            if results.get(key):
                print(f"  --- MERGED ({key}) ---")
                for c, detail in results[key]:
                    print(f"  id={c['id']:6d}  \"{_promotion_text(c)}\"  →  {detail}")
        if results.get("exact"):
            print(f"  --- EXACT IN KB: {len(results['exact'])} ---")


# ---------------------------------------------------------------------------
# Integrity check — queries resolver_* Postgres tables
# ---------------------------------------------------------------------------

def cmd_integrity_check(store) -> None:
    """Run KB integrity checks against resolver_* Postgres tables."""
    print()
    print("=== Phase 4c KB Integrity Check (Postgres resolver_* tables) ===")

    issues = 0
    with store._engine.connect() as conn:
        # Duplicate canonical names in resolver_fragrance_master
        dups = conn.execute(text(
            "SELECT canonical_name, COUNT(*) AS cnt "
            "FROM resolver_fragrance_master "
            "GROUP BY canonical_name HAVING COUNT(*) > 1 "
            "ORDER BY cnt DESC LIMIT 10"
        )).fetchall()
        if dups:
            print(f"  [WARN] Duplicate canonical_names in resolver_fragrance_master: {len(dups)}")
            for name, cnt in dups[:5]:
                print(f"    {cnt}x  \"{name}\"")
            issues += 1
        else:
            print("  [OK]   No duplicate canonical_names in resolver_fragrance_master")

        # Duplicate normalized names in resolver_fragrance_master
        dups_norm = conn.execute(text(
            "SELECT normalized_name, COUNT(*) AS cnt "
            "FROM resolver_fragrance_master WHERE normalized_name IS NOT NULL "
            "GROUP BY normalized_name HAVING COUNT(*) > 1 "
            "ORDER BY cnt DESC LIMIT 10"
        )).fetchall()
        if dups_norm:
            print(f"  [WARN] Duplicate normalized_names in resolver_fragrance_master: {len(dups_norm)}")
            for name, cnt in dups_norm[:5]:
                print(f"    {cnt}x  \"{name}\"")
            issues += 1
        else:
            print("  [OK]   No duplicate normalized_names in resolver_fragrance_master")

        # Orphan aliases (entity_id not in resolver_perfumes or resolver_brands)
        orphan_aliases = conn.execute(text(
            "SELECT COUNT(*) FROM resolver_aliases a "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM resolver_perfumes p WHERE p.id = a.entity_id AND a.entity_type = 'perfume'"
            ") AND NOT EXISTS ("
            "  SELECT 1 FROM resolver_brands b WHERE b.id = a.entity_id AND a.entity_type = 'brand'"
            ")"
        )).scalar() or 0
        if orphan_aliases:
            print(f"  [WARN] Orphan aliases in resolver_aliases: {orphan_aliases}")
            issues += 1
        else:
            print("  [OK]   No orphan aliases in resolver_aliases")

        # Orphan perfumes (brand_id not in resolver_brands)
        orphan_perfumes = conn.execute(text(
            "SELECT COUNT(*) FROM resolver_perfumes p "
            "WHERE brand_id IS NOT NULL AND NOT EXISTS ("
            "  SELECT 1 FROM resolver_brands b WHERE b.id = p.brand_id"
            ")"
        )).scalar() or 0
        if orphan_perfumes:
            print(f"  [WARN] Orphan brand_id references in resolver_perfumes: {orphan_perfumes}")
            issues += 1
        else:
            print("  [OK]   No orphan brand_id refs in resolver_perfumes")

    if issues == 0:
        print("\n  [PASS] Integrity check passed — no issues found.")
    else:
        print(f"\n  [WARN] {issues} issue(s) found — review before next promotion run.")


# ---------------------------------------------------------------------------
# KB row counts — queries resolver_* Postgres tables
# ---------------------------------------------------------------------------

def _print_kb_counts(store, label: str = "") -> None:
    from perfume_trend_sdk.analysis.candidate_validation.pg_promoter import print_kb_counts_pg
    print_kb_counts_pg(store, label)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _assert_postgres_available()

    parser = argparse.ArgumentParser(
        description="Phase 4c: review create bucket, seed brands, execute controlled creates (Postgres)"
    )

    cmd_group = parser.add_mutually_exclusive_group(required=True)
    cmd_group.add_argument("--analyze", action="store_true",
                           help="Classify all create-gated candidates (no writes)")
    cmd_group.add_argument("--seed-brand-aliases", action="store_true", dest="seed_brands",
                           help="Add missing brand short-form aliases to resolver_aliases")
    cmd_group.add_argument("--execute", action="store_true",
                           help="Execute Phase 4c: reject, merge, and create decisions")
    cmd_group.add_argument("--integrity-check", action="store_true", dest="integrity",
                           help="Check resolver_* integrity after creates")

    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writes")
    parser.add_argument("--allow-create", action="store_true",
                        help="Enable keep_as_valid_create entity insertion")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max candidates to process in --execute (default: 200)")
    parser.add_argument("--show-kb-counts", action="store_true",
                        help="Print resolver_* row counts before and after")

    args = parser.parse_args()

    from perfume_trend_sdk.storage.entities.pg_resolver_store import PgResolverStore
    from perfume_trend_sdk.storage.postgres.db import session_scope

    store = PgResolverStore()

    print()
    print("  KB target   : Postgres resolver_* tables")

    if args.integrity:
        cmd_integrity_check(store)
        return

    if args.seed_brands:
        cmd_seed_brand_aliases(store, dry_run=args.dry_run)
        return

    # For analyze and execute: open market DB session
    with session_scope() as db:
        candidates = _load_create_gated_candidates(db, limit=args.limit + 100)
        logger.info("Loaded %d create-gated candidates", len(candidates))

        kb = _load_kb_snapshot(store)
        logger.info(
            "KB snapshot: %d aliases, %d FM rows, %d brands",
            len(kb["alias_lookup"]), len(kb["fm_list"]), len(kb["brand_lookup"]),
        )

        if args.show_kb_counts:
            _print_kb_counts(store, "BEFORE")

        if args.analyze:
            cmd_analyze(candidates, kb)
        elif args.execute:
            cmd_execute(
                candidates, kb, store, db,
                dry_run=args.dry_run,
                allow_create=args.allow_create,
                limit=args.limit,
            )
            if args.show_kb_counts:
                _print_kb_counts(store, "AFTER")


if __name__ == "__main__":
    main()
