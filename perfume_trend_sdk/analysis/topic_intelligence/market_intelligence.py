"""Phase I8 — Market Intelligence Layer.

Generates actionable decision intelligence from semantic profiles (I7):
  - narrative: plain-language reason why an entity is trending
  - opportunities: rule-based market flags
  - competitors: detected competing entities (from comparison query analysis)

No AI. Template-based narrative + deterministic rule evaluation.
This layer reads I7 output and produces DECISION-READY signals.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

class MarketIntelligence(NamedTuple):
    narrative: str
    opportunities: list[str]
    competitors: list[str]


# ---------------------------------------------------------------------------
# Vocabulary constants
# ---------------------------------------------------------------------------

# Intent labels that strongly signal purchase / discovery intent
_HIGH_INTENT_LABELS: frozenset[str] = frozenset({
    "review",
    "blind buy",
    "gift idea",
    "ranking / best of",
    "comparison",
    "sample / decant",
    "new release",
})

# Scent notes used for narrative context
_SCENT_NOTES: frozenset[str] = frozenset({
    "vanilla", "oud", "fresh / citrus", "floral", "woody", "musk",
    "sweet / gourmand", "spicy", "smoky / leather", "green / earthy",
})

# Market tier labels used for narrative context
_MARKET_TIER: frozenset[str] = frozenset({
    "niche fragrance", "designer fragrance", "luxury",
})

_GENDER_LABELS: dict[str, str] = {
    "men's fragrance": "men's market",
    "women's fragrance": "women's market",
    "unisex": "unisex appeal",
}

# VS pattern: "product A vs product B"
_VS_AFTER = re.compile(r"\bvs\.?\s+(.+)", re.IGNORECASE)
_VS_BEFORE = re.compile(r"^(.+?)\s+vs\.?\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Opportunity flag rules
# ---------------------------------------------------------------------------

def _build_opportunity_flags(
    differentiators: list[str],
    positioning: list[str],
    intents: list[str],
    trend_state: Optional[str] = None,
) -> list[str]:
    """Evaluate rule-based opportunity flags.

    Each flag represents an actionable market signal:
      dupe_market          — alternative/clone positioning with active demand
      affordable_alt       — price-value positioning
      high_intent          — multiple discovery/purchase signals active
      competitive_comparison — comparison queries are driving attention
      gifting              — gift-buying demand detected
      viral_momentum       — trending/viral signal (growth opportunity or peak risk)
      launch_window        — new release / flanker activity
      social_validation    — compliment-getter reputation driving word of mouth
      performance_leader   — longevity/projection differentiator standing out
    """
    flags: list[str] = []
    diff_set = frozenset(d.lower() for d in differentiators)
    intent_set = frozenset(i.lower() for i in intents)

    if "dupe / alternative" in diff_set:
        flags.append("dupe_market")

    if "affordable" in diff_set:
        flags.append("affordable_alt")

    # High intent = multiple buy/discovery signals active
    intent_label_hits = sum(1 for i in intent_set if i in _HIGH_INTENT_LABELS)
    query_count = sum(1 for i in intents if i not in _HIGH_INTENT_LABELS)
    if intent_label_hits >= 2 or (intent_label_hits >= 1 and query_count >= 2):
        flags.append("high_intent")

    if "comparison" in intent_set:
        flags.append("competitive_comparison")

    if "gift idea" in intent_set:
        flags.append("gifting")

    if "trending / viral" in intent_set:
        flags.append("viral_momentum")

    if "new release" in intent_set or "flanker" in intent_set:
        flags.append("launch_window")

    if "compliment getter" in diff_set:
        flags.append("social_validation")

    if "longevity / projection" in diff_set:
        flags.append("performance_leader")

    return flags


# ---------------------------------------------------------------------------
# Narrative generation
# ---------------------------------------------------------------------------

def _build_narrative(
    canonical_name: str,
    differentiators: list[str],
    positioning: list[str],
    intents: list[str],
    opportunities: list[str],
    competitors: list[str],
) -> str:
    """Build a plain-language narrative explaining why an entity is trending.

    Uses template clauses — no AI. Output is deterministic given the same inputs.
    """
    diff_set = frozenset(d.lower() for d in differentiators)
    intent_set = frozenset(i.lower() for i in intents)

    # Collect reason clauses (most impactful first)
    reasons: list[str] = []

    if "comparison" in intent_set:
        if competitors:
            reasons.append(f"strong comparison activity against {competitors[0]}")
        else:
            reasons.append("strong comparison activity")

    if "dupe / alternative" in diff_set:
        reasons.append("alternative / dupe positioning")

    if "compliment getter" in diff_set:
        reasons.append("compliment-getting reputation")

    if "longevity / projection" in diff_set:
        reasons.append("performance standout status")

    if "review" in intent_set:
        reasons.append("active review coverage")

    if "trending / viral" in intent_set:
        reasons.append("viral momentum")

    if "gift idea" in intent_set:
        reasons.append("gifting demand")

    if "new release" in intent_set or "launch_window" in frozenset(opportunities):
        reasons.append("new launch activity")

    # Context qualifiers from positioning
    tier = next((t for t in positioning if t.lower() in _MARKET_TIER), None)
    note = next((n for n in positioning if n.lower() in _SCENT_NOTES), None)
    gender_key = next((g.lower() for g in positioning if g.lower() in _GENDER_LABELS), None)
    gender_phrase = _GENDER_LABELS.get(gender_key, "") if gender_key else ""

    # No reasons found — generic fallback
    if not reasons:
        if tier:
            return f"{canonical_name} is gaining attention in the {tier} space."
        if note:
            return f"{canonical_name} is gaining attention for its {note} character."
        return f"{canonical_name} is showing increased market activity."

    # Build base sentence
    if len(reasons) == 1:
        base = f"{canonical_name} is trending due to {reasons[0]}"
    elif len(reasons) == 2:
        base = f"{canonical_name} is trending due to {reasons[0]} and {reasons[1]}"
    else:
        base = (
            f"{canonical_name} is trending due to "
            f"{', '.join(reasons[:2])}, and {reasons[2]}"
        )

    # Append context qualifier
    if tier and note:
        return f"{base}, driven by {note} appeal in the {tier} space."
    elif tier:
        return f"{base}, with strong {tier} positioning."
    elif note:
        return f"{base}, with prominent {note} character."
    elif gender_phrase:
        return f"{base}, targeting the {gender_phrase}."
    else:
        return f"{base}."


# ---------------------------------------------------------------------------
# Competitor extraction from queries
# ---------------------------------------------------------------------------

def extract_vs_competitors(
    raw_queries: list[str],
    canonical_name: str,
) -> list[str]:
    """Extract likely competitor names from comparison queries.

    Handles two cases:
      1. VS pattern: "Creed Aventus vs Baccarat Rouge 540" → "Baccarat Rouge 540"
      2. Orphan query: query that doesn't mention the current entity at all
         → entire query as a candidate competitor name

    Returns raw candidate strings — caller is responsible for DB validation.
    """
    candidates: list[str] = []
    own_lower = canonical_name.lower()

    for q in raw_queries:
        q_stripped = q.strip()
        q_lower = q_stripped.lower()

        # VS pattern takes priority
        m_after = _VS_AFTER.search(q_stripped)
        if m_after:
            candidate = m_after.group(1).strip()
            if candidate.lower() != own_lower and len(candidate) > 3:
                candidates.append(candidate)
            continue

        m_before = _VS_BEFORE.match(q_stripped)
        if m_before:
            candidate = m_before.group(1).strip()
            if candidate.lower() != own_lower and len(candidate) > 3:
                candidates.append(candidate)
            continue

        # Orphan query: doesn't reference current entity → may be a competitor query
        if own_lower not in q_lower and len(q_stripped) > 5:
            candidates.append(q_stripped)

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c.lower() not in seen:
            seen.add(c.lower())
            result.append(c)
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_market_intelligence(
    canonical_name: str,
    differentiators: list[str],
    positioning: list[str],
    intents: list[str],
    raw_queries: list[str],
    resolved_competitors: list[str],
    trend_state: Optional[str] = None,
) -> MarketIntelligence:
    """Generate full market intelligence for an entity.

    Args:
        canonical_name:       entity canonical name
        differentiators:      from I7 SemanticProfile.differentiators
        positioning:          from I7 SemanticProfile.positioning
        intents:              from I7 SemanticProfile.intents
        raw_queries:          raw query strings from entity_topic_links (top_queries)
        resolved_competitors: competitor canonical names resolved from DB
        trend_state:          I3 trend state: breakout|rising|peak|declining|stable|emerging|None
    """
    opportunities = _build_opportunity_flags(
        differentiators, positioning, intents, trend_state
    )
    narrative = _build_narrative(
        canonical_name,
        differentiators,
        positioning,
        intents,
        opportunities,
        resolved_competitors,
    )
    return MarketIntelligence(
        narrative=narrative,
        opportunities=opportunities,
        competitors=resolved_competitors,
    )
