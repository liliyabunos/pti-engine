from __future__ import annotations

"""
IG1-R — Admin Instagram Public Content App Review Demo.

Provides read-only endpoints for the Meta App Review demo flow.

GET /api/v1/admin/instagram-review/status
    → Returns Instagram configuration status and account context.
    → Safe to call even when env vars are missing (returns configured=false).

GET /api/v1/admin/instagram-review/demo?hashtag=perfume
    → Runs a live hashtag search + recent media fetch against the Instagram
      Graph API. Returns a sanitized sample (≤5 items).
    → Returns 503 when INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ACCOUNT_ID
      are not set — never 500 noise.

Authorization model (identical to admin_source_intake.py):
    - All requests require X-Pti-Admin-User header.
    - Header is injected by the Next.js server route /api/admin/instagram-review
      ONLY after Supabase session verification against ADMIN_EMAILS / ADMIN_USER_IDS.
    - Browser cannot forge this header.

Security rules:
    - Access tokens are NEVER returned in any response.
    - INSTAGRAM_BUSINESS_ACCOUNT_ID is returned (it is a non-secret numeric ID
      used as a query parameter in public Graph API calls, not a secret).
    - This is a read-only demo flow — no Instagram content is persisted to DB.
    - The hashtag parameter is validated against an allowlist.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

_IG_GRAPH_BASE = "https://graph.facebook.com/v21.0"

# Hashtags allowed in the demo (prevents open-ended queries)
_DEMO_HASHTAG_ALLOWLIST = {
    "perfume",
    "fragrance",
    "nicheperfume",
    "fragrancecommunity",
    "perfumereview",
    "scentsoftheday",
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_admin_user(
    x_pti_admin_user: Optional[str] = Header(None),
) -> str:
    if not x_pti_admin_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_pti_admin_user


# ---------------------------------------------------------------------------
# Instagram credentials helper
# ---------------------------------------------------------------------------

def _get_ig_credentials() -> tuple[str, str] | None:
    """Return (access_token, ig_user_id) or None if either is missing."""
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()
    if not token or not user_id:
        return None
    return token, user_id


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class IGStatusResponse(BaseModel):
    configured: bool
    ig_business_account_id: Optional[str] = None
    username: Optional[str] = None
    error: Optional[str] = None


class IGMediaItem(BaseModel):
    id: str
    media_type: Optional[str] = None
    timestamp: Optional[str] = None
    permalink: Optional[str] = None
    caption_preview: Optional[str] = None  # first 200 chars only
    like_count: Optional[int] = None


class IGDemoResponse(BaseModel):
    hashtag: str
    hashtag_id: str
    items: List[IGMediaItem]
    total_returned: int
    note: str = (
        "FragranceIndex.ai uses this data to generate aggregated fragrance "
        "trend intelligence. Raw post content is not exposed publicly."
    )


# ---------------------------------------------------------------------------
# Graph API helpers
# ---------------------------------------------------------------------------

async def _resolve_hashtag_id(token: str, user_id: str, hashtag: str) -> str:
    """Resolve a hashtag text → IG Hashtag Object ID."""
    url = f"{_IG_GRAPH_BASE}/ig_hashtag_search"
    params = {
        "user_id": user_id,
        "q": hashtag,
        "fields": "id",
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
    if resp.status_code != 200:
        logger.error(
            "ig_hashtag_search failed status=%s body=%s",
            resp.status_code, resp.text[:200],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Instagram API error: {resp.status_code}",
        )
    data = resp.json()
    items = data.get("data", [])
    if not items:
        raise HTTPException(status_code=404, detail="Hashtag not found via Instagram API")
    return items[0]["id"]


async def _fetch_recent_media(
    token: str, user_id: str, hashtag_id: str, limit: int = 5
) -> List[Dict[str, Any]]:
    """Fetch recent media for a hashtag ID (up to limit items)."""
    url = f"{_IG_GRAPH_BASE}/{hashtag_id}/recent_media"
    params = {
        "user_id": user_id,
        "fields": "id,caption,timestamp,permalink,media_type,like_count",
        "limit": str(limit),
        "access_token": token,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
    if resp.status_code != 200:
        logger.error(
            "recent_media failed status=%s body=%s",
            resp.status_code, resp.text[:200],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Instagram recent_media error: {resp.status_code}",
        )
    return resp.json().get("data", [])


async def _fetch_ig_account_username(token: str, user_id: str) -> Optional[str]:
    """Fetch the username for the IG Business Account (for display only)."""
    url = f"{_IG_GRAPH_BASE}/{user_id}"
    params = {"fields": "username", "access_token": token}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
        if resp.status_code == 200:
            return resp.json().get("username")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=IGStatusResponse)
async def get_instagram_status(
    admin_user: str = Depends(_get_admin_user),
) -> IGStatusResponse:
    """
    Return Instagram configuration status and account context.
    Safe when env vars are missing — returns configured=false, no error raised.
    Does NOT return the access token.
    """
    creds = _get_ig_credentials()
    if not creds:
        return IGStatusResponse(
            configured=False,
            error=(
                "INSTAGRAM_ACCESS_TOKEN and/or INSTAGRAM_BUSINESS_ACCOUNT_ID "
                "are not set in environment. Set both in Railway env vars to "
                "enable the demo flow."
            ),
        )

    token, user_id = creds
    username = await _fetch_ig_account_username(token, user_id)
    return IGStatusResponse(
        configured=True,
        ig_business_account_id=user_id,
        username=username,
    )


@router.get("/demo", response_model=IGDemoResponse)
async def run_hashtag_demo(
    hashtag: str = Query(default="perfume", description="Hashtag to demo (no #)"),
    admin_user: str = Depends(_get_admin_user),
) -> IGDemoResponse:
    """
    Run a live Instagram hashtag search + recent media fetch for the demo.
    Returns up to 5 sanitized media items. Token is never returned.
    """
    hashtag = hashtag.lower().strip().lstrip("#")
    if hashtag not in _DEMO_HASHTAG_ALLOWLIST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Hashtag '{hashtag}' is not in the demo allowlist. "
                f"Allowed: {sorted(_DEMO_HASHTAG_ALLOWLIST)}"
            ),
        )

    creds = _get_ig_credentials()
    if not creds:
        raise HTTPException(
            status_code=503,
            detail=(
                "Instagram credentials not configured. "
                "Set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID "
                "in Railway env vars, then retry."
            ),
        )

    token, user_id = creds

    hashtag_id = await _resolve_hashtag_id(token, user_id, hashtag)
    raw_items = await _fetch_recent_media(token, user_id, hashtag_id, limit=5)

    items: List[IGMediaItem] = []
    for item in raw_items:
        caption = item.get("caption") or ""
        items.append(IGMediaItem(
            id=item["id"],
            media_type=item.get("media_type"),
            timestamp=item.get("timestamp"),
            permalink=item.get("permalink"),
            caption_preview=caption[:200] if caption else None,
            like_count=item.get("like_count"),
        ))

    logger.info(
        "instagram_demo hashtag=%s hashtag_id=%s items_returned=%d admin=%s",
        hashtag, hashtag_id, len(items), admin_user,
    )

    return IGDemoResponse(
        hashtag=hashtag,
        hashtag_id=hashtag_id,
        items=items,
        total_returned=len(items),
    )
