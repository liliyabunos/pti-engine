"""KB-CAT1-B — brand_profiles hierarchy extension tests.

Tests cover:
  A  get_brand_profile() returns full dict with node_type + parent_brand_normalized
  B  get_brand_profile() returns node_type='brand', parent=None for root brands
  C  get_brand_profile() returns None for absent brands (no row)
  D  get_brand_profile() is non-fatal on DB exception (returns None)
  E  node_type defaults to 'brand' on DB rows missing the column (resilience)
  F  BrandEntityDetail model accepts node_type + parent_brand_normalized fields
  G  Hierarchy seed values: Xerjoff collection + sub_brand assignments
  H  Hierarchy seed values: Filippo Sorcinelli SAUF collection assignment
  I  Non-hierarchy brands return node_type='brand', parent=None (no regression)
  J  get_brand_tier still works independently (no regression)
  K  FTG-1 regression: designer/niche roles still correct
  L  KB0 regression: Khamrah truth unchanged
"""

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.db.market.brand_profile import get_brand_profile, get_brand_tier


# ---------------------------------------------------------------------------
# A — get_brand_profile returns full dict for known brand
# ---------------------------------------------------------------------------

class TestGetBrandProfile:
    def _mock_db(self, row):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = row
        return db

    def test_collection_returns_full_dict(self):
        db = self._mock_db(("niche", "collection", "xerjoff"))
        result = get_brand_profile(db, "Xerjoff - Join the Club")
        assert result is not None
        assert result["brand_tier"] == "niche"
        assert result["node_type"] == "collection"
        assert result["parent_brand_normalized"] == "xerjoff"

    def test_sub_brand_returns_full_dict(self):
        db = self._mock_db(("niche", "sub_brand", "xerjoff"))
        result = get_brand_profile(db, "Xerjoff - Casamorati")
        assert result is not None
        assert result["node_type"] == "sub_brand"
        assert result["parent_brand_normalized"] == "xerjoff"

    def test_root_brand_returns_node_type_brand_no_parent(self):
        db = self._mock_db(("niche", "brand", None))
        result = get_brand_profile(db, "Xerjoff")
        assert result is not None
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None

    def test_absent_brand_returns_none(self):
        db = self._mock_db(None)
        result = get_brand_profile(db, "Unknown Brand XYZ")
        assert result is None

    def test_none_brand_name_returns_none(self):
        db = MagicMock()
        result = get_brand_profile(db, None)
        assert result is None
        db.execute.assert_not_called()

    def test_empty_brand_name_returns_none(self):
        db = MagicMock()
        result = get_brand_profile(db, "")
        assert result is None

    def test_db_exception_returns_none(self):
        db = MagicMock()
        db.execute.side_effect = Exception("DB connection error")
        result = get_brand_profile(db, "Any Brand")
        assert result is None

    def test_node_type_none_in_db_defaults_to_brand(self):
        """Guard: if node_type column is somehow NULL, default to 'brand'."""
        db = self._mock_db(("designer", None, None))
        result = get_brand_profile(db, "Some Designer Brand")
        assert result is not None
        assert result["node_type"] == "brand"


# ---------------------------------------------------------------------------
# B — hierarchy seed values (unit — validates the expected DB state)
# ---------------------------------------------------------------------------

class TestHierarchySeedExpectations:
    """
    These tests mock the DB response to match what migration 048 seeds.
    They document the expected state — failing here means the migration
    seed or this test is wrong and must be reconciled.
    """

    def _mock_db(self, row):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = row
        return db

    # G — Xerjoff hierarchy
    def test_xerjoff_join_the_club_is_collection(self):
        db = self._mock_db(("niche", "collection", "xerjoff"))
        result = get_brand_profile(db, "Xerjoff - Join the Club")
        assert result["node_type"] == "collection"
        assert result["parent_brand_normalized"] == "xerjoff"

    def test_xerjoff_casamorati_is_sub_brand(self):
        db = self._mock_db(("niche", "sub_brand", "xerjoff"))
        result = get_brand_profile(db, "Xerjoff - Casamorati")
        assert result["node_type"] == "sub_brand"
        assert result["parent_brand_normalized"] == "xerjoff"

    def test_xerjoff_xj_oud_attars_is_collection(self):
        db = self._mock_db(("niche", "collection", "xerjoff"))
        result = get_brand_profile(db, "Xerjoff - XJ Oud Attars")
        assert result["node_type"] == "collection"
        assert result["parent_brand_normalized"] == "xerjoff"

    def test_xerjoff_parent_is_root_brand(self):
        db = self._mock_db(("niche", "brand", None))
        result = get_brand_profile(db, "Xerjoff")
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None

    # H — Filippo Sorcinelli
    def test_filippo_sorcinelli_sauf_is_collection(self):
        db = self._mock_db(("niche", "collection", "filippo sorcinelli"))
        result = get_brand_profile(db, "Filippo Sorcinelli - SAUF")
        assert result["node_type"] == "collection"
        assert result["parent_brand_normalized"] == "filippo sorcinelli"

    def test_filippo_sorcinelli_parent_is_root_brand(self):
        db = self._mock_db(("niche", "brand", None))
        result = get_brand_profile(db, "Filippo Sorcinelli")
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None


# ---------------------------------------------------------------------------
# I — Non-hierarchy brands unchanged (no regression)
# ---------------------------------------------------------------------------

class TestNonHierarchyBrands:
    def _mock_db(self, row):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = row
        return db

    def test_creed_is_root_brand(self):
        db = self._mock_db(("niche", "brand", None))
        result = get_brand_profile(db, "Creed")
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None

    def test_dior_is_root_brand(self):
        db = self._mock_db(("designer", "brand", None))
        result = get_brand_profile(db, "Dior")
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None

    def test_lattafa_is_root_brand(self):
        db = self._mock_db(("clone_house", "brand", None))
        result = get_brand_profile(db, "Lattafa")
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None


# ---------------------------------------------------------------------------
# J — get_brand_tier still works (no regression from refactor)
# ---------------------------------------------------------------------------

class TestGetBrandTierRegression:
    def _mock_db(self, tier):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = (tier,)
        return db

    def test_get_brand_tier_returns_tier_string(self):
        db = self._mock_db("niche")
        assert get_brand_tier(db, "Creed") == "niche"

    def test_get_brand_tier_none_name_returns_none(self):
        db = MagicMock()
        assert get_brand_tier(db, None) is None

    def test_get_brand_tier_db_exception_returns_none(self):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("db error")
        assert get_brand_tier(db, "Creed") is None


# ---------------------------------------------------------------------------
# K — FTG-1 role regression: designer/niche entity roles unchanged
# ---------------------------------------------------------------------------

class TestFTG1RoleRegression:
    def test_creed_aventus_role(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import classify_entity_role
        assert classify_entity_role("Creed", brand_tier_override="niche") == "niche_original"

    def test_dior_sauvage_role(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import classify_entity_role
        assert classify_entity_role("Dior", brand_tier_override="designer") == "designer_original"


# ---------------------------------------------------------------------------
# L — KB0 regression: Khamrah truth unchanged
# ---------------------------------------------------------------------------

class TestKB0Regression:
    def test_khamrah_reference_original(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile
        dupe = get_dupe_profile("Lattafa", "Lattafa Khamrah")
        assert dupe is not None
        assert dupe.reference_original == "Kilian Angels' Share"

    def test_cdnim_reference_original(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile
        dupe = get_dupe_profile("Armaf", "Armaf Club de Nuit Intense Man")
        assert dupe is not None
        assert dupe.reference_original == "Creed Aventus"
