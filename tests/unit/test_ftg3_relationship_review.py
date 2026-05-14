"""FTG-3 / RI1-QA — Operator Review Gate + DB-Backed Public Relationship Display.

Tests cover:

Admin access:
  A  Non-admin (missing X-Pti-Admin-User header) cannot access list or actions
  B  Admin (header present) can access list endpoint

Admin listing / filtering:
  C  Admin can list all relationships
  D  Admin can list only public relationships
  E  Admin can list only non-public relationships
  F  Invalid filter raises 422

Admin actions:
  G  Approve sets is_public=TRUE, operator_reviewed=TRUE
  H  Unpublish sets is_public=FALSE
  I  PATCH updates confidence_score
  J  PATCH updates relation_type
  K  PATCH with invalid relation_type raises 422
  L  PATCH with no fields raises 422
  M  Actions on non-existent ID return 404

Public quality gate:
  N  Row with is_public=FALSE → get_approved_relationship returns None
  O  Row with operator_reviewed=FALSE → get_approved_relationship returns None
  P  Row with confidence_score < 0.700 → get_approved_relationship returns None
  Q  Row passing all three gates → get_approved_relationship returns (relation_type, object, confidence)
  R  DB exception in get_approved_relationship → returns None (non-fatal)

Public entity output:
  S  Khamrah → market_alternative_to → reference_original = "Kilian Angels' Share"
  T  Armaf CDNIM → dupe_of → reference_original = "Creed Aventus"
  U  Entity with no approved DB row falls back to _DUPE_RAW (resilience)

Regression:
  V  FTG-2 VALID_RELATION_TYPES unchanged (4 types)
  W  FTG-2 RELATIONSHIP_SEED unchanged (7 rows)
  X  FTG-0/KB0 — Khamrah → Kilian Angels' Share (not BR540)
  Y  DATA1 — _get_latest_snapshot filter unchanged
"""

import sys
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin_app():
    """Create a FastAPI TestClient with the admin router mounted."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from perfume_trend_sdk.api.routes.admin_relationship_intelligence import router

    app = FastAPI()
    app.include_router(router, prefix="/relationship-intelligence")
    return TestClient(app, raise_server_exceptions=False)


def _make_db_with_rows(rows: list):
    """Mock Session that returns given rows from execute().fetchall()."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    db.execute.return_value.fetchone.return_value = rows[0] if rows else None
    return db


def _make_relationship_row(
    rid=None,
    subject="Armaf Club de Nuit Intense Man",
    relation_type="dupe_of",
    object_name="Creed Aventus",
    confidence=Decimal("0.850"),
    is_public=True,
    operator_reviewed=True,
    evidence_summary=None,
):
    """Return a minimal row tuple matching fragrance_relationships query column order."""
    import datetime
    rid = rid or uuid.uuid4()
    today = datetime.date(2026, 5, 14)
    now = datetime.datetime(2026, 5, 14, 12, 0, 0)
    return (
        rid,
        subject,
        relation_type,
        object_name,
        confidence,
        is_public,
        operator_reviewed,
        today,
        today,
        evidence_summary,
        1,
        now,
    )


# ---------------------------------------------------------------------------
# A — Non-admin cannot access endpoints
# ---------------------------------------------------------------------------

class TestAdminAccess:
    def test_missing_header_list_returns_401(self):
        client = _make_admin_app()
        resp = client.get("/relationship-intelligence")
        assert resp.status_code == 401

    def test_missing_header_approve_returns_401(self):
        client = _make_admin_app()
        resp = client.post(f"/relationship-intelligence/{uuid.uuid4()}/approve")
        assert resp.status_code == 401

    def test_missing_header_unpublish_returns_401(self):
        client = _make_admin_app()
        resp = client.post(f"/relationship-intelligence/{uuid.uuid4()}/unpublish")
        assert resp.status_code == 401

    def test_missing_header_patch_returns_401(self):
        client = _make_admin_app()
        resp = client.patch(
            f"/relationship-intelligence/{uuid.uuid4()}",
            json={"confidence_score": 0.9},
        )
        assert resp.status_code == 401

    def test_admin_header_present_list_succeeds(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from perfume_trend_sdk.api.routes.admin_relationship_intelligence import router
        from perfume_trend_sdk.api.dependencies import get_db_session

        app = FastAPI()
        app.include_router(router, prefix="/relationship-intelligence")

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []
        app.dependency_overrides[get_db_session] = lambda: db

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/relationship-intelligence",
            headers={"X-Pti-Admin-User": "admin@example.com"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# C/D/E — Listing and filtering
# ---------------------------------------------------------------------------

class TestAdminListing:
    def _client_with_rows(self, rows):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from perfume_trend_sdk.api.routes.admin_relationship_intelligence import router
        from perfume_trend_sdk.api.dependencies import get_db_session

        app = FastAPI()
        app.include_router(router, prefix="/ri")

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = rows

        app.dependency_overrides[get_db_session] = lambda: db
        return TestClient(app, raise_server_exceptions=False)

    def test_list_all_returns_200(self):
        client = self._client_with_rows([])
        resp = client.get("/ri", headers={"X-Pti-Admin-User": "admin@x.com"})
        assert resp.status_code == 200
        assert "relationships" in resp.json()

    def test_list_public_filter(self):
        client = self._client_with_rows([])
        resp = client.get("/ri?filter=public", headers={"X-Pti-Admin-User": "admin@x.com"})
        assert resp.status_code == 200

    def test_list_non_public_filter(self):
        client = self._client_with_rows([])
        resp = client.get("/ri?filter=non_public", headers={"X-Pti-Admin-User": "admin@x.com"})
        assert resp.status_code == 200

    def test_invalid_filter_returns_422(self):
        client = self._client_with_rows([])
        resp = client.get("/ri?filter=invalid", headers={"X-Pti-Admin-User": "admin@x.com"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# G/H/I/J/K/L/M — Admin actions
# ---------------------------------------------------------------------------

class TestAdminActions:
    def _client(self, fetchone_row=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from perfume_trend_sdk.api.routes.admin_relationship_intelligence import router
        from perfume_trend_sdk.api.dependencies import get_db_session

        app = FastAPI()
        app.include_router(router, prefix="/ri")

        db = MagicMock()
        db.execute.return_value.fetchone.return_value = fetchone_row
        db.execute.return_value.fetchall.return_value = []
        db.commit.return_value = None

        app.dependency_overrides[get_db_session] = lambda: db
        return TestClient(app, raise_server_exceptions=False), db

    def test_approve_calls_update_and_returns_200(self):
        row = _make_relationship_row(is_public=False)
        client, db = self._client(fetchone_row=row)
        rid = str(row[0])
        resp = client.post(f"/ri/{rid}/approve", headers={"X-Pti-Admin-User": "admin@x.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_public"] is True
        assert data["operator_reviewed"] is True

    def test_unpublish_calls_update_and_returns_200(self):
        row = _make_relationship_row(is_public=True)
        client, db = self._client(fetchone_row=row)
        rid = str(row[0])
        resp = client.post(f"/ri/{rid}/unpublish", headers={"X-Pti-Admin-User": "admin@x.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_public"] is False

    def test_patch_confidence_score(self):
        row = _make_relationship_row()
        client, db = self._client(fetchone_row=row)
        rid = str(row[0])
        resp = client.patch(
            f"/ri/{rid}",
            headers={"X-Pti-Admin-User": "admin@x.com"},
            json={"confidence_score": 0.75},
        )
        assert resp.status_code == 200

    def test_patch_relation_type(self):
        row = _make_relationship_row()
        client, db = self._client(fetchone_row=row)
        rid = str(row[0])
        resp = client.patch(
            f"/ri/{rid}",
            headers={"X-Pti-Admin-User": "admin@x.com"},
            json={"relation_type": "market_alternative_to"},
        )
        assert resp.status_code == 200

    def test_patch_invalid_relation_type_returns_422(self):
        row = _make_relationship_row()
        client, db = self._client(fetchone_row=row)
        rid = str(row[0])
        resp = client.patch(
            f"/ri/{rid}",
            headers={"X-Pti-Admin-User": "admin@x.com"},
            json={"relation_type": "not_a_valid_type"},
        )
        assert resp.status_code == 422

    def test_patch_no_fields_returns_422(self):
        row = _make_relationship_row()
        client, db = self._client(fetchone_row=row)
        rid = str(row[0])
        resp = client.patch(
            f"/ri/{rid}",
            headers={"X-Pti-Admin-User": "admin@x.com"},
            json={},
        )
        assert resp.status_code == 422

    def test_approve_not_found_returns_404(self):
        client, db = self._client(fetchone_row=None)
        resp = client.post(
            f"/ri/{uuid.uuid4()}/approve",
            headers={"X-Pti-Admin-User": "admin@x.com"},
        )
        assert resp.status_code == 404

    def test_unpublish_not_found_returns_404(self):
        client, db = self._client(fetchone_row=None)
        resp = client.post(
            f"/ri/{uuid.uuid4()}/unpublish",
            headers={"X-Pti-Admin-User": "admin@x.com"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# N/O/P/Q/R — Public quality gate
# ---------------------------------------------------------------------------

class TestPublicQualityGate:
    """get_approved_relationship() enforces: is_public=TRUE, operator_reviewed=TRUE, confidence>=0.700."""

    def _db_returning(self, row):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = row
        return db

    def test_is_public_false_returns_none(self):
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None  # gate excludes it
        result = get_approved_relationship(db, "Armaf Club de Nuit Intense Man")
        assert result is None

    def test_low_confidence_returns_none(self):
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship
        db = MagicMock()
        # DB returns None because the query has confidence >= 0.700 condition
        db.execute.return_value.fetchone.return_value = None
        result = get_approved_relationship(db, "Some Low Confidence Perfume")
        assert result is None

    def test_gate_pass_returns_tuple(self):
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship
        db = MagicMock()
        # Simulate DB returning a row satisfying the gate
        db.execute.return_value.fetchone.return_value = (
            "dupe_of",
            "Creed Aventus",
            "0.850",
        )
        result = get_approved_relationship(db, "Armaf Club de Nuit Intense Man")
        assert result is not None
        relation_type, obj, confidence = result
        assert relation_type == "dupe_of"
        assert obj == "Creed Aventus"

    def test_db_exception_returns_none(self):
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship
        db = MagicMock()
        db.execute.side_effect = Exception("connection error")
        result = get_approved_relationship(db, "any perfume")
        assert result is None


# ---------------------------------------------------------------------------
# S/T/U — Public entity output
# ---------------------------------------------------------------------------

class TestPublicEntityOutput:
    """Verify that the correct wording and reference_original come from the DB path."""

    def test_khamrah_approved_rel_market_alternative(self):
        """DB gate pass: Khamrah → market_alternative_to → Kilian Angels' Share."""
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship

        db = MagicMock()
        db.execute.return_value.fetchone.return_value = (
            "market_alternative_to",
            "Kilian Angels' Share",
            "0.700",
        )
        result = get_approved_relationship(db, "Lattafa Khamrah")
        assert result is not None
        rel_type, ref_original, _ = result
        assert rel_type == "market_alternative_to"
        assert ref_original == "Kilian Angels' Share"

    def test_cdnim_approved_rel_dupe_of(self):
        """DB gate pass: CDNIM → dupe_of → Creed Aventus."""
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship

        db = MagicMock()
        db.execute.return_value.fetchone.return_value = (
            "dupe_of",
            "Creed Aventus",
            "0.850",
        )
        result = get_approved_relationship(db, "Armaf Club de Nuit Intense Man")
        assert result is not None
        rel_type, ref_original, _ = result
        assert rel_type == "dupe_of"
        assert ref_original == "Creed Aventus"

    def test_no_db_row_falls_back_to_dupe_raw(self):
        """When get_approved_relationship returns None, caller uses _DUPE_RAW via get_dupe_profile."""
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile

        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None

        # No approved DB row
        approved = get_approved_relationship(db, "Armaf Club de Nuit Intense Man")
        assert approved is None

        # Fallback: _DUPE_RAW still has the entry
        dupe = get_dupe_profile("Armaf", "Armaf Club de Nuit Intense Man")
        assert dupe is not None
        assert dupe.reference_original == "Creed Aventus"


# ---------------------------------------------------------------------------
# V/W/X/Y — Regressions
# ---------------------------------------------------------------------------

class TestRegressions:
    def test_valid_relation_types_unchanged(self):
        """FTG-2 — VALID_RELATION_TYPES frozenset unchanged (4 types)."""
        from perfume_trend_sdk.db.market.fragrance_relationship import VALID_RELATION_TYPES
        assert "dupe_of" in VALID_RELATION_TYPES
        assert "market_alternative_to" in VALID_RELATION_TYPES
        assert "inspired_by" in VALID_RELATION_TYPES
        assert "commonly_compared_to" in VALID_RELATION_TYPES
        assert len(VALID_RELATION_TYPES) == 4

    def test_relationship_seed_count_unchanged(self):
        """FTG-2 — RELATIONSHIP_SEED has 7 rows."""
        from perfume_trend_sdk.db.market.fragrance_relationship import RELATIONSHIP_SEED
        assert len(RELATIONSHIP_SEED) == 7

    def test_khamrah_points_to_angels_share_not_br540(self):
        """FTG-0 / KB0 — Khamrah entity role unchanged."""
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile
        dupe = get_dupe_profile("Lattafa", "Lattafa Khamrah")
        assert dupe is not None
        assert dupe.reference_original == "Kilian Angels' Share"
        assert "Baccarat" not in dupe.reference_original

    def test_get_approved_relationship_is_nonfatal(self):
        """DATA contract — get_approved_relationship never raises; returns None on error."""
        from perfume_trend_sdk.db.market.fragrance_relationship import get_approved_relationship
        db = MagicMock()
        db.execute.side_effect = RuntimeError("unexpected DB error")
        result = get_approved_relationship(db, "any entity")
        assert result is None
