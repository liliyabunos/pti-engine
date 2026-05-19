"""SIG-QA2 — Evidence Scorer

Evaluates the quality of evidence behind a resolved entity mention, scoring
whether the source text genuinely references the specific perfume product
rather than a note name, generic descriptor, or category phrase.

Five feature dimensions (D1–D5) composited into a single score [0.0–1.0].
A score below SUPPRESS_THRESHOLD indicates the evidence is too weak to
support a market mention.

Failure modes detected:
  B — Note / ingredient collision ("Orange Blossom" resolved from note list)
  C — Ordinary word collision ("Revolution" in prose)
  D — Generic descriptor phrase ("Pure Luxury" as adjective)
  F — Partial-name collision ("On the Rocks" matched from "Apple Brandy on the Rocks")
  G — Category descriptor ("Men's Cologne" as category language)

Usage:
    result = score_mention(
        matched_from="Lavender, vanilla, and orange blossom come together...",
        brand_name="Angela Flanders",
        canonical_name="Orange Blossom",
        alias_used="orange blossom",
        source_entity_count=19,
    )
    # result.score = 0.23, result.would_suppress = True

Threshold calibration (2026-05-18, production RS snippets):
  Orange Blossom (Angela Flanders)  Type B  score≈0.23  SUPPRESS ✓
  Pure Luxury (Wolken Parfums)       Type D  score≈0.45  SUPPRESS ✓
  On the Rocks (Wolken Parfums)      Type F  score≈0.43  SUPPRESS ✓
  Enjoy the Day (Wolken Parfums)     Type D  score≈0.29  SUPPRESS ✓
  Cire Trudon Revolution             Type C  score≈0.35  SUPPRESS ✓
  Men's Cologne (Coty)               Type G  score≈0.46  SUPPRESS ✓
  Vision (Jaguar)                    Type A  score≈0.94  PASS ✓
  Creed Aventus                      Type A  score≈0.91  PASS ✓

Known false-suppression risk (shadow watchlist):
  Cool Water (Davidoff) — well-known standalone fragrance. "davidoff" may
  not appear near "cool water" in all review content. Must be monitored
  during shadow observation before active-mode activation. See shadow
  review coverage notes in CLAUDE.md SIG-QA2 section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Threshold
# ─────────────────────────────────────────────────────────────────────────────

SUPPRESS_THRESHOLD: float = 0.5

# ─────────────────────────────────────────────────────────────────────────────
# Feature constants
# ─────────────────────────────────────────────────────────────────────────────

# D2 — Fragrance context tokens (positive signal)
_FRAGRANCE_CONTEXT_TOKENS: frozenset = frozenset([
    "perfume", "fragrance", "scent", "cologne", "bottle", "spray",
    "edp", "edt", "dupe", "clone", "wear", "longevity", "sillage",
    "projection", "parfum", "toilette", "review", "rating",
    "blind", "buy", "frag", "parfumerie", "niche", "designer",
    "scentsy", "aftershave",
])

# D3 — Note-list indicator phrases (anti-signal: high score = worse evidence)
# These patterns near the matched phrase indicate the name is used as an
# ingredient / note descriptor rather than a product reference.
_NOTE_INDICATOR_PHRASES: List[str] = [
    "top notes",
    "heart notes",
    "base notes",
    "middle notes",
    "notes:",
    "fragrance notes",
    "note profile",
    "key notes",
    "accord",
    "smells like",
    "contains",
    "ingredients",
    "infused with",
    "scented with",
]

# D3 — Fragrance ingredient words (used for note co-occurrence detection).
# If ≥2 of these appear within ±D3_INGREDIENT_WINDOW tokens of the alias,
# the alias is likely used as an ingredient in a note-list, not a product
# reference. Example: "lavender, vanilla, and orange blossom come together"
# — "lavender" and "vanilla" are both within the window of "orange blossom".
_FRAGRANCE_INGREDIENTS: frozenset = frozenset([
    "lavender", "vanilla", "jasmine", "sandalwood", "bergamot", "musk",
    "cedar", "vetiver", "amber", "rose", "iris", "patchouli", "tonka",
    "oud", "neroli", "ylang", "citrus", "cardamom", "pepper", "ginger",
    "myrrh", "frankincense", "incense", "leather", "tobacco",
    "mandarin", "lemon", "lime", "grapefruit", "violet", "peony",
    "benzyl", "woody", "floral", "gourmand", "aquatic", "musky",
    "spicy", "earthy", "aldehyde", "iso",
])

# Window for ingredient co-occurrence check (smaller than general D3 window)
_D3_INGREDIENT_WINDOW: int = 8

# D5 — Source entity density thresholds
_D5_HIGH_DENSITY_CUTOFF: int = 15   # >15 entities → maximum penalty
_D5_LOW_DENSITY_CUTOFF: int = 3     # <=3 entities → minimal penalty

# Proximity windows (token counts)
_D1_BRAND_WINDOW_NEAR: int = 15    # within ±15 tokens → full credit
_D1_BRAND_WINDOW_FAR: int = 30     # within ±30 tokens → half credit
_D2_CONTEXT_WINDOW: int = 20       # fragrance keywords within ±20 tokens
_D3_NOTE_WINDOW_NEAR: int = 8      # note indicator within ±8 tokens → strong anti-signal
_D3_NOTE_WINDOW_FAR: int = 20      # note indicator within ±20 tokens → weak anti-signal


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvidenceResult:
    """Score and features for a single entity-mention pair."""
    score: float
    would_suppress: bool
    features: Dict[str, float] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def score_mention(
    matched_from: str,
    brand_name: str,
    canonical_name: str,
    alias_used: str,
    source_entity_count: int,
) -> EvidenceResult:
    """Score evidence quality for one resolved entity mention.

    Args:
        matched_from:        The full source text where the alias was found
                             (resolved_entities_json[n].matched_from).
        brand_name:          entity_market.brand_name for this entity.
        canonical_name:      entity_market.canonical_name.
        alias_used:          The specific alias string that triggered resolution.
                             Pass "" if the resolver did not expose an explicit alias.
                             An empty string produces D4=0.0 (no brand-token boost).
        source_entity_count: How many distinct entities were resolved from the
                             same content item. High count = diluted evidence.

    Returns:
        EvidenceResult with composite score and per-feature breakdown.
    """
    text = (matched_from or "").lower()
    tokens = _tokenize(text)
    brand_tokens = _extract_brand_tokens(brand_name)
    # alias_norm_for_d4: only the explicit alias string (no fallback).
    # Empty → D4=0.0. Prevents source-text inflation of D4.
    alias_norm_for_d4 = _normalize(alias_used)

    # position_alias_norm: used to locate the match in the text for D1/D2/D3.
    # Falls back to canonical_name when alias_used is absent — canonical is a
    # reliable proxy for where the product name appears in the text.
    position_alias_norm = _normalize(alias_used or canonical_name)
    match_pos = _find_alias_position(tokens, position_alias_norm)

    d1 = _score_d1_brand_proximity(tokens, match_pos, brand_tokens)
    d2 = _score_d2_fragrance_context(tokens, match_pos)
    d3_raw = _score_d3_note_antisignal(text, tokens, match_pos)
    d4 = _score_d4_full_name_match(alias_norm_for_d4, brand_tokens)
    d5_density = _score_d5_source_density(source_entity_count)

    # D3 and D5 are inverted: high raw score → low contribution
    d3_contribution = (1.0 - d3_raw) * 0.20
    d5_contribution = (1.0 - d5_density) * 0.10

    score = (
        0.35 * d1
        + 0.25 * d2
        + d3_contribution
        + 0.10 * d4
        + d5_contribution
    )
    score = round(min(max(score, 0.0), 1.0), 4)

    return EvidenceResult(
        score=score,
        would_suppress=score < SUPPRESS_THRESHOLD,
        features={
            "d1": round(d1, 4),
            "d2": round(d2, 4),
            "d3_raw": round(d3_raw, 4),
            "d4": round(d4, 4),
            "d5_density": round(d5_density, 4),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Feature scorers
# ─────────────────────────────────────────────────────────────────────────────

def _score_d1_brand_proximity(
    tokens: List[str],
    match_pos: Optional[int],
    brand_tokens: frozenset,
) -> float:
    """D1 — Brand Token Proximity (weight 0.35).

    Full credit (1.0) if a brand token appears within ±D1_BRAND_WINDOW_NEAR
    of the alias position. Half credit (0.5) for ±D1_BRAND_WINDOW_FAR.
    Zero if brand token absent or alias position unknown.
    """
    if match_pos is None or not brand_tokens:
        return 0.0

    n = len(tokens)
    near_lo = max(0, match_pos - _D1_BRAND_WINDOW_NEAR)
    near_hi = min(n, match_pos + _D1_BRAND_WINDOW_NEAR + 1)
    far_lo = max(0, match_pos - _D1_BRAND_WINDOW_FAR)
    far_hi = min(n, match_pos + _D1_BRAND_WINDOW_FAR + 1)

    window_near = tokens[near_lo:near_hi]
    window_far = tokens[far_lo:far_hi]

    if any(bt in window_near for bt in brand_tokens):
        return 1.0
    if any(bt in window_far for bt in brand_tokens):
        return 0.5
    return 0.0


def _score_d2_fragrance_context(
    tokens: List[str],
    match_pos: Optional[int],
) -> float:
    """D2 — Fragrance Context Signal (weight 0.25).

    Counts fragrance-domain keywords within ±D2_CONTEXT_WINDOW tokens of
    the alias. Scaled 0–1; 5+ hits = 1.0.
    """
    if match_pos is None:
        # No alias position found — scan whole token list (conservative)
        window = tokens
    else:
        lo = max(0, match_pos - _D2_CONTEXT_WINDOW)
        hi = min(len(tokens), match_pos + _D2_CONTEXT_WINDOW + 1)
        window = tokens[lo:hi]

    hits = sum(1 for t in window if t in _FRAGRANCE_CONTEXT_TOKENS)
    return min(hits / 5.0, 1.0)


def _score_d3_note_antisignal(
    text: str,
    tokens: List[str],
    match_pos: Optional[int],
) -> float:
    """D3 — Note Context Anti-Signal (weight 0.20, inverted).

    Returns a raw anti-signal score 0–1 where 1.0 = clear note-list context
    (bad for evidence quality). The calling code inverts this as (1 - d3_raw).

    Strong anti-signal (0.9): note indicator phrase within ±D3_NOTE_WINDOW_NEAR
    Weak anti-signal (0.5): note indicator phrase within ±D3_NOTE_WINDOW_FAR
    """
    if match_pos is None:
        # Scan full text for note indicators
        for phrase in _NOTE_INDICATOR_PHRASES:
            if phrase in text:
                return 0.5
        return 0.0

    n = len(tokens)
    near_lo = max(0, match_pos - _D3_NOTE_WINDOW_NEAR)
    near_hi = min(n, match_pos + _D3_NOTE_WINDOW_NEAR + 1)
    far_lo = max(0, match_pos - _D3_NOTE_WINDOW_FAR)
    far_hi = min(n, match_pos + _D3_NOTE_WINDOW_FAR + 1)

    near_text = " ".join(tokens[near_lo:near_hi])
    far_text = " ".join(tokens[far_lo:far_hi])

    for phrase in _NOTE_INDICATOR_PHRASES:
        if phrase in near_text:
            return 0.9
    for phrase in _NOTE_INDICATOR_PHRASES:
        if phrase in far_text:
            return 0.5

    # Ingredient co-occurrence: if ≥2 known fragrance ingredient words appear
    # within ±D3_INGREDIENT_WINDOW tokens of the alias, the alias is likely
    # used as an ingredient in an enumerated note list, not a product reference.
    # Example: "lavender, vanilla, and orange blossom come together" —
    # "lavender" and "vanilla" are both within the window of "orange blossom".
    ingr_lo = max(0, match_pos - _D3_INGREDIENT_WINDOW)
    ingr_hi = min(n, match_pos + _D3_INGREDIENT_WINDOW + 1)
    ingredient_window = tokens[ingr_lo:ingr_hi]
    ingredient_hits = sum(1 for t in ingredient_window if t in _FRAGRANCE_INGREDIENTS)
    if ingredient_hits >= 2:
        return 0.8

    return 0.0


def _score_d4_full_name_match(alias_norm: str, brand_tokens: frozenset) -> float:
    """D4 — Full-Name Match (weight 0.10).

    1.0 if the alias string contains any brand token — e.g. "angela flanders
    orange blossom" contains "angela" (brand token). 0.0 for bare aliases
    like "orange blossom" alone.
    """
    if not brand_tokens:
        return 0.0
    alias_words = set(alias_norm.split())
    return 1.0 if alias_words & brand_tokens else 0.0


def _score_d5_source_density(source_entity_count: int) -> float:
    """D5 — Source Entity Density (weight 0.10, inverted).

    Returns raw density penalty 0–1 where 1.0 = very high entity count (bad).
    The calling code inverts as (1 - d5_density).

    >D5_HIGH_DENSITY_CUTOFF entities → 1.0 (maximum penalty)
    <=D5_LOW_DENSITY_CUTOFF entities → 0.1 (minimal penalty)
    Linear interpolation in between.
    """
    if source_entity_count > _D5_HIGH_DENSITY_CUTOFF:
        return 1.0
    if source_entity_count <= _D5_LOW_DENSITY_CUTOFF:
        return 0.1
    span = _D5_HIGH_DENSITY_CUTOFF - _D5_LOW_DENSITY_CUTOFF
    return 0.1 + 0.9 * (source_entity_count - _D5_LOW_DENSITY_CUTOFF) / span


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [t for t in cleaned.split() if t]


def _normalize(text: str) -> str:
    """Same normalization as tokenize but returns a single string."""
    return " ".join(_tokenize(text))


def _extract_brand_tokens(brand_name: str) -> frozenset:
    """Return meaningful tokens from brand_name for proximity matching.

    Filters out single-character tokens and common stop words to avoid
    false positives from tokens like "de", "la", "by", "for".
    """
    _BRAND_STOP_TOKENS = frozenset([
        "de", "la", "le", "les", "du", "di", "by", "for", "and",
        "of", "in", "the", "al", "von", "per", "con",
    ])
    tokens = _tokenize(brand_name)
    return frozenset(
        t for t in tokens
        if len(t) >= 3 and t not in _BRAND_STOP_TOKENS
    )


def _find_alias_position(tokens: List[str], alias_norm: str) -> Optional[int]:
    """Return the start-token index of alias_norm in the token list.

    Searches for the first occurrence of the alias token sequence. Returns
    None if the alias is not found (e.g. matched_from is truncated or the
    alias was matched against title rather than body).
    """
    alias_tokens = alias_norm.split()
    if not alias_tokens:
        return None
    n = len(tokens)
    m = len(alias_tokens)
    for i in range(n - m + 1):
        if tokens[i : i + m] == alias_tokens:
            return i
    return None
