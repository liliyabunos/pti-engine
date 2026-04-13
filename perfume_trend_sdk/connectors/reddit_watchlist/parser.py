from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


class RedditParser:
    """Parse a raw Reddit post dict into a normalizer-ready dict.

    Never raises — all missing fields are tolerated and default to safe values.
    No analytics, extraction, scoring, or entity resolution performed here.

    Input schema mirrors the Reddit API / PRAW Submission attributes as
    captured in tests/fixtures/reddit_post_raw.json.
    """

    def parse(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        external_content_id = self._str(raw_item.get("id") or raw_item.get("name") or "")
        subreddit = self._str(raw_item.get("subreddit") or "")
        title = self._str(raw_item.get("title") or "")
        selftext = self._str(raw_item.get("selftext") or raw_item.get("body") or "")
        author = self._str(raw_item.get("author") or "")
        permalink = self._str(raw_item.get("permalink") or "")
        link_flair_text = self._str(raw_item.get("link_flair_text") or "")

        # Build canonical source_url from permalink
        if permalink:
            source_url = (
                permalink
                if permalink.startswith("http")
                else f"https://www.reddit.com{permalink}"
            )
        else:
            source_url = (
                f"https://www.reddit.com/r/{subreddit}/comments/{external_content_id}/"
                if subreddit and external_content_id
                else ""
            )

        published_at = self._parse_timestamp(
            raw_item.get("created_utc") or raw_item.get("created")
        )

        score = self._int(raw_item.get("score") or 0)
        num_comments = self._int(raw_item.get("num_comments") or 0)
        upvote_ratio = self._float(raw_item.get("upvote_ratio"))

        media_metadata: Dict[str, Any] = {
            "subreddit": subreddit,
            "score": score,
            "num_comments": num_comments,
            "upvote_ratio": upvote_ratio,
            "link_flair_text": link_flair_text or None,
            "is_self": bool(raw_item.get("is_self", True)),
        }

        return {
            "external_content_id": external_content_id,
            "subreddit": subreddit,
            "source_url": source_url,
            "source_account_handle": author or None,
            "title": title,
            "selftext": selftext,
            "published_at": published_at,
            "score": score,
            "num_comments": num_comments,
            "link_flair_text": link_flair_text or None,
            "media_metadata": media_metadata,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _str(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _parse_timestamp(self, value: Any) -> str:
        """Convert a Unix timestamp (int or float) to ISO 8601 UTC string."""
        if value is None:
            return ""
        try:
            ts = float(value)
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return ""
