from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search_videos(
        self,
        query: str,
        *,
        max_results: int = 10,
        published_after: Optional[str] = None,
        region_code: str = "US",
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": "date",
            "regionCode": region_code,
            "key": self.api_key,
        }
        if published_after:
            params["publishedAfter"] = published_after
        if page_token:
            params["pageToken"] = page_token

        response = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fetch_video_stats(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not video_ids:
            return {}

        params = {
            "part": "statistics,contentDetails,snippet",
            "id": ",".join(video_ids),
            "key": self.api_key,
        }
        response = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()

        result: Dict[str, Dict[str, Any]] = {}
        for item in payload.get("items", []):
            result[item["id"]] = item
        return result
