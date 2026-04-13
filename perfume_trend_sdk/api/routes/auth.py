from __future__ import annotations

"""
Auth routes — app_users access control.

These endpoints are called by the frontend callback and guards.
They do NOT handle Supabase token verification — that is done by
the frontend middleware + Supabase client libraries.

Endpoints:
    GET  /api/v1/auth/users/{email}         — look up access status
    POST /api/v1/auth/users/{email}/login   — update last_login_at

No authentication token is required for these routes in Phase 3A.
The data returned (access_status, role) is non-sensitive and the
email pre-check on /login prevents unsolicited magic links.

Phase 3B will add Supabase JWT verification to restrict these endpoints
to authenticated callers only.
"""

from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session

router = APIRouter()


class AppUserResponse(BaseModel):
    email: str
    role: str
    access_status: str


@router.get("/auth/users/{email}", response_model=AppUserResponse)
def get_app_user(email: str, db: Session = Depends(get_db_session)):
    """Return access_status and role for an email address.

    Returns 404 if the email is not in app_users.
    Called by:
      - /login pre-check (before sending magic link)
      - /auth/callback (before establishing session)
      - middleware (on every protected request)
    """
    normalized = unquote(email).strip().lower()
    row = db.execute(
        text(
            "SELECT email, role, access_status "
            "FROM app_users WHERE email = :email LIMIT 1"
        ),
        {"email": normalized},
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    return AppUserResponse(
        email=row.email,
        role=row.role,
        access_status=row.access_status,
    )


@router.post("/auth/users/{email}/login", status_code=204)
def record_login(email: str, db: Session = Depends(get_db_session)):
    """Update last_login_at for an approved user.

    Called by /auth/callback after a successful Supabase session is
    established and the user is confirmed approved.
    Returns 204 No Content on success; 404 if email is not found.
    """
    normalized = unquote(email).strip().lower()
    result = db.execute(
        text(
            "UPDATE app_users "
            "SET last_login_at = :now, updated_at = :now "
            "WHERE email = :email AND access_status = 'approved'"
        ),
        {"email": normalized, "now": datetime.now(timezone.utc)},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Approved user not found")
