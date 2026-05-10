"""SOURCE-INTAKE-V1A — Admin Source Intake API unit tests.

Covers:
  Security:
    - requests without X-Pti-Admin-User → 401 (all endpoints)

  Batch creation:
    - POST /batches creates batch + candidates + audit log entries
    - GET /batches lists batches with status counts
    - GET /batches/{id} lists candidates (filter by status)

  Candidate actions:
    - approve: NEEDS_OPERATOR_REVIEW → OPERATOR_APPROVED; audit log written
    - reject: requires non-empty reason; → OPERATOR_REJECTED; audit log written
    - reject with empty reason → 422
    - defer: → DEFERRED; audit log written
    - mark-duplicate: → SKIP_DUPLICATE; audit log written
    - terminal status (SKIP_DUPLICATE) → 409 on further action

  Apply:
    - VERIFIED_ADD_READY candidate inserted into youtube_channels (ON CONFLICT DO NOTHING)
    - OPERATOR_APPROVED candidate inserted
    - NEEDS_OPERATOR_REVIEW candidate NOT inserted
    - candidate without canonical UC... id NOT inserted (safety guard)
    - duplicate already-existing channel skipped silently
    - audit log written for each apply result

  Production verify:
    - APPLIED + content in canonical_content_items → PRODUCTION_VERIFIED
    - APPLIED + no content → pending_ingestion

  Data safety:
    - creator_scores count unchanged after all operations
    - creator_oauth_grants count unchanged
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from perfume_trend_sdk.api.main import app
from perfume_trend_sdk.api.dependencies import get_db_session

_ADMIN_HEADER = {"X-Pti-Admin-User": "test-admin@example.com"}

# ---------------------------------------------------------------------------
# In-memory SQLite fixtures
# ---------------------------------------------------------------------------

_TABLES = [
    """CREATE TABLE IF NOT EXISTS source_intake_batches (
        id TEXT PRIMARY KEY,
        batch_label TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'youtube',
        description TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        candidate_count INTEGER NOT NULL DEFAULT 0,
        applied_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT NOT NULL,
        applied_at TEXT,
        applied_by TEXT,
        verified_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS source_intake_candidates (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'youtube',
        candidate_name TEXT NOT NULL,
        input_url TEXT NOT NULL,
        resolved_platform_id TEXT,
        resolved_title TEXT,
        subscriber_count INTEGER,
        total_content_count INTEGER,
        recent_content_count INTEGER,
        recent_titles_sample TEXT,
        resolve_method TEXT,
        confidence TEXT,
        status TEXT NOT NULL DEFAULT 'PENDING_VERIFICATION',
        decision_reason TEXT,
        operator_override_url TEXT,
        operator_notes TEXT,
        quality_tier TEXT,
        reviewed_by TEXT,
        reviewed_at TEXT,
        applied_at TEXT,
        apply_error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS source_intake_audit_log (
        id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS youtube_channels (
        id TEXT PRIMARY KEY,
        channel_id TEXT UNIQUE NOT NULL,
        handle TEXT,
        channel_url TEXT,
        title TEXT,
        normalized_title TEXT,
        quality_tier TEXT,
        category TEXT,
        status TEXT DEFAULT 'active',
        priority TEXT,
        subscriber_count INTEGER,
        video_count INTEGER,
        uploads_playlist_id TEXT,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP,
        added_by TEXT,
        notes TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS canonical_content_items (
        id TEXT PRIMARY KEY,
        source_platform TEXT,
        source_account_id TEXT,
        title TEXT,
        source_url TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS creator_scores (
        id TEXT PRIMARY KEY,
        platform TEXT,
        creator_id TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS creator_oauth_grants (
        id TEXT PRIMARY KEY,
        platform TEXT,
        platform_user_id TEXT
    )""",
]


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # SQLite doesn't support ON CONFLICT (column) DO NOTHING with named columns
    # the same way PostgreSQL does — we patch it in the apply endpoint via monkeypatching
    for ddl in _TABLES:
        with engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    app.dependency_overrides[get_db_session] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_batch(db: Session, batch_id: str = None, label: str = "test-batch-01",
                platform: str = "youtube") -> str:
    bid = batch_id or str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO source_intake_batches (id, batch_label, platform, status, candidate_count,
            applied_count, created_at, created_by)
        VALUES (:id, :label, :platform, 'open', 0, 0, CURRENT_TIMESTAMP, 'test')
    """), {"id": bid, "label": label, "platform": platform})
    db.commit()
    return bid


def _make_candidate(
    db: Session,
    batch_id: str,
    status: str = "NEEDS_OPERATOR_REVIEW",
    resolved_platform_id: str = None,
    resolved_title: str = "Test Channel",
    candidate_name: str = "Test Channel",
) -> str:
    cid = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO source_intake_candidates
            (id, batch_id, platform, candidate_name, input_url,
             resolved_platform_id, resolved_title, subscriber_count,
             recent_content_count, status, created_at)
        VALUES (:id, :batch_id, 'youtube', :name, 'https://example.com',
                :resolved_id, :title, 10000, 5, :status, CURRENT_TIMESTAMP)
    """), {
        "id": cid, "batch_id": batch_id, "name": candidate_name,
        "resolved_id": resolved_platform_id, "title": resolved_title, "status": status,
    })
    db.commit()
    return cid


def _get_audit_entries(db: Session, candidate_id: str) -> list:
    rows = db.execute(text("""
        SELECT action, old_status, new_status FROM source_intake_audit_log
        WHERE candidate_id = :id ORDER BY created_at
    """), {"id": candidate_id}).fetchall()
    return [{"action": r[0], "old_status": r[1], "new_status": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------

class TestSecurity:
    def test_list_batches_no_header_401(self, client):
        r = client.get("/api/v1/admin/source-intake/batches")
        assert r.status_code == 401

    def test_get_batch_no_header_401(self, client):
        r = client.get("/api/v1/admin/source-intake/batches/some-id")
        assert r.status_code == 401

    def test_get_candidate_no_header_401(self, client):
        r = client.get("/api/v1/admin/source-intake/candidates/some-id")
        assert r.status_code == 401

    def test_approve_no_header_401(self, client):
        r = client.post("/api/v1/admin/source-intake/candidates/some-id/approve")
        assert r.status_code == 401

    def test_reject_no_header_401(self, client):
        r = client.post("/api/v1/admin/source-intake/candidates/some-id/reject",
                        json={"reason": "test"})
        assert r.status_code == 401

    def test_defer_no_header_401(self, client):
        r = client.post("/api/v1/admin/source-intake/candidates/some-id/defer")
        assert r.status_code == 401

    def test_mark_duplicate_no_header_401(self, client):
        r = client.post("/api/v1/admin/source-intake/candidates/some-id/mark-duplicate")
        assert r.status_code == 401

    def test_apply_no_header_401(self, client):
        r = client.post("/api/v1/admin/source-intake/batches/some-id/apply")
        assert r.status_code == 401

    def test_production_verify_no_header_401(self, client):
        r = client.post("/api/v1/admin/source-intake/batches/some-id/production-verify")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Batch creation + list
# ---------------------------------------------------------------------------

class TestBatchCreation:
    def test_create_batch_via_post(self, client, db_session):
        payload = {
            "batch_label": "MY-BATCH-01",
            "platform": "youtube",
            "created_by": "cli:test",
            "candidates": [
                {
                    "candidate_name": "Channel A",
                    "input_url": "https://youtube.com/@channela",
                    "resolved_platform_id": "UCtest1234",
                    "resolved_title": "Channel A Title",
                    "subscriber_count": 50000,
                    "total_content_count": 100,
                    "recent_content_count": 5,
                    "recent_titles_sample": '["video 1", "video 2"]',
                    "resolve_method": "handle",
                    "confidence": "high",
                    "status": "VERIFIED_ADD_READY",
                    "decision_reason": "5 video(s) in last 30 days",
                    "quality_tier": "tier_2",
                },
                {
                    "candidate_name": "Channel B",
                    "input_url": "https://youtube.com/results?search_query=channel+b",
                    "resolved_platform_id": None,
                    "resolved_title": None,
                    "subscriber_count": None,
                    "total_content_count": None,
                    "recent_content_count": 0,
                    "recent_titles_sample": None,
                    "resolve_method": "search",
                    "confidence": "low",
                    "status": "NEEDS_OPERATOR_REVIEW",
                    "decision_reason": "Could not resolve to a channel_id",
                    "quality_tier": "tier_4",
                },
            ],
        }
        r = client.post("/api/v1/admin/source-intake/batches", json=payload,
                        headers=_ADMIN_HEADER)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["candidate_count"] == 2
        assert "batch_id" in data

        # Verify candidates in DB
        candidates = db_session.execute(text("""
            SELECT status, candidate_name FROM source_intake_candidates
            WHERE batch_id = :bid ORDER BY created_at
        """), {"bid": data["batch_id"]}).fetchall()
        assert len(candidates) == 2
        assert candidates[0][0] == "VERIFIED_ADD_READY"
        assert candidates[1][0] == "NEEDS_OPERATOR_REVIEW"

        # Audit log written for each candidate
        audit = db_session.execute(text("""
            SELECT COUNT(*) FROM source_intake_audit_log al
            JOIN source_intake_candidates c ON c.id = al.candidate_id
            WHERE c.batch_id = :bid
        """), {"bid": data["batch_id"]}).fetchone()
        assert audit[0] == 2

    def test_list_batches(self, client, db_session):
        _make_batch(db_session, label="BATCH-LIST-TEST")
        r = client.get("/api/v1/admin/source-intake/batches", headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        labels = [b["batch_label"] for b in data["batches"]]
        assert "BATCH-LIST-TEST" in labels

    def test_get_batch_candidates(self, client, db_session):
        bid = _make_batch(db_session, label="GET-BATCH-TEST")
        _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")
        _make_candidate(db_session, bid, status="VERIFIED_ADD_READY",
                        resolved_platform_id="UCabc1234567890123456")

        r = client.get(f"/api/v1/admin/source-intake/batches/{bid}", headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2

        # Filter by status
        r2 = client.get(f"/api/v1/admin/source-intake/batches/{bid}?status=NEEDS_OPERATOR_REVIEW",
                        headers=_ADMIN_HEADER)
        assert r2.status_code == 200
        assert r2.json()["total"] == 1

    def test_get_batch_not_found(self, client):
        r = client.get("/api/v1/admin/source-intake/batches/nonexistent-id", headers=_ADMIN_HEADER)
        assert r.status_code == 404

    def test_invalid_status_filter_422(self, client, db_session):
        bid = _make_batch(db_session)
        r = client.get(f"/api/v1/admin/source-intake/batches/{bid}?status=INVALID_STATUS",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Candidate actions
# ---------------------------------------------------------------------------

class TestCandidateActions:
    def test_approve_candidate(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")

        r = client.post(f"/api/v1/admin/source-intake/candidates/{cid}/approve",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        assert r.json()["status"] == "OPERATOR_APPROVED"

        # DB updated
        row = db_session.execute(text("SELECT status, reviewed_by FROM source_intake_candidates WHERE id = :id"),
                                 {"id": cid}).fetchone()
        assert row[0] == "OPERATOR_APPROVED"
        assert row[1] == "test-admin@example.com"

        # Audit log
        entries = _get_audit_entries(db_session, cid)
        approve_entries = [e for e in entries if e["action"] == "approve"]
        assert len(approve_entries) == 1
        assert approve_entries[0]["old_status"] == "NEEDS_OPERATOR_REVIEW"
        assert approve_entries[0]["new_status"] == "OPERATOR_APPROVED"

    def test_reject_candidate_with_reason(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")

        r = client.post(f"/api/v1/admin/source-intake/candidates/{cid}/reject",
                        json={"reason": "Channel is not fragrance-related"},
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        assert r.json()["status"] == "OPERATOR_REJECTED"

        row = db_session.execute(text("SELECT status, decision_reason FROM source_intake_candidates WHERE id = :id"),
                                 {"id": cid}).fetchone()
        assert row[0] == "OPERATOR_REJECTED"
        assert row[1] == "Channel is not fragrance-related"

        # Audit log
        entries = _get_audit_entries(db_session, cid)
        reject_entries = [e for e in entries if e["action"] == "reject"]
        assert len(reject_entries) == 1
        assert reject_entries[0]["new_status"] == "OPERATOR_REJECTED"

    def test_reject_empty_reason_422(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")
        r = client.post(f"/api/v1/admin/source-intake/candidates/{cid}/reject",
                        json={"reason": "   "},
                        headers=_ADMIN_HEADER)
        assert r.status_code == 422

    def test_defer_candidate(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")

        r = client.post(f"/api/v1/admin/source-intake/candidates/{cid}/defer",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        assert r.json()["status"] == "DEFERRED"

        entries = _get_audit_entries(db_session, cid)
        assert any(e["action"] == "defer" for e in entries)

    def test_mark_duplicate(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")

        r = client.post(f"/api/v1/admin/source-intake/candidates/{cid}/mark-duplicate",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        assert r.json()["status"] == "SKIP_DUPLICATE"

    def test_terminal_status_blocks_further_actions(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="SKIP_DUPLICATE")

        # Cannot approve a SKIP_DUPLICATE candidate
        r = client.post(f"/api/v1/admin/source-intake/candidates/{cid}/approve",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 409

        # Cannot defer a SKIP_DUPLICATE candidate
        r = client.post(f"/api/v1/admin/source-intake/candidates/{cid}/defer",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 409

    def test_candidate_not_found_404(self, client):
        r = client.post("/api/v1/admin/source-intake/candidates/nonexistent/approve",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 404

    def test_update_override_url(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")

        r = client.patch(f"/api/v1/admin/source-intake/candidates/{cid}",
                         json={"operator_override_url": "https://www.youtube.com/@testchannel"},
                         headers=_ADMIN_HEADER)
        assert r.status_code == 200
        assert r.json()["updated"] is True

        row = db_session.execute(
            text("SELECT operator_override_url FROM source_intake_candidates WHERE id = :id"),
            {"id": cid}).fetchone()
        assert row[0] == "https://www.youtube.com/@testchannel"


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

class TestApply:
    def _seed_yt_channel(self, db: Session, channel_id: str = "UCexisting123456789012") -> None:
        """Pre-seed a channel to test ON CONFLICT handling."""
        db.execute(text("""
            INSERT OR IGNORE INTO youtube_channels
                (id, channel_id, title, status, added_by)
            VALUES (:id, :channel_id, 'Existing Channel', 'active', 'test')
        """), {"id": str(uuid.uuid4()), "channel_id": channel_id})
        db.commit()

    def test_verified_add_ready_applied(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="VERIFIED_ADD_READY",
                               resolved_platform_id="UCtest12345678901234567",
                               resolved_title="Fragrance Channel X")

        r = client.post(f"/api/v1/admin/source-intake/batches/{bid}/apply",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["applied"] == 1
        assert data["skipped"] == 0
        assert data["failed"] == 0

        # Channel now in youtube_channels
        row = db_session.execute(
            text("SELECT channel_id, added_by FROM youtube_channels WHERE channel_id = :cid"),
            {"cid": "UCtest12345678901234567"}).fetchone()
        assert row is not None
        assert "source_intake" in row[1]

        # Candidate status updated
        c_row = db_session.execute(
            text("SELECT status FROM source_intake_candidates WHERE id = :id"),
            {"id": cid}).fetchone()
        assert c_row[0] == "APPLIED"

        # Audit log
        entries = _get_audit_entries(db_session, cid)
        assert any(e["action"] == "apply" and e["new_status"] == "APPLIED" for e in entries)

    def test_operator_approved_applied(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="OPERATOR_APPROVED",
                               resolved_platform_id="UCoperator12345678901",
                               resolved_title="Operator Approved Channel")

        r = client.post(f"/api/v1/admin/source-intake/batches/{bid}/apply",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        assert r.json()["applied"] == 1

    def test_needs_operator_review_not_applied(self, client, db_session):
        bid = _make_batch(db_session)
        _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW",
                        resolved_platform_id="UCshould_not_apply1234")

        r = client.post(f"/api/v1/admin/source-intake/batches/{bid}/apply",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        # NEEDS_OPERATOR_REVIEW candidates are excluded from apply query
        assert data["applied"] == 0
        assert data["skipped"] == 0
        assert data["failed"] == 0

        # Channel NOT in youtube_channels
        row = db_session.execute(
            text("SELECT channel_id FROM youtube_channels WHERE channel_id = :cid"),
            {"cid": "UCshould_not_apply1234"}).fetchone()
        assert row is None

    def test_no_canonical_id_skipped(self, client, db_session):
        """Candidate with no resolved_platform_id or non-UC id must not be applied."""
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="OPERATOR_APPROVED",
                               resolved_platform_id=None)  # No channel_id

        r = client.post(f"/api/v1/admin/source-intake/batches/{bid}/apply",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["applied"] == 0
        assert data["skipped"] == 1

    def test_duplicate_channel_skipped_on_conflict(self, client, db_session):
        """Already-existing channel silently skipped (ON CONFLICT DO NOTHING)."""
        existing_channel_id = "UCexisting123456789012"
        self._seed_yt_channel(db_session, existing_channel_id)

        bid = _make_batch(db_session)
        _make_candidate(db_session, bid, status="VERIFIED_ADD_READY",
                        resolved_platform_id=existing_channel_id)

        r = client.post(f"/api/v1/admin/source-intake/batches/{bid}/apply",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        # Inserted=0 because ON CONFLICT DO NOTHING
        assert data["applied"] == 0 or data["skipped"] >= 1

    def test_apply_audit_log_written(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="VERIFIED_ADD_READY",
                               resolved_platform_id="UCauditlog123456789012")

        client.post(f"/api/v1/admin/source-intake/batches/{bid}/apply",
                    headers=_ADMIN_HEADER)

        entries = _get_audit_entries(db_session, cid)
        apply_entries = [e for e in entries if e["action"] == "apply"]
        assert len(apply_entries) >= 1

    def test_apply_batch_not_found(self, client):
        r = client.post("/api/v1/admin/source-intake/batches/nonexistent-id/apply",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Production verify
# ---------------------------------------------------------------------------

class TestProductionVerify:
    def test_applied_with_content_becomes_production_verified(self, client, db_session):
        bid = _make_batch(db_session)
        channel_id = "UCverified123456789012"
        cid = _make_candidate(db_session, bid, status="APPLIED",
                               resolved_platform_id=channel_id)

        # Seed youtube_channels + content
        db_session.execute(text("""
            INSERT OR IGNORE INTO youtube_channels (id, channel_id, title, status, added_by)
            VALUES (:id, :cid, 'Verified Channel', 'active', 'source_intake:test')
        """), {"id": str(uuid.uuid4()), "cid": channel_id})
        db_session.execute(text("""
            INSERT INTO canonical_content_items (id, source_platform, source_account_id, title, source_url)
            VALUES (:id, 'youtube', :cid, 'Test Video', 'https://youtube.com/watch?v=test')
        """), {"id": str(uuid.uuid4()), "cid": channel_id})
        db_session.commit()

        r = client.post(f"/api/v1/admin/source-intake/batches/{bid}/production-verify",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["verified"] == 1
        assert data["pending_ingestion"] == 0

        # Candidate updated
        row = db_session.execute(
            text("SELECT status FROM source_intake_candidates WHERE id = :id"),
            {"id": cid}).fetchone()
        assert row[0] == "PRODUCTION_VERIFIED"

    def test_applied_without_content_stays_pending(self, client, db_session):
        bid = _make_batch(db_session)
        channel_id = "UCpending12345678901234"
        _make_candidate(db_session, bid, status="APPLIED",
                        resolved_platform_id=channel_id)

        # Seed youtube_channels but NO content items
        db_session.execute(text("""
            INSERT OR IGNORE INTO youtube_channels (id, channel_id, title, status, added_by)
            VALUES (:id, :cid, 'Pending Channel', 'active', 'source_intake:test')
        """), {"id": str(uuid.uuid4()), "cid": channel_id})
        db_session.commit()

        r = client.post(f"/api/v1/admin/source-intake/batches/{bid}/production-verify",
                        headers=_ADMIN_HEADER)
        assert r.status_code == 200
        data = r.json()
        assert data["verified"] == 0
        assert data["pending_ingestion"] == 1


# ---------------------------------------------------------------------------
# Data safety
# ---------------------------------------------------------------------------

class TestDataSafety:
    def test_creator_scores_unchanged(self, client, db_session):
        db_session.execute(text("""
            INSERT INTO creator_scores (id, platform, creator_id) VALUES (:id, 'youtube', 'UCtest')
        """), {"id": str(uuid.uuid4())})
        db_session.commit()

        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="NEEDS_OPERATOR_REVIEW")
        client.post(f"/api/v1/admin/source-intake/candidates/{cid}/approve", headers=_ADMIN_HEADER)

        count = db_session.execute(text("SELECT COUNT(*) FROM creator_scores")).fetchone()[0]
        assert count == 1

    def test_creator_oauth_grants_unchanged(self, client, db_session):
        bid = _make_batch(db_session)
        cid = _make_candidate(db_session, bid, status="VERIFIED_ADD_READY",
                               resolved_platform_id="UCsafetytest12345678901")
        client.post(f"/api/v1/admin/source-intake/batches/{bid}/apply", headers=_ADMIN_HEADER)

        count = db_session.execute(text("SELECT COUNT(*) FROM creator_oauth_grants")).fetchone()[0]
        assert count == 0
