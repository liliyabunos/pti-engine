from __future__ import annotations

"""
C2.1 — Operator Review Console: Admin Creator Claims API.

GET  /api/v1/admin/creator-claims              — list claims (filterable by status)
POST /api/v1/admin/creator-claims/{id}/approve — approve a claim
POST /api/v1/admin/creator-claims/{id}/reject  — reject a claim (reason required)

Authorization model (server-side only):
  - All requests must include the X-Pti-Admin-User header.
  - This header is injected by the Next.js server route ONLY after reading the
    Supabase session and confirming the user's email/ID against the ADMIN_EMAILS
    or ADMIN_USER_IDS environment allowlist.
  - Browser clients cannot forge this header — the Next.js route is the only path.
  - FastAPI rejects any request missing X-Pti-Admin-User with 401.
  - Admin identity from request body or query params is NEVER accepted.

Allowlist note (C2.1 temporary gate):
  This environment-based allowlist is a temporary operator access mechanism.
  Future hardening option: app_admins table or Supabase custom claims.

Hard constraints:
  - Never modifies creator_oauth_grants.
  - Never touches pipeline tables (entity_mentions, canonical_content_items, etc.).
  - Never returns verification_code_hash, access_token_encrypted, or
    refresh_token_encrypted.
  - reviewed_by is set to the admin identifier from the header (not from body).
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.schemas.creator_claims import (
    AdminClaimEntry,
    AdminClaimListResponse,
    AdminRejectRequest,
)

router = APIRouter()
_log = logging.getLogger(__name__)

_VALID_STATUSES = {"pending", "verified", "rejected", "revoked", "all"}


def _get_admin_user(
    x_pti_admin_user: Optional[str] = Header(None),
) -> str:
    """Require X-Pti-Admin-User header — set only by the Next.js server route.

    This header is injected after the Next.js route verifies the Supabase session
    and confirms the user is in the ADMIN_EMAILS / ADMIN_USER_IDS allowlist.
    Requests without this header are always rejected.
    """
    if not x_pti_admin_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_pti_admin_user


def _fmt(val) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/creator-claims
# ---------------------------------------------------------------------------

@router.get("", response_model=AdminClaimListResponse, summary="Admin: list creator claims")
def admin_list_claims(
    status: Optional[str] = "pending",
    limit: int = 100,
    offset: int = 0,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> AdminClaimListResponse:
    """
    List creator profile claims for operator review.

    - Requires X-Pti-Admin-User header (set by Next.js server route only).
    - status: pending (default) | verified | rejected | revoked | all
    - Never returns verification_code_hash or any oauth token fields.
    - Creator display name resolved from youtube_channels if available.
    """
    if status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    where_clauses = []
    params: dict = {"limit": min(limit, 500), "offset": offset}

    if status != "all":
        where_clauses.append("cpc.claim_status = :status")
        params["status"] = status

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        rows = db.execute(text(f"""
            SELECT
                cpc.id,
                cpc.user_id,
                cpc.platform,
                cpc.creator_id,
                cpc.claim_method,
                cpc.claim_status,
                cpc.evidence_url,
                cpc.reviewer_notes,
                cpc.claimed_at,
                cpc.reviewed_at,
                cpc.reviewed_by,
                cpc.rejection_reason,
                COALESCE(yc.title, sp.source_name) AS creator_display_name
            FROM creator_profile_claims cpc
            LEFT JOIN youtube_channels yc
                ON cpc.platform = 'youtube'
               AND cpc.creator_id = yc.channel_id
            LEFT JOIN source_profiles sp
                ON cpc.creator_id = sp.source_id
            {where_sql}
            ORDER BY cpc.claimed_at DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        count_row = db.execute(text(f"""
            SELECT COUNT(*) FROM creator_profile_claims cpc
            {where_sql}
        """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).fetchone()

    except Exception as exc:
        _log.error("[C2.1] admin_list_claims failed admin=%s: %s", admin_user, exc)
        raise HTTPException(status_code=503, detail="Claim service unavailable")

    total = count_row[0] if count_row else 0

    def _profile_url(platform: str, creator_id: str) -> Optional[str]:
        if platform == "youtube":
            return f"/creators/{creator_id}"
        return None

    claims = [
        AdminClaimEntry(
            claim_id=str(r[0]),
            user_id=str(r[1]),
            platform=r[2],
            creator_id=r[3],
            claim_method=r[4],
            claim_status=r[5],
            evidence_url=r[6],
            reviewer_notes=r[7],
            claimed_at=_fmt(r[8]),
            reviewed_at=_fmt(r[9]),
            reviewed_by=r[10],
            rejection_reason=r[11],
            creator_display_name=r[12],
            creator_profile_url=_profile_url(r[2], r[3]),
        )
        for r in rows
    ]

    _log.info(
        "[C2.1] admin_list_claims admin=%s status=%s total=%d returned=%d",
        admin_user, status, total, len(claims),
    )

    return AdminClaimListResponse(claims=claims, total=total)


# ---------------------------------------------------------------------------
# POST /api/v1/admin/creator-claims/{claim_id}/approve
# ---------------------------------------------------------------------------

@router.post(
    "/{claim_id}/approve",
    summary="Admin: approve a creator claim",
    status_code=200,
)
def admin_approve_claim(
    claim_id: str,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    """
    Approve a pending creator profile claim.

    - Sets claim_status='verified', verified_at=NOW(), reviewed_at=NOW().
    - Sets reviewed_by to the admin identifier from X-Pti-Admin-User header.
    - Only pending claims can be approved (404 if not found or wrong status).
    - Never modifies creator_oauth_grants or pipeline tables.
    """
    now = datetime.now(timezone.utc)

    try:
        result = db.execute(text("""
            UPDATE creator_profile_claims
            SET
                claim_status  = 'verified',
                verified_at   = :now,
                reviewed_at   = :now,
                reviewed_by   = :admin_user
            WHERE id = :claim_id
              AND claim_status = 'pending'
            RETURNING id
        """), {
            "claim_id": claim_id,
            "now": now,
            "admin_user": admin_user,
        }).fetchone()
    except Exception as exc:
        _log.error("[C2.1] approve failed admin=%s claim=%s: %s", admin_user, claim_id, exc)
        raise HTTPException(status_code=503, detail="Claim service unavailable")

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Claim not found or not in pending status",
        )

    _log.info("[C2.1] claim approved id=%s by=%s", claim_id, admin_user)
    return {"claim_id": claim_id, "claim_status": "verified", "reviewed_by": admin_user}


# ---------------------------------------------------------------------------
# POST /api/v1/admin/creator-claims/{claim_id}/reject
# ---------------------------------------------------------------------------

@router.post(
    "/{claim_id}/reject",
    summary="Admin: reject a creator claim",
    status_code=200,
)
def admin_reject_claim(
    claim_id: str,
    body: AdminRejectRequest,
    admin_user: str = Depends(_get_admin_user),
    db: Session = Depends(get_db_session),
) -> dict:
    """
    Reject a pending creator profile claim.

    - rejection_reason is required and must not be empty.
    - Sets claim_status='rejected', reviewed_at=NOW(), reviewed_by=admin.
    - Creator may resubmit after rejection (C2 resubmit flow).
    - Only pending claims can be rejected (404 if not found or wrong status).
    - Never modifies creator_oauth_grants or pipeline tables.
    """
    now = datetime.now(timezone.utc)

    try:
        result = db.execute(text("""
            UPDATE creator_profile_claims
            SET
                claim_status     = 'rejected',
                reviewed_at      = :now,
                reviewed_by      = :admin_user,
                rejection_reason = :reason
            WHERE id = :claim_id
              AND claim_status = 'pending'
            RETURNING id
        """), {
            "claim_id": claim_id,
            "now": now,
            "admin_user": admin_user,
            "reason": body.rejection_reason,
        }).fetchone()
    except Exception as exc:
        _log.error("[C2.1] reject failed admin=%s claim=%s: %s", admin_user, claim_id, exc)
        raise HTTPException(status_code=503, detail="Claim service unavailable")

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Claim not found or not in pending status",
        )

    _log.info("[C2.1] claim rejected id=%s by=%s reason=%r", claim_id, admin_user, body.rejection_reason)
    return {
        "claim_id": claim_id,
        "claim_status": "rejected",
        "reviewed_by": admin_user,
        "rejection_reason": body.rejection_reason,
    }
