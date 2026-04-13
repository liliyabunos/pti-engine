from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from perfume_trend_sdk.connectors.reddit_watchlist.client import RedditWatchlistClient
from perfume_trend_sdk.connectors.reddit_watchlist.config import RedditWatchlistConfig

logger = logging.getLogger(__name__)


@dataclass
class RedditFetchResult:
    """Result of a single Reddit subreddit fetch run."""

    source_name: str
    subreddit: str
    fetched_count: int
    raw_items: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    next_cursor: Optional[str] = None    # fullname for next page; None = exhausted


class RedditWatchlistConnector:
    """Connector for Reddit subreddit watchlist — public JSON endpoints.

    Fetches raw Reddit post payloads only — no analytics, extraction,
    scoring, or entity resolution.

    v1 uses public JSON endpoints (no credentials required).
    Rate-limited at 1 req/sec by default (configurable).
    """

    name: str = "reddit_watchlist_connector"
    version: str = "1.0"

    def __init__(self, config: RedditWatchlistConfig) -> None:
        self.config = config
        self._client = RedditWatchlistClient(
            user_agent=config.user_agent,
            sort_mode=config.sort_mode,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            backoff_seconds=config.backoff_seconds,
            requests_per_second=config.requests_per_second,
        )

    def validate_config(self) -> None:
        """Raise ValueError if no subreddits are configured."""
        if not self.config.subreddits:
            raise ValueError(
                f"[{self.name}] No subreddits configured. "
                f"Check watchlist_file: {self.config.watchlist_file}"
            )

    def healthcheck(self) -> bool:
        """Return True — no credentials to verify for public JSON access."""
        return True

    def get_cursor(self) -> Optional[str]:
        """Return None — cursor is managed per-subreddit in fetch()."""
        return None

    def set_cursor(self, cursor: str) -> None:
        """No-op — cursor passed directly to fetch()."""

    def fetch(
        self,
        subreddit_name: str,
        *,
        max_results: int = 25,
        published_after: Optional[str] = None,
        after_cursor: Optional[str] = None,
    ) -> RedditFetchResult:
        """
        Fetch raw Reddit posts for a single subreddit via public JSON.

        Args:
            subreddit_name:  Subreddit name without r/ prefix.
            max_results:     Maximum number of posts to fetch (API max=100).
            published_after: ISO 8601 string; posts older than this are
                             discarded and pagination stops.
            after_cursor:    Fullname cursor from a previous fetch for
                             the next page ("t3_abc123").

        Returns:
            RedditFetchResult with raw post dicts, fetched_count, and
            next_cursor for the following page (None if no more pages).
        """
        if not self.config.enabled:
            logger.info("[%s] Connector is disabled — skipping fetch.", self.name)
            return RedditFetchResult(
                source_name=self.name,
                subreddit=subreddit_name,
                fetched_count=0,
                warnings=["Connector disabled via config."],
            )

        logger.info(
            "[%s] fetch_started subreddit=r/%s max_results=%d sort=%s",
            self.name, subreddit_name, max_results, self.config.sort_mode,
        )

        warnings: List[str] = []
        raw_items: List[Dict] = []
        next_page_cursor: Optional[str] = None

        try:
            raw_items, next_page_cursor = self._client.fetch_subreddit_posts(
                subreddit_name,
                max_count=max_results,
                published_after=published_after,
                after_cursor=after_cursor,
            )
            logger.info(
                "[%s] fetch_succeeded subreddit=r/%s fetched=%d next_cursor=%s",
                self.name, subreddit_name, len(raw_items), next_page_cursor or "none",
            )
        except Exception as exc:
            msg = f"Failed to fetch r/{subreddit_name}: {exc}"
            logger.warning(
                "[%s] fetch_failed subreddit=r/%s error=%s", self.name, subreddit_name, exc
            )
            warnings.append(msg)

        return RedditFetchResult(
            source_name=self.name,
            subreddit=subreddit_name,
            fetched_count=len(raw_items),
            raw_items=raw_items,
            warnings=warnings,
            next_cursor=next_page_cursor,
        )
