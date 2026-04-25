"""Phase I7 — Semantic Topic Intelligence.

Transforms raw entity_topic_links rows into structured semantic profiles:
  - Differentiators: what makes the perfume unique / stand out
  - Positioning:     what the perfume *is* (notes, gender, season, market tier)
  - Intent:          why people search for it (queries + search-intent topic labels)

No AI. Pure deterministic classification against defined vocabulary sets.
The existing topic extraction pipeline (I5/I6) is unchanged — this is a
read-only transformation layer on top of entity_topic_links.
"""
from __future__ import annotations

from typing import NamedTuple

# ---------------------------------------------------------------------------
# Vocabulary sets
# ---------------------------------------------------------------------------

# Topics excluded from Differentiators and Positioning — shown in Intent only
# (or omitted from the primary semantic view entirely, as they are too generic).
STOPLIST: frozenset[str] = frozenset({
    "review",
    "comparison",
    "trending / viral",
    "ranking / best of",
})

# What makes the perfume stand out — unique value / differentiation signals.
DIFFERENTIATOR_TOPICS: frozenset[str] = frozenset({
    "dupe / alternative",
    "compliment getter",
    "longevity / projection",
    "reformulation",
    "affordable",
    "blind buy",
})

# Identity tags — what the perfume IS.
POSITIONING_TOPICS: frozenset[str] = frozenset({
    # Market tier
    "niche fragrance",
    "designer fragrance",
    "luxury",
    # Scent character
    "vanilla",
    "oud",
    "fresh / citrus",
    "floral",
    "woody",
    "musk",
    "sweet / gourmand",
    "spicy",
    "smoky / leather",
    "green / earthy",
    # Gender / audience
    "men's fragrance",
    "women's fragrance",
    "unisex",
    # Season
    "summer",
    "winter",
    "fall / autumn",
    "spring",
    # Geographic origin
    "arab / oriental",
    "french fragrance",
    "italian fragrance",
    # Usage context
    "office scent",
    "date night",
    "signature scent",
    "gym / sport",
    "beach / vacation",
})

# Topic labels (not raw queries) that signal search intent.
INTENT_TOPIC_LABELS: frozenset[str] = frozenset({
    "review",
    "ranking / best of",
    "comparison",
    "gift idea",
    "trending / viral",
    "new release",
    "flanker",
    "sample / decant",
    "blind buy",
})


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

class SemanticProfile(NamedTuple):
    differentiators: list[str]
    positioning: list[str]
    intents: list[str]


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def classify_entity_topics(
    rows: list[tuple[str, str, int, float]],
    max_per_category: int = 5,
) -> SemanticProfile:
    """Classify entity_topic_links rows into a semantic profile.

    Args:
        rows: list of (topic_type, topic_text, occ, avg_quality_score)
              where topic_type is one of 'topic' | 'query' | 'subreddit'.
        max_per_category: max items per output category.

    Scoring formula (per row):
        score = occ * (1.0 + avg_quality_score)

    Classification rules:
        topic_type=='query'    → intent (all raw search queries)
        topic_type=='topic':
            text in DIFFERENTIATOR_TOPICS → differentiators
            text in POSITIONING_TOPICS   → positioning
            text in INTENT_TOPIC_LABELS  → intent (label-only, no duplicates)
            else                         → skipped (unmapped)
        topic_type=='subreddit' → not classified here; handled separately in API

    Returns:
        SemanticProfile(differentiators, positioning, intents)
    """
    diff_scored: list[tuple[float, str]] = []
    pos_scored: list[tuple[float, str]] = []
    intent_scored: list[tuple[float, str]] = []
    seen_intent: set[str] = set()

    for topic_type, topic_text, occ, avg_score in rows:
        score = float(occ) * (1.0 + float(avg_score or 0.0))
        text_key = topic_text.lower().strip()

        if topic_type == "query":
            if text_key not in seen_intent:
                intent_scored.append((score, topic_text))
                seen_intent.add(text_key)

        elif topic_type == "topic":
            if text_key in DIFFERENTIATOR_TOPICS:
                diff_scored.append((score, topic_text))
            elif text_key in POSITIONING_TOPICS:
                pos_scored.append((score, topic_text))
            elif text_key in INTENT_TOPIC_LABELS:
                if text_key not in seen_intent:
                    intent_scored.append((score, topic_text))
                    seen_intent.add(text_key)
            # else: unmapped — skip

        # subreddit rows: not placed in semantic sections

    def _top(items: list[tuple[float, str]], n: int) -> list[str]:
        return [t for _, t in sorted(items, key=lambda x: -x[0])[:n]]

    return SemanticProfile(
        differentiators=_top(diff_scored, max_per_category),
        positioning=_top(pos_scored, max_per_category),
        intents=_top(intent_scored, max_per_category),
    )
