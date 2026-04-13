from __future__ import annotations

"""
TikTok Research API client — keyword-based video search.

Docs: https://developers.tiktok.com/products/research-api/
Endpoint: POST /v2/research/video/query/

Auth: OAuth 2.0 client_credentials flow.
  Env vars required:
    TIKTOK_CLIENT_KEY    — app client key
    TIKTOK_CLIENT_SECRET — app client secret

Usage:
    client = TikTokWatchlistClient()
    videos, next_cursor = client.search_videos(
        query="Parfums de Marly Delina",
        start_date="20260401",
        end_date="20260410",
    )
    while next_cursor is not None:
        more, next_cursor = client.search_videos(
            ..., cursor=next_cursor
        )
"""

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# TikTok Research API base URL
_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_SEARCH_URL = "https://open.tiktokapis.com/v2/research/video/query/"

# Fields requested in every video query response.
# Must be specified explicitly — TikTok returns nothing without this param.
_VIDEO_FIELDS = ",".join([
    "id",
    "create_time",
    "username",
    "region_code",
    "video_description",
    "music_id",
    "like_count",
    "comment_count",
    "share_count",
    "view_count",
    "hashtag_names",
    "voice_to_text",
    "duration",
])

# Retry configuration
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0   # seconds; doubles each attempt
_RATE_LIMIT_WAIT = 60.0     # seconds to wait on 429


class TikTokAPIError(Exception):
    """Raised on non-retryable TikTok API errors (auth, bad request)."""


class TikTokWatchlistClient:
    """
    Real client for the TikTok Research API v2.

    Obtains a client_credentials access token on first use, caches it in
    memory, and refreshes automatically when it expires.

    Only search_videos() is implemented — per-account fetch_user_posts()
    remains a stub because the watchlist-by-keyword strategy is preferred
    and the Research API does not expose a simple per-account endpoint
    with the same convenience as the search endpoint.
    """

    def __init__(
        self,
        *,
        accounts: Optional[List[Dict]] = None,  # kept for connector compatibility
        client_key: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout_seconds: int = 30,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._client_key = client_key or os.getenv("TIKTOK_CLIENT_KEY", "")
        self._client_secret = client_secret or os.getenv("TIKTOK_CLIENT_SECRET", "")
        self._timeout = timeout_seconds
        self._max_retries = max_retries

        # In-memory token cache
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0  # epoch seconds

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search_videos(
        self,
        query: str,
        start_date: str,
        end_date: str,
        *,
        max_count: int = 100,
        cursor: int = 0,
    ) -> Tuple[List[Dict], Optional[int]]:
        """
        Search TikTok videos by keyword using the Research API.

        Args:
            query:      Keyword to search (e.g. "Parfums de Marly Delina").
            start_date: Inclusive start date in YYYYMMDD format.
            end_date:   Inclusive end date in YYYYMMDD format.
            max_count:  Videos per page (max 100 per API docs).
            cursor:     Pagination cursor from a previous response (0 = first page).

        Returns:
            (videos, next_cursor) where:
              videos      — list of raw video dicts as returned by the API,
                            normalised to match the fixture schema the parser expects.
              next_cursor — integer cursor for the next page, or None if exhausted.

        Raises:
            TikTokAPIError: on auth failures or 4xx responses that are not retryable.
        """
        logger.info(
            "tiktok_search_started query=%r start=%s end=%s cursor=%d max_count=%d",
            query, start_date, end_date, cursor, max_count,
        )

        token = self._get_token()
        payload = {
            "query": {
                "and": [{"operation": "IN", "field_name": "keyword", "field_values": [query]}]
            },
            "max_count": min(max_count, 100),
            "cursor": cursor,
            "start_date": start_date,
            "end_date": end_date,
        }

        raw = self._post(
            url=f"{_SEARCH_URL}?fields={_VIDEO_FIELDS}",
            payload=payload,
            token=token,
        )

        data = raw.get("data", {})
        raw_videos: List[Dict] = data.get("videos", [])
        has_more: bool = data.get("has_more", False)
        # Guard: treat cursor=0 or cursor=None the same as "no next page".
        # TikTok uses 0 as the initial request cursor; receiving it back in a
        # response with has_more=True would cause an infinite pagination loop.
        raw_cursor = data.get("cursor")
        next_cursor: Optional[int] = raw_cursor if (has_more and raw_cursor) else None

        # Translate Research API field names → parser-compatible schema
        videos = [self._translate(v) for v in raw_videos]

        logger.info(
            "tiktok_search_completed query=%r count=%d has_more=%s next_cursor=%s",
            query, len(videos), has_more, next_cursor,
        )

        return videos, next_cursor

    def fetch_user_posts(
        self,
        handle: str,
        max_count: int = 25,
        published_after: Optional[str] = None,
    ) -> List[Dict]:
        """
        Per-account post fetch — stub retained for connector interface compatibility.

        The Research API does not expose a simple per-account search endpoint
        without additional account-level OAuth scopes. Use search_videos() with
        a creator-name query for watchlist-style monitoring instead.
        """
        logger.warning(
            "tiktok_fetch_user_posts_stub handle=%r — "
            "use search_videos() for keyword-based ingestion; "
            "per-account fetch requires user-level OAuth scopes not available in v1",
            handle,
        )
        return []

    # ------------------------------------------------------------------
    # OAuth — client_credentials token
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid access token, fetching a new one if expired."""
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        if not self._client_key or not self._client_secret:
            raise TikTokAPIError(
                "TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET must be set. "
                "Apply for Research API access at "
                "https://developers.tiktok.com/products/research-api/"
            )

        logger.info("tiktok_token_refresh client_key=%s", self._client_key[:6] + "***")

        resp = requests.post(
            _TOKEN_URL,
            data={
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self._timeout,
        )

        if resp.status_code == 401:
            raise TikTokAPIError(
                f"TikTok auth failed (HTTP 401) — check TIKTOK_CLIENT_KEY / "
                f"TIKTOK_CLIENT_SECRET. Response: {resp.text[:200]}"
            )
        resp.raise_for_status()

        body = resp.json()
        self._access_token = body["access_token"]
        expires_in: int = body.get("expires_in", 7200)
        self._token_expires_at = time.time() + expires_in

        logger.info("tiktok_token_obtained expires_in=%ds", expires_in)
        return self._access_token

    # ------------------------------------------------------------------
    # HTTP — POST with retry
    # ------------------------------------------------------------------

    def _post(self, url: str, payload: Dict, token: str) -> Dict:
        """POST to a TikTok Research API endpoint with retry on 429 / 5xx."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                wait = _RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "tiktok_request_error attempt=%d/%d exc=%s retrying_in=%.0fs",
                    attempt, self._max_retries, exc, wait,
                )
                time.sleep(wait)
                continue

            if resp.status_code == 401:
                # Auth error — fail fast, no retry.
                # Invalidate the cached token so the next search_videos() call
                # fetches a fresh one instead of reusing the stale token.
                self._access_token = None
                raise TikTokAPIError(
                    f"TikTok API auth error (HTTP 401) — token may have expired. "
                    f"Response: {resp.text[:200]}"
                )

            if resp.status_code == 429:
                wait = _RATE_LIMIT_WAIT
                logger.warning(
                    "tiktok_rate_limited attempt=%d/%d waiting=%.0fs",
                    attempt, self._max_retries, wait,
                )
                time.sleep(wait)
                continue

            if resp.status_code in _RETRY_STATUSES:
                wait = _RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "tiktok_server_error attempt=%d/%d status=%d retrying_in=%.0fs",
                    attempt, self._max_retries, resp.status_code, wait,
                )
                time.sleep(wait)
                continue

            if not resp.ok:
                # 4xx other than 401/429 — fail fast
                raise TikTokAPIError(
                    f"TikTok API error HTTP {resp.status_code}: {resp.text[:400]}"
                )

            body = resp.json()
            # Research API wraps errors in {"error": {"code": ..., "message": ...}}
            error = body.get("error", {})
            if error and error.get("code") not in (None, 0, "ok"):
                raise TikTokAPIError(
                    f"TikTok API error code={error.get('code')!r} "
                    f"message={error.get('message')!r}"
                )

            return body

        # All retries exhausted
        raise TikTokAPIError(
            f"TikTok API request failed after {self._max_retries} attempts. "
            f"Last error: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Field translation — Research API → parser schema
    # ------------------------------------------------------------------

    @staticmethod
    def _translate(v: Dict) -> Dict:
        """
        Map a Research API video object to the field schema TikTokParser expects.

        Research API response fields  →  Parser fixture schema
        ─────────────────────────────────────────────────────
        id                           →  id
        create_time  (epoch int)     →  createTime
        username                     →  author.uniqueId  (+ synthetic author dict)
        video_description            →  desc
        view_count                   →  stats.playCount
        like_count                   →  stats.diggCount
        comment_count                →  stats.commentCount
        share_count                  →  stats.shareCount
        duration                     →  video.duration
        hashtag_names (list[str])    →  challenges (list of {"title": name})
        """
        hashtags = v.get("hashtag_names") or []
        return {
            "id": str(v.get("id", "")),
            "desc": v.get("video_description") or "",
            "createTime": v.get("create_time") or 0,
            "author": {
                "id": v.get("username", ""),   # Research API has no numeric author ID
                "uniqueId": v.get("username", ""),
                "nickname": v.get("username", ""),
                "followerCount": 0,            # not returned by search endpoint
                "verified": False,
            },
            "stats": {
                "playCount": v.get("view_count") or 0,
                "diggCount": v.get("like_count") or 0,
                "commentCount": v.get("comment_count") or 0,
                "shareCount": v.get("share_count") or 0,
            },
            "video": {
                "duration": v.get("duration") or 0,
            },
            "challenges": [{"title": tag} for tag in hashtags],
        }
