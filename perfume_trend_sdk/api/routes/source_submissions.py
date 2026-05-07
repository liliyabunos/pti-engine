from __future__ import annotations

"""
Source submission routes — Submit a Source MVP.

POST /api/v1/source-submissions
  Accepts a URL + terms acceptance from an authenticated user.
  Stores for manual review — no automatic ingestion, no score manipulation.

Status values assigned at submission time:
  pending              — YouTube direct /channel/UC... URL, new, ready for operator review
  needs_manual_resolve — YouTube handle/@/video/shorts URL, requires channel_id resolution
  platform_pending     — TikTok / Instagram / Reddit / blog (no ingestion pipeline yet)
  already_tracked      — YouTube channel already present in youtube_channels table

SC1.1 TikTok handling (correction 5):
  TikTok video URL + context → canonical_content_item (mention_weight_override=0.7) + source_submission
  TikTok video URL without context → source_submission only (status=platform_pending)
  TikTok channel/profile URL → source_submission only (status=platform_pending)
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.schemas.source_submissions import (
    SourceSubmissionRequest,
    SourceSubmissionResponse,
)

router = APIRouter()
_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tracking / UTM params stripped during normalization
_STRIP_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "si", "feature", "ab_channel",
    "fbclid", "gclid",
})

# YouTube hosts (bare, after www./m. stripping)
_YOUTUBE_BARE_HOSTS = frozenset({"youtube.com"})

# UC... channel ID — same regex as manage_channels.py
_CHANNEL_ID_RE = re.compile(r"UC[a-zA-Z0-9_-]{22}")

# TikTok video URL pattern — SC1.1
_TIKTOK_VIDEO_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._]+)/video/(\d{10,25})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# URL utilities (pure — no DB, no network calls)
# ---------------------------------------------------------------------------

def _normalize_url(raw: str) -> str:
    """Normalize a URL for deduplication.

    - Lowercase scheme and host
    - Strip www. and m. prefixes
    - Remove tracking query params (UTM, fbclid, gclid, …)
    - Strip fragment
    - Strip trailing slash from path (except bare root)
    """
    try:
        parsed = urlparse(raw.strip())
        # Strip www. and m. prefixes from host
        host = re.sub(r"^(?:www\.|m\.)", "", parsed.netloc.lower())
        path = parsed.path.rstrip("/") or "/"
        filtered_params = [
            (k, v) for k, v in parse_qsl(parsed.query)
            if k.lower() not in _STRIP_PARAMS
        ]
        query = urlencode(filtered_params) if filtered_params else ""
        return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))
    except Exception:
        return raw.strip().lower()


def _detect_platform(url: str) -> Optional[str]:
    """Auto-detect platform from URL host.

    Handles www. / m. variants explicitly.
    """
    try:
        host = re.sub(r"^(?:www\.|m\.)", "", urlparse(url).netloc.lower())
    except Exception:
        return None
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "tiktok.com" in host:
        return "tiktok"
    if "instagram.com" in host:
        return "instagram"
    if "reddit.com" in host:
        return "reddit"
    return None


def _classify_youtube_url_type(url: str) -> str:
    """Classify a YouTube URL into a promotion-relevant type.

    Returns:
      'channel_direct'     — /channel/UC... with extractable channel_id (promotable in S1)
      'handle'             — /@handle, /c/name, /user/name (needs API resolution)
      'video'              — /watch?v= or youtu.be/... (needs API resolution)
      'shorts'             — /shorts/ (needs API resolution)
      'other'              — other YouTube-hosted path
    """
    try:
        parsed = urlparse(url)
        host = re.sub(r"^(?:www\.|m\.)", "", parsed.netloc.lower())
        path = parsed.path
        query = parsed.query
    except Exception:
        return "other"

    if host == "youtu.be":
        return "video"

    if host not in _YOUTUBE_BARE_HOSTS:
        return "other"

    if "/channel/" in path and _CHANNEL_ID_RE.search(path):
        return "channel_direct"
    if path.startswith("/@") or "/c/" in path or "/user/" in path:
        return "handle"
    if "/shorts/" in path:
        return "shorts"
    if "/watch" in path or "v=" in query:
        return "video"
    return "other"


def _extract_channel_id(url: str) -> Optional[str]:
    """Extract UC... channel_id from a /channel/UC... URL path only.

    Returns None for handles, video URLs, shorts, or youtu.be links.
    """
    try:
        path = urlparse(url).path
    except Exception:
        return None
    if "/channel/" not in path:
        return None
    m = _CHANNEL_ID_RE.search(path)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# TikTok SC1.1 helpers
# ---------------------------------------------------------------------------

def _is_tiktok_video_url(url: str) -> bool:
    """Return True if url is a TikTok video URL (not a channel/profile)."""
    return bool(_TIKTOK_VIDEO_RE.match(url))


def _save_tiktok_content_item(
    url: str,
    context: str,
    db: Session,
) -> None:
    """Insert a TikTok video URL + context as a canonical_content_item.

    Sets mention_weight_override=0.7 (direct submission with context — enters
    the resolver pipeline but with lower weight than a native ingest).
    Sets tiktok_layer=1.

    Silently skips on duplicate (ON CONFLICT DO NOTHING) — the item may already
    exist from a prior YouTube/Reddit derivation.
    """
    m = _TIKTOK_VIDEO_RE.match(url)
    if not m:
        return

    handle = m.group(1)
    video_id = m.group(2)
    source_url = f"https://www.tiktok.com/@{handle}/video/{video_id}"
    context_snippet = (context or "")[:200]
    now = datetime.now(timezone.utc).isoformat()

    try:
        db.execute(
            text("""
                INSERT INTO canonical_content_items (
                    id, schema_version, source_platform,
                    source_account_handle, source_account_type,
                    source_url, external_content_id,
                    published_at, collected_at,
                    content_type, hashtags_json, mentions_raw_json,
                    media_metadata_json, engagement_json,
                    region, raw_payload_ref, normalizer_version,
                    ingestion_method,
                    tiktok_layer, mention_weight_override,
                    referencing_context
                )
                VALUES (
                    :vid, '1.0', 'tiktok',
                    :handle, 'creator',
                    :source_url, :vid,
                    '', :now,
                    'video', '[]', '[]',
                    '{}', '{}',
                    'US', 'submit_source', '1.0',
                    'submit_source',
                    1, 0.7,
                    :context
                )
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "vid": video_id,
                "handle": handle,
                "source_url": source_url,
                "now": now,
                "context": context_snippet,
            },
        )
    except Exception as exc:
        _log.warning("[source_submissions] TikTok content item insert skipped: %s", exc)


# ---------------------------------------------------------------------------
# Status determination (uses DB for already_tracked check)
# ---------------------------------------------------------------------------

def _determine_initial_status(url: str, platform: Optional[str], db: Session) -> str:
    """Determine the correct initial status for a new submission.

    YouTube channel_direct URLs:
      → checks youtube_channels; returns 'already_tracked' or 'pending'
    YouTube handle/video/shorts:
      → 'needs_manual_resolve'
    Non-YouTube:
      → 'platform_pending'
    """
    if platform != "youtube":
        return "platform_pending"

    url_type = _classify_youtube_url_type(url)

    if url_type in ("handle", "video", "shorts", "other"):
        return "needs_manual_resolve"

    if url_type == "channel_direct":
        channel_id = _extract_channel_id(url)
        if channel_id:
            try:
                row = db.execute(
                    text("SELECT 1 FROM youtube_channels WHERE channel_id = :cid"),
                    {"cid": channel_id},
                ).fetchone()
                if row:
                    return "already_tracked"
            except Exception as exc:
                _log.warning("[source_submissions] youtube_channels check failed: %s", exc)

    return "pending"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=SourceSubmissionResponse,
    status_code=201,
    summary="Submit a public source for review",
)
def submit_source(
    body: SourceSubmissionRequest,
    db: Session = Depends(get_db_session),
) -> SourceSubmissionResponse:
    """Accept a URL submission from an authenticated user.

    - Normalizes the URL for deduplication
    - Auto-detects platform
    - Classifies YouTube URL type; sets status accordingly
    - Checks youtube_channels for already-tracked channels
    - Stores with correct status for operator review
    - Returns 409 if the normalized URL was already submitted
    - No automatic ingestion. No score manipulation.
    """
    normalized = _normalize_url(body.url)
    platform = _detect_platform(body.url)
    initial_status = _determine_initial_status(body.url, platform, db)
    now = datetime.now(timezone.utc)

    # SC1.1: TikTok video + context → create canonical_content_item for resolver pipeline.
    # This must happen before the source_submission insert so the content item exists first.
    tiktok_item_created = False
    if platform == "tiktok" and _is_tiktok_video_url(body.url):
        context = (body.context or "").strip()
        if context:
            _save_tiktok_content_item(body.url, context, db)
            tiktok_item_created = True

    # Duplicate check — UNIQUE constraint on normalized_url prevents duplicates
    existing = db.execute(
        text("SELECT id FROM source_submissions WHERE normalized_url = :u"),
        {"u": normalized},
    ).fetchone()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="This source has already been submitted and is under review.",
        )

    # Insert
    try:
        result = db.execute(
            text("""
                INSERT INTO source_submissions
                    (raw_url, normalized_url, platform, status,
                     submitted_by_user_id, submitted_by_email, terms_accepted_at, created_at)
                VALUES
                    (:raw, :norm, :platform, :status,
                     :user_id, :email, :terms_at, :now)
                RETURNING id
            """),
            {
                "raw": body.url,
                "norm": normalized,
                "platform": platform,
                "status": initial_status,
                "user_id": body.submitted_by_user_id,
                "email": body.submitted_by_email,
                "terms_at": now if body.terms_accepted else None,
                "now": now,
            },
        )
        row = result.fetchone()
        db.commit()
    except Exception as exc:
        db.rollback()
        _log.error("[source_submissions] insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Submission failed. Please try again.")

    # Build response message based on status
    if initial_status == "already_tracked":
        message = "This source is already tracked by FragranceIndex.ai."
    elif initial_status == "needs_manual_resolve":
        message = "Thank you! This URL requires manual review to resolve the channel."
    elif initial_status == "platform_pending":
        if tiktok_item_created:
            message = "Thank you! This TikTok video has been submitted for analysis."
        elif platform == "tiktok" and _is_tiktok_video_url(body.url):
            message = "Thank you! Add a context note to help us analyze this TikTok video."
        else:
            message = "Thank you! This platform is on our roadmap — we'll review your suggestion."
    else:
        message = "Thank you! Your submission is under review."

    return SourceSubmissionResponse(
        id=row[0],
        normalized_url=normalized,
        platform=platform,
        status=initial_status,
        message=message,
    )
