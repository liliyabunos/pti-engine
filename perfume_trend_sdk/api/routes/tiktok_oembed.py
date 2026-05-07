from __future__ import annotations

"""
SC1.1 — TikTok oEmbed Proxy

GET /api/v1/tiktok/oembed?url=<tiktok_video_url>

Proxies the public TikTok oEmbed endpoint to avoid CORS issues in the frontend.

Security:
  - Validates that the URL host is tiktok.com before making any network call.
  - Uses a 3-second timeout; returns {"html": null} on any error.
  - Returns only the fields needed for frontend rendering: html, thumbnail_url,
    author_name. No raw platform data is forwarded.

TikTok oEmbed is a public, no-auth endpoint:
  https://www.tiktok.com/oembed?url=<video_url>

Compliance:
  - We do not store oEmbed responses.
  - This is a pass-through proxy for official TikTok markup only.
  - No private data is involved — oEmbed returns only public embed HTML.
"""

import json as _json
import logging
import re
import urllib.request
from typing import Optional
from urllib.parse import quote as _url_quote, urlparse

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter()
_log = logging.getLogger(__name__)

_TIKTOK_OEMBED_ENDPOINT = "https://www.tiktok.com/oembed"
_ALLOWED_HOSTS = frozenset({"tiktok.com"})
_TIKTOK_VIDEO_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._]+/video/\d{10,25}",
    re.IGNORECASE,
)
_SAFE_FALLBACK: dict = {"html": None}


def _validate_tiktok_url(url: str) -> bool:
    """Return True only if url is a valid TikTok video URL on tiktok.com."""
    try:
        parsed = urlparse(url)
        host = re.sub(r"^(?:www\.|m\.)", "", parsed.netloc.lower())
        if host not in _ALLOWED_HOSTS:
            return False
        return bool(_TIKTOK_VIDEO_RE.match(url))
    except Exception:
        return False


@router.get(
    "/oembed",
    summary="TikTok oEmbed proxy",
    response_class=JSONResponse,
)
def tiktok_oembed(
    url: str = Query(..., description="TikTok video URL to embed"),
) -> dict:
    """Proxy the public TikTok oEmbed endpoint.

    Returns:
        {"html": "<blockquote ...>", "thumbnail_url": "...", "author_name": "..."}
        {"html": null} on validation failure, network error, or non-200 response.
    """
    if not _validate_tiktok_url(url):
        _log.warning("[tiktok_oembed] rejected url: %s", url[:200])
        return _SAFE_FALLBACK

    try:
        oembed_url = f"{_TIKTOK_OEMBED_ENDPOINT}?url={_url_quote(url, safe='')}"
        req = urllib.request.Request(
            oembed_url,
            headers={"User-Agent": "FragranceIndex.ai oEmbed/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status != 200:
                _log.debug("[tiktok_oembed] non-200 from TikTok: %s", resp.status)
                return _SAFE_FALLBACK
            raw = resp.read().decode("utf-8", errors="replace")

        data = _json.loads(raw)
        return {
            "html": data.get("html"),
            "thumbnail_url": data.get("thumbnail_url"),
            "author_name": data.get("author_name"),
        }

    except Exception as exc:
        _log.debug("[tiktok_oembed] fetch failed for %s: %s", url[:100], exc)
        return _SAFE_FALLBACK
