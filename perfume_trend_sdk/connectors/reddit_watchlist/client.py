from __future__ import annotations

"""
Reddit public JSON client — no OAuth, no API credentials required.

Fetches posts from subreddit listing endpoints:
  GET https://www.reddit.com/r/<subreddit>/<sort>.json?limit=N&after=<cursor>

Reddit public API rules:
  - Unauthenticated: ~1 request / second (enforced by _rate_limit_delay)
  - User-Agent MUST be set to a descriptive string (Reddit blocks default agents)
  - Pagination via `after` cursor (fullname e.g. "t3_abc123")
  - No credentials required for public subreddits

Reddit API (future / OAuth — TODO):
  When higher rate limits or private subreddit access is needed, migrate to
  official Reddit API (PRAW / OAuth). See CLAUDE.md — "Reddit API (Future)".
  Only client.py needs to change — connector, parser, normalizer are stable.

Docs: https://www.reddit.com/dev/api
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.reddit.com/r/{subreddit}/{sort}.json"

# Retry configuration
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0    # seconds; doubles each attempt
_RATE_LIMIT_WAIT = 60.0  # seconds to wait on 429


class RedditAPIError(Exception):
    """Raised on non-retryable Reddit API errors."""


class RedditWatchlistClient:
    """
    Reddit public JSON client — subreddit listing fetch, no credentials.

    Implements conservative rate limiting (1 req/sec by default) and
    retry with exponential backoff on 5xx / 429.

    fetch_subreddit_posts() returns raw post dicts matching the schema
    used by RedditParser — identical to the PRAW Submission dict structure.
    """

    def __init__(
        self,
        *,
        user_agent: str = "pti-sdk/1.0 (perfume trend intelligence; public data only)",
        sort_mode: str = "new",
        timeout_seconds: int = 20,
        max_retries: int = _MAX_RETRIES,
        backoff_seconds: float = _BACKOFF_BASE,
        requests_per_second: float = 1.0,
    ) -> None:
        self._user_agent = user_agent
        self._sort_mode = sort_mode
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        # Minimum seconds between requests — conservative default
        self._min_interval = 1.0 / max(requests_per_second, 0.01)
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_subreddit_posts(
        self,
        subreddit_name: str,
        *,
        max_count: int = 25,
        published_after: Optional[str] = None,
        after_cursor: Optional[str] = None,
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        Fetch raw post dicts from a subreddit listing.

        Args:
            subreddit_name:  Subreddit name without r/ prefix.
            max_count:       Maximum number of posts to return (API max=100).
            published_after: ISO 8601 string; posts created before this are
                             filtered out.  None = no filter.
            after_cursor:    Pagination fullname (e.g. "t3_abc123") for the
                             next page.  None = first page.

        Returns:
            (posts, next_after_cursor)
              posts            — list of raw post dicts (matching parser schema)
              next_after_cursor — fullname for next page, or None if exhausted

        Raises:
            RedditAPIError: on non-retryable HTTP errors.
        """
        cutoff_ts: Optional[float] = _parse_iso_to_ts(published_after)

        limit = min(max_count, 100)
        params: Dict[str, str] = {"limit": str(limit), "raw_json": "1"}
        if after_cursor:
            params["after"] = after_cursor

        url = _BASE_URL.format(subreddit=subreddit_name, sort=self._sort_mode)
        full_url = f"{url}?{urlencode(params)}"

        logger.info(
            "reddit_fetch_started subreddit=r/%s sort=%s limit=%d after=%s",
            subreddit_name, self._sort_mode, limit, after_cursor or "start",
        )

        body = self._get(full_url)

        raw_children = body.get("data", {}).get("children", [])
        next_cursor: Optional[str] = body.get("data", {}).get("after") or None

        posts = []
        for child in raw_children:
            if child.get("kind") != "t3":
                continue
            post = child.get("data", {})
            # Filter by cutoff timestamp when requested
            if cutoff_ts is not None:
                created_utc = float(post.get("created_utc") or 0)
                if created_utc < cutoff_ts:
                    # Reddit sorts by created DESC for "new" — older posts follow
                    # Signal caller that further pages won't help
                    next_cursor = None
                    break
            posts.append(post)

        logger.info(
            "reddit_fetch_completed subreddit=r/%s count=%d next_cursor=%s",
            subreddit_name, len(posts), next_cursor or "none",
        )

        return posts, next_cursor

    # ------------------------------------------------------------------
    # HTTP — GET with rate limiting and retry
    # ------------------------------------------------------------------

    def _get(self, url: str) -> Dict:
        """GET with conservative rate limiting and retry on 429 / 5xx."""
        self._rate_limit()

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

        last_exc: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, timeout=self._timeout)
            except requests.RequestException as exc:
                last_exc = exc
                wait = self._backoff ** attempt
                logger.warning(
                    "reddit_request_error attempt=%d/%d exc=%s retrying_in=%.0fs",
                    attempt, self._max_retries, exc, wait,
                )
                time.sleep(wait)
                continue
            finally:
                self._last_request_at = time.monotonic()

            if resp.status_code == 429:
                wait = _RATE_LIMIT_WAIT
                logger.warning(
                    "reddit_rate_limited attempt=%d/%d waiting=%.0fs",
                    attempt, self._max_retries, wait,
                )
                time.sleep(wait)
                self._last_request_at = time.monotonic()
                continue

            if resp.status_code in _RETRY_STATUSES:
                wait = self._backoff ** attempt
                logger.warning(
                    "reddit_server_error attempt=%d/%d status=%d retrying_in=%.0fs",
                    attempt, self._max_retries, resp.status_code, wait,
                )
                time.sleep(wait)
                continue

            if not resp.ok:
                raise RedditAPIError(
                    f"Reddit API error HTTP {resp.status_code} for {url}: {resp.text[:300]}"
                )

            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type.lower():
                raise RedditAPIError(
                    f"Reddit returned non-JSON response (possible bot-detection page). "
                    f"HTTP {resp.status_code}  Content-Type={content_type!r}  "
                    f"body_prefix={resp.text[:200]!r}"
                )

            return resp.json()

        raise RedditAPIError(
            f"Reddit API request failed after {self._max_retries} attempts. "
            f"URL: {url}. Last error: {last_exc}"
        )

    def _rate_limit(self) -> None:
        """Sleep if needed to honour requests_per_second."""
        elapsed = time.monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_iso_to_ts(iso_str: Optional[str]) -> Optional[float]:
    """Convert ISO 8601 string to Unix timestamp float. Returns None on failure."""
    if not iso_str:
        return None
    # Accept both "Z" suffix and "+00:00"
    normalised = iso_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalised).timestamp()
    except (ValueError, TypeError):
        return None
