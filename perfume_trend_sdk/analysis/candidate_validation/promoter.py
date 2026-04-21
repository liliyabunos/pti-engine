from __future__ import annotations

"""Phase 4b — Promotion pre-check and execution layer.

This module handles the safe promotion of reviewed candidates into the
Knowledge Base (fragrance_master, aliases, brands, perfumes tables in
the resolver DB — outputs/pti.db or RESOLVER_DB_PATH).

Promotion decisions
-------------------
  exact_existing_entity  — candidate already exists in KB (alias / FM / brand)
                           Action: record only, no new entity created
  merge_into_existing    — candidate is a variant/prefix of an existing entity
                           Action: add alias pointing to existing entity
  create_new_entity      — candidate is genuinely new and brand is resolvable
                           Action: create brand/perfume/FM rows + alias
  reject_promotion       — candidate fails final safeguards
                           Action: log rejection reason, no KB writes

CRITICAL: This module NEVER overwrites existing canonical entities.
All operations are additive (INSERT alias) or read-only.
Brand-resolution is required before any create_new_entity write.
"""

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from .rules import (
    AMBIGUOUS_BRAND_TOKENS,
    FRAGRANCE_COMMUNITY_WORDS,
    STOPWORDS,
)

# ---------------------------------------------------------------------------
# Decision constants
# ---------------------------------------------------------------------------

DECISION_EXACT = "exact_existing_entity"
DECISION_MERGE = "merge_into_existing"
DECISION_CREATE = "create_new_entity"
DECISION_REJECT = "reject_promotion"

# ---------------------------------------------------------------------------
# Promotion-time rejection token set
# Extends FRAGRANCE_COMMUNITY_WORDS with plurals and known non-English words
# ---------------------------------------------------------------------------

_PROMO_REJECT_TOKENS: frozenset = FRAGRANCE_COMMUNITY_WORDS | frozenset({
    # Plurals / variants not in base set
    "dupes", "clones",
    # Scent-analytics jargon (not entity names)
    "dna",
    # Review / content context words
    "review", "reviews", "guide", "guides",
    # Dutch / non-English fragment indicators
    "betaalbare", "alternatieven",
})

# Single words that are not valid standalone entity names
_REJECT_SINGLE_TOKENS: frozenset = STOPWORDS | AMBIGUOUS_BRAND_TOKENS | FRAGRANCE_COMMUNITY_WORDS


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PromotionCheck:
    candidate_id: int
    promotion_text: str           # text used for promotion (normalized_candidate_text or normalized_text)
    original_text: str            # normalized_text from fragrance_candidates
    entity_type: str              # perfume | brand | note
    decision: str                 # DECISION_* constant
    reason: str                   # human-readable rationale
    rejection_reason: Optional[str] = None
    # For existing entity matches
    matched_entity_id: Optional[int] = None
    matched_canonical_name: Optional[str] = None
    # For create_new_entity decisions
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    canonical_name_to_create: Optional[str] = None
    normalized_name_to_create: Optional[str] = None


@dataclass
class PromotionResult:
    check: PromotionCheck
    executed: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# KB snapshot (loaded once per job run)
# ---------------------------------------------------------------------------

def load_kb_snapshot(kb_conn: sqlite3.Connection) -> Dict[str, Any]:
    """Load resolver DB tables into memory for fast lookups.

    Returns a dict with:
      alias_lookup:       {normalized_alias_text: (entity_id, entity_type)}
      fm_lookup:          {normalized_name: (fragrance_id, canonical_name, perfume_id)}
      brand_lookup:       {normalized_name: (brand_id, canonical_name)}
      brand_alias_lookup: {normalized_alias_text: (brand_id, canonical_name)}  — brand aliases only
      perfume_canon:      {perfume_id: canonical_name}
      brand_canon:        {brand_id: canonical_name}
      fm_list:            [(normalized_name, fragrance_id, canonical_name, perfume_id)]
                          Used for fuzzy matching
    """
    cur = kb_conn.cursor()

    cur.execute("SELECT normalized_alias_text, entity_id, entity_type FROM aliases")
    alias_rows = cur.fetchall()
    alias_lookup: Dict[str, Tuple] = {}
    brand_alias_lookup: Dict[str, Tuple] = {}

    cur.execute("SELECT id, canonical_name FROM perfumes")
    perfume_canon: Dict[int, str] = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("SELECT id, canonical_name FROM brands")
    brand_canon: Dict[int, str] = {r[0]: r[1] for r in cur.fetchall()}

    for norm_text, entity_id, entity_type in alias_rows:
        alias_lookup[norm_text] = (entity_id, entity_type)
        if entity_type == "brand":
            brand_alias_lookup[norm_text] = (
                entity_id,
                brand_canon.get(entity_id, ""),
            )

    cur.execute(
        "SELECT fragrance_id, canonical_name, normalized_name, perfume_id "
        "FROM fragrance_master WHERE normalized_name IS NOT NULL"
    )
    fm_rows = cur.fetchall()
    fm_lookup: Dict[str, Tuple] = {r[2]: (r[0], r[1], r[3]) for r in fm_rows}
    fm_list: List[Tuple] = [(r[2], r[0], r[1], r[3]) for r in fm_rows]

    cur.execute("SELECT normalized_name, id, canonical_name FROM brands WHERE normalized_name IS NOT NULL")
    brand_rows = cur.fetchall()
    brand_lookup: Dict[str, Tuple] = {r[0]: (r[1], r[2]) for r in brand_rows}

    return {
        "alias_lookup": alias_lookup,
        "fm_lookup": fm_lookup,
        "brand_lookup": brand_lookup,
        "brand_alias_lookup": brand_alias_lookup,
        "perfume_canon": perfume_canon,
        "brand_canon": brand_canon,
        "fm_list": fm_list,
    }


# ---------------------------------------------------------------------------
# Promotion text selection
# ---------------------------------------------------------------------------

def get_promotion_text(candidate: Dict[str, Any]) -> str:
    """Return the text to use for KB promotion.

    Uses normalized_candidate_text if set (context-stripped), otherwise
    falls back to normalized_text.
    """
    norm_cand = (candidate.get("normalized_candidate_text") or "").strip()
    return norm_cand if norm_cand else candidate["normalized_text"]


# ---------------------------------------------------------------------------
# Step 1 — Safeguard rejection check
# ---------------------------------------------------------------------------

def safeguard_check(promo_text: str) -> Optional[str]:
    """Return rejection reason if the promotion text fails final safeguards.

    Checks (in order):
    1. Too short (<= 3 chars)
    2. Non-ASCII characters (non-Latin scripts)
    3. Known descriptor / community tokens (dupes, scent, dna, etc.)
    4. Single token that is a common English word
    5. Single token too short (< 5 chars)
    6. Starts with a digit
    """
    tokens = promo_text.split()

    if len(promo_text) <= 3:
        return "too_short"

    if not promo_text.isascii():
        return "non_ascii"

    token_set = set(tokens)
    descriptor_hits = token_set & _PROMO_REJECT_TOKENS
    if descriptor_hits:
        first_hit = next(iter(descriptor_hits))
        return f"descriptor_token:{first_hit}"

    if len(tokens) == 1:
        tok = tokens[0]
        if tok in _REJECT_SINGLE_TOKENS:
            return "single_common_word"
        if len(tok) < 5:
            return "single_token_too_short"

    if tokens[0].isdigit():
        return "digit_start"

    return None


# ---------------------------------------------------------------------------
# Step 2 — Exact KB match
# ---------------------------------------------------------------------------

def check_exact(promo_text: str, kb: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return match info if candidate already exists in KB, else None."""
    # Aliases (most comprehensive index)
    if promo_text in kb["alias_lookup"]:
        entity_id, entity_type = kb["alias_lookup"][promo_text]
        if entity_type == "perfume":
            canonical = kb["perfume_canon"].get(entity_id)
        else:
            canonical = kb["brand_canon"].get(entity_id)
        return {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "canonical_name": canonical,
            "via": "alias",
        }

    # Fragrance master (direct normalized_name hit)
    if promo_text in kb["fm_lookup"]:
        fid, canonical, perfume_id = kb["fm_lookup"][promo_text]
        return {
            "entity_id": perfume_id,
            "entity_type": "perfume",
            "canonical_name": canonical,
            "via": "fragrance_master",
        }

    # Brands table
    if promo_text in kb["brand_lookup"]:
        brand_id, canonical = kb["brand_lookup"][promo_text]
        return {
            "entity_id": brand_id,
            "entity_type": "brand",
            "canonical_name": canonical,
            "via": "brands",
        }

    return None


# ---------------------------------------------------------------------------
# Step 3 — Fuzzy / prefix merge detection
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def check_merge(promo_text: str, kb: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return merge target if promo_text is a safe variant of an existing entity.

    Requires at least 2 tokens and 8+ characters to avoid trivial matches.

    Strategy:
    1. Prefix check: promo_text is a clean prefix of an existing alias
       (e.g. "baccarat rouge" → prefix of "baccarat rouge 540")
    2. Fuzzy ratio >= 0.88 against fragrance_master names
       (e.g. "xerjoff erba bura" ~= "xerjoff erba pura")
    """
    tokens = promo_text.split()
    if len(tokens) < 2 or len(promo_text) < 8:
        return None

    # Prefix check against perfume aliases
    for norm_alias, (entity_id, entity_type) in kb["alias_lookup"].items():
        if entity_type != "perfume":
            continue
        if norm_alias.startswith(promo_text + " "):
            canonical = kb["perfume_canon"].get(entity_id)
            return {
                "entity_id": entity_id,
                "entity_type": "perfume",
                "canonical_name": canonical,
                "reason": f"prefix_of_alias:{norm_alias}",
            }

    # Fuzzy match against fragrance_master
    best_score = 0.0
    best_match: Optional[Tuple] = None
    for norm_name, fid, canonical, perfume_id in kb["fm_list"]:
        score = _similarity(promo_text, norm_name)
        if score > best_score and score >= 0.88:
            best_score = score
            best_match = (perfume_id, canonical, norm_name)

    if best_match:
        return {
            "entity_id": best_match[0],
            "entity_type": "perfume",
            "canonical_name": best_match[1],
            "reason": f"fuzzy_{best_score:.2f}:{best_match[2]}",
        }

    return None


# ---------------------------------------------------------------------------
# Step 4 — Brand resolution (required for create_new_entity)
# ---------------------------------------------------------------------------

def resolve_brand(promo_text: str, kb: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attempt to identify the brand from the promotion text.

    Tries 2-token prefix first, then 1-token prefix, against:
    - brands.normalized_name (direct match)
    - aliases where entity_type = 'brand' (alias match)

    Returns:
        dict with brand_id, brand_name, perfume_tokens, canonical_name, normalized_name
        or None if brand cannot be determined.
    """
    tokens = promo_text.split()

    for n in [2, 1]:
        if len(tokens) <= n:
            continue
        brand_prefix = " ".join(tokens[:n])
        perfume_tokens = tokens[n:]

        # Direct brand table match
        if brand_prefix in kb["brand_lookup"]:
            brand_id, brand_canonical = kb["brand_lookup"][brand_prefix]
            return _build_brand_info(brand_id, brand_canonical, perfume_tokens)

        # Brand alias match
        if brand_prefix in kb["brand_alias_lookup"]:
            brand_id, brand_canonical = kb["brand_alias_lookup"][brand_prefix]
            return _build_brand_info(brand_id, brand_canonical, perfume_tokens)

    return None


def _build_brand_info(
    brand_id: int,
    brand_canonical: str,
    perfume_tokens: List[str],
) -> Dict[str, Any]:
    perfume_name = " ".join(t.capitalize() for t in perfume_tokens)
    canonical_name = f"{brand_canonical} {perfume_name}"
    normalized_name = canonical_name.lower()
    return {
        "brand_id": brand_id,
        "brand_name": brand_canonical,
        "perfume_name": perfume_name,
        "perfume_tokens": perfume_tokens,
        "canonical_name": canonical_name,
        "normalized_name": normalized_name,
    }


# ---------------------------------------------------------------------------
# Pre-check orchestration
# ---------------------------------------------------------------------------

def precheck_candidate(
    candidate: Dict[str, Any],
    kb: Dict[str, Any],
) -> PromotionCheck:
    """Run all pre-checks and return a PromotionCheck with the decision."""
    cid = candidate["id"]
    entity_type = candidate.get("approved_entity_type") or candidate.get("candidate_type") or "unknown"
    promo_text = get_promotion_text(candidate)
    original_text = candidate["normalized_text"]

    def _reject(reason: str) -> PromotionCheck:
        return PromotionCheck(
            candidate_id=cid,
            promotion_text=promo_text,
            original_text=original_text,
            entity_type=entity_type,
            decision=DECISION_REJECT,
            reason=f"safeguard:{reason}",
            rejection_reason=reason,
        )

    # 1. Safeguard checks
    reject_reason = safeguard_check(promo_text)
    if reject_reason:
        return _reject(reject_reason)

    # 2. Exact KB match
    exact = check_exact(promo_text, kb)
    if exact:
        return PromotionCheck(
            candidate_id=cid,
            promotion_text=promo_text,
            original_text=original_text,
            entity_type=entity_type,
            decision=DECISION_EXACT,
            reason=f"already_in_kb:{exact['via']}",
            matched_entity_id=exact["entity_id"],
            matched_canonical_name=exact["canonical_name"],
        )

    # 3. Merge / fuzzy match
    merge = check_merge(promo_text, kb)
    if merge:
        return PromotionCheck(
            candidate_id=cid,
            promotion_text=promo_text,
            original_text=original_text,
            entity_type=entity_type,
            decision=DECISION_MERGE,
            reason=f"merge:{merge['reason']}",
            matched_entity_id=merge["entity_id"],
            matched_canonical_name=merge["canonical_name"],
        )

    # 4. Brand resolution (required for perfume creates)
    if entity_type == "perfume":
        brand_info = resolve_brand(promo_text, kb)
        if brand_info is None:
            return _reject("brand_not_resolvable")
        if not brand_info["perfume_tokens"]:
            return _reject("no_perfume_name_after_brand")
        # Validate proposed canonical is not already in KB
        if check_exact(brand_info["normalized_name"], kb):
            # Canonical would collide under a different form → treat as exact
            exact2 = check_exact(brand_info["normalized_name"], kb)
            return PromotionCheck(
                candidate_id=cid,
                promotion_text=promo_text,
                original_text=original_text,
                entity_type=entity_type,
                decision=DECISION_EXACT,
                reason=f"canonical_already_in_kb:{exact2['via']}",
                matched_entity_id=exact2["entity_id"],
                matched_canonical_name=exact2["canonical_name"],
            )
        return PromotionCheck(
            candidate_id=cid,
            promotion_text=promo_text,
            original_text=original_text,
            entity_type=entity_type,
            decision=DECISION_CREATE,
            reason=f"new_perfume:brand={brand_info['brand_name']}",
            brand_id=brand_info["brand_id"],
            brand_name=brand_info["brand_name"],
            canonical_name_to_create=brand_info["canonical_name"],
            normalized_name_to_create=brand_info["normalized_name"],
        )

    if entity_type == "brand":
        # Brand candidate not in KB — create brand entry
        return PromotionCheck(
            candidate_id=cid,
            promotion_text=promo_text,
            original_text=original_text,
            entity_type=entity_type,
            decision=DECISION_CREATE,
            reason="new_brand",
            canonical_name_to_create=" ".join(t.capitalize() for t in promo_text.split()),
            normalized_name_to_create=promo_text,
        )

    # Notes and unknown types — defer to manual review
    return _reject(f"deferred_type:{entity_type}")


def run_prechecks(
    candidates: List[Dict[str, Any]],
    kb: Dict[str, Any],
) -> List[PromotionCheck]:
    """Run pre-checks on a list of candidates. Returns one check per candidate."""
    return [precheck_candidate(c, kb) for c in candidates]


# ---------------------------------------------------------------------------
# Promotion execution (writes to KB)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alias_exists(kb_cur: sqlite3.Cursor, normalized_text: str, entity_id: int, entity_type: str) -> bool:
    kb_cur.execute(
        "SELECT id FROM aliases WHERE normalized_alias_text = ? AND entity_id = ? AND entity_type = ?",
        (normalized_text, entity_id, entity_type),
    )
    return kb_cur.fetchone() is not None


def execute_merge(
    check: PromotionCheck,
    kb_cur: sqlite3.Cursor,
) -> str:
    """Add the candidate as a new alias for an existing entity.

    Returns the alias_text that was inserted, or 'already_exists' if duplicate.
    """
    entity_id = check.matched_entity_id
    entity_type = "perfume"  # merge is always perfume in Phase 4b v1
    norm_text = check.promotion_text
    alias_text = " ".join(t.capitalize() for t in norm_text.split())

    if _alias_exists(kb_cur, norm_text, entity_id, entity_type):
        return "already_exists"

    now = _now_iso()
    kb_cur.execute(
        "INSERT INTO aliases "
        "  (alias_text, normalized_alias_text, entity_type, entity_id, match_type, confidence, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'discovery_generated', 0.85, ?, ?)",
        (alias_text, norm_text, entity_type, entity_id, now, now),
    )
    return alias_text


def execute_create_perfume(
    check: PromotionCheck,
    kb_cur: sqlite3.Cursor,
    candidate_id: int,
) -> Tuple[int, str]:
    """Create a new perfume in the KB.

    Steps:
    1. INSERT INTO perfumes (brand_id, canonical_name, normalized_name)
    2. INSERT INTO fragrance_master (fragrance_id, brand_name, perfume_name, ...)
    3. INSERT alias pointing to the new perfume

    Returns: (new_perfume_id, canonical_name)
    """
    now = _now_iso()
    brand_id = check.brand_id
    canonical_name = check.canonical_name_to_create
    normalized_name = check.normalized_name_to_create
    brand_name = check.brand_name
    perfume_name = canonical_name.replace(brand_name, "").strip()
    fragrance_id = f"disc_{candidate_id:06d}"

    # 1. Insert into perfumes
    kb_cur.execute(
        "INSERT INTO perfumes (brand_id, canonical_name, normalized_name) VALUES (?, ?, ?)",
        (brand_id, canonical_name, normalized_name),
    )
    new_perfume_id: int = kb_cur.lastrowid  # type: ignore[assignment]

    # 2. Insert into fragrance_master
    kb_cur.execute(
        "INSERT OR IGNORE INTO fragrance_master "
        "  (fragrance_id, brand_name, perfume_name, canonical_name, normalized_name, source, created_at, brand_id, perfume_id) "
        "VALUES (?, ?, ?, ?, ?, 'discovery', ?, ?, ?)",
        (
            fragrance_id,
            brand_name,
            perfume_name,
            canonical_name,
            normalized_name,
            now,
            brand_id,
            new_perfume_id,
        ),
    )

    # 3. Insert primary alias
    alias_text = canonical_name
    if not _alias_exists(kb_cur, normalized_name, new_perfume_id, "perfume"):
        kb_cur.execute(
            "INSERT INTO aliases "
            "  (alias_text, normalized_alias_text, entity_type, entity_id, match_type, confidence, created_at, updated_at) "
            "VALUES (?, ?, 'perfume', ?, 'discovery_generated', 0.80, ?, ?)",
            (alias_text, normalized_name, new_perfume_id, now, now),
        )

    # 4. Also add candidate normalized_text as alias if different from canonical
    orig_norm = check.promotion_text
    if orig_norm != normalized_name and not _alias_exists(kb_cur, orig_norm, new_perfume_id, "perfume"):
        orig_alias_text = " ".join(t.capitalize() for t in orig_norm.split())
        kb_cur.execute(
            "INSERT INTO aliases "
            "  (alias_text, normalized_alias_text, entity_type, entity_id, match_type, confidence, created_at, updated_at) "
            "VALUES (?, ?, 'perfume', ?, 'discovery_generated', 0.75, ?, ?)",
            (orig_alias_text, orig_norm, new_perfume_id, now, now),
        )

    return new_perfume_id, canonical_name


def execute_create_brand(
    check: PromotionCheck,
    kb_cur: sqlite3.Cursor,
) -> Tuple[int, str]:
    """Create a new brand in the KB.

    Returns: (new_brand_id, canonical_name)
    """
    now = _now_iso()
    canonical_name = check.canonical_name_to_create
    normalized_name = check.normalized_name_to_create

    kb_cur.execute(
        "INSERT OR IGNORE INTO brands (canonical_name, normalized_name) VALUES (?, ?)",
        (canonical_name, normalized_name),
    )
    new_brand_id: int = kb_cur.lastrowid  # type: ignore[assignment]

    # Add alias
    if not _alias_exists(kb_cur, normalized_name, new_brand_id, "brand"):
        kb_cur.execute(
            "INSERT INTO aliases "
            "  (alias_text, normalized_alias_text, entity_type, entity_id, match_type, confidence, created_at, updated_at) "
            "VALUES (?, ?, 'brand', ?, 'discovery_generated', 0.80, ?, ?)",
            (canonical_name, normalized_name, new_brand_id, now, now),
        )

    return new_brand_id, canonical_name


# ---------------------------------------------------------------------------
# Candidate row update (in market DB)
# ---------------------------------------------------------------------------

def record_promotion_outcome(
    market_cur: sqlite3.Cursor,
    candidate_id: int,
    decision: str,
    canonical_name: Optional[str],
    promoted_as: Optional[str],
    rejection_reason: Optional[str],
) -> None:
    """Write promotion decision fields to fragrance_candidates."""
    market_cur.execute(
        "UPDATE fragrance_candidates SET "
        "  promotion_decision = ?, "
        "  promoted_at = ?, "
        "  promoted_canonical_name = ?, "
        "  promoted_as = ?, "
        "  promotion_rejection_reason = ? "
        "WHERE id = ?",
        (
            decision,
            _now_iso(),
            canonical_name,
            promoted_as,
            rejection_reason,
            candidate_id,
        ),
    )
