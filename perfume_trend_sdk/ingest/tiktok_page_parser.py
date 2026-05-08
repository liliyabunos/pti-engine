from __future__ import annotations

"""
SC1.2C — TikTok public profile page parser.

Extracts what is available from a TikTok creator profile page via simple HTTP.

LIMITATION (verified 2026-05-08):
    TikTok's profile page SSR JSON includes user metadata (userInfo, stats)
    but the video feed (itemList) is always empty in the server-rendered
    response. Video lists are loaded client-side via the internal
    /api/post/item_list/ endpoint which requires authenticated session cookies.

    This parser therefore:
      - Verifies the creator profile exists and is public (statusCode=0)
      - Extracts follower_count, video_count, verified, secUid from userInfo
      - Returns an empty video list with VIDEO_LIST_REQUIRES_AUTH flag set

    Video discovery will require a separate approved approach (e.g. TikTok
    Research API access or a separately approved browser-based method).
    That will be implemented in a future phase — NOT in SC1.2C.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

_log = logging.getLogger(__name__)

_UNIVERSAL_DATA_RE = re.compile(
    r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Status codes from TikTok's API
_STATUS_OK = 0
_STATUS_USER_NOT_FOUND = 10221


@dataclass
class TikTokProfileResult:
    handle: str
    reachable: bool = False
    status_code: Optional[int] = None
    # User metadata (when reachable)
    verified: bool = False
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    video_count: Optional[int] = None
    heart_count: Optional[int] = None
    sec_uid: Optional[str] = None
    nickname: Optional[str] = None
    # Video discovery
    video_ids: List[str] = field(default_factory=list)
    video_list_requires_auth: bool = False
    # Error info
    error: Optional[str] = None
    http_status: Optional[int] = None


def parse_profile_page(handle: str, html: str) -> TikTokProfileResult:
    """
    Parse a TikTok creator profile page HTML.

    Returns TikTokProfileResult with whatever data is available.
    Never raises — all errors are captured in result.error.
    """
    result = TikTokProfileResult(handle=handle)

    if not html:
        result.error = "empty HTML response"
        return result

    m = _UNIVERSAL_DATA_RE.search(html)
    if not m:
        result.error = "no __UNIVERSAL_DATA_FOR_REHYDRATION__ script tag found"
        return result

    try:
        data = json.loads(m.group(1))
    except Exception as exc:
        result.error = f"JSON parse error: {exc}"
        return result

    try:
        scope = data.get("__DEFAULT_SCOPE__", {})
        user_detail = scope.get("webapp.user-detail", {})
        status_code = user_detail.get("statusCode")
        result.status_code = status_code

        if status_code == _STATUS_USER_NOT_FOUND:
            result.reachable = False
            result.error = f"TikTok statusCode={status_code} (user not found or private)"
            return result

        if status_code != _STATUS_OK:
            result.reachable = False
            result.error = f"TikTok statusCode={status_code}"
            return result

        result.reachable = True
        user_info = user_detail.get("userInfo", {})
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})
        stats_v2 = user_info.get("statsV2", {})

        result.sec_uid = user.get("secUid")
        result.nickname = user.get("nickname")
        result.verified = bool(user.get("verified", False))

        # Prefer statsV2 (string values) then stats (int values)
        def _int_stat(key: str) -> Optional[int]:
            v = stats_v2.get(key) or stats.get(key)
            if v is None:
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
                return None

        result.follower_count = _int_stat("followerCount")
        result.following_count = _int_stat("followingCount")
        result.video_count = _int_stat("videoCount")
        result.heart_count = _int_stat("heartCount") or _int_stat("diggCount")

        # Video list — always empty in SSR; flag this clearly
        item_list = user_info.get("itemList", [])
        if item_list:
            # If TikTok ever starts including items, capture them
            result.video_ids = [
                str(item["id"])
                for item in item_list
                if isinstance(item, dict) and "id" in item
            ]
        else:
            result.video_list_requires_auth = True

    except Exception as exc:
        result.error = f"data extraction error: {exc}"

    return result
