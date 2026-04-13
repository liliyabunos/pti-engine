from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import yaml


@dataclass
class RedditWatchlistConfig:
    """Configuration for the Reddit watchlist connector.

    v1 uses public JSON endpoints — no credentials required.
    All fields have safe defaults so minimal config files work.
    """

    name: str = "reddit_watchlist"
    enabled: bool = True
    fetch_limit: int = 25
    watchlist_file: str = "configs/watchlists/reddit_watchlist.yaml"

    # HTTP client settings
    sort_mode: str = "new"          # "new" | "hot"
    user_agent: str = (
        "pti-sdk/1.0 (perfume trend intelligence; public data only; "
        "contact: https://github.com/pti-sdk)"
    )
    timeout_seconds: int = 20
    max_retries: int = 3
    backoff_seconds: float = 2.0
    requests_per_second: float = 1.0   # conservative; Reddit allows ~1 req/s unauthenticated

    subreddits: List[Dict] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, watchlist_file: str) -> "RedditWatchlistConfig":
        """Load config and subreddit list from a watchlist YAML file.

        Returns a config with empty subreddits if the file is missing.
        """
        try:
            with open(watchlist_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            data = {}

        subreddits: List[Dict] = data.get("subreddits") or []

        # Optional overrides from YAML (all have dataclass defaults)
        kwargs = {
            "watchlist_file": watchlist_file,
            "subreddits": subreddits,
        }
        for key in (
            "name", "enabled", "fetch_limit",
            "sort_mode", "user_agent",
            "timeout_seconds", "max_retries", "backoff_seconds",
            "requests_per_second",
        ):
            if key in data:
                kwargs[key] = data[key]

        return cls(**kwargs)
