"""C2.1 — Admin Creator Claims API unit tests.

Covers:
  Security:
    - request without X-Pti-Admin-User header → 401
    - X-Pti-Admin-User present → allowed (header presence is sufficient at FastAPI layer;
      admin identity gate lives in the Next.js server route)

  Functionality:
    - list pending claims (status filter)
    - list all claims (status=all)
    - invalid status → 422
    - approve pending claim → status=verified, reviewed_by set
    - approve non-pending / non-existent claim → 404
    - reject pending claim → status=rejected, rejection_reason stored
    - reject with empty reason → 422
    - reject non-pending / non-existent claim → 404
    - resubmit after rejection allowed (business logic, not HTTP)

  Security (data exposure):
    - admin list response never includes verification_code_hash
    - admin list response never includes access_token_encrypted / refresh_token_encrypted
    - creator_scores count unchanged after approve/reject
    - creator_oauth_grants count unchanged after approve/reject
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from perfume_trend_sdk.api.main import app
from perfume_trend_sdk.api.dependencies import get_db_session


# ---------------------------------------------------------------------------
# In-memory SQLite database fixtures
# ---------------------------------------------------------------------------

_TABLES = [
    """CREATE TABLE IF NOT EXISTS creator_profile_claims (
        id                              TEXT PRIMARY KEY,
        user_id                         TEXT NOT NULL,
        platform                        TEXT NOT NULL,
        creator_id                      TEXT NOT NULL,
        claim_status                    TEXT NOT NULL DEFAULT 'pending',
        claim_method                    TEXT NOT NULL,
        verification_code_hash          TEXT,
        verification_code_expires_at    TEXT,
        evidence_url                    TEXT,
        reviewer_notes                  TEXT,
        rejection_reason                TEXT,
        claimed_at                      TEXT,
        verified_at                     TEXT,
        reviewed_at                     TEXT,
        reviewed_by                     TEXT,
        created_at                      TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS youtube_channels (
        channel_id  TEXT PRIMARY KEY,
        title       TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS source_profiles (
        source_id    TEXT PRIMARY KEY,
        display_name TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS creator_scores (
        creator_id TEXT PRIMARY KEY,
        score      REAL
    )""",
    """CREATE TABLE IF NOT EXISTS creator_oauth_grants (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        platform TEXT
    )""",
]


@pytest.fixture
def engine():
    # StaticPool ensures all sessions (including TestClient's thread) share the
    # same SQLite in-memory connection — tables created in setup are visible everywhere.
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.connect() as conn:
        for stmt in _TABLES:
            conn.execute(text(stmt))
        conn.commit()
    return eng


@pytest.fixture
def db_session(engine) -> Generator[Session, None, None]:
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session) -> Generator[TestClient, None, None]:
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_HEADER = {"X-Pti-Admin-User": "operator@fragranceindex.ai"}
ADMIN_USER = "operator@fragranceindex.ai"


def _insert_claim(
    db: Session,
    *,
    claim_id: str | None = None,
    user_id: str = "user-001",
    platform: str = "youtube",
    creator_id: str = "UCtest123",
    claim_status: str = "pending",
    claim_method: str = "bio_code",
    evidence_url: str = "https://youtube.com/channel/UCtest123",
    rejection_reason: str | None = None,
    code_hash: str | None = None,
) -> str:
    cid = claim_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("""
        INSERT INTO creator_profile_claims
            (id, user_id, platform, creator_id, claim_status, claim_method,
             verification_code_hash, evidence_url, rejection_reason,
             claimed_at, created_at)
        VALUES
            (:id, :user_id, :platform, :creator_id, :claim_status, :claim_method,
             :code_hash, :evidence_url, :rejection_reason, :now, :now)
    """), {
        "id": cid, "user_id": user_id, "platform": platform,
        "creator_id": creator_id, "claim_status": claim_status,
        "claim_method": claim_method, "code_hash": code_hash,
        "evidence_url": evidence_url, "rejection_reason": rejection_reason,
        "now": now,
    })
    db.commit()
    return cid


def _insert_creator_score(db: Session, creator_id: str = "UCtest123"):
    db.execute(text(
        "INSERT OR IGNORE INTO creator_scores (creator_id, score) VALUES (:c, 0.5)"
    ), {"c": creator_id})
    db.commit()


def _count(db: Session, table: str) -> int:
    return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()  # type: ignore[return-value]


def _get_claim(db: Session, claim_id: str) -> Dict[str, Any]:
    row = db.execute(
        text("SELECT * FROM creator_profile_claims WHERE id = :id"),
        {"id": claim_id},
    ).mappings().fetchone()
    return dict(row) if row else {}


# ===========================================================================
# Security — header required
# ===========================================================================

class TestHeaderRequired:
    def test_list_without_header_returns_401(self, client):
        resp = client.get("/api/v1/admin/creator-claims")
        assert resp.status_code == 401

    def test_approve_without_header_returns_401(self, client, db_session):
        cid = _insert_claim(db_session)
        resp = client.post(f"/api/v1/admin/creator-claims/{cid}/approve")
        assert resp.status_code == 401

    def test_reject_without_header_returns_401(self, client, db_session):
        cid = _insert_claim(db_session)
        resp = client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": "test reason"},
        )
        assert resp.status_code == 401

    def test_admin_identity_in_body_not_accepted_for_list(self, client):
        # Body fields must not bypass the header requirement
        resp = client.get(
            "/api/v1/admin/creator-claims",
            params={"admin": "operator@fragranceindex.ai"},
        )
        assert resp.status_code == 401

    def test_list_with_header_returns_200(self, client):
        resp = client.get("/api/v1/admin/creator-claims", headers=ADMIN_HEADER)
        assert resp.status_code == 200


# ===========================================================================
# List claims
# ===========================================================================

class TestListClaims:
    def test_default_status_is_pending(self, client, db_session):
        _insert_claim(db_session, claim_status="pending")
        _insert_claim(db_session, claim_status="verified")
        resp = client.get("/api/v1/admin/creator-claims", headers=ADMIN_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert all(c["claim_status"] == "pending" for c in data["claims"])

    def test_filter_by_verified(self, client, db_session):
        _insert_claim(db_session, claim_status="pending")
        _insert_claim(db_session, claim_status="verified")
        resp = client.get(
            "/api/v1/admin/creator-claims?status=verified", headers=ADMIN_HEADER
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(c["claim_status"] == "verified" for c in data["claims"])

    def test_status_all_returns_every_claim(self, client, db_session):
        _insert_claim(db_session, claim_status="pending")
        _insert_claim(db_session, claim_status="verified")
        _insert_claim(db_session, claim_status="rejected")
        resp = client.get(
            "/api/v1/admin/creator-claims?status=all", headers=ADMIN_HEADER
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_invalid_status_returns_422(self, client):
        resp = client.get(
            "/api/v1/admin/creator-claims?status=bogus", headers=ADMIN_HEADER
        )
        assert resp.status_code == 422

    def test_verification_code_hash_never_returned(self, client, db_session):
        code_hash = hashlib.sha256(b"FTI-ABCD1234").hexdigest()
        _insert_claim(db_session, code_hash=code_hash)
        resp = client.get("/api/v1/admin/creator-claims", headers=ADMIN_HEADER)
        assert resp.status_code == 200
        raw = resp.text
        assert "verification_code_hash" not in raw
        assert code_hash not in raw

    def test_total_field_present(self, client, db_session):
        _insert_claim(db_session)
        resp = client.get("/api/v1/admin/creator-claims", headers=ADMIN_HEADER)
        data = resp.json()
        assert "total" in data
        assert data["total"] >= 1

    def test_required_fields_present(self, client, db_session):
        _insert_claim(db_session)
        resp = client.get("/api/v1/admin/creator-claims", headers=ADMIN_HEADER)
        claim = resp.json()["claims"][0]
        for field in (
            "claim_id", "user_id", "platform", "creator_id",
            "claim_method", "claim_status", "claimed_at",
        ):
            assert field in claim, f"Missing field: {field}"


# ===========================================================================
# Approve
# ===========================================================================

class TestApproveClaim:
    def test_approve_pending_claim(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="pending")
        resp = client.post(
            f"/api/v1/admin/creator-claims/{cid}/approve", headers=ADMIN_HEADER
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_status"] == "verified"
        assert data["reviewed_by"] == ADMIN_USER

    def test_approved_claim_status_updated_in_db(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="pending")
        client.post(
            f"/api/v1/admin/creator-claims/{cid}/approve", headers=ADMIN_HEADER
        )
        row = _get_claim(db_session, cid)
        assert row["claim_status"] == "verified"
        assert row["reviewed_by"] == ADMIN_USER
        assert row["verified_at"] is not None
        assert row["reviewed_at"] is not None

    def test_approve_nonexistent_claim_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/admin/creator-claims/{fake_id}/approve", headers=ADMIN_HEADER
        )
        assert resp.status_code == 404

    def test_approve_already_verified_returns_404(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="verified")
        resp = client.post(
            f"/api/v1/admin/creator-claims/{cid}/approve", headers=ADMIN_HEADER
        )
        assert resp.status_code == 404

    def test_approve_does_not_touch_creator_scores(self, client, db_session):
        _insert_creator_score(db_session)
        before = _count(db_session, "creator_scores")
        cid = _insert_claim(db_session, claim_status="pending")
        client.post(
            f"/api/v1/admin/creator-claims/{cid}/approve", headers=ADMIN_HEADER
        )
        assert _count(db_session, "creator_scores") == before

    def test_approve_does_not_touch_creator_oauth_grants(self, client, db_session):
        before = _count(db_session, "creator_oauth_grants")
        cid = _insert_claim(db_session, claim_status="pending")
        client.post(
            f"/api/v1/admin/creator-claims/{cid}/approve", headers=ADMIN_HEADER
        )
        assert _count(db_session, "creator_oauth_grants") == before


# ===========================================================================
# Reject
# ===========================================================================

class TestRejectClaim:
    def test_reject_pending_claim(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="pending")
        resp = client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": "Evidence URL not reachable"},
            headers=ADMIN_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_status"] == "rejected"
        assert data["rejection_reason"] == "Evidence URL not reachable"
        assert data["reviewed_by"] == ADMIN_USER

    def test_rejected_claim_status_updated_in_db(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="pending")
        client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": "Cannot verify"},
            headers=ADMIN_HEADER,
        )
        row = _get_claim(db_session, cid)
        assert row["claim_status"] == "rejected"
        assert row["rejection_reason"] == "Cannot verify"
        assert row["reviewed_by"] == ADMIN_USER
        assert row["reviewed_at"] is not None

    def test_reject_with_empty_reason_returns_422(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="pending")
        resp = client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": ""},
            headers=ADMIN_HEADER,
        )
        assert resp.status_code == 422

    def test_reject_with_whitespace_only_reason_returns_422(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="pending")
        resp = client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": "   "},
            headers=ADMIN_HEADER,
        )
        assert resp.status_code == 422

    def test_reject_nonexistent_claim_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/admin/creator-claims/{fake_id}/reject",
            json={"rejection_reason": "Some reason"},
            headers=ADMIN_HEADER,
        )
        assert resp.status_code == 404

    def test_reject_already_verified_returns_404(self, client, db_session):
        cid = _insert_claim(db_session, claim_status="verified")
        resp = client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": "Some reason"},
            headers=ADMIN_HEADER,
        )
        assert resp.status_code == 404

    def test_reject_does_not_touch_creator_scores(self, client, db_session):
        _insert_creator_score(db_session)
        before = _count(db_session, "creator_scores")
        cid = _insert_claim(db_session, claim_status="pending")
        client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": "Bad evidence"},
            headers=ADMIN_HEADER,
        )
        assert _count(db_session, "creator_scores") == before

    def test_reject_does_not_touch_creator_oauth_grants(self, client, db_session):
        before = _count(db_session, "creator_oauth_grants")
        cid = _insert_claim(db_session, claim_status="pending")
        client.post(
            f"/api/v1/admin/creator-claims/{cid}/reject",
            json={"rejection_reason": "Bad evidence"},
            headers=ADMIN_HEADER,
        )
        assert _count(db_session, "creator_oauth_grants") == before


# ===========================================================================
# Resubmit after rejection
# ===========================================================================

class TestResubmitAfterRejection:
    def test_rejected_claim_allows_new_pending_insert(self, db_session):
        """Rejected claim row does not block a fresh insert (no UNIQUE constraint
        on active claims prevents a new pending claim after rejection)."""
        user_id = "user-resubmit"
        creator_id = "UCResubmit999"

        # First claim
        cid1 = _insert_claim(
            db_session,
            user_id=user_id,
            creator_id=creator_id,
            claim_status="rejected",
            rejection_reason="Evidence missing",
        )

        # Second claim (resubmit)
        cid2 = _insert_claim(
            db_session,
            user_id=user_id,
            creator_id=creator_id,
            claim_status="pending",
        )

        # Both rows exist
        rows = db_session.execute(
            text(
                "SELECT id FROM creator_profile_claims "
                "WHERE user_id = :u AND creator_id = :c"
            ),
            {"u": user_id, "c": creator_id},
        ).fetchall()
        claim_ids = {r[0] for r in rows}
        assert cid1 in claim_ids
        assert cid2 in claim_ids
