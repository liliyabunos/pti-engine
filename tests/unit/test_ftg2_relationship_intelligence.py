"""FTG-2 / RI1 — Relationship Intelligence Core tests.

Tests cover:
  - VALID_RELATION_TYPES contains all 4 approved types and no others
  - RELATIONSHIP_SEED has expected row count and evidence count
  - Seed semantic correctness:
    - Armaf CDNIM → dupe_of Creed Aventus (strong clone)
    - Khamrah → market_alternative_to Angels' Share (founder correction: not dupe_of)
    - Khamrah Qahwa → market_alternative_to Angels' Share (conservative: same reasoning)
    - Montblanc Explorer → market_alternative_to Creed Aventus (designer alternative)
    - Zara Red Temptation → dupe_of BR540
    - Ariana Grande Cloud → market_alternative_to BR540
  - Confidence score defaults: dupe_of ≈ 0.85, market_alternative_to ≈ 0.70
  - All seeded rows: is_public=False, operator_reviewed=True
  - Column naming: subject_canonical_name / object_canonical_name (not *_id)
  - get_relationships() returns [] on DB exception (non-fatal)
  - get_relationships() returns [] when no matching rows
  - entity_role.py / KB0 behavior unchanged (FTG-2 does not alter public display)
  - Alias collapse: CDNIM/alias variants are NOT separate relationship rows
"""

import importlib.util
import os
import pytest
from unittest.mock import MagicMock
from decimal import Decimal

from perfume_trend_sdk.db.market.fragrance_relationship import (
    VALID_RELATION_TYPES,
    RELATIONSHIP_SEED,
    get_relationships,
    FragranceRelationship,
    RelationshipEvidence,
)

# Migration module loaded via spec_from_file_location (filename starts with digit)
_MIG046_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../alembic/versions/046_fragrance_relationships.py",
)
_spec = importlib.util.spec_from_file_location("mig046", _MIG046_PATH)
_mig046 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig046)


# ---------------------------------------------------------------------------
# VALID_RELATION_TYPES
# ---------------------------------------------------------------------------

class TestValidRelationTypes:
    def test_contains_dupe_of(self):
        assert "dupe_of" in VALID_RELATION_TYPES

    def test_contains_market_alternative_to(self):
        assert "market_alternative_to" in VALID_RELATION_TYPES

    def test_contains_inspired_by(self):
        assert "inspired_by" in VALID_RELATION_TYPES

    def test_contains_commonly_compared_to(self):
        assert "commonly_compared_to" in VALID_RELATION_TYPES

    def test_exactly_four_types(self):
        assert len(VALID_RELATION_TYPES) == 4

    def test_no_brand_tier_encoding(self):
        """Relation types must not encode brand tier (e.g. no 'designer_alternative')."""
        for t in VALID_RELATION_TYPES:
            assert "designer" not in t
            assert "celebrity" not in t
            assert "niche" not in t
            assert "clone_house" not in t

    def test_no_disputed_type(self):
        """'disputed' must not be a relation_type (deferred to FTG-3 consensus model)."""
        assert "disputed" not in VALID_RELATION_TYPES

    def test_is_frozenset(self):
        assert isinstance(VALID_RELATION_TYPES, frozenset)


# ---------------------------------------------------------------------------
# RELATIONSHIP_SEED structure
# ---------------------------------------------------------------------------

class TestRelationshipSeedStructure:
    def test_seed_has_seven_rows(self):
        assert len(RELATIONSHIP_SEED) == 7

    def test_all_rows_have_required_fields(self):
        required = {
            "subject_canonical_name", "relation_type", "object_canonical_name",
            "confidence_score", "evidence_summary",
        }
        for row in RELATIONSHIP_SEED:
            assert required.issubset(row.keys()), f"Missing fields in {row['subject_canonical_name']}"

    def test_all_relation_types_are_valid(self):
        for row in RELATIONSHIP_SEED:
            assert row["relation_type"] in VALID_RELATION_TYPES, (
                f"Invalid relation_type '{row['relation_type']}' for {row['subject_canonical_name']}"
            )

    def test_column_naming_uses_canonical_name_not_id(self):
        """Columns must be subject_canonical_name / object_canonical_name, not *_id."""
        for row in RELATIONSHIP_SEED:
            assert "subject_canonical_name" in row
            assert "object_canonical_name" in row
            assert "subject_entity_id" not in row
            assert "object_entity_id" not in row
            assert "subject_id" not in row
            assert "object_id" not in row

    def test_no_alias_variants_in_seed(self):
        """CDNIM / 'Club de Nuit Intense Man' / 'Armaf CDNIM' must not be separate seed rows.
        Only the canonical perfume name is stored."""
        subjects = [r["subject_canonical_name"] for r in RELATIONSHIP_SEED]
        assert "CDNIM" not in subjects
        assert "Armaf CDNIM" not in subjects
        assert "Club de Nuit Intense Man" not in subjects


# ---------------------------------------------------------------------------
# Seed semantic correctness
# ---------------------------------------------------------------------------

def _find_seed(subject: str) -> dict:
    """Helper: return seed row for given subject, raises if not found."""
    matches = [r for r in RELATIONSHIP_SEED if r["subject_canonical_name"] == subject]
    assert matches, f"No seed row for subject '{subject}'"
    return matches[0]


class TestSeedSemantics:

    def test_cdnim_is_dupe_of_aventus(self):
        row = _find_seed("Armaf Club de Nuit Intense Man")
        assert row["relation_type"] == "dupe_of"
        assert row["object_canonical_name"] == "Creed Aventus"

    def test_cdni_is_dupe_of_aventus(self):
        row = _find_seed("Armaf Club de Nuit Intense")
        assert row["relation_type"] == "dupe_of"
        assert row["object_canonical_name"] == "Creed Aventus"

    def test_montblanc_explorer_is_market_alternative_to_aventus(self):
        row = _find_seed("Montblanc Explorer")
        assert row["relation_type"] == "market_alternative_to"
        assert row["object_canonical_name"] == "Creed Aventus"

    # Khamrah founder correction: must NOT be dupe_of
    def test_khamrah_is_market_alternative_to_angels_share(self):
        """Founder correction: Khamrah is market_alternative_to, not dupe_of."""
        row = _find_seed("Lattafa Khamrah")
        assert row["relation_type"] == "market_alternative_to"
        assert row["object_canonical_name"] == "Kilian Angels' Share"

    def test_khamrah_is_not_dupe_of(self):
        """Critical: Khamrah must NOT be dupe_of in RI1 seed."""
        row = _find_seed("Lattafa Khamrah")
        assert row["relation_type"] != "dupe_of"

    def test_khamrah_is_not_angels_share_dupe(self):
        """Khamrah RI1 relation_type must be conservative (market_alternative_to)."""
        row = _find_seed("Lattafa Khamrah")
        assert row["relation_type"] == "market_alternative_to"

    # Qahwa: same conservative treatment as Khamrah
    def test_qahwa_is_market_alternative_to_angels_share(self):
        """Qahwa: conservative — same as Khamrah parent."""
        row = _find_seed("Lattafa Khamrah Qahwa")
        assert row["relation_type"] == "market_alternative_to"
        assert row["object_canonical_name"] == "Kilian Angels' Share"

    def test_qahwa_is_not_dupe_of(self):
        row = _find_seed("Lattafa Khamrah Qahwa")
        assert row["relation_type"] != "dupe_of"

    def test_zara_red_temptation_is_dupe_of_br540(self):
        row = _find_seed("Zara Red Temptation")
        assert row["relation_type"] == "dupe_of"
        assert "Baccarat Rouge 540" in row["object_canonical_name"]

    def test_ariana_cloud_is_market_alternative_to_br540(self):
        row = _find_seed("Ariana Grande Cloud")
        assert row["relation_type"] == "market_alternative_to"
        assert "Baccarat Rouge 540" in row["object_canonical_name"]


# ---------------------------------------------------------------------------
# Confidence scores
# ---------------------------------------------------------------------------

class TestConfidenceScores:

    def test_dupe_of_rows_have_085_confidence(self):
        dupe_rows = [r for r in RELATIONSHIP_SEED if r["relation_type"] == "dupe_of"]
        for row in dupe_rows:
            assert Decimal(row["confidence_score"]) == Decimal("0.850"), (
                f"Expected 0.850 for {row['subject_canonical_name']}"
            )

    def test_market_alternative_rows_have_070_confidence(self):
        alt_rows = [r for r in RELATIONSHIP_SEED if r["relation_type"] == "market_alternative_to"]
        for row in alt_rows:
            assert Decimal(row["confidence_score"]) == Decimal("0.700"), (
                f"Expected 0.700 for {row['subject_canonical_name']}"
            )

    def test_khamrah_confidence_is_070(self):
        """Khamrah is market_alternative_to at 0.70 — not elevated to 0.85."""
        row = _find_seed("Lattafa Khamrah")
        assert Decimal(row["confidence_score"]) == Decimal("0.700")


# ---------------------------------------------------------------------------
# is_public / operator_reviewed (FTG-2 public contract)
# ---------------------------------------------------------------------------

class TestPublicContract:

    def test_all_seeded_rows_are_not_public(self):
        """FTG-2 seeds with is_public=FALSE — FTG-3 promotes to public."""
        for row in _mig046._RELATIONSHIPS:
            assert row["is_public"] is False, (
                f"Expected is_public=FALSE for {row['subject_canonical_name']}"
            )

    def test_all_seeded_rows_are_operator_reviewed(self):
        for row in _mig046._RELATIONSHIPS:
            assert row["operator_reviewed"] is True, (
                f"Expected operator_reviewed=TRUE for {row['subject_canonical_name']}"
            )

    def test_migration_seed_count_matches_relationship_seed(self):
        assert len(_mig046._RELATIONSHIPS) == len(RELATIONSHIP_SEED) == 7
        assert len(_mig046._EVIDENCE) == 7

    def test_migration_evidence_is_dupe_map_seed_type(self):
        for ev in _mig046._EVIDENCE:
            assert ev["evidence_type"] == "dupe_map_seed"


# ---------------------------------------------------------------------------
# get_relationships() — read helper safety
# ---------------------------------------------------------------------------

class TestGetRelationshipsSafety:

    def test_db_exception_returns_empty_list(self):
        """Non-fatal: DB exception → []."""
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("table does not exist")
        result = get_relationships(mock_db, "Armaf Club de Nuit Intense Man")
        assert result == []

    def test_db_miss_returns_empty_list(self):
        """No matching rows → []."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []
        result = get_relationships(mock_db, "Unknown Fragrance XYZ")
        assert result == []

    def test_db_hit_returns_rows(self):
        """Matching rows returned as list."""
        mock_db = MagicMock()
        mock_row = ("fake-id", "Armaf Club de Nuit Intense Man", "dupe_of",
                    "Creed Aventus", 0.85, False, True,
                    None, None, "evidence text", 1, None)
        mock_db.execute.return_value.fetchall.return_value = [mock_row]
        result = get_relationships(mock_db, "Armaf Club de Nuit Intense Man")
        assert len(result) == 1

    def test_none_subject_does_not_crash(self):
        """None input handled without crash."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []
        result = get_relationships(mock_db, None)
        assert result == []

    def test_relation_type_filter_passes_param(self):
        """relation_type filter param is included in query."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []
        get_relationships(mock_db, "Creed Aventus", relation_type="commonly_compared_to")
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params.get("rtype") == "commonly_compared_to"


# ---------------------------------------------------------------------------
# KB0 / entity_role.py regression — FTG-2 must not break public display
# ---------------------------------------------------------------------------

class TestEntityRoleFTG2Regression:
    """FTG-2 must not alter entity_role.py / KB0 public display behavior."""

    def test_khamrah_entity_role_is_dupe_alternative(self):
        """entity_role.py still returns dupe_alternative for Khamrah (legacy path).
        FTG-3, not FTG-2, decides when RI1 data overrides the public label."""
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import (
            classify_entity_role,
            get_dupe_profile,
        )
        role = classify_entity_role("Lattafa", "Lattafa Khamrah")
        assert role == "dupe_alternative"

    def test_khamrah_reference_original_is_angels_share(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile
        dupe = get_dupe_profile("Lattafa", "Lattafa Khamrah")
        assert dupe is not None
        assert dupe.reference_original == "Kilian Angels' Share"

    def test_khamrah_is_not_br540_in_entity_role(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile
        dupe = get_dupe_profile("Lattafa", "Lattafa Khamrah")
        assert dupe.reference_original != "Maison Francis Kurkdjian Baccarat Rouge 540"

    def test_cdnim_entity_role_unchanged(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import classify_entity_role
        role = classify_entity_role("Armaf", "Armaf Club de Nuit Intense Man")
        assert role == "dupe_alternative"

    def test_creed_entity_role_unchanged(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import classify_entity_role
        assert classify_entity_role("Creed") == "niche_original"

    def test_dior_entity_role_unchanged(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import classify_entity_role
        assert classify_entity_role("Dior") == "designer_original"

    def test_ariana_grande_entity_role_unchanged(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import classify_entity_role
        role = classify_entity_role("Ariana Grande", "Ariana Grande Cloud")
        assert role == "celebrity_alternative"
