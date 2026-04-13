from __future__ import annotations

"""
Daily Market Aggregator — Market Engine v1

Reads from the existing NormalizedContentStore + SignalStore (new pipeline)
and computes per-entity daily metrics for the market engine.

Extends the pipeline — does NOT modify canonical_content_items or
resolved_signals tables.
"""

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Scoring constants
MENTION_CEILING = 10.0           # mention_count cap for normalization
ENGAGEMENT_CEILING = 500_000.0   # engagement_sum cap for normalization
MAX_SOURCE_DIVERSITY = 3         # YouTube + TikTok + Reddit = 3

# TikTok play counts are 10-100× higher than YouTube view counts for comparable
# reach. TIKTOK_VIEW_CAP clips raw playCount before it enters engagement_sum so
# a single viral TikTok short cannot drown out multiple YouTube videos.
# Set equal to ENGAGEMENT_CEILING: one item can never exceed the ceiling alone.
TIKTOK_VIEW_CAP = 500_000.0

# Source platform weights — applied to mention count contribution.
# YouTube carries stronger editorial/creator weight than unverified feeds.
# Reddit is a first-class real source in v1 (public JSON ingestion, weight 1.0).
# TikTok weight is reserved for when Research API credentials are approved.
_PLATFORM_WEIGHTS: Dict[str, float] = {
    "youtube": 1.2,
    "tiktok": 1.3,   # reserved — deferred until Research API approval
    "reddit": 1.0,   # active — public JSON ingestion
    "other": 0.8,    # catch-all for truly uncategorized / legacy synthetic data
}

_PLATFORM_LABEL = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "reddit": "Reddit",
    "other": "Other",  # no longer maps to Reddit — Reddit uses its own key
}

_STOP_WORDS = frozenset({
    "de", "du", "la", "le", "les", "by", "of", "the", "a", "an",
    "and", "et", "maison", "parfums", "parfum", "eau",
})


def generate_ticker(canonical_name: str) -> str:
    """Generate a short uppercase ticker symbol from a canonical entity name."""
    words = canonical_name.split()
    digits = re.findall(r"\d+", canonical_name)
    digit_str = digits[0] if digits else ""

    sig = [w for w in words if w.lower() not in _STOP_WORDS and not re.fullmatch(r"\d+", w)]
    if not sig:
        sig = [w for w in words if not re.fullmatch(r"\d+", w)] or words

    if len(sig) == 1:
        base = sig[0][:5].upper()
    elif len(sig) == 2:
        base = (sig[0][:2] + sig[1][:3]).upper()
    else:
        base = "".join(w[0] for w in sig[:6]).upper()

    if digit_str:
        result = base[:4] + digit_str
    else:
        result = base[:6]

    return result[:8]


def _parse_json(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def _normalize_views(views: float, platform: str) -> float:
    """Clip TikTok play counts to prevent inflating engagement_sum.

    TikTok playCount is typically 10–100× higher than YouTube viewCount for
    comparable reach. Without normalization a single viral TikTok short
    dominates engagement_sum and distorts composite_market_score.

    Strategy: min(views, TIKTOK_VIEW_CAP) — hard cap at 500 K plays.
    YouTube, Reddit, and unknown platforms: raw views, unchanged.
    """
    if platform == "tiktok":
        return min(float(views), TIKTOK_VIEW_CAP)
    return float(views)


def _engagement_total(engagement: Dict[str, Any], platform: str = "other") -> float:
    views = _normalize_views(float(engagement.get("views") or 0), platform)
    likes = engagement.get("likes") or 0
    comments = engagement.get("comments") or 0
    return views + float(likes) * 3 + float(comments) * 5


def _trend_score(influence_score: float, sentiment_mult: float, confidence: float) -> float:
    """Replicates existing TrendScorer weighting logic."""
    weight = (influence_score / 100.0) if influence_score else 1.0
    weight *= sentiment_mult
    weight *= confidence
    return weight


def _compute_composite(
    mention_count: float,
    engagement_sum: float,
    growth: float,
    source_diversity: int,
    momentum: float = 0.0,
) -> float:
    """Compute composite_market_score in [0, 100].

    Weights (v2 — momentum added):
      mention_count  35% (was 40%)
      engagement     25% (was 30%)
      growth         20% (unchanged)
      momentum       10% (new — acceleration affects ranking, not just signals)
      diversity      10% (unchanged)

    Momentum contribution caps at momentum=3.0 (3× yesterday's mentions).
    """
    mention_score = min(mention_count / MENTION_CEILING, 1.0)
    engagement_score = min(engagement_sum / ENGAGEMENT_CEILING, 1.0)
    # growth in [-1, 1] → normalize to [0, 1]
    growth_clamped = max(min(growth, 1.0), -1.0)
    growth_score = (growth_clamped + 1.0) / 2.0
    diversity_score = min(source_diversity / MAX_SOURCE_DIVERSITY, 1.0)
    # momentum capped at 3.0 (e.g. 3× mentions day-over-day = full score)
    momentum_score = min(max(momentum, 0.0) / 3.0, 1.0)

    composite = (
        mention_score * 0.35
        + engagement_score * 0.25
        + growth_score * 0.20
        + momentum_score * 0.10
        + diversity_score * 0.10
    )
    return round(composite * 100, 4)


class DailyAggregator:
    """Compute per-entity daily market metrics from pipeline storage data."""

    def aggregate_from_data(
        self,
        content_items: List[Dict[str, Any]],
        resolved_signals: List[Dict[str, Any]],
        target_date: str,
        prev_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Build daily snapshots for all entities found in the data.

        Args:
            content_items:     From NormalizedContentStore.list_content_items_full().
            resolved_signals:  From SignalStore.list_resolved_signals().
            target_date:       ISO date string (YYYY-MM-DD) to aggregate for.
            prev_snapshots:    Map entity_id → previous snapshot (for momentum/accel).

        Returns:
            List of snapshot dicts ready for MarketStore.upsert_daily_snapshot().
        """
        prev_snapshots = prev_snapshots or {}

        # Index content items by id
        items_by_id: Dict[str, Dict[str, Any]] = {}
        for item in content_items:
            published = (item.get("published_at") or "")[:10]
            if published == target_date:
                items_by_id[item["id"]] = item

        # Per-entity accumulators
        entity_data: Dict[str, Dict[str, Any]] = {}

        for sig in resolved_signals:
            cid = sig["content_item_id"]
            item = items_by_id.get(cid)
            if item is None:
                continue

            entities = _parse_json(sig.get("resolved_entities_json"), [])
            if not entities:
                continue

            platform = item.get("source_platform") or "other"
            engagement = _parse_json(item.get("engagement_json"), {})
            meta = _parse_json(item.get("media_metadata_json"), {})
            eng_total = _engagement_total(engagement, platform)
            influence = float(meta.get("influence_score") or 0)
            author = item.get("source_account_handle") or ""

            for ent in entities:
                if ent.get("entity_type") != "perfume":
                    continue
                canonical = ent.get("canonical_name", "")
                if not canonical:
                    continue

                eid = canonical  # use canonical_name as stable entity_id

                if eid not in entity_data:
                    entity_data[eid] = {
                        "canonical_name": canonical,
                        "mention_count": 0.0,
                        "unique_authors": set(),
                        "engagement_sum": 0.0,
                        "trend_score": 0.0,
                        "confidence_sum": 0.0,
                        "confidence_count": 0,
                        "platforms": set(),
                        "content_item_ids": set(),
                    }

                d = entity_data[eid]
                # Only count each content item once per entity
                if cid in d["content_item_ids"]:
                    continue
                d["content_item_ids"].add(cid)
                # Apply source platform weight to mention count
                platform_weight = _PLATFORM_WEIGHTS.get(platform, 1.0)
                d["mention_count"] += platform_weight
                d["unique_authors"].add(author)
                d["engagement_sum"] += eng_total
                d["platforms"].add(platform)
                confidence = float(ent.get("confidence") or 1.0)
                d["trend_score"] += _trend_score(influence, 1.0, confidence)
                d["confidence_sum"] += confidence
                d["confidence_count"] += 1

        # Build snapshot dicts
        snapshots: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for eid, d in entity_data.items():
            mention_count = d["mention_count"]
            engagement_sum = d["engagement_sum"]
            source_diversity = len(d["platforms"])
            unique_authors = len(d["unique_authors"])
            trend_score = round(d["trend_score"], 4)
            confidence_avg = (
                round(d["confidence_sum"] / d["confidence_count"], 4)
                if d["confidence_count"] > 0
                else None
            )

            prev = prev_snapshots.get(eid)
            prev_count = float(prev["mention_count"]) if prev else 0.0
            prev_momentum = float(prev["momentum"]) if prev else 0.0

            # Growth
            if prev_count > 0:
                growth = (mention_count - prev_count) / prev_count
            elif mention_count > 0:
                growth = 1.0
            else:
                growth = 0.0

            # Momentum = today's mentions / max(yesterday's, 1)
            momentum = round(mention_count / max(prev_count, 1.0), 4)
            acceleration = round(momentum - prev_momentum, 4)
            volatility = round(abs(acceleration), 4)

            composite = _compute_composite(
                mention_count, engagement_sum, growth, source_diversity,
                momentum=momentum,
            )

            snapshots.append({
                "entity_id": eid,          # string canonical name; job converts to UUID
                "entity_type": "perfume",
                "date": target_date,
                "mention_count": mention_count,
                "unique_authors": unique_authors,
                "engagement_sum": round(engagement_sum, 2),
                "sentiment_avg": None,
                "confidence_avg": confidence_avg,
                "search_index": None,
                "retailer_score": None,
                "growth_rate": round(growth, 4),
                "composite_market_score": composite,
                "momentum": momentum,
                "acceleration": acceleration,
                "volatility": volatility,
            })

        return snapshots

    def build_entity_records(
        self, snapshots: List[Dict[str, Any]], created_at: str
    ) -> List[Dict[str, Any]]:
        """Build entity_market records from aggregated snapshots."""
        records = []
        for snap in snapshots:
            name = snap["entity_id"]  # canonical_name IS the entity_id
            records.append({
                "entity_id": name,
                "entity_type": "perfume",
                "ticker": generate_ticker(name),
                "canonical_name": name,
                "created_at": created_at,
            })
        return records
