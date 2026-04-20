from __future__ import annotations

"""CDP-based Fragrantica client.

Connects to a real Chrome instance (already running with --remote-debugging-port=9222)
via the Chrome DevTools Protocol. The running Chrome browser has already passed
Cloudflare bot checks, so no 403 is received.

This is the Phase 1b local verification client. Interface is identical to
FragranticaClient:

    client = CDPFragranticaClient()
    html = client.fetch_page(url)

Requirements:
    1. Chrome must be running with remote debugging enabled:
       /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
           --remote-debugging-port=9222 \\
           --user-data-dir=/tmp/chrome_frag_debug \\
           https://www.fragrantica.com/
    2. playwright must be installed: pip install playwright

URL resolution:
    Fragrantica requires a numeric perfume ID in the URL:
    https://www.fragrantica.com/perfume/Brand-Name/Perfume-Name-12345.html
    If the supplied URL lacks the ID (returns 404), the client performs a
    Fragrantica search to find the correct URL automatically.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode

from perfume_trend_sdk.core.logging.logger import log_event

logger = logging.getLogger(__name__)

_CDP_ENDPOINT = "http://127.0.0.1:9222"
_BASE_URL = "https://www.fragrantica.com"
_NOTE_WAIT_SECONDS = 3  # seconds to wait for Vue.js notes to render


class CDPFragranticaClient:
    """Fragrantica client via Chrome DevTools Protocol.

    Connects to a real user Chrome instance that has already passed Cloudflare.
    Performs search-based URL resolution so slug-only URLs (which 404) are
    automatically resolved to the correct numeric-ID URL.

    Parameters
    ----------
    cdp_endpoint : str
        Chrome remote debugging endpoint (default: http://127.0.0.1:9222).
    raw_html_dir : str | None
        Directory to save raw HTML for replay. None to skip.
    render_wait_seconds : int
        Seconds to wait for Vue.js content to finish rendering.
    """

    def __init__(
        self,
        cdp_endpoint: str = _CDP_ENDPOINT,
        raw_html_dir: Optional[str] = "data/raw/fragrantica",
        render_wait_seconds: int = _NOTE_WAIT_SECONDS,
    ) -> None:
        self.cdp_endpoint = cdp_endpoint
        self.raw_html_dir = raw_html_dir
        self.render_wait_seconds = render_wait_seconds

    # ------------------------------------------------------------------
    # Public interface (mirrors FragranticaClient)
    # ------------------------------------------------------------------

    def fetch_page(self, url: str) -> str:
        """Fetch rendered HTML from a Fragrantica perfume URL.

        If the URL is a slug-only URL that returns 404, automatically
        performs a Fragrantica search to find the correct URL and fetches
        that instead.

        Returns full page HTML as a string.
        Raises RuntimeError on failure.
        """
        log_event("INFO", "fetch_started", url=url, source="fragrantica", client="cdp")
        try:
            html = self._fetch(url)
            self._save_raw_html(url, html)
            log_event(
                "INFO", "fetch_succeeded",
                url=url, source="fragrantica", client="cdp",
                html_length=len(html),
            )
            return html
        except Exception as exc:
            log_event("ERROR", "fetch_failed", url=url, source="fragrantica", client="cdp", error=str(exc))
            raise RuntimeError(f"CDPFragranticaClient: fetch failed for {url}: {exc}") from exc

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_page(self):
        """Return (playwright, browser, page) connected via CDP."""
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(self.cdp_endpoint)
        ctx = browser.contexts[0]
        pages = ctx.pages
        page = pages[0] if pages else ctx.new_page()
        return pw, browser, page

    def _fetch(self, url: str) -> str:
        pw, browser, page = self._get_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            if resp is None:
                raise RuntimeError(f"No response from {url}")

            if resp.status == 404:
                # Slug-only URL — resolve via search
                logger.info("[CDPClient] 404 for %s — trying search-based resolution", url)
                resolved = self._resolve_via_search(page, url)
                if not resolved:
                    raise RuntimeError(f"Could not resolve URL via search: {url}")
                resp2 = page.goto(resolved, wait_until="domcontentloaded", timeout=30_000)
                if resp2 and resp2.status >= 400:
                    raise RuntimeError(f"HTTP {resp2.status} for resolved URL {resolved}")
                log_event("INFO", "url_resolved", original_url=url, resolved_url=resolved, source="fragrantica")

            elif resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status} fetching {url}")

            # Wait for Vue.js to render notes
            try:
                page.wait_for_selector(".pyramid-note-label", timeout=6_000, state="attached")
            except Exception:
                # Notes may not be present on all pages — continue anyway
                pass

            time.sleep(self.render_wait_seconds)
            return page.content()

        finally:
            try:
                browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

    def _resolve_via_search(self, page, original_url: str) -> Optional[str]:
        """Search Fragrantica to find the correct URL (with numeric ID).

        Extracts brand and perfume name from the slug URL, searches Fragrantica,
        and returns the first matching perfume URL from the search results.
        """
        # Extract brand and perfume from slug URL
        # URL format: https://www.fragrantica.com/perfume/{brand-slug}/{perfume-slug}.html
        m = re.search(r"/perfume/([^/]+)/([^/]+?)(?:\.html)?$", original_url)
        if not m:
            return None

        brand_slug = m.group(1).replace("-", " ")
        perfume_slug = m.group(2).replace("-", " ")
        query = f"{perfume_slug} {brand_slug}".strip()

        search_url = f"{_BASE_URL}/search/?query={quote_plus(query)}"
        logger.info("[CDPClient] searching: %s", search_url)

        page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
        time.sleep(2)

        html = page.content()
        # Find perfume links in search results
        links = re.findall(r'href="(/perfume/[^"]+\.html)"', html)

        if not links:
            return None

        # Filter to links that are plausibly the right perfume
        perfume_fragment = perfume_slug.split()[0].lower()
        for link in links:
            if perfume_fragment in link.lower():
                return f"{_BASE_URL}{link}"

        # Fallback: return first perfume link
        return f"{_BASE_URL}{links[0]}"

    def _save_raw_html(self, url: str, html: str) -> None:
        if not self.raw_html_dir:
            return
        try:
            slug = url.rstrip("/").split("/")[-1].replace(".html", "")
            out_dir = Path(self.raw_html_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{slug}.html"
            out_path.write_text(html, encoding="utf-8")
            logger.debug("[CDPClient] saved raw HTML → %s", out_path)
        except Exception as exc:
            logger.warning("[CDPClient] could not save raw HTML: %s", exc)
