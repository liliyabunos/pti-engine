from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class TikTokWatchlistConfig:
    """
    Configuration for the TikTok watchlist connector.

    Accounts are loaded from a watchlist YAML file.
    No API keys stored here — credentials must come from environment variables.
    """

    name: str = "tiktok_watchlist"
    enabled: bool = True
    fetch_limit: int = 25
    watchlist_file: str = "configs/watchlists/tiktok_watchlist.yaml"
    timeout_seconds: int = 20
    max_retries: int = 3
    backoff_seconds: int = 5
    accounts: List[Dict] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, watchlist_file: str) -> "TikTokWatchlistConfig":
        """
        Load config and accounts from a watchlist YAML file.

        Args:
            watchlist_file: Path to tiktok_watchlist.yaml

        Returns:
            TikTokWatchlistConfig with accounts populated from file.
        """
        try:
            with open(watchlist_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            data = {}

        accounts: List[Dict] = data.get("accounts") or []
        return cls(watchlist_file=watchlist_file, accounts=accounts)
