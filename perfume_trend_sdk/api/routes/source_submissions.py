from __future__ import annotations

"""
Source submission routes — Submit a Source MVP.

POST /api/v1/source-submissions
  Accepts a URL + terms acceptance from an authenticated user.
  Stores for manual review — no automatic ingestion, no score manipulation.
"""

import logging
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

# UTM and tracking params stripped during normalization
_STRIP_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "si", "feature", "ab_channel",
})


def _normalize_url(raw: str) -> str:
    """Normalize a URL for deduplication.

    - Lowercase scheme and host
    - Strip www. prefix
    - Remove tracking query params
    - Strip fragment
    - Strip trailing slash from path
    """
    try:
        parsed = urlparse(raw.strip())
        host = parsed.netloc.lower().lstrip("www.")
        path = parsed.path.rstrip("/") or "/"
        # Filter out tracking params
        filtered_params = [
            (k, v) for k, v in parse_qsl(parsed.query)
            if k.lower() not in _STRIP_PARAMS
        ]
        query = urlencode(filtered_params) if filtered_params else ""
        return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))
    except Exception:
        return raw.strip().lower()


def _detect_platform(url: str) -> Optional[str]:
    """Auto-detect platform from URL host."""
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
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
    - Stores with status=pending for manual review
    - Returns 409 if the normalized URL was already submitted
    - No automatic ingestion or score manipulation
    """
    normalized = _normalize_url(body.url)
    platform = _detect_platform(body.url)
    now = datetime.now(timezone.utc)

    # Duplicate check
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
                    (:raw, :norm, :platform, 'pending',
                     :user_id, :email, :terms_at, :now)
                RETURNING id
            """),
            {
                "raw": body.url,
                "norm": normalized,
                "platform": platform,
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

    return SourceSubmissionResponse(
        id=row[0],
        normalized_url=normalized,
        platform=platform,
        status="pending",
        message="Thank you! Your submission is under review.",
    )
