from __future__ import annotations

from typing import Any, Dict, Union


def compute_influence(content_item: Any) -> float:
    """
    Raw engagement-based influence score from a content item.
    Works with both dict and object formats.
    """
    engagement = (
        content_item.get("engagement", {})
        if isinstance(content_item, dict)
        else getattr(content_item, "engagement", {})
    )

    if isinstance(engagement, dict):
        views = engagement.get("views") or 0
        likes = engagement.get("likes") or 0
    else:
        views = getattr(engagement, "views", 0) or 0
        likes = getattr(engagement, "likes", 0) or 0

    return views * 0.6 + likes * 0.4


def score_influence(source_result: Dict[str, Any]) -> float:
    """
    Normalize influence_score to a 0.0–1.0 multiplier
    for use in trend scoring.
    """
    raw = source_result.get("influence_score", 0.0) or 0.0
    return min(raw / 100.0, 1.0)


def score_credibility(source_result: Dict[str, Any]) -> float:
    """
    Return credibility_score as-is (already 0.0–1.0).
    """
    return float(source_result.get("credibility_score", 0.5) or 0.5)


def compute_source_weight(source_result: Dict[str, Any]) -> float:
    """
    Combined weight for a single source signal.

    Formula:
        weight = influence * credibility

    Range: 0.0 – 1.0
    Default (no source data): 0.5
    """
    if not source_result:
        return 0.5

    influence = score_influence(source_result)
    credibility = score_credibility(source_result)

    return round(influence * credibility, 4)


def apply_source_weight(
    base_score: float,
    source_result: Dict[str, Any],
) -> float:
    """
    Multiply a base trend score by the source weight.
    Minimum output is capped at base_score * 0.1
    so low-influence sources are dampened but not zeroed.
    """
    weight = compute_source_weight(source_result)
    weighted = base_score * weight
    floor = base_score * 0.1
    return max(weighted, floor)
