from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from perfume_trend_sdk.connectors.tiktok_watchlist.client import TikTokWatchlistClient
from perfume_trend_sdk.connectors.tiktok_watchlist.config import TikTokWatchlistConfig

logger = logging.getLogger(__name__)


@dataclass
class TikTokFetchResult:
    """Result of a single TikTok watchlist fetch run."""

    source_name: str
    fetched_count: int
    raw_items: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class TikTokWatchlistConnector:
    """
    Connector for TikTok watchlist accounts.

    Fetches raw post data only — no analytics, no extraction, no scoring.
    Designed to be disabled without breaking other pipeline stages.

    v1 uses a stub client (TikTok Research API not freely accessible).
    """

    name: str = "tiktok_watchlist_connector"
    version: str = "1.0"

    def __init__(self, config: TikTokWatchlistConfig) -> None:
        self.config = config
        self._client = TikTokWatchlistClient(accounts=config.accounts)

    def validate_config(self) -> None:
        """Check that at least one account is configured."""
        if not self.config.accounts:
            raise ValueError(
                f"[{self.name}] No accounts configured. "
                f"Check watchlist_file: {self.config.watchlist_file}"
            )

    def healthcheck(self) -> bool:
        """
        Return True — stub connector is always healthy.
        Replace with real API ping once TikTok Research API access is granted.
        """
        return True

    def get_cursor(self) -> Optional[str]:
        """Return None — cursor not implemented in v1."""
        return None

    def set_cursor(self, cursor: str) -> None:
        """No-op — cursor not implemented in v1."""
        pass

    def fetch(
        self,
        *,
        max_results: int = 25,
        published_after: Optional[str] = None,
    ) -> TikTokFetchResult:
        """
        Fetch raw TikTok posts for all active accounts in the watchlist.

        In v1, the stub client returns empty lists. Raw items are returned
        as-is for downstream raw storage and normalization.

        Args:
            max_results: Maximum posts to fetch per account.
            published_after: ISO 8601 string; skip posts before this date.

        Returns:
            TikTokFetchResult with all raw post dicts and any warnings.
        """
        if not self.config.enabled:
            logger.info("[%s] Connector is disabled — skipping fetch.", self.name)
            return TikTokFetchResult(
                source_name=self.name,
                fetched_count=0,
                raw_items=[],
                warnings=["Connector disabled via config."],
            )

        all_raw_items: List[Dict] = []
        warnings: List[str] = []
        active_accounts = [a for a in self.config.accounts if a.get("active", True)]

        if not active_accounts:
            warnings.append("No active accounts found in watchlist.")
            logger.warning("[%s] No active accounts in watchlist.", self.name)

        for account in active_accounts:
            handle = account.get("account_handle", "")
            if not handle:
                warnings.append(f"Account entry missing account_handle: {account}")
                continue

            logger.info("[%s] Fetching posts for @%s", self.name, handle)
            try:
                items = self._client.fetch_user_posts(
                    handle=handle,
                    max_count=max_results,
                    published_after=published_after,
                )
                all_raw_items.extend(items)
            except Exception as exc:
                msg = f"Failed to fetch @{handle}: {exc}"
                logger.warning("[%s] %s", self.name, msg)
                warnings.append(msg)

        logger.info(
            "[%s] Fetch complete. total_items=%d accounts_checked=%d",
            self.name,
            len(all_raw_items),
            len(active_accounts),
        )

        return TikTokFetchResult(
            source_name=self.name,
            fetched_count=len(all_raw_items),
            raw_items=all_raw_items,
            warnings=warnings,
        )
