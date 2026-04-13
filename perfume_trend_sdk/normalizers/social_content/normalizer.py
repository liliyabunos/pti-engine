from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from perfume_trend_sdk.connectors.tiktok_watchlist.parser import TikTokParser
from perfume_trend_sdk.connectors.reddit_watchlist.parser import RedditParser

logger = logging.getLogger(__name__)


class SocialContentNormalizer:
    version = "1.0"

    def normalize_youtube_item(
        self,
        raw_item: dict[str, Any],
        *,
        raw_payload_ref: str,
    ) -> dict[str, Any]:
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
            "language": None,
            "region": "US",
            "raw_payload_ref": raw_payload_ref,
            "normalizer_version": self.version,
            "query": raw_item.get("query"),
        }

    def normalize_tiktok_item(
        self,
        raw_item: Dict[str, Any],
        raw_payload_ref: str,
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
