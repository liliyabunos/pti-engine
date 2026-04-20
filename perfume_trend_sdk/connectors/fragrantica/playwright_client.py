from __future__ import annotations

"""Playwright-based HTTP client for Fragrantica pages.

Replaces FragranticaClient for environments where direct HTTP requests
return HTTP 403 (bot protection). Uses a headless Chromium browser to
render pages before returning HTML.

Interface is identical to FragranticaClient:
    client.fetch_page(url: str) -> str

Only this file changes — parser, normalizer, store are untouched.
"""

import time
import logging
from pathlib import Path
from typing import Optional

from perfume_trend_sdk.core.logging.logger import log_event

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class PlaywrightFragranticaClient:
    """Headless-browser client for Fragrantica pages.

    Parameters
    ----------
    timeout_ms : int
        Page-load timeout in milliseconds (default 30s).
    max_retries : int
        Number of attempts before raising RuntimeError (default 2).
    backoff_seconds : int
        Wait between retries (default 5).
    raw_html_dir : str | None
        If set, save each fetched HTML to this directory as
        ``{slug}.html`` for replay/debug. Skipped if None.
    """

    def __init__(
        self,
        timeout_ms: int = 30_000,
        max_retries: int = 2,
        backoff_seconds: int = 5,
        raw_html_dir: Optional[str] = "data/raw/fragrantica",
    ) -> None:
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.raw_html_dir = raw_html_dir

    # ------------------------------------------------------------------
    # Public interface (mirrors FragranticaClient)
    # ------------------------------------------------------------------

    def fetch_page(self, url: str) -> str:
        """Fetch rendered HTML from a Fragrantica URL.

        Returns the full HTML string after JavaScript execution.
        Raises RuntimeError if all retries fail.
        """
        log_event("INFO", "fetch_started", url=url, source="fragrantica", client="playwright")

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                html = self._fetch_with_playwright(url, attempt)
                self._save_raw_html(url, html)
                log_event(
                    "INFO",
                    "fetch_succeeded",
                    url=url,
                    source="fragrantica",
                    client="playwright",
                    attempt=attempt,
                    html_length=len(html),
                )
                return html
            except Exception as exc:
                last_error = exc
                log_event(
                    "WARNING",
                    "fetch_failed",
                    url=url,
                    source="fragrantica",
                    client="playwright",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self.max_retries:
                    time.sleep(self.backoff_seconds)

        log_event(
            "ERROR",
            "fetch_exhausted",
            url=url,
            source="fragrantica",
            client="playwright",
            attempts=self.max_retries,
            error=str(last_error),
        )
        raise RuntimeError(
            f"PlaywrightFragranticaClient: failed to fetch {url} "
            f"after {self.max_retries} attempts: {last_error}"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_with_playwright(self, url: str, attempt: int) -> str:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=_USER_AGENT,
                    locale="en-US",
                    viewport={"width": 1280, "height": 900},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": (
                            "text/html,application/xhtml+xml,"
                            "application/xml;q=0.9,image/webp,*/*;q=0.8"
                        ),
                    },
                )
                page = context.new_page()

                try:
                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                except PWTimeout as exc:
                    raise RuntimeError(f"Page load timed out (attempt {attempt}): {exc}") from exc

                if response is None:
                    raise RuntimeError(f"No response received for {url}")

                status = response.status
                if status == 403:
                    raise RuntimeError(
                        f"HTTP 403 Forbidden — Fragrantica bot protection still active (attempt {attempt})"
                    )
                if status >= 400:
                    raise RuntimeError(f"HTTP {status} error fetching {url}")

                # Wait for accord/note elements to be present in DOM (best-effort)
                try:
                    page.wait_for_selector(
                        ".accord-box, #pyramid, h1",
                        timeout=8_000,
                        state="attached",
                    )
                except PWTimeout:
                    # Selectors not found — page still valid, parse what we have
                    logger.debug("[PlaywrightClient] selector wait timed out for %s — continuing", url)

                html = page.content()
                return html

            finally:
                browser.close()

    def _save_raw_html(self, url: str, html: str) -> None:
        """Save raw HTML to disk for replay/debug. Silently skips on error."""
        if not self.raw_html_dir:
            return
        try:
            slug = url.rstrip("/").split("/")[-1].replace(".html", "")
            out_dir = Path(self.raw_html_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{slug}.html"
            out_path.write_text(html, encoding="utf-8")
            logger.debug("[PlaywrightClient] saved raw HTML → %s", out_path)
        except Exception as exc:
            logger.warning("[PlaywrightClient] could not save raw HTML: %s", exc)
