"""Tests for KB-CAT1-D — Perfume Hierarchy Display + Compact Market Row Context.

Tests:
- fetch_brand_hierarchy_map: returns only non-root brands, handles empty/exception
- format_brand_hierarchy_label: compact label, root brand, missing, various prefixes
- brand_hierarchy_label on TopMoverRow / EntitySummary schemas (field presence)
- BrandDisplayContext Pydantic model (field validation)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from perfume_trend_sdk.db.market.brand_profile import (
    fetch_brand_hierarchy_map,
    format_brand_hierarchy_label,
)
from perfume_trend_sdk.api.schemas.dashboard import TopMoverRow
from perfume_trend_sdk.api.schemas.entity import EntitySummary


# ---------------------------------------------------------------------------
# fetch_brand_hierarchy_map
# ---------------------------------------------------------------------------

class TestFetchBrandHierarchyMap:
    def _make_db(self, rows):
        db = MagicMock()
        result = MagicMock()
        result.fetchall.return_value = rows
        db.execute.return_value = result
        return db

    def test_returns_non_root_brands_only(self):
        rows = [
            ("xerjoff - join the club", "collection", "xerjoff"),
            ("xerjoff - casamorati", "sub_brand", "xerjoff"),
        ]
        db = self._make_db(rows)
        result = fetch_brand_hierarchy_map(db)
        assert len(result) == 2
        assert result["xerjoff - join the club"]["node_type"] == "collection"
        assert result["xerjoff - join the club"]["parent_normalized"] == "xerjoff"
        assert result["xerjoff - casamorati"]["node_type"] == "sub_brand"

    def test_excludes_rows_with_no_parent(self):
        """Rows without parent_brand_normalized should be filtered out."""
        rows = [
            ("xerjoff - join the club", "collection", "xerjoff"),
            ("orphan - node", "collection", None),  # no parent → skip
        ]
        db = self._make_db(rows)
        result = fetch_brand_hierarchy_map(db)
        assert "xerjoff - join the club" in result
        assert "orphan - node" not in result

    def test_returns_empty_on_exception(self):
        db = MagicMock()
        db.execute.side_effect = Exception("DB error")
        result = fetch_brand_hierarchy_map(db)
        assert result == {}

    def test_returns_empty_when_no_hierarchy_rows(self):
        db = self._make_db([])
        result = fetch_brand_hierarchy_map(db)
        assert result == {}

    def test_all_four_seeded_hierarchy_brands(self):
        """Reflects the 4 production seed rows from KB-CAT1-B."""
        rows = [
            ("xerjoff - join the club", "collection", "xerjoff"),
            ("xerjoff - casamorati", "sub_brand", "xerjoff"),
            ("xerjoff - xj oud attars", "collection", "xerjoff"),
            ("filippo sorcinelli - sauf", "collection", "filippo sorcinelli"),
        ]
        db = self._make_db(rows)
        result = fetch_brand_hierarchy_map(db)
        assert len(result) == 4
        assert result["filippo sorcinelli - sauf"]["parent_normalized"] == "filippo sorcinelli"


# ---------------------------------------------------------------------------
# format_brand_hierarchy_label
# ---------------------------------------------------------------------------

class TestFormatBrandHierarchyLabel:
    """hierarchy_map key = normalized brand name (lowercase, stripped)."""

    HIERARCHY_MAP = {
        "xerjoff - join the club": {"node_type": "collection", "parent_normalized": "xerjoff"},
        "xerjoff - casamorati": {"node_type": "sub_brand", "parent_normalized": "xerjoff"},
        "xerjoff - xj oud attars": {"node_type": "collection", "parent_normalized": "xerjoff"},
        "filippo sorcinelli - sauf": {"node_type": "collection", "parent_normalized": "filippo sorcinelli"},
    }

    def test_join_the_club_label(self):
        label = format_brand_hierarchy_label("Xerjoff - Join the Club", self.HIERARCHY_MAP)
        assert label == "Xerjoff · Join the Club"

    def test_casamorati_label(self):
        label = format_brand_hierarchy_label("Xerjoff - Casamorati", self.HIERARCHY_MAP)
        assert label == "Xerjoff · Casamorati"

    def test_xj_oud_attars_label(self):
        label = format_brand_hierarchy_label("Xerjoff - XJ Oud Attars", self.HIERARCHY_MAP)
        assert label == "Xerjoff · XJ Oud Attars"

    def test_filippo_sorcinelli_sauf_label(self):
        label = format_brand_hierarchy_label("Filippo Sorcinelli - SAUF", self.HIERARCHY_MAP)
        assert label == "Filippo Sorcinelli · SAUF"

    def test_root_brand_returns_none(self):
        """Brands not in hierarchy_map get None."""
        label = format_brand_hierarchy_label("Creed", self.HIERARCHY_MAP)
        assert label is None

    def test_none_brand_name_returns_none(self):
        label = format_brand_hierarchy_label(None, self.HIERARCHY_MAP)
        assert label is None

    def test_empty_brand_name_returns_none(self):
        label = format_brand_hierarchy_label("", self.HIERARCHY_MAP)
        assert label is None

    def test_empty_hierarchy_map_returns_none(self):
        label = format_brand_hierarchy_label("Xerjoff - Join the Club", {})
        assert label is None

    def test_brand_name_not_in_map_returns_none(self):
        label = format_brand_hierarchy_label("Unknown Brand - Sub", self.HIERARCHY_MAP)
        assert label is None

    def test_node_name_without_parent_prefix(self):
        """If brand_name doesn't start with parent prefix, use brand_name as node_short."""
        custom_map = {
            "strange - node": {"node_type": "collection", "parent_normalized": "different parent"},
        }
        label = format_brand_hierarchy_label("Strange - Node", custom_map)
        # parent_display = "Different Parent", prefix = "Different Parent - "
        # brand_name "Strange - Node" does not start with that prefix → use brand_name as node_short
        assert label == "Different Parent · Strange - Node"

    def test_case_insensitive_prefix_match(self):
        """Case-insensitive prefix stripping (brand_name mixed case)."""
        custom_map = {
            "xerjoff - join the club": {"node_type": "collection", "parent_normalized": "xerjoff"},
        }
        # brand_name with different case for parent prefix
        label = format_brand_hierarchy_label("XERJOFF - Join the Club", custom_map)
        assert label == "Xerjoff · Join the Club"


# ---------------------------------------------------------------------------
# Schema field presence — TopMoverRow and EntitySummary
# ---------------------------------------------------------------------------

class TestSchemaFieldPresence:
    def test_top_mover_row_has_brand_hierarchy_label(self):
        row = TopMoverRow(
            rank=1,
            entity_id="test-id",
            entity_type="perfume",
            ticker="TEST",
            canonical_name="Test Perfume",
            name="Test Perfume",
            brand_name="Xerjoff - Join the Club",
            composite_market_score=50.0,
            effective_rank_score=50.0,
            mention_count=10.0,
            brand_hierarchy_label="Xerjoff · Join the Club",
        )
        assert row.brand_hierarchy_label == "Xerjoff · Join the Club"

    def test_top_mover_row_brand_hierarchy_label_defaults_none(self):
        row = TopMoverRow(
            rank=1,
            entity_id="test-id",
            entity_type="perfume",
            ticker="TEST",
            canonical_name="Test Perfume",
            name="Test Perfume",
            brand_name="Creed",
            composite_market_score=50.0,
            effective_rank_score=50.0,
            mention_count=10.0,
        )
        assert row.brand_hierarchy_label is None

    def test_entity_summary_has_brand_hierarchy_label(self):
        summary = EntitySummary(
            entity_id="test-id",
            entity_type="perfume",
            ticker="TEST",
            canonical_name="Test Perfume",
            brand_name="Xerjoff - Join the Club",
            brand_hierarchy_label="Xerjoff · Join the Club",
        )
        assert summary.brand_hierarchy_label == "Xerjoff · Join the Club"

    def test_entity_summary_brand_hierarchy_label_defaults_none(self):
        summary = EntitySummary(
            entity_id="test-id",
            entity_type="perfume",
            ticker="TEST",
            canonical_name="Test Perfume",
            brand_name="Creed",
        )
        assert summary.brand_hierarchy_label is None

    def test_root_brand_entity_summary_no_hierarchy_label(self):
        """Brand entity type should also accept null hierarchy label."""
        summary = EntitySummary(
            entity_id="brand-creed",
            entity_type="brand",
            ticker="CREED",
            canonical_name="Creed",
            brand_name=None,
        )
        assert summary.brand_hierarchy_label is None
