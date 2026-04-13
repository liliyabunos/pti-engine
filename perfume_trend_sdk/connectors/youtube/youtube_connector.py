import json
import urllib.error
import urllib.parse
import urllib.request

from perfume_trend_sdk.core.config.sources.youtube import YouTubeSourceConfig

SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeConnector:
    name = "youtube"

    def __init__(self, config: YouTubeSourceConfig) -> None:
        self.config = config

    def _fetch_statistics(self, video_ids: list) -> dict:
        params = urllib.parse.urlencode({
            "part": "statistics",
            "id": ",".join(video_ids),
            "key": self.config.api_key,
        })
        url = f"{VIDEOS_ENDPOINT}?{params}"

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print("YOUTUBE STATS ERROR:", e.code, e.read().decode("utf-8"))
            return {}

        stats = {}
        for item in data.get("items", []):
            vid_id = item.get("id")
            s = item.get("statistics", {})
            stats[vid_id] = {
                "view_count": int(s["viewCount"]) if "viewCount" in s else None,
                "like_count": int(s["likeCount"]) if "likeCount" in s else None,
                "comment_count": int(s["commentCount"]) if "commentCount" in s else None,
            }
        return stats

    def fetch(self) -> dict:
        if not self.config.api_key:
            print("YouTubeConnector: YOUTUBE_API_KEY not set")
        items = []

        for query in self.config.search_queries:
            params = urllib.parse.urlencode({
                "part": "snippet",
                "q": query,
                "maxResults": self.config.max_results,
                "key": self.config.api_key,
                "type": "video",
            })
            url = f"{SEARCH_ENDPOINT}?{params}"

            try:
                with urllib.request.urlopen(url) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                print("YOUTUBE URL:", url)
                print("HTTP STATUS:", e.code)
                print("YOUTUBE ERROR BODY:", e.read().decode("utf-8"))
                raise

            for item in data.get("items", []):
                video_id = item.get("id", {}).get("videoId")
                if not video_id:
                    continue
                snippet = item.get("snippet", {})
                items.append({
                    "id": video_id,
                    "title": snippet.get("title"),
                    "text": snippet.get("description"),
                    "channel_title": snippet.get("channelTitle"),
                    "published_at": snippet.get("publishedAt"),
                })

        # Enrich with statistics
        video_ids = [item["id"] for item in items]
        if video_ids:
            stats = self._fetch_statistics(video_ids)
            for item in items:
                s = stats.get(item["id"], {})
                item["view_count"] = s.get("view_count")
                item["like_count"] = s.get("like_count")
                item["comment_count"] = s.get("comment_count")

        return {"items": items}
