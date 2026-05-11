from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"


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

    def get_channel_info(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Fetch snippet + contentDetails for a channel. Costs 1 quota unit.

        Returns a dict with:
          uploads_playlist_id — stable UU... playlist ID (cache in youtube_channels)
          title               — channel display name from snippet.title
          country             — ISO 3166-1 alpha-2 code from snippet.country, or None
          language            — BCP-47 language code from snippet.defaultLanguage, or None

        Returns None if the channel is not found (private, deleted, or invalid ID).
        """
        params = {
            "part": "snippet,contentDetails",
            "id": channel_id,
            "key": self.api_key,
        }
        response = requests.get(YOUTUBE_CHANNELS_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        items = response.json().get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet", {})
        return {
            "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
            "title": snippet.get("title") or None,
            "country": snippet.get("country") or None,
            "language": snippet.get("defaultLanguage") or None,
        }

    def get_uploads_playlist_id(self, channel_id: str) -> Optional[str]:
        """Return the uploads playlist ID (UU...) for a channel. Costs 1 quota unit.

        Prefer get_channel_info() for first-poll paths — it fetches playlist_id +
        language/country in the same single quota unit.
        Kept for backward-compat callers that only need the playlist ID.
        """
        info = self.get_channel_info(channel_id)
        return info["uploads_playlist_id"] if info else None

    def list_channel_uploads(
        self,
        playlist_id: str,
        *,
        published_after: Optional[str] = None,
        max_results: int = 50,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List videos from a channel's uploads playlist. Costs 1 quota unit per page.

        Args:
            playlist_id: The UU... uploads playlist ID.
            published_after: ISO 8601 datetime string — filter videos published after this time.
            max_results: Max results per page (1–50).
            page_token: Continuation token for pagination.

        Returns:
            Raw API response dict with 'items' and optional 'nextPageToken'.

        Note: playlistItems.list does not natively support publishedAfter filtering —
        filtering is applied client-side in the ingestion script by checking
        snippet.publishedAt against the cutoff.
        """
        params: Dict[str, Any] = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": min(max_results, 50),
            "key": self.api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        response = requests.get(YOUTUBE_PLAYLIST_ITEMS_URL, params=params, timeout=self.timeout)
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
