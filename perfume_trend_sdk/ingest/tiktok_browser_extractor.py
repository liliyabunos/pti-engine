from __future__ import annotations

"""
SC1.2D — TikTok browser-rendered profile extractor.

EVALUATION ONLY — not wired into the production pipeline.

Uses Playwright Chromium (headless) to load a public TikTok creator profile
page as a real browser would and attempts to extract:

  - Recent public video URLs from the rendered DOM
  - Basic profile metadata (display_name, follower_count, bio)
  - Script-tag JSON blobs (__UNIVERSAL_DATA_FOR_REHYDRATION__ etc.)
  - Any network responses containing video data (via route interception)

Hard rules — this module NEVER:
  - Logs in or uses a TikTok account
  - Sends cookies or session tokens
  - Creates canonical_content_items rows
  - Creates entity_mentions rows
  - Updates creator_platform_accounts.last_checked_at
  - Changes creator status

Detection checks (stop immediately if found):
  - Login wall: page redirected to login flow or shows login modal
  - CAPTCHA: challenge page or captcha element detected
  - Block page: access-denied / rate-limit response

Extraction methods attempted (in order):
  1. dom_links   — anchor hrefs matching /@handle/video/<id>
  2. script_json — __UNIVERSAL_DATA_FOR_REHYDRATION__ itemList (usually empty)
  3. network_response — intercepted /api/post/item_list/ XHR if it fires
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BrowserProfileResult:
    handle: str
    profile_url: str

    rendered_success: bool = False
    captcha_or_block_detected: bool = False
    login_wall_detected: bool = False

    # Video discovery
    video_urls_found: int = 0
    sample_video_urls: List[str] = field(default_factory=list)
    extraction_method: str = "none"   # dom_links | script_json | network_response | none

    # Profile metadata
    metadata_found: bool = False
    display_name: Optional[str] = None
    follower_count: Optional[int] = None
    bio_found: bool = False
    bio: Optional[str] = None

    # Timing
    render_time_seconds: float = 0.0

    # Debug
    http_status: Optional[int] = None
    page_title: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "profile_url": self.profile_url,
            "rendered_success": self.rendered_success,
            "captcha_or_block_detected": self.captcha_or_block_detected,
            "login_wall_detected": self.login_wall_detected,
            "video_urls_found": self.video_urls_found,
            "sample_video_urls": self.sample_video_urls[:5],
            "extraction_method": self.extraction_method,
            "metadata_found": self.metadata_found,
            "display_name": self.display_name,
            "follower_count": self.follower_count,
            "bio_found": self.bio_found,
            "render_time_seconds": round(self.render_time_seconds, 2),
            "http_status": self.http_status,
            "page_title": self.page_title,
            "error_message": self.error_message,
        }


# ---------------------------------------------------------------------------
# Detection helpers (operate on page content strings — testable without browser)
# ---------------------------------------------------------------------------

# Login wall signals: URL patterns or DOM text that indicate a login redirect
_LOGIN_URL_PATTERNS = [
    r"tiktok\.com/login",
    r"tiktok\.com/signup",
    r"/passport/",
    r"accounts\.tiktok\.com",
]
_LOGIN_TEXT_PATTERNS = [
    "log in to tiktok",
    "sign up for tiktok",
    "create account",
    "log in with",
    "sign up with",
]

# CAPTCHA / block signals
_CAPTCHA_TEXT_PATTERNS = [
    "please verify",
    "security check",
    "are you human",
    "captcha",
    "i'm not a robot",
    "access denied",
    "rate limit",
    "too many requests",
    "403 forbidden",
    "blocked",
]

# Video URL pattern: /video/<id> under a TikTok profile
_VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[\w.]+/video/(\d{10,25})",
)
_VIDEO_PATH_RE = re.compile(
    r'/@([\w.]+)/video/(\d{10,25})',
)

# Script tag with SSR data
_UNIVERSAL_DATA_RE = re.compile(
    r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_SIGI_STATE_RE = re.compile(
    r'<script[^>]*id="SIGI_STATE"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def detect_login_wall(url: str, page_text: str) -> bool:
    """Return True if this looks like a login wall."""
    url_lower = url.lower()
    for pat in _LOGIN_URL_PATTERNS:
        if re.search(pat, url_lower):
            return True
    text_lower = page_text.lower()
    for phrase in _LOGIN_TEXT_PATTERNS:
        if phrase in text_lower:
            return True
    return False


def detect_captcha_or_block(page_text: str) -> bool:
    """Return True if this looks like a captcha or block page."""
    text_lower = page_text.lower()
    for phrase in _CAPTCHA_TEXT_PATTERNS:
        if phrase in text_lower:
            return True
    return False


def extract_video_urls_from_dom(html: str, handle: str) -> List[str]:
    """
    Extract video URLs from rendered HTML anchor hrefs.
    Matches both absolute (https://tiktok.com/@h/video/ID) and
    relative paths (/@handle/video/ID).
    """
    seen_ids: set = set()
    urls: List[str] = []

    handle_lower = handle.lower().lstrip("@")

    # Absolute URLs
    for m in _VIDEO_URL_RE.finditer(html):
        vid_id = m.group(1)
        url = m.group(0)
        # Only include videos from this creator's profile
        if handle_lower in url.lower() and vid_id not in seen_ids:
            seen_ids.add(vid_id)
            urls.append(f"https://www.tiktok.com/@{handle_lower}/video/{vid_id}")

    # Relative paths (when absolute URLs not present)
    if not urls:
        for m in _VIDEO_PATH_RE.finditer(html):
            path_handle = m.group(1).lower()
            vid_id = m.group(2)
            # Only include paths that belong to this creator
            if path_handle == handle_lower and vid_id not in seen_ids:
                seen_ids.add(vid_id)
                urls.append(f"https://www.tiktok.com/@{handle_lower}/video/{vid_id}")

    return urls


def extract_video_urls_from_script_json(html: str, handle: str) -> List[str]:
    """
    Extract video URLs from __UNIVERSAL_DATA_FOR_REHYDRATION__ or SIGI_STATE
    script tags. TikTok SSR itemList is typically empty, but worth checking.
    """
    urls: List[str] = []
    handle_lower = handle.lower().lstrip("@")

    for pattern in (_UNIVERSAL_DATA_RE, _SIGI_STATE_RE):
        m = pattern.search(html)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

        # Walk the JSON looking for itemList or video id arrays
        items = _find_item_list(data)
        for item in items:
            vid_id = item.get("id") or item.get("videoId")
            if vid_id:
                urls.append(f"https://www.tiktok.com/@{handle_lower}/video/{vid_id}")

    return urls


def _find_item_list(obj, depth: int = 0) -> list:
    """Recursively search for itemList arrays in JSON data."""
    if depth > 8:
        return []
    if isinstance(obj, dict):
        if "itemList" in obj and isinstance(obj["itemList"], list):
            return obj["itemList"]
        for v in obj.values():
            result = _find_item_list(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_item_list(item, depth + 1)
            if result:
                return result
    return []


def extract_metadata_from_script_json(html: str) -> dict:
    """
    Extract display_name, follower_count, bio from SSR JSON.
    Returns empty dict on failure.
    """
    for pattern in (_UNIVERSAL_DATA_RE, _SIGI_STATE_RE):
        m = pattern.search(html)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

        user_info = _find_user_info(data)
        if user_info:
            return user_info

    return {}


def _find_user_info(obj, depth: int = 0) -> dict:
    """Recursively find userInfo / user metadata in SSR JSON."""
    if depth > 8:
        return {}
    if isinstance(obj, dict):
        # TikTok SSR pattern: webapp.user-detail.userInfo.user + .stats
        if "user" in obj and "stats" in obj:
            user = obj.get("user", {})
            stats = obj.get("stats", {})
            if isinstance(user, dict) and user.get("uniqueId"):
                return {
                    "display_name": user.get("nickname"),
                    "follower_count": stats.get("followerCount"),
                    "bio": user.get("signature") or None,
                }
        for v in obj.values():
            result = _find_user_info(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_user_info(item, depth + 1)
            if result:
                return result
    return {}


# ---------------------------------------------------------------------------
# Network response collector (used during Playwright evaluation)
# ---------------------------------------------------------------------------

def parse_item_list_api_response(body: str, handle: str) -> List[str]:
    """
    Parse a captured /api/post/item_list/ XHR response body.
    Returns video URLs if items are present.
    """
    urls: List[str] = []
    handle_lower = handle.lower().lstrip("@")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return urls

    items = data.get("itemList") or []
    for item in items:
        vid_id = item.get("id")
        if vid_id:
            urls.append(f"https://www.tiktok.com/@{handle_lower}/video/{vid_id}")
    return urls


# ---------------------------------------------------------------------------
# Browser evaluation (requires playwright)
# ---------------------------------------------------------------------------

BROWSER_TIMEOUT_MS = 20_000   # 20s page load timeout
NETWORK_IDLE_TIMEOUT_MS = 8_000  # wait up to 8s for network idle after load


def evaluate_profile(handle: str, *, headless: bool = True) -> BrowserProfileResult:
    """
    Open a TikTok public profile page in Playwright Chromium and evaluate
    what data is accessible without authentication.

    This function NEVER writes to the database.
    It NEVER logs in or sends cookies.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return BrowserProfileResult(
            handle=handle,
            profile_url=f"https://www.tiktok.com/@{handle}",
            error_message="playwright not installed — run: pip install playwright && python -m playwright install chromium",
        )

    handle_clean = handle.lstrip("@")
    profile_url = f"https://www.tiktok.com/@{handle_clean}"
    result = BrowserProfileResult(handle=handle_clean, profile_url=profile_url)

    # Collect network responses for /api/post/item_list/
    network_video_urls: List[str] = []

    t_start = time.monotonic()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            ctx = browser.new_context(
                # Minimal browser fingerprint — standard UA, no custom headers
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                # No stored cookies, no session state
                storage_state=None,
            )
            page = ctx.new_page()

            # Intercept network responses to catch /api/post/item_list/ XHR
            def _on_response(response):
                try:
                    if "/api/post/item_list/" in response.url:
                        body = response.text()
                        urls = parse_item_list_api_response(body, handle_clean)
                        network_video_urls.extend(urls)
                        _log.debug(
                            "[sc1.2d] network_item_list handle=%s urls=%d",
                            handle_clean, len(urls),
                        )
                except Exception:
                    pass

            page.on("response", _on_response)

            # Navigate to profile
            response = page.goto(
                profile_url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )
            result.http_status = response.status if response else None

            # Wait briefly for JS-rendered content
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
            except PWTimeout:
                _log.debug("[sc1.2d] networkidle timeout (non-fatal) handle=%s", handle_clean)

            result.render_time_seconds = time.monotonic() - t_start

            # Grab rendered state
            current_url = page.url
            page_title = page.title()
            html = page.content()

            result.page_title = page_title

            # ── Detection checks ──
            result.login_wall_detected = detect_login_wall(current_url, html)
            result.captcha_or_block_detected = detect_captcha_or_block(html)

            if result.login_wall_detected or result.captcha_or_block_detected:
                result.rendered_success = False
                result.error_message = (
                    "login_wall" if result.login_wall_detected else "captcha_or_block"
                )
                browser.close()
                return result

            result.rendered_success = True

            # ── Method 1: DOM link extraction ──
            dom_urls = extract_video_urls_from_dom(html, handle_clean)
            if dom_urls:
                result.video_urls_found = len(dom_urls)
                result.sample_video_urls = dom_urls[:10]
                result.extraction_method = "dom_links"
                _log.info(
                    "[sc1.2d] dom_links handle=%s found=%d",
                    handle_clean, len(dom_urls),
                )

            # ── Method 2: Script JSON extraction ──
            if not dom_urls:
                script_urls = extract_video_urls_from_script_json(html, handle_clean)
                if script_urls:
                    result.video_urls_found = len(script_urls)
                    result.sample_video_urls = script_urls[:10]
                    result.extraction_method = "script_json"
                    _log.info(
                        "[sc1.2d] script_json handle=%s found=%d",
                        handle_clean, len(script_urls),
                    )

            # ── Method 3: Network response (XHR intercept) ──
            if not result.video_urls_found and network_video_urls:
                result.video_urls_found = len(network_video_urls)
                result.sample_video_urls = network_video_urls[:10]
                result.extraction_method = "network_response"
                _log.info(
                    "[sc1.2d] network_response handle=%s found=%d",
                    handle_clean, len(network_video_urls),
                )

            # ── Metadata extraction ──
            meta = extract_metadata_from_script_json(html)
            if meta:
                result.metadata_found = True
                result.display_name = meta.get("display_name")
                result.follower_count = meta.get("follower_count")
                bio = meta.get("bio")
                if bio:
                    result.bio_found = True
                    result.bio = bio[:120]

            browser.close()

    except Exception as exc:
        result.render_time_seconds = time.monotonic() - t_start
        result.rendered_success = False
        result.error_message = str(exc)[:200]
        _log.error("[sc1.2d] evaluate_profile error handle=%s: %s", handle_clean, exc)

    return result
