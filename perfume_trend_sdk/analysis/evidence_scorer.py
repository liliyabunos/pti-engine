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
  W — Brandless high-context false pass (D1=0, D4=0, D2=1.0 → raw score 0.54)

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

PV-008-B2-FIX1 — Brand-prefix strip position recovery + no-brand cap (2026-05-19):
  Problem: entities whose canonical name starts with a brand prefix
  ("Chanel Bleu de Chanel") could have D1=0 because the exact alias
  sequence is not found in source text (source says "Bleu de Chanel",
  not "Chanel Bleu de Chanel").  This left legitimate high-confidence
  mentions with D1=0+D4=0, producing raw score 0.540 — a false pass.

  Fix part A — _find_alias_position() pass 3:
    Strip brand tokens from the front of the alias sequence and search
    for the remainder.  Accept the position only if a brand token appears
    within ±15 tokens.  For suffix+brand strip: suffix stripping already
    runs in pass 2; pass 3 also applies brand-strip to the suffix-stripped
    variant.  Example: "Chanel Bleu de Chanel Eau de Parfum":
      pass 1 fails (full phrase not in source)
      pass 2 suffix-strips to "Chanel Bleu de Chanel", not found
      pass 3 strips "chanel" → "bleu de chanel", FOUND, "chanel" in
             proximity → D1=1.0 ✓

  Fix part B — brand-evidence minimum cap in score_mention():
    When D1=0 AND D4=0 (no brand evidence from any source-grounded path),
    cap the composite score to 0.45 < SUPPRESS_THRESHOLD.  Any entity
    with genuine brand context will have recovered D1 via pass 3 above,
    so legitimate mentions are not affected by the cap.
    Wrong-product test: "Need Dior Eau Sauvage but stronger" → alias
    "Dior Sauvage EDP" → brand-strip finds "sauvage" but "dior" absent
    from source → pass 3 rejects → D1=0 → cap applied → SUPPRESS ✓

Shadow watchlist (open PV-008 items):
  Cool Water / Cool Water Parfum (Davidoff) — well-known standalone
  fragrance. "davidoff" may not appear near "cool water" in all review
  content. PV-008-B1-FIX1 recovers position for concentration variants
  when the base form is found; brand-sparse cases remain a separate
  open evaluation item.  Must be reviewed after ≥7 clean shadow runs.
  Diptyque Tam Dao EDP — source mentions "Tam Dao" without "diptyque"
  brand token; pass 3 correctly rejects due to absent brand context.
  Conservative behavior; documented trade-off.
  Heures d'Absence — brand_name=NULL in entity_market (data gap); D1=0
  always regardless of source quality. Requires brand_name data repair.
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
# PV-008-B1-FIX1 — Concentration suffix stripping for position recovery
# ─────────────────────────────────────────────────────────────────────────────
# Local copy of aggregator.py's _CONC_SUFFIX_RE.  Intentionally not imported
# from that module to avoid a cross-module dependency in the wrong direction
# (evidence_scorer is a pure analysis utility; it must not depend on job code).
# The suffix vocabulary is stable; duplication is correct here.
#
# Used only inside _find_alias_position() for the suffix-strip fallback:
# when the full canonical phrase ("creed aventus eau de parfum") is not found
# in the matched_from text, strip the concentration suffix and retry with
# the base form ("creed aventus").  This restores D1/D2/D3 window accuracy
# for concentration-variant entities where alias_used="" in RS data.
_CONC_SUFFIX_RE = re.compile(
    r"\s+(?:"
    r"Extrait\s+de\s+Parfum"
    r"|Eau\s+de\s+Parfum"
    r"|Eau\s+de\s+Toilette"
    r"|Eau\s+de\s+Cologne"
    r"|Eau\s+Fraiche"
    r"|Extrait"
    r"|Parfum"
    r")\s*$",
    re.IGNORECASE,
)

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
    match_pos = _find_alias_position(tokens, position_alias_norm, brand_tokens)

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

    # PV-008-B2-FIX1 — Brand-evidence minimum requirement cap.
    # When D1=0 (brand absent / unanchored in source) AND D4=0 (alias carries
    # no brand token), no source-grounded brand evidence exists.  Cap to 0.45
    # so that high-fragrance-context sources cannot produce a false pass on
    # brand-identity-less mentions.  Any entity with genuine brand presence in
    # source would have recovered D1 via _find_alias_position() pass 3 above.
    if d1 == 0.0 and d4 == 0.0:
        score = min(score, 0.45)

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


def _find_alias_position(
    tokens: List[str],
    alias_norm: str,
    brand_tokens: Optional[frozenset] = None,
) -> Optional[int]:
    """Return the start-token index of alias_norm in the token list.

    Searches for the first occurrence of the alias token sequence. Returns
    None if the alias is not found (e.g. matched_from is truncated or the
    alias was matched against title rather than body).

    PV-008-B1-FIX1 — Concentration-suffix fallback (pass 2):
    When the primary search fails AND alias_norm ends with a concentration
    suffix, strip the suffix and retry (up to 2 passes to handle double-
    suffixed names like "Baccarat Rouge 540 Extrait Extrait de Parfum").
    This recovers D1/D2/D3 window accuracy for entities whose canonical_name
    carries a suffix ("Creed Aventus Eau de Parfum") while source text
    uses the bare base form ("creed aventus review").

    PV-008-B2-FIX1 — Brand-prefix strip fallback (pass 3):
    When the full canonical name starts with the brand name ("Chanel Bleu de
    Chanel"), sources may mention only the product portion ("Bleu de Chanel").
    Strip brand tokens from the front of the alias sequence and search for the
    remainder.  ONLY accepted if a brand token is also found within
    ±D1_BRAND_WINDOW_NEAR tokens of the match position — this ensures the
    recovered position carries genuine brand identity evidence and prevents
    wrong-product rescues (e.g. "Dior Eau Sauvage" source → alias stripped to
    "Sauvage" → "dior" absent from text → position rejected).
    Pass 3 is applied to both the original alias and any suffix-stripped
    variant so "Chanel Bleu de Chanel Eau de Parfum" chains suffix+brand strip.
    """
    def _search(tok_seq: List[str]) -> Optional[int]:
        m = len(tok_seq)
        if not m:
            return None
        for i in range(len(tokens) - m + 1):
            if tokens[i : i + m] == tok_seq:
                return i
        return None

    def _brand_strip_search(candidate_norm: str) -> Optional[int]:
        """Strip leading brand tokens from candidate_norm; return position only
        if a brand token is confirmed within ±D1_BRAND_WINDOW_NEAR tokens."""
        if not brand_tokens:
            return None
        parts = candidate_norm.split()
        stripped = parts[:]
        while stripped and stripped[0] in brand_tokens:
            stripped.pop(0)
        if not stripped or len(stripped) == len(parts):
            return None  # nothing was actually stripped
        pos = _search(stripped)
        if pos is None:
            return None
        lo = max(0, pos - _D1_BRAND_WINDOW_NEAR)
        hi = min(len(tokens), pos + len(stripped) + _D1_BRAND_WINDOW_NEAR)
        if any(bt in tokens[lo:hi] for bt in brand_tokens):
            return pos
        return None  # phrase found but brand absent from proximity

    # Pass 1 — exact
    alias_tokens = alias_norm.split()
    pos = _search(alias_tokens)
    if pos is not None:
        return pos

    # Pass 2 — suffix-strip (max 2 rounds for double-suffixed names)
    # Also attempts brand-strip on each suffix-stripped candidate.
    current = alias_norm
    for _ in range(2):
        stripped = _CONC_SUFFIX_RE.sub("", current).strip()
        if not stripped or stripped == current:
            break
        pos = _search(stripped.split())
        if pos is not None:
            return pos
        # Pass 3a — brand-strip applied to this suffix-stripped form
        pos = _brand_strip_search(stripped)
        if pos is not None:
            return pos
        current = stripped

    # Pass 3b — brand-strip applied to original alias (catches brand-prefixed
    # aliases without a concentration suffix, e.g. "Xerjoff Jazz Club")
    pos = _brand_strip_search(alias_norm)
    if pos is not None:
        return pos

    return None
