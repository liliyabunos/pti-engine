from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from perfume_trend_sdk.connectors.tiktok_watchlist.parser import TikTokParser
from perfume_trend_sdk.connectors.reddit_watchlist.parser import RedditParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Country → normalized region bucket mapping
# Phase 043 — Content Language & Region Propagation v1
# Used as fallback when source_region is not set on a youtube_channels row.
# Countries not in this map resolve to "UNKNOWN".
# ---------------------------------------------------------------------------
_COUNTRY_TO_REGION: dict[str, str] = {
    # US / Canada
    "US": "US_CANADA", "CA": "US_CANADA",
    # UK / Ireland
    "GB": "UK_IRELAND", "IE": "UK_IRELAND",
    # EU DACH
    "DE": "EU_DACH", "AT": "EU_DACH", "CH": "EU_DACH",
    # EU Francophone
    "FR": "EU_FRANCOPHONE", "BE": "EU_FRANCOPHONE", "LU": "EU_FRANCOPHONE",
    # EU South
    "IT": "EU_SOUTH", "ES": "EU_SOUTH", "PT": "EU_SOUTH",
    "GR": "EU_SOUTH", "HR": "EU_SOUTH", "RO": "EU_SOUTH",
    # LATAM (non-Brazil)
    "MX": "LATAM", "AR": "LATAM", "CO": "LATAM", "CL": "LATAM",
    "PE": "LATAM", "VE": "LATAM", "EC": "LATAM", "BO": "LATAM",
    "PY": "LATAM", "UY": "LATAM",
    # Brazil (own bucket)
    "BR": "BRAZIL",
    # Middle East / GCC
    "AE": "MIDDLE_EAST_GCC", "SA": "MIDDLE_EAST_GCC", "KW": "MIDDLE_EAST_GCC",
    "QA": "MIDDLE_EAST_GCC", "BH": "MIDDLE_EAST_GCC", "OM": "MIDDLE_EAST_GCC",
    "EG": "MIDDLE_EAST_GCC", "JO": "MIDDLE_EAST_GCC", "LB": "MIDDLE_EAST_GCC",
    "IQ": "MIDDLE_EAST_GCC", "YE": "MIDDLE_EAST_GCC",
    # South Asia
    "IN": "SOUTH_ASIA", "PK": "SOUTH_ASIA", "BD": "SOUTH_ASIA",
    "LK": "SOUTH_ASIA", "NP": "SOUTH_ASIA",
    # East Asia
    "JP": "EAST_ASIA", "KR": "EAST_ASIA", "CN": "EAST_ASIA",
    "TW": "EAST_ASIA", "HK": "EAST_ASIA",
    # Southeast Asia
    "ID": "SOUTHEAST_ASIA", "MY": "SOUTHEAST_ASIA", "SG": "SOUTHEAST_ASIA",
    "TH": "SOUTHEAST_ASIA", "PH": "SOUTHEAST_ASIA", "VN": "SOUTHEAST_ASIA",
    "MM": "SOUTHEAST_ASIA",
}


def _resolve_content_language(channel_context: dict[str, Any] | None) -> str | None:
    """Resolve content language from youtube_channels metadata.

    Returns:
        The channel language string if available.
        "UNKNOWN" if context was provided but no language was determinable.
        None if no context was provided (legacy / not attempted).

    Distinction matters:
        None  = not attempted (legacy rows, search-based ingestion)
        UNKNOWN = attempted but not determinable (channel_poll with no language set)
    """
    if channel_context is None:
        return None
    lang = channel_context.get("language")
    if lang and lang.strip():
        return lang.strip()
    return "UNKNOWN"


def _resolve_content_region(channel_context: dict[str, Any] | None) -> str:
    """Resolve content region from youtube_channels metadata using fallback chain.

    Fallback order:
        1. channel_context["source_region"] — explicitly set by operator (Phase 042 metadata)
        2. _COUNTRY_TO_REGION[channel_context["country"]] — derived from country code
        3. "UNKNOWN" — not determinable

    Returns "UNKNOWN" instead of "US" when context is absent or resolution fails.
    "US" must only appear when the channel is verifiably US-based.
    """
    if channel_context is None:
        return "UNKNOWN"
    # 1. Operator-set source_region (Phase 042)
    source_region = channel_context.get("source_region")
    if source_region and source_region.strip():
        return source_region.strip()
    # 2. Country → region map
    country = channel_context.get("country")
    if country and country.strip():
        mapped = _COUNTRY_TO_REGION.get(country.strip().upper())
        if mapped:
            return mapped
    return "UNKNOWN"


class SocialContentNormalizer:
    version = "1.0"

    def normalize_youtube_item(
        self,
        raw_item: dict[str, Any],
        *,
        raw_payload_ref: str,
        channel_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Normalize a raw YouTube item into the canonical content item schema.

        Args:
            raw_item:        Raw item dict from the YouTube connector.
            raw_payload_ref: Filesystem ref to the raw payload.
            channel_context: Optional dict with youtube_channels metadata for this item's
                             channel. Should contain: language, country, source_region.
                             When provided, language and region are derived from channel
                             metadata instead of defaulting to None / "UNKNOWN".
                             Pass None (default) for legacy / search-based ingestion paths
                             where channel metadata is not pre-loaded.
        """
        search_item = raw_item.get("search_item", {})
        snippet = search_item.get("snippet", {})
        video_details = raw_item.get("video_details", {})
        statistics = video_details.get("statistics", {})
        # video_details also receives part=snippet from fetch_video_stats —
        # use it as a fallback source for channel fields.
        vd_snippet = video_details.get("snippet", {})

        video_id: str = search_item.get("id", {}).get("videoId", "")
        source_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

        # --- Channel identity: search snippet → video_details snippet fallback ---
        channel_id: Optional[str] = (
            snippet.get("channelId") or vd_snippet.get("channelId") or None
        )
        channel_title: Optional[str] = (
            snippet.get("channelTitle") or vd_snippet.get("channelTitle") or None
        )

        if not channel_id or not channel_title:
            logger.warning(
                "youtube_normalizer_missing_channel video_id=%s "
                "channel_id=%s channel_title=%s — item will still be stored as youtube",
                video_id,
                channel_id,
                channel_title,
            )

        def _int(val: Any) -> int | None:
            try:
                return int(val)
            except (TypeError, ValueError):
                return None

        engagement = {
            "views": _int(statistics.get("viewCount")),
            "likes": _int(statistics.get("likeCount")),
            "comments": _int(statistics.get("commentCount")),
        }

        collected_at = raw_item.get("fetched_at") or datetime.now(timezone.utc).isoformat()

        # Thumbnails: prefer search snippet, fallback to video_details snippet
        thumbnails = snippet.get("thumbnails") or vd_snippet.get("thumbnails", {})

        media_metadata = {
            "thumbnails": thumbnails,
            "channel_title": channel_title,
            "channel_id": channel_id,
        }

        return {
            "id": video_id,
            "schema_version": "1.0",
            "source_platform": "youtube",
            "source_account_id": channel_id,        # real UC* ID when available
            "source_account_handle": channel_title,  # human-readable channel name
            "source_account_type": "creator",
            "source_url": source_url,
            "external_content_id": video_id,
            "published_at": snippet.get("publishedAt") or vd_snippet.get("publishedAt", ""),
            "collected_at": collected_at,
            "content_type": "video",
            "title": snippet.get("title") or vd_snippet.get("title"),
            "caption": None,
            "text_content": snippet.get("description") or vd_snippet.get("description"),
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": media_metadata,
            "engagement": engagement,
            "language": _resolve_content_language(channel_context),
            "region": _resolve_content_region(channel_context),
            "raw_payload_ref": raw_payload_ref,
            "normalizer_version": self.version,
            "query": raw_item.get("query"),
        }

    def normalize_tiktok_item(
        self,
        raw_item: Dict[str, Any],
        raw_payload_ref: str,
        *,
        tiktok_layer: int = 1,
        mention_weight_override: Optional[float] = None,
        referencing_source_id: Optional[str] = None,
        referencing_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Normalize a raw TikTok post dict into the canonical content item schema.

        Mirrors normalize_youtube_item() output structure exactly.
        Delegates field extraction to TikTokParser — no analytics here.

        text_content merges caption + expanded hashtags so the resolver sees
        both sources.  TikTok captions are short and entity names often appear
        only as hashtags (#delina, #pdm), so excluding them would silently drop
        resolvable mentions.

        Example:
            caption  = "My new signature scent 🌸"
            hashtags = ["delina", "pdm", "perfume"]
            text_content → "My new signature scent 🌸 delina pdm perfume"
        """
        parser = TikTokParser()
        parsed = parser.parse(raw_item)

        duration_seconds: int = parsed.get("duration_seconds") or 0
        content_type: str = "short" if duration_seconds <= 60 else "video"

        collected_at: str = datetime.now(timezone.utc).isoformat()

        engagement: Dict[str, Any] = {
            "views": parsed.get("views"),
            "likes": parsed.get("likes"),
            "comments": parsed.get("comments"),
            "shares": parsed.get("shares"),
        }

        caption: str = parsed.get("caption") or ""
        hashtags: List[str] = parsed.get("hashtags", [])
        # Expand hashtags as plain words and append to caption so the resolver
        # and extractor see "delina pdm" rather than requiring the full caption
        # to contain the entity name.
        hashtag_text: str = " ".join(hashtags)
        if caption and hashtag_text:
            text_content: Optional[str] = f"{caption} {hashtag_text}"
        elif hashtag_text:
            text_content = hashtag_text
        else:
            text_content = caption or None

        return {
            "id": parsed["external_content_id"],
            "schema_version": "1.0",
            "source_platform": "tiktok",
            "source_account_id": parsed.get("source_account_id"),
            "source_account_handle": parsed.get("source_account_handle"),
            "source_account_type": "creator",
            "source_url": parsed.get("source_url", ""),
            "external_content_id": parsed["external_content_id"],
            "published_at": parsed.get("published_at", ""),
            "collected_at": collected_at,
            "content_type": content_type,
            "title": None,
            "caption": None,
            "text_content": text_content,
            "hashtags": hashtags,
            "mentions_raw": [],
            "media_metadata": parsed.get("media_metadata", {}),
            "engagement": engagement,
            "language": None,
            "region": "US",
            "raw_payload_ref": raw_payload_ref,
            "normalizer_version": self.version,
            "query": None,
            # SC1.1 layer fields
            "tiktok_layer": tiktok_layer,
            "mention_weight_override": mention_weight_override,
            "referencing_source_id": referencing_source_id,
            "referencing_context": referencing_context,
        }

    def normalize_tiktok_derived_item(
        self,
        *,
        tiktok_url: str,
        referencing_source_id: str,
        referencing_context: str,
        collected_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a minimal TikTok content item derived from a URL found in another item.

        Derived items (mention_weight_override=0.0) are stored for resolver enrichment
        only — they do NOT contribute a mention_count in aggregation.

        The tiktok_url must be a full https://www.tiktok.com/@<handle>/video/<id> URL.
        The video id is used as the canonical item id; handle is used as account handle.

        Args:
            tiktok_url:           Full TikTok video URL.
            referencing_source_id: id of the parent canonical_content_item.
            referencing_context:   Short snippet (≤ 200 chars) from parent text.
            collected_at:          ISO 8601 string; defaults to now.

        Returns:
            Normalized content item dict ready for pg_store.save_content_items().
            Returns None if the URL cannot be parsed into a valid video id.
        """
        import re as _re
        if collected_at is None:
            collected_at = datetime.now(timezone.utc).isoformat()

        # Extract handle and video_id from URL
        # Handles: https://www.tiktok.com/@handle/video/123456789
        m = _re.search(
            r"tiktok\.com/@([^/?#]+)/video/(\d+)",
            tiktok_url,
            _re.IGNORECASE,
        )
        if not m:
            return None  # type: ignore[return-value]

        handle = m.group(1)
        video_id = m.group(2)
        source_url = f"https://www.tiktok.com/@{handle}/video/{video_id}"
        context_snippet = (referencing_context or "")[:200]

        return {
            "id": video_id,
            "schema_version": "1.0",
            "source_platform": "tiktok",
            "source_account_id": None,
            "source_account_handle": handle,
            "source_account_type": "creator",
            "source_url": source_url,
            "external_content_id": video_id,
            "published_at": "",
            "collected_at": collected_at,
            "content_type": "video",
            "title": None,
            "caption": None,
            "text_content": None,
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {},
            "engagement": {},
            "language": None,
            "region": "US",
            "raw_payload_ref": f"derived:{referencing_source_id}",
            "normalizer_version": self.version,
            "query": None,
            # SC1.1 layer fields — derived record
            "tiktok_layer": 1,
            "mention_weight_override": 0.0,
            "referencing_source_id": referencing_source_id,
            "referencing_context": context_snippet,
        }

    def normalize_reddit_item(
        self,
        raw_item: Dict[str, Any],
        raw_payload_ref: str,
    ) -> Dict[str, Any]:
        """Normalize a raw Reddit post dict into the canonical content item schema.

        text_content = title + " " + selftext so extractors see the full post.
        source_platform = "reddit" — Reddit is a first-class real source in v1.
        engagement.likes maps from Reddit score; engagement.comments from num_comments.
        Subreddit is preserved in media_metadata for source-level reporting.
        """
        parser = RedditParser()
        parsed = parser.parse(raw_item)

        title: str = parsed.get("title") or ""
        selftext: str = parsed.get("selftext") or ""
        text_content: str = (title + " " + selftext).strip() if selftext else title

        collected_at: str = datetime.now(timezone.utc).isoformat()

        engagement: Dict[str, Any] = {
            "views": None,
            "likes": parsed.get("score"),
            "comments": parsed.get("num_comments"),
            "shares": None,
        }

        return {
            "id": parsed["external_content_id"],
            "schema_version": "1.0",
            "source_platform": "reddit",
            "source_account_id": None,
            "source_account_handle": parsed.get("source_account_handle"),
            "source_account_type": "creator",
            "source_url": parsed.get("source_url", ""),
            "external_content_id": parsed["external_content_id"],
            "published_at": parsed.get("published_at", ""),
            "collected_at": collected_at,
            "content_type": "post",
            "title": title or None,
            "caption": None,
            "text_content": text_content or None,
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": parsed.get("media_metadata", {}),
            "engagement": engagement,
            "language": None,
            "region": "US",
            "raw_payload_ref": raw_payload_ref,
            "normalizer_version": self.version,
            "query": None,
        }

    # kept for backward compatibility with ingest_social_content.py
    def normalize(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        video_id = raw_item.get("id", "")
        return {
            "id": video_id,
            "schema_version": "1.0",
            "source_platform": "youtube",
            "source_account_id": None,
            "source_account_handle": None,
            "source_account_type": None,
            "source_url": f"https://www.youtube.com/watch?v={video_id}",
            "external_content_id": video_id,
            "published_at": raw_item.get("published_at", ""),
            "collected_at": raw_item.get("collected_at", ""),
            "content_type": "video",
            "title": raw_item.get("title"),
            "caption": None,
            "text_content": raw_item.get("text"),
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {},
            "engagement": {},
            "language": None,
            "region": "US",
            "raw_payload_ref": "",
            "normalizer_version": self.version,
            "query": None,
        }
