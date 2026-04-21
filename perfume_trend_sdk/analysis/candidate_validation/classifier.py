from __future__ import annotations

"""Deterministic rule-based candidate classifier — Phase 3B.

Each candidate phrase goes through three ordered steps:

  Step 1 — Noise detection (early exit with rejected_noise)
  Step 2 — Type classification (perfume | brand | note | unknown)
  Step 3 — Validation status assignment

Rules are deterministic and explicit.  When uncertain, the classifier defaults
to candidate_type='unknown' / validation_status='review' rather than
accepting or rejecting prematurely.

Public API::

    from perfume_trend_sdk.analysis.candidate_validation.classifier import (
        ClassificationResult, classify
    )

    result = classify(normalized_text, brand_tokens, note_names)
"""

import re
from dataclasses import dataclass
from typing import Optional, Set

from .rules import (
    AMBIGUOUS_BRAND_TOKENS,
    CONCENTRATION_WORDS,
    CONTRACTION_SUFFIXES,
    FRAGRANCE_COMMUNITY_WORDS,
    NOTE_KEYWORDS,
    STOP_PHRASES,
    STOPWORDS,
    URL_TOKENS,
    content_tokens,
    is_contraction_fragment,
    is_url_artifact,
    looks_like_social_handle,
    stopword_ratio,
)

# Imported for use in _meaningful_product_tokens
_FRAGRANCE_COMMUNITY_WORDS = FRAGRANCE_COMMUNITY_WORDS


@dataclass
class ClassificationResult:
    candidate_type: str           # perfume | brand | note | unknown | noise
    validation_status: str        # pending | accepted_rule_based | rejected_noise | review
    rejection_reason: Optional[str]
    token_count: int
    contains_brand_keyword: bool
    contains_perfume_keyword: bool


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify(
    normalized_text: str,
    brand_tokens: Set[str],
    note_names: Set[str],
) -> ClassificationResult:
    """Classify a single candidate phrase.

    Args:
        normalized_text:  Lowercased, stripped phrase from fragrance_candidates.
        brand_tokens:     Set of brand name tokens loaded from the brands table.
        note_names:       Set of canonical note names from notes_canonical.

    Returns:
        ClassificationResult with all fields populated.
    """
    tokens = normalized_text.strip().split()
    token_count = len(tokens)
    token_set = set(tokens)

    # Pre-compute keyword presence flags
    contains_brand_kw = _has_brand_signal(token_set, brand_tokens)
    contains_perfume_kw = bool(
        token_set & CONCENTRATION_WORDS
        or token_set & NOTE_KEYWORDS
        or bool(note_names and token_set & note_names)
    )

    # -----------------------------------------------------------------------
    # Step 1 — Noise detection
    # -----------------------------------------------------------------------
    noise_reason = _detect_noise(normalized_text, tokens, token_set)
    if noise_reason:
        return ClassificationResult(
            candidate_type="noise",
            validation_status="rejected_noise",
            rejection_reason=noise_reason,
            token_count=token_count,
            contains_brand_keyword=contains_brand_kw,
            contains_perfume_keyword=contains_perfume_kw,
        )

    # -----------------------------------------------------------------------
    # Step 2 — Type classification
    # -----------------------------------------------------------------------
    candidate_type = _classify_type(
        normalized_text, tokens, token_set, brand_tokens, note_names
    )

    # -----------------------------------------------------------------------
    # Step 3 — Validation status
    # -----------------------------------------------------------------------
    validation_status = _assign_status(
        normalized_text, tokens, token_set,
        candidate_type, contains_brand_kw, contains_perfume_kw,
        brand_tokens, note_names,
    )

    return ClassificationResult(
        candidate_type=candidate_type,
        validation_status=validation_status,
        rejection_reason=None,
        token_count=token_count,
        contains_brand_keyword=contains_brand_kw,
        contains_perfume_keyword=contains_perfume_kw,
    )


# ---------------------------------------------------------------------------
# Step 1 — Noise detection helpers
# ---------------------------------------------------------------------------

def _detect_noise(text: str, tokens: list, token_set: set) -> Optional[str]:
    """Return a rejection_reason string if the phrase is noise, else None.

    Rules are checked in this order — first match wins.
    """

    # 1. Too short (≤ 1 char or empty after strip)
    if len(text.strip()) <= 1:
        return "too_short"

    # 2. URL / technical artifact (http, bit, www, etc.)
    if is_url_artifact(tokens):
        return "url_artifact"

    # 3. Social-media handle pattern (single token, consonant-heavy)
    if looks_like_social_handle(text):
        return "social_handle"

    # 4. Explicit stop-phrase match
    if text in STOP_PHRASES:
        return "stop_phrase"

    # 5. Contraction fragment: "don t", "aren t", "i m", "you ve"
    if is_contraction_fragment(tokens):
        return "contraction_fragment"

    # 6. All tokens are stopwords
    if all(t in STOPWORDS for t in tokens):
        return "all_stopwords"

    # 7. Two-token phrase where both parts are community/generic words
    #    e.g. "fragrance i", "fragrances that", "dry down" (discussion vocab)
    if token_count_is(tokens, 2) and _is_community_fragment(tokens):
        return "community_fragment"

    # 8. High stopword ratio (≥ 0.75) with no perfume signal
    sr = stopword_ratio(tokens)
    if (
        sr >= 0.75
        and not bool(token_set & NOTE_KEYWORDS)
        and not bool(token_set & CONCENTRATION_WORDS)
    ):
        return f"high_stopword_ratio_{sr:.2f}"

    # 9. Starts with a clear 1st-person or 2nd-person pronoun
    #    and ends with a stopword — looks like a sentence tail/fragment
    if tokens and tokens[0] in {"i", "we", "you", "they", "he", "she", "it"}:
        if tokens[-1] in STOPWORDS:
            return "sentence_fragment"

    # 10. Pure digit string or number artifacts
    if re.match(r"^\d[\d\s]*$", text):
        return "numeric_artifact"

    # 11. "perfume" / "fragrance" as the ONLY content word
    #     e.g. "this fragrance", "a perfume", "your fragrance"
    content = content_tokens(tokens)
    if content and all(t in FRAGRANCE_COMMUNITY_WORDS for t in content):
        if len(content) <= 1:
            return "generic_fragrance_word"

    return None


def token_count_is(tokens: list, n: int) -> bool:
    return len(tokens) == n


def _is_community_fragment(tokens: list) -> bool:
    """Return True if a 2-token phrase is a generic fragrance-community fragment.

    These are phrases like "fragrance i", "dry down", "skin chemistry" that
    appear frequently in reviews but aren't entity names.
    """
    pair = " ".join(tokens)
    # Exact known community fragments
    COMMUNITY_PAIRS = frozenset({
        "dry down", "skin chemistry", "top note", "base note", "heart note",
        "blind buy", "sample decant", "fragrance i", "fragrances i",
        "fragrances that", "fragrances and",
        "scent or",
    })
    return pair in COMMUNITY_PAIRS


# ---------------------------------------------------------------------------
# Step 2 — Type classification helpers
# ---------------------------------------------------------------------------

def _has_brand_signal(token_set: set, brand_tokens: Set[str]) -> bool:
    """Return True if any token in the candidate matches a known brand token."""
    return bool(token_set & brand_tokens)


def _classify_type(
    text: str,
    tokens: list,
    token_set: set,
    brand_tokens: Set[str],
    note_names: Set[str],
) -> str:
    """Assign candidate_type to a non-noise candidate."""

    # Note: entire phrase or all content tokens are known notes
    # Require no leading/trailing stopwords in the full phrase.
    if _is_pure_note(text, tokens, token_set, note_names):
        return "note"

    # Brand: single distinctive token that is a known brand
    if len(tokens) == 1 and _is_brand_token(tokens[0], brand_tokens):
        return "brand"

    # Perfume: contains a known brand token AND at least one meaningful
    # product token (non-stopword, non-brand, not a pure number, not community vocab)
    brand_hits = [t for t in tokens if _is_brand_token(t, brand_tokens)]
    if brand_hits:
        product_tokens = _meaningful_product_tokens(tokens, brand_tokens)
        if product_tokens:
            return "perfume"
        # Multiple brand hits in one phrase → treat as named perfume
        if len(brand_hits) >= 2:
            return "perfume"
        # Single brand hit, no meaningful product token → brand mention
        return "brand"

    # Perfume: contains a concentration word alongside content words
    if bool(token_set & CONCENTRATION_WORDS):
        non_concentration = [
            t for t in tokens
            if t not in CONCENTRATION_WORDS
            and t not in STOPWORDS
            and not t.isdigit()
            and len(t) >= 3
        ]
        if non_concentration:
            return "perfume"

    return "unknown"


def _is_pure_note(
    text: str, tokens: list, token_set: set, note_names: Set[str]
) -> bool:
    """Return True if the candidate is a pure note name / phrase.

    Requires:
    - Phrase does NOT start or end with a stopword (no fragments like "rose and")
    - All non-stopword tokens are known note names / keywords
    """
    # Exact match in notes_canonical or NOTE_KEYWORDS
    if text in note_names or text in NOTE_KEYWORDS:
        return True

    # Reject if phrase starts or ends with a stopword — it's a fragment
    if tokens and (tokens[0] in STOPWORDS or tokens[-1] in STOPWORDS):
        return False

    # All non-stopword tokens must be notes
    content = content_tokens(tokens)
    if content and all(t in NOTE_KEYWORDS or t in note_names for t in content):
        return True
    return False


def _meaningful_product_tokens(tokens: list, brand_tokens: Set[str]) -> list:
    """Return product tokens that are genuinely meaningful entity words.

    Filters out:
    - Stopwords
    - Brand tokens (already accounted for)
    - Pure digit strings ("21", "540")
    - Very short tokens (< 3 chars)
    - Community/generic fragrance vocabulary
    """
    return [
        t for t in tokens
        if t not in STOPWORDS
        and not _is_brand_token(t, brand_tokens)
        and not t.isdigit()
        and len(t) >= 3
        and t not in FRAGRANCE_COMMUNITY_WORDS
    ]


def _is_brand_token(token: str, brand_tokens: Set[str]) -> bool:
    """Return True if token is a known brand token (not an ambiguous word)."""
    return token in brand_tokens and token not in AMBIGUOUS_BRAND_TOKENS


# ---------------------------------------------------------------------------
# Step 3 — Validation status helpers
# ---------------------------------------------------------------------------

def _assign_status(
    text: str,
    tokens: list,
    token_set: set,
    candidate_type: str,
    contains_brand_kw: bool,
    contains_perfume_kw: bool,
    brand_tokens: Set[str],
    note_names: Set[str],
) -> str:
    """Assign validation_status for non-noise candidates."""

    if candidate_type == "note":
        # Confirmed in notes_canonical → accept; otherwise send for review
        if text in note_names or any(t in note_names for t in tokens):
            return "accepted_rule_based"
        return "review"

    if candidate_type == "brand":
        # Single-token exact brand match → accept
        return "accepted_rule_based"

    if candidate_type == "perfume":
        # Brand + meaningful product token(s) → strong signal
        brand_hits = [t for t in tokens if _is_brand_token(t, brand_tokens)]
        product_tokens = [
            t for t in tokens
            if t not in STOPWORDS and not _is_brand_token(t, brand_tokens)
        ]
        if brand_hits and product_tokens:
            return "accepted_rule_based"
        # Has concentration word + content → also accept
        if bool(token_set & CONCENTRATION_WORDS) and product_tokens:
            return "accepted_rule_based"
        return "review"

    # candidate_type == "unknown"
    if contains_brand_kw or contains_perfume_kw:
        # Some signal but not enough for acceptance → review
        return "review"

    # No signal at all → review (preserve, don't auto-reject non-noise)
    return "review"
