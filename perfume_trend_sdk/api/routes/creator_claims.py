from __future__ import annotations

"""
C2 — Creator Profile Claim API.

POST /api/v1/creator-claims        — submit a claim (bio_code | screenshot | manual_review)
GET  /api/v1/creator-claims/me     — list current user's own claims

Auth: user identity is read from X-Pti-Verified-User-Id header only.
This header is set by the Next.js API route (/api/creator-claims) which
reads the Supabase session server-side. Arbitrary user_id in request body
is never trusted.

Verification: all claims remain pending until operator manual review.
No automatic verification in C2.
creator_oauth_grants remains empty — no OAuth implemented.
"""

import hashlib
import logging
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.schemas.creator_claims import (
    ClaimCreateRequest,
    ClaimListResponse,
    ClaimResponse,
    ClaimSummary,
)

router = APIRouter()
_log = logging.getLogger(__name__)

_CODE_CHARSET = string.ascii_uppercase + string.digits


def _generate_verification_code() -> tuple[str, str]:
    """Generate FTI-XXXXXXXX code. Returns (plaintext, sha256_hex_hash)."""
    plaintext = "FTI-" + "".join(secrets.choice(_CODE_CHARSET) for _ in range(8))
    code_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    return plaintext, code_hash


def _fmt(val) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _get_verified_user_id(
    x_pti_verified_user_id: Optional[str] = Header(None),
) -> str:
    """Extract verified user identity from trusted internal header.

    This header is injected by the Next.js server route after reading the
    Supabase session server-side. It must never be set by browser clients.
    """
    if not x_pti_verified_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_pti_verified_user_id


# ---------------------------------------------------------------------------
# POST /api/v1/creator-claims
# ---------------------------------------------------------------------------

@router.post("", response_model=ClaimResponse, status_code=201, summary="Submit a creator claim")
def create_claim(
    body: ClaimCreateRequest,
    user_id: str = Depends(_get_verified_user_id),
    db: Session = Depends(get_db_session),
) -> ClaimResponse:
    """
    Submit a creator profile claim.

    - user_id is derived server-side from X-Pti-Verified-User-Id header only.
    - Any user_id field in the request body is ignored.
    - Duplicate active (pending/verified) claims are rejected with 409.
    - bio_code claims: returns plaintext verification code once. Store it — it will not be shown again.
    - All claims remain pending until operator manual review.
    - creator_oauth_grants is not touched.
    """
    # Check for existing active claim
    try:
        existing = db.execute(text("""
            SELECT id FROM creator_profile_claims
            WHERE platform = :platform
              AND creator_id = :creator_id
              AND user_id = :user_id
              AND claim_status IN ('pending', 'verified')
            LIMIT 1
        """), {
            "platform": body.platform,
            "creator_id": body.creator_id,
            "user_id": user_id,
        }).fetchone()
    except Exception as exc:
        _log.error("[C2] creator_profile_claims unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Claim service unavailable")

    if existing:
        raise HTTPException(
            status_code=409,
            detail="active_claim_exists",
        )

    # Generate verification code for bio_code claims
    plaintext_code: Optional[str] = None
    code_hash: Optional[str] = None
    expires_at: Optional[datetime] = None

    if body.claim_method == "bio_code":
        plaintext_code, code_hash = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    claim_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        db.execute(text("""
            INSERT INTO creator_profile_claims (
                id, user_id, platform, creator_id,
                claim_status, claim_method,
                verification_code_hash, verification_code_expires_at,
                evidence_url, reviewer_notes,
                claimed_at, created_at
            ) VALUES (
                :id, :user_id, :platform, :creator_id,
                'pending', :claim_method,
                :code_hash, :expires_at,
                :evidence_url, :note,
                :now, :now
            )
        """), {
            "id": claim_id,
            "user_id": user_id,
            "platform": body.platform,
            "creator_id": body.creator_id,
            "claim_method": body.claim_method,
            "code_hash": code_hash,
            "expires_at": expires_at,
            "evidence_url": body.evidence_url,
            "note": body.note,
            "now": now,
        })
    except Exception as exc:
        _log.error("[C2] claim insert failed user=%s creator=%s: %s", user_id, body.creator_id, exc)
        raise HTTPException(status_code=500, detail="Failed to submit claim")

    _log.info(
        "[C2] claim created id=%s method=%s platform=%s creator=%s",
        claim_id, body.claim_method, body.platform, body.creator_id,
    )

    msg = (
        "Claim submitted for review. Add the verification code to your public profile. "
        "Our team will review the public evidence."
        if body.claim_method == "bio_code"
        else "Claim submitted for review. Our team will check the public evidence you provided."
    )

    return ClaimResponse(
        claim_id=claim_id,
        platform=body.platform,
        creator_id=body.creator_id,
        claim_status="pending",
        claim_method=body.claim_method,
        evidence_url=body.evidence_url,
        verification_code=plaintext_code,       # None for non-bio_code
        verification_code_expires_at=_fmt(expires_at),
        message=msg,
        claimed_at=_fmt(now),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/creator-claims/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=ClaimListResponse, summary="List current user's claims")
def list_my_claims(
    platform: Optional[str] = None,
    creator_id: Optional[str] = None,
    user_id: str = Depends(_get_verified_user_id),
    db: Session = Depends(get_db_session),
) -> ClaimListResponse:
    """
    Return the authenticated user's own claims.

    - user_id from X-Pti-Verified-User-Id header only — never from query params.
    - verification_code_hash is never returned.
    - Other users' claims are never returned.
    """
    where = ["cpc.user_id = :user_id"]
    params: dict = {"user_id": user_id}

    if platform:
        where.append("cpc.platform = :platform")
        params["platform"] = platform
    if creator_id:
        where.append("cpc.creator_id = :creator_id")
        params["creator_id"] = creator_id

    where_sql = " AND ".join(where)

    try:
        rows = db.execute(text(f"""
            SELECT
                cpc.id,
                cpc.platform,
                cpc.creator_id,
                cpc.claim_status,
                cpc.claim_method,
                cpc.evidence_url,
                cpc.claimed_at,
                cpc.verified_at,
                cpc.reviewed_at,
                cpc.rejection_reason
            FROM creator_profile_claims cpc
            WHERE {where_sql}
            ORDER BY cpc.created_at DESC
        """), params).fetchall()
    except Exception as exc:
        _log.error("[C2] list_my_claims failed user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail="Claim service unavailable")

    claims = [
        ClaimSummary(
            claim_id=r[0],
            platform=r[1],
            creator_id=r[2],
            claim_status=r[3],
            claim_method=r[4],
            evidence_url=r[5],
            claimed_at=_fmt(r[6]),
            verified_at=_fmt(r[7]),
            reviewed_at=_fmt(r[8]),
            rejection_reason=r[9],
        )
        for r in rows
    ]

    return ClaimListResponse(claims=claims)
