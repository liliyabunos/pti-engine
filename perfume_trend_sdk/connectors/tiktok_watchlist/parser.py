from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List


class TikTokParser:
    """
    Parse a raw TikTok API-like post dict into a normalizer-ready dict.

    Never raises — all missing fields are tolerated and default to safe values.
    No analytics, no extraction, no scoring performed here.
    """

    def parse(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        try:
            external_content_id = str(raw_item.get("id") or "")
        except Exception:
            external_content_id = ""

        author = raw_item.get("author") or {}
        try:
            author_id = str(author.get("id") or "")
        except Exception:
            author_id = ""

        try:
            handle = str(author.get("uniqueId") or "")
        except Exception:
            handle = ""

        try:
            followers = int(author.get("followerCount") or 0)
        except (TypeError, ValueError):
            followers = 0

        try:
            verified = bool(author.get("verified") or False)
        except Exception:
            verified = False

        try:
            caption = str(raw_item.get("desc") or "")
        except Exception:
            caption = ""

        # Build source URL — requires both handle and id
        if handle and external_content_id:
            source_url = f"https://www.tiktok.com/@{handle}/video/{external_content_id}"
        else:
            source_url = ""

        hashtags = self._extract_hashtags(raw_item)

        try:
            create_time = int(raw_item.get("createTime") or 0)
            published_at = datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            published_at = ""

        stats = raw_item.get("stats") or {}
        try:
            views = int(stats.get("playCount") or 0)
        except (TypeError, ValueError):
            views = 0
        try:
            likes = int(stats.get("diggCount") or 0)
        except (TypeError, ValueError):
            likes = 0
        try:
            comments = int(stats.get("commentCount") or 0)
        except (TypeError, ValueError):
            comments = 0
        try:
            shares = int(stats.get("shareCount") or 0)
        except (TypeError, ValueError):
            shares = 0

        video = raw_item.get("video") or {}
        try:
            duration_seconds = int(video.get("duration") or 0)
        except (TypeError, ValueError):
            duration_seconds = 0

        media_metadata: Dict[str, Any] = {
            "followers": followers,
            "duration_seconds": duration_seconds,
            "verified": verified,
        }

        return {
            "external_content_id": external_content_id,
            "source_url": source_url,
            "source_account_id": author_id,
            "source_account_handle": handle,
            "caption": caption,
            "hashtags": hashtags,
            "published_at": published_at,
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "followers": followers,
            "duration_seconds": duration_seconds,
            "media_metadata": media_metadata,
        }

    def _extract_hashtags(self, raw_item: Dict[str, Any]) -> List[str]:
        """
        Extract hashtags from challenges list first; fall back to parsing desc.
        Never raises.
        """
        try:
            challenges = raw_item.get("challenges") or []
            if challenges and isinstance(challenges, list):
                tags = []
                for c in challenges:
                    if isinstance(c, dict):
                        title = c.get("title") or ""
                        if title:
                            tags.append(str(title))
                if tags:
                    return tags
        except Exception:
            pass

        try:
            desc = str(raw_item.get("desc") or "")
            return re.findall(r"#(\w+)", desc)
        except Exception:
            return []
