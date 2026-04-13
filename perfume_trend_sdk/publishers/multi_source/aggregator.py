from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# Platform labels used throughout the report
CREATOR_PLATFORMS = {"youtube", "tiktok"}
COMMUNITY_PLATFORMS = {"reddit"}  # Reddit is a first-class real platform in v1
_PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "reddit": "Reddit",
    "other": "Other",  # catch-all for truly uncategorized sources
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def aggregate_cross_source(
    content_items: List[Dict[str, Any]],
    resolved_signals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate resolved signals and content items across all sources.

    Args:
        content_items: Rows from NormalizedContentStore.list_content_items_full().
        resolved_signals: Rows from SignalStore.list_resolved_signals().

    Returns:
        {
            perfumes: {canonical_name: PerfumeAgg},
            source_breakdown: {platform_label: SourceAgg},
            creator_community: CreatorCommunityAgg,
        }

    PerfumeAgg:
        total_mentions, by_source {platform_label: count},
        weighted_score, top_sources [label, ...]

    SourceAgg:
        item_count, mention_count

    CreatorCommunityAgg:
        creator_mentions, community_mentions, mixed_signals [canonical_name, ...]
    """
    content_map = {item["id"]: item for item in content_items}

    # ── per-perfume accumulator ──────────────────────────────────────────────
    perfumes: Dict[str, Dict[str, Any]] = {}

    # ── per-platform accumulator ─────────────────────────────────────────────
    platform_items: Dict[str, int] = {}     # label → item count
    platform_mentions: Dict[str, int] = {}  # label → perfume-mention count

    # ── creator / community signal accumulators ──────────────────────────────
    creator_mentions = 0
    community_mentions = 0
    mixed_perfumes: set = set()

    for signal in resolved_signals:
        item_id = signal.get("content_item_id", "")
        item = content_map.get(item_id, {})

        platform_raw = item.get("source_platform", "other")
        label = _PLATFORM_LABELS.get(platform_raw, platform_raw)

        platform_items[label] = platform_items.get(label, 0) + 1

        engagement = _parse_json(item.get("engagement_json", "{}"))
        meta = _parse_json(item.get("media_metadata_json", "{}"))
        source_type = meta.get("source_type", "")
        influence = _float(meta.get("influence_score", 1.0))

        views = _int(engagement.get("views", 0))
        likes = _int(engagement.get("likes", 0))
        item_engagement_weight = (views * 0.6 + likes * 0.4) / 1_000_000

        try:
            entities = json.loads(signal.get("resolved_entities_json") or "[]")
        except (ValueError, TypeError):
            entities = []

        perfume_entities = [
            e for e in entities
            if e.get("entity_type") == "perfume" and e.get("canonical_name")
        ]

        platform_mentions[label] = platform_mentions.get(label, 0) + len(perfume_entities)

        is_community = platform_raw in COMMUNITY_PLATFORMS or source_type == "community"
        is_creator = platform_raw in CREATOR_PLATFORMS

        for entity in perfume_entities:
            name = entity["canonical_name"]

            if name not in perfumes:
                perfumes[name] = {
                    "total_mentions": 0,
                    "by_source": {},
                    "weighted_score": 0.0,
                    "seen_as_creator": False,
                    "seen_as_community": False,
                }

            agg = perfumes[name]
            agg["total_mentions"] += 1
            agg["by_source"][label] = agg["by_source"].get(label, 0) + 1
            agg["weighted_score"] += influence + item_engagement_weight

            if is_community:
                agg["seen_as_community"] = True
                community_mentions += 1
            if is_creator:
                agg["seen_as_creator"] = True
                creator_mentions += 1
            if agg["seen_as_creator"] and agg["seen_as_community"]:
                mixed_perfumes.add(name)

    # Compute top_sources per perfume (sorted by count desc)
    for agg in perfumes.values():
        agg["top_sources"] = [
            lbl for lbl, _ in sorted(
                agg["by_source"].items(), key=lambda x: x[1], reverse=True
            )
        ]
        agg["weighted_score"] = round(agg["weighted_score"], 4)

    # Build source_breakdown
    all_labels = set(platform_items) | set(platform_mentions)
    source_breakdown = {
        lbl: {
            "item_count": platform_items.get(lbl, 0),
            "mention_count": platform_mentions.get(lbl, 0),
        }
        for lbl in all_labels
    }

    return {
        "perfumes": perfumes,
        "source_breakdown": source_breakdown,
        "creator_community": {
            "creator_mentions": creator_mentions,
            "community_mentions": community_mentions,
            "mixed_signals": sorted(mixed_perfumes),
        },
    }


def classify_signal_type(creator_mentions: int, community_mentions: int) -> str:
    """Classify the overall market signal as creator-led, community-led, or mixed.

    Returns: "creator-led", "community-led", or "mixed"
    """
    total = creator_mentions + community_mentions
    if total == 0:
        return "mixed"
    creator_ratio = creator_mentions / total
    if creator_ratio >= 0.75:
        return "creator-led"
    if creator_ratio <= 0.25:
        return "community-led"
    return "mixed"


def rank_perfumes(
    perfumes: Dict[str, Dict[str, Any]],
    *,
    previous_scores: Optional[Dict[str, float]] = None,
    n: int = 20,
) -> List[Dict[str, Any]]:
    """Return top-N perfumes sorted by total_mentions descending.

    Each row:
        rank, name, total_mentions, weighted_score, by_source, top_sources, direction
    """
    sorted_items = sorted(
        perfumes.items(),
        key=lambda x: (x[1]["total_mentions"], x[1]["weighted_score"]),
        reverse=True,
    )[:n]

    results = []
    for rank, (name, agg) in enumerate(sorted_items, 1):
        prev = (previous_scores or {}).get(name)
        if prev is None:
            direction = "new"
        elif agg["total_mentions"] > prev:
            direction = "up"
        elif agg["total_mentions"] < prev:
            direction = "down"
        else:
            direction = "flat"

        results.append(
            {
                "rank": rank,
                "name": name,
                "total_mentions": agg["total_mentions"],
                "weighted_score": agg["weighted_score"],
                "by_source": agg["by_source"],
                "top_sources": agg["top_sources"],
                "direction": direction,
            }
        )
    return results


def build_opportunity_risk(
    ranked_perfumes: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Classify perfumes into opportunities, risks, and declining based on signal.

    Rules (deterministic, no LLM):
        opportunity  — direction up or new, mentions >= 2
        risk         — total_mentions >= 5 (potential oversaturation)
        declining    — direction down
    """
    opportunities: List[str] = []
    risks: List[str] = []
    declining: List[str] = []

    for row in ranked_perfumes:
        name = row["name"]
        direction = row["direction"]
        mentions = row["total_mentions"]

        if direction in ("up", "new") and mentions >= 2:
            opportunities.append(name)
        if mentions >= 5:
            risks.append(name)
        if direction == "down":
            declining.append(name)

    return {
        "opportunities": opportunities[:5],
        "risks": risks[:5],
        "declining": declining[:5],
    }


def build_executive_summary(
    ranked_perfumes: List[Dict[str, Any]],
    note_results: List[Dict[str, Any]],
    signal_type: str,
    source_breakdown: Dict[str, Any],
    window_label: str = "this period",
) -> str:
    """Build a concise executive summary string — deterministic, no LLM.

    Args:
        ranked_perfumes: Output of rank_perfumes().
        note_results: Output of build_note_results() from NoteMomentumScorer.
        signal_type: "creator-led", "community-led", or "mixed".
        source_breakdown: Per-platform item and mention counts.
        window_label: Human-readable period label e.g. "past 7 days".
    """
    total_perfumes = len(ranked_perfumes)
    total_sources = len([s for s in source_breakdown if source_breakdown[s]["item_count"] > 0])
    top_perfume = ranked_perfumes[0]["name"] if ranked_perfumes else "—"
    top_mentions = ranked_perfumes[0]["total_mentions"] if ranked_perfumes else 0

    rising_notes = [r["note"].title() for r in note_results if r["direction"] == "up"][:3]
    note_str = ", ".join(rising_notes) if rising_notes else "no clear note trend"

    source_names = sorted(
        [lbl for lbl, data in source_breakdown.items() if data["item_count"] > 0]
    )
    source_str = " + ".join(source_names) if source_names else "unknown sources"

    return (
        f"**{total_perfumes} perfumes** tracked across {total_sources} source(s) "
        f"({source_str}) {window_label}. "
        f"Top performer: **{top_perfume}** with {top_mentions} mention(s). "
        f"Signal is **{signal_type}**. "
        f"Rising notes: {note_str}."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
