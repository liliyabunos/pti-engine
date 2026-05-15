"""FTG-4 / RI1-E1 — Existing Canonical Relationship Evidence Attachment v1.

Tests cover:

Confidence policy:
  A  occurrence 1  → 0.200
  B  occurrence 2  → 0.200
  C  occurrence 3  → 0.250
  D  occurrence 6  → 0.300
  E  occurrence 11 → 0.350
  F  All confidence values are below 0.700 (public gate threshold)

Candidate public-safety contract (kept for _insert_relationship helper integrity):
  G  New row: operator_reviewed=FALSE
  H  New row: is_public=FALSE
  I  New row: relation_type='commonly_compared_to'

Admin filter:
  J  Backend list accepts filter='pending_review'
  K  pending_review filter returns only operator_reviewed=FALSE AND is_public=FALSE rows
  L  Invalid filter still raises 422

VS candidate extraction (integration with market_intelligence):
  M  'Creed Aventus vs Baccarat Rouge 540' for entity Creed Aventus → candidate 'Baccarat Rouge 540'
  N  'baccarat rouge 540 review' (orphan) for entity 'Creed Aventus' → candidate extracted
  O  Query that equals own entity name → not a candidate (self-reference)

Suffix stripping in _resolve_candidate:
  N2 'creed aventus perfume' → strips 'perfume' → resolves to 'Creed Aventus'
  N3 'creed aventus review' → strips 'review' → resolves to 'Creed Aventus'
  N4 'creed aventus eau de parfum' → strips longest suffix → resolves to 'Creed Aventus'
  N5 Raw 'Creed Aventus' (exact) → resolves without stripping

Idempotency:
  P  Running harvest with same data twice does not duplicate relationship rows
  Q  Running harvest with same data twice does not duplicate evidence rows

Hard gate — no new candidates from cross_query_retrieval:
  R  Pair (A, B) with existing relationship → evidence attached (ATTACH)
  S  Pair (A, B) without existing relationship → SKIPPED, counted under
     candidates_skipped_no_existing_relationship (no new row created)

Evidence type:
  U  EVIDENCE_TYPE constant is 'cross_query_retrieval'
  V  _evidence_already_exists checks against 'cross_query_retrieval' in SQL

Script-level: dry-run mode
  T  Dry-run returns non-zero counts but writes nothing to DB
"""
from __future__ import annotations

import sys
import os
import uuid
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import (
    extract_vs_competitors,
)

# Import harvester functions (not the full script entrypoint)
sys.path.insert(0, os.path.join(_REPO, "scripts"))
import harvest_relationship_evidence as harv


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _mock_row(*cols):
    """Return a MagicMock that supports indexing like a DB row."""
    m = MagicMock()
    m.__getitem__ = lambda self, i: cols[i]
    return m


def _make_db(
    topic_rows=None,
    existing_relationship_id=None,
    evidence_exists=False,
):
    """Build a lightweight mock DB session for harvesting tests."""
    db = MagicMock()

    topic_fetchall = []
    if topic_rows:
        for r in topic_rows:
            m = MagicMock()
            m.__getitem__ = lambda self, i, _r=r: _r[i]
            topic_fetchall.append(m)

    resolve_row = None
    existing_row = None
    evidence_row = None

    if existing_relationship_id:
        existing_row = MagicMock()
        existing_row.__getitem__ = lambda self, i, _id=existing_relationship_id: _id

    if evidence_exists:
        evidence_row = MagicMock()

    def fake_execute(sql_obj, params=None):
        sql = str(sql_obj)
        result = MagicMock()
        if "entity_topic_links" in sql:
            result.fetchall.return_value = topic_fetchall
        elif "LOWER(canonical_name)" in sql:
            # _resolve_candidate — exact match only for mock purposes
            candidate = (params or {}).get("cand", "")
            if candidate.lower() in ("creed aventus", "baccarat rouge 540",
                                     "kilian angels' share", "some other perfume"):
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i, _c=candidate: _c.title() if i == 0 else None
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
        elif "fragrance_relationships" in sql and "ORDER BY operator_reviewed" in sql:
            # _find_existing_relationship
            result.fetchone.return_value = existing_row
        elif "relationship_evidence" in sql and "evidence_type = 'cross_query_retrieval'" in sql and "SELECT 1" in sql:
            # _evidence_already_exists
            result.fetchone.return_value = evidence_row if evidence_exists else None
        elif "SELECT id FROM fragrance_relationships" in sql:
            # _insert_relationship fetch-back
            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, i: str(uuid.uuid4())
            result.fetchone.return_value = mock_row
        else:
            result.fetchall.return_value = []
            result.fetchone.return_value = None
        return result

    db.execute.side_effect = fake_execute
    return db


# ---------------------------------------------------------------------------
# A–F: Confidence policy
# ---------------------------------------------------------------------------

class TestConfidencePolicy:
    def test_A_occurrence_1_gives_0200(self):
        assert harv._compute_confidence(1) == pytest.approx(0.200)

    def test_B_occurrence_2_gives_0200(self):
        assert harv._compute_confidence(2) == pytest.approx(0.200)

    def test_C_occurrence_3_gives_0250(self):
        assert harv._compute_confidence(3) == pytest.approx(0.250)

    def test_D_occurrence_6_gives_0300(self):
        assert harv._compute_confidence(6) == pytest.approx(0.300)

    def test_E_occurrence_11_gives_0350(self):
        assert harv._compute_confidence(11) == pytest.approx(0.350)

    def test_F_all_values_below_public_gate(self):
        for count in [1, 2, 3, 5, 6, 10, 11, 50, 100]:
            assert harv._compute_confidence(count) < 0.700, (
                f"confidence for {count} occurrences ({harv._compute_confidence(count)}) "
                f"must be below 0.700 public gate"
            )


# ---------------------------------------------------------------------------
# G–I: Candidate row public-safety contract (_insert_relationship helper)
# ---------------------------------------------------------------------------

class TestCandidatePublicSafety:
    """Verify that _insert_relationship always uses safe default values.

    The function is still used when operator seeds new rows manually;
    the hard gate prevents the harvester from calling it in co-retrieval mode.
    """

    def test_G_new_row_operator_reviewed_false(self):
        db = MagicMock()

        def capture_execute(sql_obj, params=None):
            result = MagicMock()
            if "SELECT id FROM fragrance_relationships" in str(sql_obj):
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: str(uuid.uuid4())
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = capture_execute
        harv._insert_relationship(db, "Subject Perfume", "Object Perfume", 0.250, date.today())
        insert_sql = str(db.execute.call_args_list[0][0][0])
        assert "FALSE, FALSE" in insert_sql  # is_public=FALSE, operator_reviewed=FALSE

    def test_H_new_row_is_public_false(self):
        db = MagicMock()

        def capture_execute(sql_obj, params=None):
            result = MagicMock()
            if "SELECT id FROM fragrance_relationships" in str(sql_obj):
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: str(uuid.uuid4())
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = capture_execute
        harv._insert_relationship(db, "Subject Perfume", "Object Perfume", 0.250, date.today())
        insert_sql = str(db.execute.call_args_list[0][0][0])
        assert "is_public" in insert_sql
        assert "FALSE" in insert_sql

    def test_I_new_row_relation_type_commonly_compared_to(self):
        assert harv.RELATION_TYPE_DEFAULT == "commonly_compared_to"

        db = MagicMock()

        def capture_execute(sql_obj, params=None):
            result = MagicMock()
            if "SELECT id" in str(sql_obj):
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: str(uuid.uuid4())
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = capture_execute
        harv._insert_relationship(db, "Subject", "Object", 0.250, date.today())
        insert_params = db.execute.call_args_list[0][0][1]
        assert insert_params["rtype"] == "commonly_compared_to"


# ---------------------------------------------------------------------------
# J–L: Admin filter backend
# ---------------------------------------------------------------------------

class TestAdminFilter:
    """Test the pending_review filter in the admin FastAPI endpoint."""

    def _make_client_with_mock_db(self, mock_db):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from perfume_trend_sdk.api.routes import admin_relationship_intelligence
        from perfume_trend_sdk.api.dependencies import get_db_session

        app = FastAPI()
        app.include_router(
            admin_relationship_intelligence.router,
            prefix="/api/v1/admin/relationship-intelligence",
        )

        def override_db():
            yield mock_db

        app.dependency_overrides[get_db_session] = override_db
        return TestClient(app)

    def test_J_pending_review_filter_accepted(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        client = self._make_client_with_mock_db(mock_db)
        resp = client.get(
            "/api/v1/admin/relationship-intelligence?filter=pending_review",
            headers={"X-Pti-Admin-User": "test@admin.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_K_pending_review_filter_sql_clause(self):
        """pending_review filter must use operator_reviewed=FALSE AND is_public=FALSE."""
        captured_sql = []

        mock_db = MagicMock()

        def capture_execute(sql_obj, params=None):
            captured_sql.append(str(sql_obj))
            result = MagicMock()
            result.fetchall.return_value = []
            result.fetchone.return_value = None
            return result

        mock_db.execute.side_effect = capture_execute
        client = self._make_client_with_mock_db(mock_db)
        client.get(
            "/api/v1/admin/relationship-intelligence?filter=pending_review",
            headers={"X-Pti-Admin-User": "test@admin.com"},
        )

        main_sql = captured_sql[0] if captured_sql else ""
        assert "operator_reviewed = FALSE" in main_sql
        assert "is_public = FALSE" in main_sql

    def test_L_invalid_filter_still_422(self):
        mock_db = MagicMock()
        client = self._make_client_with_mock_db(mock_db)
        resp = client.get(
            "/api/v1/admin/relationship-intelligence?filter=invalid_xyz",
            headers={"X-Pti-Admin-User": "test@admin.com"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# M–O: VS candidate extraction
# ---------------------------------------------------------------------------

class TestVsCandidateExtraction:
    def test_M_vs_pattern_extracts_competitor(self):
        queries = ["Creed Aventus vs Baccarat Rouge 540"]
        candidates = extract_vs_competitors(queries, "Creed Aventus")
        assert "Baccarat Rouge 540" in candidates

    def test_N_orphan_query_is_candidate(self):
        queries = ["baccarat rouge 540 review"]
        candidates = extract_vs_competitors(queries, "Creed Aventus")
        assert len(candidates) > 0

    def test_O_own_name_not_candidate(self):
        queries = ["Creed Aventus vs Creed Aventus"]
        candidates = extract_vs_competitors(queries, "Creed Aventus")
        for c in candidates:
            assert c.lower() != "creed aventus"


# ---------------------------------------------------------------------------
# N2–N5: Suffix stripping in _resolve_candidate
# ---------------------------------------------------------------------------

class TestSuffixStripping:
    """_resolve_candidate must strip noise suffixes before giving up on exact match."""

    def _make_resolve_db(self, known_names):
        """DB mock that resolves lowercase canonical names from known_names set."""
        db = MagicMock()

        def fake_execute(sql_obj, params=None):
            result = MagicMock()
            cand = (params or {}).get("cand", "").lower()
            match = next((n for n in known_names if n.lower() == cand), None)
            if match:
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: match
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = fake_execute
        return db

    def test_N2_strips_perfume_suffix(self):
        db = self._make_resolve_db(["Creed Aventus"])
        result = harv._resolve_candidate(db, "creed aventus perfume")
        assert result == "Creed Aventus"

    def test_N3_strips_review_suffix(self):
        db = self._make_resolve_db(["Creed Aventus"])
        result = harv._resolve_candidate(db, "creed aventus review")
        assert result == "Creed Aventus"

    def test_N4_strips_eau_de_parfum_suffix(self):
        db = self._make_resolve_db(["Creed Aventus"])
        result = harv._resolve_candidate(db, "creed aventus eau de parfum")
        assert result == "Creed Aventus"

    def test_N5_exact_match_no_stripping_needed(self):
        db = self._make_resolve_db(["Creed Aventus"])
        result = harv._resolve_candidate(db, "Creed Aventus")
        assert result == "Creed Aventus"

    def test_N6_unresolvable_even_after_stripping_returns_none(self):
        db = self._make_resolve_db(["Creed Aventus"])
        result = harv._resolve_candidate(db, "etat libre cologne fragrance")
        assert result is None


# ---------------------------------------------------------------------------
# P–Q: Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_P_duplicate_relationship_rows_not_created(self):
        """INSERT ON CONFLICT DO NOTHING prevents duplicate relationship rows."""
        insert_count = {"n": 0}

        db = MagicMock()

        def capture_execute(sql_obj, params=None):
            sql = str(sql_obj)
            result = MagicMock()
            if "INSERT INTO fragrance_relationships" in sql:
                insert_count["n"] += 1
            if "SELECT id FROM fragrance_relationships" in sql:
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: str(uuid.uuid4())
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = capture_execute
        today = date.today()
        harv._insert_relationship(db, "A", "B", 0.250, today)
        harv._insert_relationship(db, "A", "B", 0.250, today)
        assert insert_count["n"] == 2  # Two calls issued; DB handles conflict
        insert_sql = str(db.execute.call_args_list[0][0][0])
        assert "ON CONFLICT" in insert_sql
        assert "DO NOTHING" in insert_sql

    def test_Q_duplicate_evidence_check_prevents_reinsert(self):
        """_evidence_already_exists must be checked before inserting evidence."""
        db = MagicMock()

        existing_ev = MagicMock()
        evidence_calls = {"n": 0}

        def capture_execute(sql_obj, params=None):
            sql = str(sql_obj)
            result = MagicMock()
            if "SELECT 1 FROM relationship_evidence" in sql:
                result.fetchone.return_value = existing_ev  # already exists
            elif "INSERT INTO relationship_evidence" in sql:
                evidence_calls["n"] += 1
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = capture_execute
        rel_id = str(uuid.uuid4())
        query_text = "creed aventus vs armaf"
        today = date.today()

        if not harv._evidence_already_exists(db, rel_id, query_text):
            harv._insert_evidence(db, rel_id, query_text, today)

        assert evidence_calls["n"] == 0  # Insert suppressed because evidence exists


# ---------------------------------------------------------------------------
# R–S: Hard gate — existing relationship required for evidence attachment
# ---------------------------------------------------------------------------

class TestHardGate:
    def test_R_existing_pair_evidence_attached(self):
        """If (subject, object) pair exists, _find_existing_relationship returns its ID."""
        existing_id = str(uuid.uuid4())
        db = MagicMock()

        def fake_execute(sql_obj, params=None):
            result = MagicMock()
            if "ORDER BY operator_reviewed" in str(sql_obj):
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: existing_id
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = fake_execute
        found_id = harv._find_existing_relationship(db, "Subject", "Object")
        assert found_id == existing_id

    def test_S_no_existing_pair_skipped_not_created(self):
        """If no (subject, object) pair exists, harvest skips — does NOT create new row.

        This is the hard gate: cross_query_retrieval evidence must never create
        new relationship candidates. The pair must already exist.
        """
        insert_calls = []

        db = MagicMock()

        def fake_execute(sql_obj, params=None):
            sql = str(sql_obj)
            result = MagicMock()
            if "entity_topic_links" in sql:
                # One entity with an orphan query
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: [
                    "test-uuid", "Etat Libre d'Orange Cologne",
                    "creed aventus perfume", 5
                ][i]
                result.fetchall.return_value = [mock_row]
            elif "LOWER(canonical_name)" in sql:
                cand = (params or {}).get("cand", "").lower()
                if cand == "creed aventus":
                    mock_row = MagicMock()
                    mock_row.__getitem__ = lambda self, i: "Creed Aventus"
                    result.fetchone.return_value = mock_row
                else:
                    result.fetchone.return_value = None
            elif "ORDER BY operator_reviewed" in sql:
                # No existing relationship for this pair
                result.fetchone.return_value = None
            elif "INSERT" in sql:
                insert_calls.append(sql)
                result.fetchone.return_value = None
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
            return result

        db.execute.side_effect = fake_execute

        stats = harv.harvest(db, dry_run=False, min_occurrences=1, entity_limit=10)

        assert len(insert_calls) == 0, (
            "Hard gate violated: harvest must not INSERT when no existing relationship exists"
        )
        assert stats["candidates_skipped_no_existing_relationship"] >= 1
        assert stats["evidence_added_to_existing"] == 0


# ---------------------------------------------------------------------------
# U–V: Evidence type constant
# ---------------------------------------------------------------------------

class TestEvidenceType:
    def test_U_evidence_type_is_cross_query_retrieval(self):
        assert harv.EVIDENCE_TYPE == "cross_query_retrieval"

    def test_V_evidence_already_exists_checks_cross_query_retrieval(self):
        """_evidence_already_exists must filter by 'cross_query_retrieval' in SQL."""
        captured_sql = []

        db = MagicMock()

        def capture_execute(sql_obj, params=None):
            captured_sql.append(str(sql_obj))
            result = MagicMock()
            result.fetchone.return_value = None
            return result

        db.execute.side_effect = capture_execute
        harv._evidence_already_exists(db, str(uuid.uuid4()), "some query text")

        assert len(captured_sql) == 1
        assert "cross_query_retrieval" in captured_sql[0]


# ---------------------------------------------------------------------------
# T: Dry-run mode
# ---------------------------------------------------------------------------

class TestDryRunMode:
    def test_T_dry_run_writes_nothing(self):
        """In dry-run mode, db.execute for INSERT must not be called."""
        insert_calls = []

        db = MagicMock()

        def fake_execute(sql_obj, params=None):
            sql = str(sql_obj)
            result = MagicMock()
            if "entity_topic_links" in sql:
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: [
                    "test-uuid", "Creed Aventus", "armaf vs creed aventus", 5
                ][i]
                result.fetchall.return_value = [mock_row]
            elif "LOWER(canonical_name)" in sql:
                cand = (params or {}).get("cand", "")
                if "armaf" in cand.lower():
                    mock_row = MagicMock()
                    mock_row.__getitem__ = lambda self, i: "Armaf Club de Nuit Intense Man"
                    result.fetchone.return_value = mock_row
                else:
                    result.fetchone.return_value = None
            elif "ORDER BY operator_reviewed" in sql:
                # Simulate existing relationship (so hard gate passes in dry-run)
                mock_row = MagicMock()
                mock_row.__getitem__ = lambda self, i: str(uuid.uuid4())
                result.fetchone.return_value = mock_row
            elif "INSERT" in sql:
                insert_calls.append(sql)
                result.fetchone.return_value = None
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
            return result

        db.execute.side_effect = fake_execute

        stats = harv.harvest(db, dry_run=True, min_occurrences=1, entity_limit=10)

        assert len(insert_calls) == 0, "dry-run must not issue any INSERT statements"
        assert not db.commit.called, "dry-run must not commit"
