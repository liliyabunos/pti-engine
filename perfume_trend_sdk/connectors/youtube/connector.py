from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from perfume_trend_sdk.connectors.youtube.client import YouTubeClient


@dataclass
class YouTubeFetchResult:
    source_name: str
    fetched_count: int
    success_count: int
    failed_count: int
    next_cursor: Optional[str]
    raw_items: List[Dict[str, Any]]
    warnings: List[str]


class YouTubeConnector:
    name = "youtube_connector"
    version = "1.0"

    def __init__(self, api_key: str) -> None:
        self.client = YouTubeClient(api_key=api_key)

    def fetch(
        self,
        *,
        query: str,
        max_results: int = 10,
        published_after: Optional[str] = None,
        region_code: str = "US",
        page_token: Optional[str] = None,
    ) -> YouTubeFetchResult:
        search_payload = self.client.search_videos(
            query=query,
            max_results=max_results,
            published_after=published_after,
            region_code=region_code,
            page_token=page_token,
        )

        items = search_payload.get("items", [])
        video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]

        stats_map = self.client.fetch_video_stats(video_ids)
        now_iso = datetime.now(timezone.utc).isoformat()

        raw_items: List[Dict[str, Any]] = []
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue

            enriched = {
                "fetched_at": now_iso,
                "query": query,
                "search_item": item,
                "video_details": stats_map.get(video_id, {}),
            }
            raw_items.append(enriched)

        return YouTubeFetchResult(
            source_name="youtube",
            fetched_count=len(items),
            success_count=len(raw_items),
            failed_count=max(0, len(items) - len(raw_items)),
            next_cursor=search_payload.get("nextPageToken"),
            raw_items=raw_items,
            warnings=[],
        )
