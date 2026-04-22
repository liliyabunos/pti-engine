from __future__ import annotations

import time
from typing import Optional

import requests

from perfume_trend_sdk.core.logging.logger import log_event


class FragranticaClient:
    """HTTP client for fetching raw HTML from Fragrantica pages.

    Responsibilities:
    - Fetch raw HTML only — no parsing
    - Retry with exponential backoff on failure
    - Log fetch lifecycle events
    """

    # Realistic browser User-Agent — required to pass Fragrantica bot detection.
    # "PTI-SDK/1.0" was previously used and returned HTTP 403 from all environments.
    _DEFAULT_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        timeout: int = 20,
        user_agent: str = _DEFAULT_UA,
        max_retries: int = 3,
        backoff_seconds: int = 3,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    def _headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def fetch_page(self, url: str) -> str:
        """Fetch raw HTML from the given URL.

        Returns raw HTML string. Raises RuntimeError on repeated failure.
        """
        log_event("INFO", "fetch_started", url=url, source="fragrantica")

        last_exception: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                log_event(
                    "INFO",
                    "fetch_succeeded",
                    url=url,
                    source="fragrantica",
                    status_code=response.status_code,
                    attempt=attempt,
                )
                return response.text
            except requests.RequestException as exc:
                last_exception = exc
                log_event(
                    "WARNING",
                    "fetch_failed",
                    url=url,
                    source="fragrantica",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self.max_retries:
                    sleep_seconds = self.backoff_seconds * (2 ** (attempt - 1))
                    time.sleep(sleep_seconds)

        log_event(
            "ERROR",
            "fetch_failed",
            url=url,
            source="fragrantica",
            attempts=self.max_retries,
            error=str(last_exception),
        )
        raise RuntimeError(
            f"Failed to fetch {url} after {self.max_retries} attempts: {last_exception}"
        )
