from __future__ import annotations

from typing import Any, Dict, Optional


class SourceIntelligenceAnalyzer:
    def analyze(self, item: Dict[str, Any]) -> Dict[str, Any]:
        # Support both old flat format and new nested YouTubeConnector format
        snippet = item.get("search_item", {}).get("snippet", {})
        statistics = item.get("video_details", {}).get("statistics", {})

        channel_name = (
            snippet.get("channelTitle")
            or item.get("channel_title")
            or ""
        )

        view_count = self._int(
            statistics.get("viewCount")
            or item.get("view_count")
        )

        subscriber_count = self._int(statistics.get("subscriberCount"))

        influence_score = self._score_influence(view_count, subscriber_count)
        credibility_score = 0.8 if channel_name else 0.3
        source_type = self._classify_source(channel_name, view_count)

        return {
            "source_type": source_type,
            "channel_name": channel_name,
            "influence_score": influence_score,
            "credibility_score": credibility_score,
        }

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _score_influence(view_count: int, subscriber_count: int) -> float:
        # Use the stronger signal if both available
        score_from_views = 0.0
        if view_count > 500_000:
            score_from_views = 95.0
        elif view_count > 100_000:
            score_from_views = 80.0
        elif view_count > 10_000:
            score_from_views = 60.0
        elif view_count > 1_000:
            score_from_views = 35.0
        else:
            score_from_views = 10.0

        score_from_subs = 0.0
        if subscriber_count > 1_000_000:
            score_from_subs = 95.0
        elif subscriber_count > 100_000:
            score_from_subs = 75.0
        elif subscriber_count > 10_000:
            score_from_subs = 50.0
        elif subscriber_count > 0:
            score_from_subs = 25.0

        return max(score_from_views, score_from_subs)

    @staticmethod
    def _classify_source(channel_name: str, view_count: int) -> str:
        if not channel_name:
            return "user"
        name_lower = channel_name.lower()
        if any(kw in name_lower for kw in ("official", "brand", "store", "shop", "beauty")):
            return "brand"
        if view_count > 10_000:
            return "influencer"
        return "user"


def classify_source(content_item: Any) -> str:
    """
    Classify source from a normalized content item dict or object.
    Used by the new ingest_youtube_to_signals pipeline.
    """
    media_metadata = (
        content_item.get("media_metadata", {})
        if isinstance(content_item, dict)
        else getattr(content_item, "media_metadata", {})
    )
    engagement = (
        content_item.get("engagement", {})
        if isinstance(content_item, dict)
        else getattr(content_item, "engagement", {})
    )
    handle = (
        content_item.get("source_account_handle")
        if isinstance(content_item, dict)
        else getattr(content_item, "source_account_handle", None)
    )

    followers = media_metadata.get("followers", 0) if isinstance(media_metadata, dict) else 0
    views = (
        engagement.get("views", 0)
        if isinstance(engagement, dict)
        else getattr(engagement, "views", 0)
    ) or 0

    if followers > 500_000:
        return "influencer"

    if "official" in (handle or "").lower():
        return "brand"

    if views < 100:
        return "low"

    return "user"
