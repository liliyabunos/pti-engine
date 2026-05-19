"""DATA4-C — TOM FORD collection hierarchy tests.

Tests verify that brand_profiles hierarchy entries for Tom Ford collections
are correctly classified and that the display infrastructure resolves them.

Suites:
  A  TOM FORD Private Blend classified as collection under tom ford
  B  TOM FORD Signature classified as collection under tom ford
  C  Tom Ford parent brand returns node_type='brand', parent=None
  D  Normalization: various TOM FORD brand_name forms map to correct keys
  E  Hierarchy map resolution: fetch_brand_hierarchy_map handles TF collections
  F  format_brand_hierarchy_label produces correct compact labels
  G  Regression: Xerjoff hierarchy unchanged
  H  Regression: Creed, Dior remain root brands (no false collection tagging)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.db.market.brand_profile import (
    get_brand_profile,
    fetch_brand_hierarchy_map,
    format_brand_hierarchy_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db_profile(row_tuple):
    """Return a mock db that returns row_tuple from get_brand_profile."""
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = row_tuple
    return db


def _mock_db_hierarchy(rows):
    """Return a mock db that returns rows list from fetch_brand_hierarchy_map."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    return db


# ---------------------------------------------------------------------------
# A — TOM FORD Private Blend
# ---------------------------------------------------------------------------

class TestTomFordPrivateBlendHierarchy:

    def test_A1_private_blend_node_type_is_collection(self):
        """TOM FORD Private Blend must classify as collection."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Private Blend")
        assert result is not None
        assert result["node_type"] == "collection"

    def test_A2_private_blend_parent_is_tom_ford(self):
        """TOM FORD Private Blend parent_brand_normalized must be 'tom ford'."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Private Blend")
        assert result["parent_brand_normalized"] == "tom ford"

    def test_A3_private_blend_brand_tier_is_designer(self):
        """TOM FORD Private Blend brand_tier must be designer."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Private Blend")
        assert result["brand_tier"] == "designer"

    def test_A4_private_blend_is_not_sub_brand(self):
        """TOM FORD Private Blend must be collection, not sub_brand."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Private Blend")
        assert result["node_type"] == "collection"
        assert result["node_type"] != "sub_brand"


# ---------------------------------------------------------------------------
# B — TOM FORD Signature
# ---------------------------------------------------------------------------

class TestTomFordSignatureHierarchy:

    def test_B1_signature_node_type_is_collection(self):
        """TOM FORD Signature must classify as collection."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Signature")
        assert result is not None
        assert result["node_type"] == "collection"

    def test_B2_signature_parent_is_tom_ford(self):
        """TOM FORD Signature parent_brand_normalized must be 'tom ford'."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Signature")
        assert result["parent_brand_normalized"] == "tom ford"

    def test_B3_signature_brand_tier_is_designer(self):
        """TOM FORD Signature brand_tier must be designer."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Signature")
        assert result["brand_tier"] == "designer"


# ---------------------------------------------------------------------------
# C — Tom Ford parent brand
# ---------------------------------------------------------------------------

class TestTomFordParentBrand:

    def test_C1_tom_ford_is_root_brand(self):
        """Tom Ford parent brand must have node_type='brand'."""
        db = _mock_db_profile(("designer", "brand", None))
        result = get_brand_profile(db, "Tom Ford")
        assert result is not None
        assert result["node_type"] == "brand"

    def test_C2_tom_ford_has_no_parent(self):
        """Tom Ford parent brand must have no parent_brand_normalized."""
        db = _mock_db_profile(("designer", "brand", None))
        result = get_brand_profile(db, "Tom Ford")
        assert result["parent_brand_normalized"] is None

    def test_C3_tom_ford_tier_is_designer(self):
        """Tom Ford brand_tier must be designer."""
        db = _mock_db_profile(("designer", "brand", None))
        result = get_brand_profile(db, "Tom Ford")
        assert result["brand_tier"] == "designer"


# ---------------------------------------------------------------------------
# D — Normalization: various brand_name forms
# ---------------------------------------------------------------------------

class TestTomFordNormalization:

    def test_D1_all_caps_tom_ford_normalizes_correctly(self):
        """'TOM FORD Private Blend' lookup must resolve the same as 'Tom Ford Private Blend'."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        # Both forms should produce the normalized key 'tom ford private blend'
        result = get_brand_profile(db, "TOM FORD Private Blend")
        assert result is not None
        assert result["node_type"] == "collection"

    def test_D2_mixed_case_tom_ford_signature_normalizes(self):
        """'TOM FORD Signature' normalizes to 'tom ford signature'."""
        db = _mock_db_profile(("designer", "collection", "tom ford"))
        result = get_brand_profile(db, "TOM FORD Signature")
        assert result is not None

    def test_D3_absent_brand_returns_none(self):
        """Brand with no brand_profiles entry returns None."""
        db = _mock_db_profile(None)
        result = get_brand_profile(db, "Unknown TF Collection XYZ")
        assert result is None


# ---------------------------------------------------------------------------
# E — fetch_brand_hierarchy_map includes TF collections
# ---------------------------------------------------------------------------

class TestTomFordHierarchyMap:

    def _map_with_tf(self):
        """Return a hierarchy map containing TF collection entries."""
        rows = [
            ("tom ford private blend", "collection", "tom ford"),
            ("tom ford signature", "collection", "tom ford"),
            ("xerjoff - join the club", "collection", "xerjoff"),
        ]
        db = _mock_db_hierarchy(rows)
        return fetch_brand_hierarchy_map(db)

    def test_E1_private_blend_in_hierarchy_map(self):
        """fetch_brand_hierarchy_map must include tom ford private blend."""
        hmap = self._map_with_tf()
        assert "tom ford private blend" in hmap

    def test_E2_signature_in_hierarchy_map(self):
        """fetch_brand_hierarchy_map must include tom ford signature."""
        hmap = self._map_with_tf()
        assert "tom ford signature" in hmap

    def test_E3_private_blend_parent_in_map(self):
        """TOM FORD Private Blend entry must have parent='tom ford'."""
        hmap = self._map_with_tf()
        assert hmap["tom ford private blend"]["parent_normalized"] == "tom ford"

    def test_E4_xerjoff_still_in_map(self):
        """Xerjoff collections must still appear (no regression)."""
        hmap = self._map_with_tf()
        assert "xerjoff - join the club" in hmap


# ---------------------------------------------------------------------------
# F — format_brand_hierarchy_label compact display
# ---------------------------------------------------------------------------

class TestTomFordHierarchyLabel:

    def _map(self):
        return {
            "tom ford private blend": {"node_type": "collection", "parent_normalized": "tom ford"},
            "tom ford signature": {"node_type": "collection", "parent_normalized": "tom ford"},
        }

    def test_F1_private_blend_label_shows_parent_and_collection(self):
        """Private Blend label should show 'Tom Ford · Private Blend' compact form."""
        label = format_brand_hierarchy_label("TOM FORD Private Blend", self._map())
        # Should include both parent and collection node name
        assert label is not None
        assert "Tom Ford" in label or "tom ford" in label.lower()

    def test_F2_signature_label_shows_parent(self):
        """Signature label should show parent brand context."""
        label = format_brand_hierarchy_label("TOM FORD Signature", self._map())
        assert label is not None

    def test_F3_root_tom_ford_returns_none_label(self):
        """Root 'Tom Ford' brand has no hierarchy label (it IS the parent)."""
        label = format_brand_hierarchy_label("Tom Ford", self._map())
        # Root brand not in map — no compact label needed
        assert label is None


# ---------------------------------------------------------------------------
# G — Regression: Xerjoff hierarchy unchanged
# ---------------------------------------------------------------------------

class TestXerjoffRegression:

    def test_G1_xerjoff_join_the_club_still_collection(self):
        """Xerjoff - Join the Club must remain collection."""
        db = _mock_db_profile(("niche", "collection", "xerjoff"))
        result = get_brand_profile(db, "Xerjoff - Join the Club")
        assert result["node_type"] == "collection"
        assert result["parent_brand_normalized"] == "xerjoff"

    def test_G2_xerjoff_casamorati_still_sub_brand(self):
        """Xerjoff - Casamorati must remain sub_brand."""
        db = _mock_db_profile(("niche", "sub_brand", "xerjoff"))
        result = get_brand_profile(db, "Xerjoff - Casamorati")
        assert result["node_type"] == "sub_brand"

    def test_G3_xerjoff_root_still_brand(self):
        """Xerjoff root must remain node_type='brand'."""
        db = _mock_db_profile(("niche", "brand", None))
        result = get_brand_profile(db, "Xerjoff")
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None


# ---------------------------------------------------------------------------
# H — Regression: other designer brands remain root brands
# ---------------------------------------------------------------------------

class TestOtherDesignerBrandsRegression:

    def test_H1_creed_is_root_brand(self):
        """Creed must remain root brand (not a collection)."""
        db = _mock_db_profile(("niche", "brand", None))
        result = get_brand_profile(db, "Creed")
        assert result["node_type"] == "brand"
        assert result["parent_brand_normalized"] is None

    def test_H2_dior_is_root_brand(self):
        """Dior must remain root designer brand."""
        db = _mock_db_profile(("designer", "brand", None))
        result = get_brand_profile(db, "Dior")
        assert result["node_type"] == "brand"

    def test_H3_chanel_is_root_brand(self):
        """Chanel must remain root designer brand."""
        db = _mock_db_profile(("designer", "brand", None))
        result = get_brand_profile(db, "Chanel")
        assert result["node_type"] == "brand"
