from __future__ import annotations

"""Job: review_create_bucket — Phase 4c Create Bucket Review & Controlled New Entity Creation.

Processes candidates left in the create_new_entity gated bucket from Phase 4b.
Applies stricter classification, seeds missing brand aliases, and executes a
bounded controlled create run.

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
import sqlite3
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

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
# Phase 4c classification constants
# ---------------------------------------------------------------------------

# Product-name substrings that are not valid standalone brand names
_BRAND_PRODUCT_FRAGMENTS: frozenset = frozenset({
    "rouge", "baccarat", "libre", "pt", "blanc", "noir", "intense",
    "elixir", "absolute", "extreme", "pure",
})

# Generic English words that are not valid brand names
_BRAND_GENERIC_WORDS: frozenset = frozenset({
    "different", "blend", "essential", "another", "therapy",
    "secret", "purchase", "join", "notes", "good", "nice",
    "amazing", "great", "love", "like", "want", "need",
})

# French/Spanish/Italian function words that signal non-English fragments
_FOREIGN_FUNCTION_WORDS: frozenset = frozenset({
    "el", "en", "de", "del", "les", "du", "le", "la", "al",
    "un", "una", "por", "il", "gli", "lo", "los",
})

# Words in the perfume part that indicate context, not a perfume name
_PERFUME_CONTEXT_TOKENS: frozenset = frozenset({
    "and", "with", "from", "for", "what", "have", "actually",
    "very", "good", "awesome", "a", "all", "about",
    "samples", "sample", "i", "we", "is", "by",
    "if", "one", "then",
    # Fragrance pyramid position words — signal note description, not product name
    "notes", "bottom", "top", "middle", "heart", "base",
})

# Note/ingredient words frequently misclassified as brand name parts
_NOTE_BRAND_CONFUSERS: frozenset = frozenset({
    "vanille", "vanilla", "lilac", "ambrette", "sage",
    "amber", "musk", "oud",  # only when used as brand, not perfume part
})

# Words in raw candidate text that indicate content context, not entity name
_CONTENT_PHRASE_INDICATORS: frozenset = frozenset({
    "fucking", "bullshit", "actually can", "very good", "samples",
})

# Lenient fuzzy threshold for perfume create → convert_to_merge
# Requires score ≥ 0.75 to prevent false positives from shared brand-prefix similarity.
# Example: "tom ford tobacco oud" vs "tom ford black orchid" scores 0.732 — correctly rejected.
_LENIENT_FUZZY_THRESHOLD = 0.75

# Short brand alias seeds: known missing short-form aliases for existing KB brands
# Format: (alias_text, normalized_alias_text, entity_type, entity_id, brand_canonical)
_BRAND_ALIAS_SEEDS: List[Tuple] = [
    # "jovoy" → Jovoy Paris (brand_id=634, verified in pti.db)
    ("Jovoy", "jovoy", "brand", 634, "Jovoy Paris"),
]


# ---------------------------------------------------------------------------
# Candidate loader
# ---------------------------------------------------------------------------

def _load_create_gated_candidates(
    market_cur: sqlite3.Cursor,
    limit: int = 500,
    include_deferred: bool = True,
) -> List[Dict[str, Any]]:
    """Load candidates that are in the create bucket (not yet processed)."""
    conditions = ["review_status = 'approved_for_promotion'"]

    if include_deferred:
        conditions.append(
            "(promotion_decision IS NULL OR promotion_decision = 'deferred_create')"
        )
    else:
        conditions.append("promotion_decision IS NULL")

    where = " AND ".join(conditions)
    sql = (
        f"SELECT id, normalized_text, normalized_candidate_text, candidate_type, "
        f"  approved_entity_type, occurrences, source_platform, promotion_decision "
        f"FROM fragrance_candidates "
        f"WHERE {where} "
        f"ORDER BY occurrences DESC, candidate_type, id "
        f"LIMIT ?"
    )
    market_cur.execute(sql, (limit,))
    rows = market_cur.fetchall()
    keys = [
        "id", "normalized_text", "normalized_candidate_text", "candidate_type",
        "approved_entity_type", "occurrences", "source_platform", "promotion_decision",
    ]
    return [dict(zip(keys, r)) for r in rows]


# ---------------------------------------------------------------------------
# Phase 4c enhanced classifier
# ---------------------------------------------------------------------------

def _promotion_text(candidate: Dict[str, Any]) -> str:
    """Use normalized_candidate_text if set, else normalized_text."""
    nc = (candidate.get("normalized_candidate_text") or "").strip()
    return nc if nc else candidate["normalized_text"]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _resolve_brand(promo_text: str, kb: Dict) -> Optional[Dict]:
    """Lightweight brand resolver (same logic as promoter.py)."""
    tokens = promo_text.split()
    brand_lookup = kb["brand_lookup"]
    brand_alias_lookup = kb["brand_alias_lookup"]
    brand_canon = kb["brand_canon"]

    for n in [2, 1]:
        if len(tokens) <= n:
            continue
        prefix = " ".join(tokens[:n])
        perf_tokens = tokens[n:]

        if prefix in brand_lookup:
            bid, bcanon = brand_lookup[prefix]
            return {
                "brand_id": bid,
                "brand_name": bcanon,
                "perfume_tokens": perf_tokens,
                "canonical_name": bcanon + " " + " ".join(t.capitalize() for t in perf_tokens),
                "normalized_name": bcanon.lower() + " " + " ".join(perf_tokens),
            }
        if prefix in brand_alias_lookup:
            bid, bcanon = brand_alias_lookup[prefix]
            return {
                "brand_id": bid,
                "brand_name": bcanon,
                "perfume_tokens": perf_tokens,
                "canonical_name": bcanon + " " + " ".join(t.capitalize() for t in perf_tokens),
                "normalized_name": bcanon.lower() + " " + " ".join(perf_tokens),
            }

    return None


def enhanced_classify_4c(candidate: Dict[str, Any], kb: Dict) -> Tuple[str, str]:
    """Classify a create-gated candidate into one of 4 Phase 4c buckets.

    Returns:
        (decision, reason) where decision is one of:
          reject_create_candidate
          convert_to_merge
          keep_as_valid_create
          defer_create
    """
    from perfume_trend_sdk.analysis.candidate_validation.promoter import (
        check_exact, check_merge,
    )
    from perfume_trend_sdk.analysis.candidate_validation.rules import (
        FRAGRANCE_COMMUNITY_WORDS, NOTE_KEYWORDS, STOPWORDS,
    )

    promo_text = _promotion_text(candidate)
    entity_type = (
        candidate.get("approved_entity_type")
        or candidate.get("candidate_type")
        or "unknown"
    )
    tokens = promo_text.split()

    # --- Step 0: check if KB was updated (seed step may have added aliases) ---
    exact = check_exact(promo_text, kb)
    if exact:
        return "exact_now_in_kb", f"in_kb_via_{exact['via']}:{exact['canonical_name']}"

    merge = check_merge(promo_text, kb)
    if merge:
        return "convert_to_merge", f"prefix_or_fuzzy:{merge['canonical_name']}"

    # --- Note candidates: always defer (notes path not implemented) ---
    if entity_type == "note":
        return "defer_create", "notes_promotion_deferred"

    # -------------------------------------------------------------------
    # BRAND candidates
    # -------------------------------------------------------------------
    if entity_type == "brand":

        # Single-token brand candidates — very strict
        if len(tokens) == 1:
            tok = tokens[0]
            # Product name fragments
            if tok in _BRAND_PRODUCT_FRAGMENTS:
                return "reject_create_candidate", f"product_fragment:{tok}"
            # Generic English words
            if tok in _BRAND_GENERIC_WORDS:
                return "reject_create_candidate", f"generic_word:{tok}"
            # Common stopwords
            if tok in STOPWORDS:
                return "reject_create_candidate", f"stopword:{tok}"
            # Note/ingredient words misused as brand
            if tok in NOTE_KEYWORDS:
                return "reject_create_candidate", f"note_ingredient_not_brand:{tok}"
            if tok in _NOTE_BRAND_CONFUSERS:
                return "reject_create_candidate", f"note_confuser_not_brand:{tok}"
            # Short single token — too short to be a confident brand
            if len(tok) < 4:
                return "reject_create_candidate", f"too_short_single_token:{tok}"
            # Defer anything else that's a single-word brand unknown to us
            return "defer_create", f"unknown_single_word_brand:{tok}"

        # Multi-token brand candidates
        # Foreign function word at start
        if tokens[0] in _FOREIGN_FUNCTION_WORDS:
            return "reject_create_candidate", f"foreign_function_word_start:{tokens[0]}"

        # Product fragments anywhere in tokens
        if any(t in _BRAND_PRODUCT_FRAGMENTS for t in tokens):
            hit = next(t for t in tokens if t in _BRAND_PRODUCT_FRAGMENTS)
            return "reject_create_candidate", f"product_fragment_in_name:{hit}"

        # Digit token (version numbers etc.)
        if any(t.isdigit() for t in tokens):
            dig = next(t for t in tokens if t.isdigit())
            return "reject_create_candidate", f"contains_digit:{dig}"

        # Stopwords in the token set (multi-word brand with filler)
        stopword_hits = set(tokens) & STOPWORDS
        if stopword_hits:
            hit = next(iter(stopword_hits))
            return "reject_create_candidate", f"contains_stopword:{hit}"

        # Note/ingredient words used as brand
        note_hits = (set(tokens) & NOTE_KEYWORDS) | (set(tokens) & _NOTE_BRAND_CONFUSERS)
        if note_hits:
            hit = next(iter(note_hits))
            return "reject_create_candidate", f"note_word_in_brand:{hit}"

        # Generic words anywhere in the name
        generic_hits = set(tokens) & _BRAND_GENERIC_WORDS
        if generic_hits:
            hit = next(iter(generic_hits))
            return "reject_create_candidate", f"generic_word_in_name:{hit}"

        # Community vocabulary
        community_hits = set(tokens) & FRAGRANCE_COMMUNITY_WORDS
        if community_hits:
            hit = next(iter(community_hits))
            return "reject_create_candidate", f"community_word_in_brand:{hit}"

        # Passed all checks — still defer for multi-word brands (extra caution)
        return "defer_create", "multi_word_brand_needs_human_review"

    # -------------------------------------------------------------------
    # PERFUME candidates
    # -------------------------------------------------------------------
    if entity_type == "perfume":

        # Check for obvious content indicators in the full candidate text
        raw = candidate.get("normalized_text", "").lower()
        for indicator in _CONTENT_PHRASE_INDICATORS:
            if indicator in raw:
                return "reject_create_candidate", f"content_phrase:{indicator}"

        # Malformed concatenated token (no spaces, > 12 chars lowercase)
        if any(len(t) > 12 for t in tokens):
            long_tok = next(t for t in tokens if len(t) > 12)
            return "reject_create_candidate", f"malformed_long_token:{long_tok}"

        # Context tokens in the promotion text
        context_hits = set(tokens) & _PERFUME_CONTEXT_TOKENS
        if context_hits:
            hit = next(iter(context_hits))
            return "reject_create_candidate", f"context_word:{hit}"

        # Brand resolution
        brand_info = _resolve_brand(promo_text, kb)

        if brand_info is None:
            # Cannot determine brand → defer (not reject; brand may be added later)
            return "defer_create", "brand_not_resolvable"

        perfume_tokens = brand_info.get("perfume_tokens", [])

        if not perfume_tokens:
            return "reject_create_candidate", "no_perfume_name_after_brand"

        # Context words in the perfume part
        perf_context = set(perfume_tokens) & _PERFUME_CONTEXT_TOKENS
        if perf_context:
            hit = next(iter(perf_context))
            return "reject_create_candidate", f"perfume_part_context_word:{hit}"

        # Check if the perfume part text is already an alias in the KB (brand-agnostic lookup)
        # e.g. "tom ford tobacco oud" → perfume_part="tobacco oud" → alias for TF Tobacco Oud EDP
        perf_part_text = " ".join(perfume_tokens)
        alias_hit = kb.get("alias_lookup", {}).get(perf_part_text)
        if alias_hit is None:
            alias_hit = kb.get("brand_alias_lookup", {}).get(perf_part_text)
        if alias_hit is None:
            # Try full-text alias lookup
            full_text_alias = kb.get("alias_lookup", {}).get(promo_text)
            if full_text_alias:
                alias_hit = full_text_alias
        if alias_hit:
            # alias_hit is (entity_id, entity_type) from alias_lookup
            perf_entity_id = alias_hit[0] if isinstance(alias_hit, tuple) else None
            canon_label = kb.get("perfume_id_canon", {}).get(perf_entity_id, str(alias_hit))
            return "convert_to_merge", f"perfume_part_in_aliases:{canon_label}"

        # Single-token perfume name that is a note word → likely a note reference not a product
        if len(perfume_tokens) == 1:
            tok = perfume_tokens[0]
            from perfume_trend_sdk.analysis.candidate_validation.rules import NOTE_KEYWORDS
            if tok in NOTE_KEYWORDS or tok in _NOTE_BRAND_CONFUSERS:
                return "reject_create_candidate", f"single_note_token_not_product:{tok}"

        # Note words in perfume tokens are OK in multi-word contexts (e.g. "tobacco oud", "grey vetiver")

        # Lenient fuzzy match: proposed canonical vs all existing FM entries (0.75)
        proposed_norm = brand_info["normalized_name"]
        best_score = 0.0
        best_match: Optional[Tuple] = None
        for fm_norm, fid, fm_canonical, fm_perfume_id in kb["fm_list"]:
            score = _similarity(proposed_norm, fm_norm)
            if score > best_score and score >= _LENIENT_FUZZY_THRESHOLD:
                best_score = score
                best_match = (fm_perfume_id, fm_canonical, fm_norm)

        if best_match:
            # Close to existing entity → convert to merge (add alias)
            return "convert_to_merge", (
                f"lenient_fuzzy_{best_score:.2f}:"
                f"{best_match[1]}"
            )

        # Duplicate proposed canonical check
        if check_exact(proposed_norm, kb):
            exact2 = check_exact(proposed_norm, kb)
            return "exact_now_in_kb", f"proposed_canonical_in_kb:{exact2['canonical_name']}"

        # Clean perfume with known brand → valid create candidate
        return "keep_as_valid_create", f"new_perfume:brand={brand_info['brand_name']}"

    # Unknown type
    return "defer_create", f"unknown_entity_type:{entity_type}"


# ---------------------------------------------------------------------------
# KB snapshot loader
# ---------------------------------------------------------------------------

def _load_kb_snapshot(kb_conn: sqlite3.Connection) -> Dict:
    from perfume_trend_sdk.analysis.candidate_validation.promoter import load_kb_snapshot
    kb = load_kb_snapshot(kb_conn)

    # Add perfume_id_canon: {perfumes.id -> canonical_name}
    # alias_lookup values are (perfumes.id, entity_type) — this gives us canonical lookup
    cur = kb_conn.cursor()
    try:
        cur.execute("SELECT id, canonical_name FROM perfumes")
        kb["perfume_id_canon"] = {row[0]: row[1] for row in cur.fetchall()}
    except Exception:
        kb["perfume_id_canon"] = {}

    return kb


# ---------------------------------------------------------------------------
# Seed brand aliases
# ---------------------------------------------------------------------------

def cmd_seed_brand_aliases(kb_conn: sqlite3.Connection, *, dry_run: bool) -> None:
    """Add missing short-form brand aliases to the KB."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kb_cur = kb_conn.cursor()

    mode = "[DRY RUN]" if dry_run else "[APPLIED]"
    print(f"\n{mode} Seed brand short-form aliases")
    print()

    added = 0
    for alias_text, norm_alias, entity_type, entity_id, brand_canonical in _BRAND_ALIAS_SEEDS:
        # Verify entity exists
        kb_cur.execute(
            "SELECT id, canonical_name FROM brands WHERE id = ?", (entity_id,)
        )
        brand_row = kb_cur.fetchone()
        if not brand_row:
            print(f"  SKIP  \"{norm_alias}\" — brand_id={entity_id} not found in KB")
            continue

        # Check if alias already exists
        kb_cur.execute(
            "SELECT id FROM aliases WHERE normalized_alias_text = ? AND entity_type = ? AND entity_id = ?",
            (norm_alias, entity_type, entity_id),
        )
        if kb_cur.fetchone():
            print(f"  SKIP  \"{norm_alias}\" → \"{brand_canonical}\" — alias already exists")
            continue

        print(f"  ADD   \"{alias_text}\" / \"{norm_alias}\" → \"{brand_canonical}\" (brand_id={entity_id})")
        if not dry_run:
            kb_cur.execute(
                "INSERT INTO aliases "
                "  (alias_text, normalized_alias_text, entity_type, entity_id, "
                "   match_type, confidence, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'discovery_generated', 0.90, ?, ?)",
                (alias_text, norm_alias, entity_type, entity_id, now, now),
            )
            added += 1

    if not dry_run:
        kb_conn.commit()
        print(f"\n  Added {added} alias(es) to KB.")
    else:
        print(f"\n  Would add {len(_BRAND_ALIAS_SEEDS)} alias(es). Re-run without --dry-run to apply.")


# ---------------------------------------------------------------------------
# Analyze mode (no writes)
# ---------------------------------------------------------------------------

def cmd_analyze(candidates: List[Dict], kb: Dict) -> None:
    """Print full Phase 4c classification of all create-gated candidates."""
    buckets: Dict[str, List] = defaultdict(list)
    exact_now: List = []

    for c in candidates:
        decision, reason = enhanced_classify_4c(c, kb)
        if decision in ("exact_now_in_kb",):
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
# Execute mode
# ---------------------------------------------------------------------------

def _execute_candidate_4c(
    candidate: Dict,
    decision: str,
    reason: str,
    kb: Dict,
    kb_cur: sqlite3.Cursor,
    market_cur: sqlite3.Cursor,
    allow_create: bool,
) -> Tuple[str, str]:
    """Execute a single candidate's Phase 4c decision. Returns (outcome, detail)."""
    from perfume_trend_sdk.analysis.candidate_validation.promoter import (
        DECISION_CREATE, DECISION_EXACT, DECISION_MERGE, DECISION_REJECT,
        PromotionCheck, check_exact, check_merge, execute_create_perfume,
        execute_merge, record_promotion_outcome,
    )
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cid = candidate["id"]
    promo_text = _promotion_text(candidate)
    entity_type = candidate.get("approved_entity_type") or candidate.get("candidate_type") or "unknown"

    if decision == "exact_now_in_kb":
        # Now found in KB after seed expansion
        exact = check_exact(promo_text, kb)
        canonical = exact["canonical_name"] if exact else reason
        record_promotion_outcome(market_cur, cid, DECISION_EXACT, canonical, entity_type, None)
        return "exact", canonical

    if decision == "convert_to_merge":
        # Add alias to existing entity
        # First try phase 4b check_merge to get entity_id
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
            alias_result = execute_merge(check, kb_cur)
            record_promotion_outcome(
                market_cur, cid, DECISION_MERGE,
                merge["canonical_name"], entity_type, None,
            )
            return "merged", f"{promo_text} → {merge['canonical_name']} (alias={alias_result})"

        # Perfume-part alias path: if the classifier found the perfume part in aliases,
        # extract entity_id from alias_lookup and add the full candidate text as alias
        brand_info = _resolve_brand(promo_text, kb)
        if brand_info and "perfume_part_in_aliases" in reason:
            perf_part_text = " ".join(brand_info.get("perfume_tokens", []))
            alias_hit = kb.get("alias_lookup", {}).get(perf_part_text)
            if alias_hit and isinstance(alias_hit, tuple):
                target_pid = alias_hit[0]
                canon_from_pid = kb.get("perfume_id_canon", {}).get(target_pid, perf_part_text)
                from datetime import datetime, timezone
                now2 = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                alias_text = " ".join(t.capitalize() for t in promo_text.split())
                kb_cur.execute(
                    "SELECT id FROM aliases WHERE normalized_alias_text = ? AND entity_id = ? AND entity_type = 'perfume'",
                    (promo_text, target_pid),
                )
                if not kb_cur.fetchone():
                    kb_cur.execute(
                        "INSERT INTO aliases "
                        "  (alias_text, normalized_alias_text, entity_type, entity_id, "
                        "   match_type, confidence, created_at, updated_at) "
                        "VALUES (?, ?, 'perfume', ?, 'discovery_generated', 0.85, ?, ?)",
                        (alias_text, promo_text, target_pid, now2, now2),
                    )
                    alias_result = alias_text
                else:
                    alias_result = "already_exists"
                record_promotion_outcome(market_cur, cid, DECISION_MERGE, canon_from_pid, entity_type, None)
                return "merged_alias_path", f"{promo_text} → {canon_from_pid} (alias={alias_result})"

        # Lenient fuzzy merge: find the closest FM entry and add alias
        if brand_info:
            proposed_norm = brand_info["normalized_name"]
            best_score = 0.0
            best_entity_id: Optional[int] = None
            best_canonical: Optional[str] = None
            for fm_norm, fid, fm_canonical, fm_perfume_id in kb["fm_list"]:
                from difflib import SequenceMatcher
                score = SequenceMatcher(None, proposed_norm, fm_norm).ratio()
                if score > best_score and score >= _LENIENT_FUZZY_THRESHOLD:
                    best_score = score
                    best_entity_id = fm_perfume_id
                    best_canonical = fm_canonical

            if best_entity_id is not None:
                # Add alias pointing to existing entity
                from datetime import datetime, timezone
                now2 = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                alias_text = " ".join(t.capitalize() for t in promo_text.split())
                # Check for duplicate
                kb_cur.execute(
                    "SELECT id FROM aliases WHERE normalized_alias_text = ? AND entity_id = ? AND entity_type = 'perfume'",
                    (promo_text, best_entity_id),
                )
                if not kb_cur.fetchone():
                    kb_cur.execute(
                        "INSERT INTO aliases "
                        "  (alias_text, normalized_alias_text, entity_type, entity_id, "
                        "   match_type, confidence, created_at, updated_at) "
                        "VALUES (?, ?, 'perfume', ?, 'discovery_generated', 0.80, ?, ?)",
                        (alias_text, promo_text, best_entity_id, now2, now2),
                    )
                    alias_result = alias_text
                else:
                    alias_result = "already_exists"
                record_promotion_outcome(
                    market_cur, cid, DECISION_MERGE,
                    best_canonical, entity_type, None,
                )
                return "merged_lenient", f"{promo_text} → {best_canonical} (alias={alias_result})"

        # No merge target found — fall through to reject
        record_promotion_outcome(
            market_cur, cid, DECISION_REJECT, None, None,
            "phase4c:convert_to_merge_no_target",
        )
        return "rejected", "convert_to_merge_no_target"

    if decision == "reject_create_candidate":
        # Record rejection with Phase 4c reason
        record_promotion_outcome(
            market_cur, cid, DECISION_REJECT, None, None, f"phase4c:{reason}",
        )
        return "rejected", reason

    if decision == "keep_as_valid_create":
        if not allow_create:
            # Record as deferred but don't leave NULL (so it can be re-queried)
            market_cur.execute(
                "UPDATE fragrance_candidates SET "
                "  promotion_decision = 'deferred_create', "
                "  promotion_rejection_reason = 'create_gated:allow_create_not_set', "
                "  promoted_at = ? "
                "WHERE id = ?",
                (now, cid),
            )
            return "deferred_create_gated", "allow_create_not_set"

        # Execute create
        brand_info = _resolve_brand(promo_text, kb)
        if brand_info is None:
            record_promotion_outcome(
                market_cur, cid, DECISION_REJECT, None, None,
                "phase4c:brand_resolve_failed_at_execute",
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
                new_id, canonical = execute_create_perfume(check, kb_cur, cid)
            else:
                from perfume_trend_sdk.analysis.candidate_validation.promoter import execute_create_brand
                new_id, canonical = execute_create_brand(check, kb_cur)

            record_promotion_outcome(
                market_cur, cid, DECISION_CREATE, canonical, entity_type, None,
            )
            return "created", f"new_id={new_id} canonical=\"{canonical}\""

        except Exception as exc:  # noqa: BLE001
            record_promotion_outcome(
                market_cur, cid, DECISION_REJECT, None, None,
                f"phase4c:create_error:{exc}",
            )
            return "error", str(exc)

    if decision == "defer_create":
        market_cur.execute(
            "UPDATE fragrance_candidates SET "
            "  promotion_decision = 'deferred_create', "
            "  promotion_rejection_reason = ?, "
            "  promoted_at = ? "
            "WHERE id = ? AND (promotion_decision IS NULL OR promotion_decision = 'deferred_create')",
            (f"phase4c_deferred:{reason}", now, cid),
        )
        return "deferred", reason

    return "skipped", decision


def cmd_execute(
    candidates: List[Dict],
    kb: Dict,
    kb_conn: sqlite3.Connection,
    market_conn: sqlite3.Connection,
    *,
    dry_run: bool,
    allow_create: bool,
    limit: int,
) -> None:
    """Execute Phase 4c decisions for create-gated candidates."""
    from perfume_trend_sdk.analysis.candidate_validation.promoter import (
        DECISION_CREATE, DECISION_EXACT, DECISION_MERGE, DECISION_REJECT,
    )

    mode = "[DRY RUN]" if dry_run else "[REAL]"
    print(f"\n{mode} Phase 4c Execute")
    print(f"  Processing {min(len(candidates), limit)} candidates"
          f"  allow_create={allow_create}")

    kb_cur = kb_conn.cursor()
    market_cur = market_conn.cursor()

    results: Dict[str, List] = defaultdict(list)

    # Pre-classify all candidates to support in-batch deduplication
    classified = []
    for candidate in candidates:
        decision, reason = enhanced_classify_4c(candidate, kb)
        classified.append((candidate, decision, reason))

    # Collect all proposed canonicals for creates so we can detect partial-name duplicates
    # e.g. "Xerjoff Jazz" is a prefix of "Xerjoff Jazz Club" — shorter becomes alias, not entity
    create_canonicals: List[str] = []
    for candidate, decision, reason in classified:
        if decision == "keep_as_valid_create":
            bi = _resolve_brand(_promotion_text(candidate), kb)
            if bi:
                create_canonicals.append(bi["normalized_name"])

    def _is_prefix_of_longer_create(proposed_norm: str) -> bool:
        """Return True if another proposed canonical starts with proposed_norm + ' '."""
        prefix_with_space = proposed_norm + " "
        return any(
            other.startswith(prefix_with_space)
            for other in create_canonicals
            if other != proposed_norm
        )

    # Track created canonical names this batch to deduplicate
    created_this_batch: set = set()

    processed = 0
    for candidate, decision, reason in classified:
        if processed >= limit:
            break

        promo_text = _promotion_text(candidate)
        etype = candidate.get("approved_entity_type") or candidate.get("candidate_type") or "?"

        # Detect partial-name creates: if this proposed canonical is a prefix of a longer
        # create in the same batch, defer it (it should become an alias post-creation)
        if decision == "keep_as_valid_create":
            bi = _resolve_brand(promo_text, kb)
            if bi and _is_prefix_of_longer_create(bi["normalized_name"]):
                decision = "defer_create"
                reason = "partial_name:longer_canonical_in_batch"
            elif bi and bi["normalized_name"] in created_this_batch:
                # Same canonical already created this batch → skip (it's an alias duplicate)
                decision = "defer_create"
                reason = "duplicate_canonical_this_batch"
            elif bi:
                created_this_batch.add(bi["normalized_name"])

        if dry_run:
            results[decision].append((candidate, reason))
            processed += 1
            continue

        outcome, detail = _execute_candidate_4c(
            candidate, decision, reason, kb, kb_cur, market_cur, allow_create,
        )
        results[outcome].append((candidate, detail))
        processed += 1

    if not dry_run:
        kb_conn.commit()
        market_conn.commit()

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
            print("  --- CREATED ---")
            for c, detail in results["created"]:
                print(f"  id={c['id']:6d}  \"{_promotion_text(c)}\"  →  {detail}")
        if results.get("merged") or results.get("merged_lenient"):
            print("  --- MERGED ---")
            for outcome in ["merged", "merged_lenient"]:
                for c, detail in results.get(outcome, []):
                    print(f"  id={c['id']:6d}  \"{_promotion_text(c)}\"  →  {detail}")
        if results.get("exact"):
            print(f"  --- EXACT IN KB: {len(results['exact'])} ---")


# ---------------------------------------------------------------------------
# Integrity check
# ---------------------------------------------------------------------------

def cmd_integrity_check(kb_conn: sqlite3.Connection) -> None:
    """Run KB integrity checks after Phase 4c creates."""
    kb_cur = kb_conn.cursor()
    print()
    print("=== Phase 4c KB Integrity Check ===")

    issues = 0

    # Duplicate canonical names in fragrance_master
    kb_cur.execute(
        "SELECT canonical_name, COUNT(*) AS cnt "
        "FROM fragrance_master "
        "GROUP BY canonical_name "
        "HAVING cnt > 1 "
        "ORDER BY cnt DESC "
        "LIMIT 10"
    )
    dups = kb_cur.fetchall()
    if dups:
        print(f"  [WARN] Duplicate canonical_names in fragrance_master: {len(dups)}")
        for name, cnt in dups[:5]:
            print(f"    {cnt}x  \"{name}\"")
        issues += 1
    else:
        print("  [OK]   No duplicate canonical_names in fragrance_master")

    # Duplicate normalized names in fragrance_master
    kb_cur.execute(
        "SELECT normalized_name, COUNT(*) AS cnt "
        "FROM fragrance_master "
        "WHERE normalized_name IS NOT NULL "
        "GROUP BY normalized_name "
        "HAVING cnt > 1 "
        "ORDER BY cnt DESC "
        "LIMIT 10"
    )
    dups_norm = kb_cur.fetchall()
    if dups_norm:
        print(f"  [WARN] Duplicate normalized_names in fragrance_master: {len(dups_norm)}")
        for name, cnt in dups_norm[:5]:
            print(f"    {cnt}x  \"{name}\"")
        issues += 1
    else:
        print("  [OK]   No duplicate normalized_names in fragrance_master")

    # Aliases pointing to missing perfumes
    kb_cur.execute(
        "SELECT COUNT(*) FROM aliases a "
        "WHERE a.entity_type = 'perfume' "
        "  AND NOT EXISTS (SELECT 1 FROM perfumes p WHERE p.id = a.entity_id)"
    )
    orphan_perf = kb_cur.fetchone()[0]
    if orphan_perf:
        print(f"  [WARN] Aliases pointing to missing perfumes: {orphan_perf}")
        issues += 1
    else:
        print("  [OK]   All perfume aliases point to valid perfume entities")

    # Aliases pointing to missing brands
    kb_cur.execute(
        "SELECT COUNT(*) FROM aliases a "
        "WHERE a.entity_type = 'brand' "
        "  AND NOT EXISTS (SELECT 1 FROM brands b WHERE b.id = a.entity_id)"
    )
    orphan_brand = kb_cur.fetchone()[0]
    if orphan_brand:
        print(f"  [WARN] Aliases pointing to missing brands: {orphan_brand}")
        issues += 1
    else:
        print("  [OK]   All brand aliases point to valid brand entities")

    # FM rows with missing perfume_id
    kb_cur.execute(
        "SELECT COUNT(*) FROM fragrance_master "
        "WHERE perfume_id IS NOT NULL "
        "  AND NOT EXISTS (SELECT 1 FROM perfumes p WHERE p.id = perfume_id)"
    )
    orphan_fm = kb_cur.fetchone()[0]
    if orphan_fm:
        print(f"  [WARN] FM rows with missing perfume_id reference: {orphan_fm}")
        issues += 1
    else:
        print("  [OK]   All fragrance_master perfume_id references are valid")

    # Discovery rows and aliases summary
    kb_cur.execute("SELECT COUNT(*) FROM fragrance_master WHERE source = 'discovery'")
    disc_fm = kb_cur.fetchone()[0]
    kb_cur.execute("SELECT COUNT(*) FROM aliases WHERE match_type = 'discovery_generated'")
    disc_alias = kb_cur.fetchone()[0]
    print(f"\n  Discovery FM rows          : {disc_fm}")
    print(f"  Discovery-generated aliases: {disc_alias}")

    print()
    if issues:
        print(f"  [STOP] {issues} integrity issue(s) found. Investigate before scaling.")
    else:
        print("  [PASS] KB integrity verified — safe to continue.")


# ---------------------------------------------------------------------------
# KB counts
# ---------------------------------------------------------------------------

def _print_kb_counts(kb_cur: sqlite3.Cursor, label: str = "") -> None:
    if label:
        print(f"\n  [{label}] KB row counts:")
    tables = [
        ("fragrance_master", "fragrance_master"),
        ("aliases", "aliases"),
        ("brands", "brands"),
        ("perfumes", "perfumes"),
    ]
    for lbl, tbl in tables:
        kb_cur.execute(f"SELECT COUNT(*) FROM {tbl}")  # noqa: S608
        cnt = kb_cur.fetchone()[0]
        print(f"    {lbl:20s}: {cnt:,}")
    kb_cur.execute("SELECT COUNT(*) FROM fragrance_master WHERE source = 'discovery'")
    print(f"    discovery FM rows     : {kb_cur.fetchone()[0]}")
    kb_cur.execute("SELECT COUNT(*) FROM aliases WHERE match_type = 'discovery_generated'")
    print(f"    discovery aliases     : {kb_cur.fetchone()[0]}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 4c: review create bucket, seed brands, execute controlled creates"
    )

    cmd_group = parser.add_mutually_exclusive_group(required=True)
    cmd_group.add_argument("--analyze", action="store_true",
                           help="Classify all create-gated candidates (no writes)")
    cmd_group.add_argument("--seed-brand-aliases", action="store_true",
                           dest="seed_brands",
                           help="Add missing brand short-form aliases to KB")
    cmd_group.add_argument("--execute", action="store_true",
                           help="Execute Phase 4c: reject, merge, and create decisions")
    cmd_group.add_argument("--integrity-check", action="store_true",
                           dest="integrity",
                           help="Check KB integrity after creates")

    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writes (default for --seed-brand-aliases)")
    parser.add_argument("--allow-create", action="store_true",
                        help="Enable keep_as_valid_create entity insertion")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max candidates to process in --execute (default: 200)")
    parser.add_argument("--show-kb-counts", action="store_true")
    parser.add_argument("--market-db", metavar="PATH", default=_DEFAULT_MARKET_DB)
    parser.add_argument("--kb-db", metavar="PATH", default=_DEFAULT_KB_DB)

    args = parser.parse_args()

    if not os.path.exists(args.market_db):
        print(f"ERROR: market DB not found: {args.market_db}")
        sys.exit(1)
    if not os.path.exists(args.kb_db):
        print(f"ERROR: KB DB not found: {args.kb_db}")
        sys.exit(1)

    market_conn = sqlite3.connect(args.market_db)
    kb_conn = sqlite3.connect(args.kb_db)
    market_cur = market_conn.cursor()
    kb_cur = kb_conn.cursor()

    try:
        print(f"\n  Market DB : {args.market_db}")
        print(f"  KB DB     : {args.kb_db}")

        if args.integrity:
            cmd_integrity_check(kb_conn)
            return

        if args.seed_brands:
            cmd_seed_brand_aliases(kb_conn, dry_run=args.dry_run)
            return

        # For analyze and execute: load candidates + KB
        candidates = _load_create_gated_candidates(market_cur, limit=args.limit + 100)
        logger.info("Loaded %d create-gated candidates", len(candidates))

        kb = _load_kb_snapshot(kb_conn)
        logger.info(
            "KB snapshot: %d aliases, %d FM rows, %d brands",
            len(kb["alias_lookup"]), len(kb["fm_list"]), len(kb["brand_lookup"]),
        )

        if args.show_kb_counts:
            _print_kb_counts(kb_cur, "BEFORE")

        if args.analyze:
            cmd_analyze(candidates, kb)
        elif args.execute:
            cmd_execute(
                candidates, kb, kb_conn, market_conn,
                dry_run=args.dry_run,
                allow_create=args.allow_create,
                limit=args.limit,
            )
            if args.show_kb_counts:
                _print_kb_counts(kb_cur, "AFTER")

    finally:
        market_conn.close()
        kb_conn.close()


if __name__ == "__main__":
    main()
