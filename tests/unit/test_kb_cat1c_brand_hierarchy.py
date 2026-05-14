"""KB-CAT1-C — brand hierarchy display unit tests.

Tests cover:
  A  _get_child_brands() returns collections and sub_brands for a parent brand
  B  _get_child_brands() returns empty lists for non-parent / leaf brands
  C  _get_child_brands() returns empty lists on DB exception (non-fatal)
  D  _get_child_brands() correctly routes node_type='sub_brand' vs 'collection'
  E  _get_parent_entity_id() returns entity_id when parent is in entity_market
  F  _get_parent_entity_id() returns None when parent is absent from entity_market
  G  _get_parent_entity_id() returns None when parent_brand_normalized is None
  H  _get_parent_entity_id() returns None on DB exception (non-fatal)
  I  BrandEntityDetail includes new fields with correct defaults
  J  child nodes use entity_market canonical_name as display name when tracked
  K  child nodes use resolver_brands name when untracked (catalog_only)
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.api.routes.entities import (
    _get_child_brands,
    _get_parent_entity_id,
    ChildBrandNode,
    BrandEntityDetail,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_with_rows(rows):
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    return db


def _make_db_with_one_row(row):
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = row
    return db


# ---------------------------------------------------------------------------
# A — _get_child_brands returns collections and sub_brands
# ---------------------------------------------------------------------------

class TestGetChildBrands:
    def test_returns_collections_and_sub_brands_for_xerjoff(self):
        rows = [
            ("xerjoff - casamorati", "sub_brand", "brand-xerjoff---casamorati", "Xerjoff - Casamorati"),
            ("xerjoff - join the club", "collection", "brand-xerjoff---join-the-club", "Xerjoff - Join the Club"),
            ("xerjoff - xj oud attars", "collection", None, "Xerjoff - XJ Oud Attars"),
        ]
        db = _make_db_with_rows(rows)
        # _normalize is imported locally inside _get_child_brands, no mock needed
        collections, sub_brands = _get_child_brands(db, "Xerjoff")

        assert len(collections) == 2
        assert len(sub_brands) == 1
        assert sub_brands[0].node_type == "sub_brand"
        assert sub_brands[0].canonical_name == "Xerjoff - Casamorati"
        assert sub_brands[0].entity_id == "brand-xerjoff---casamorati"
        assert sub_brands[0].state == "tracked"

    def test_untracked_child_has_catalog_only_state(self):
        rows = [
            ("xerjoff - xj oud attars", "collection", None, "Xerjoff - XJ Oud Attars"),
        ]
        db = _make_db_with_rows(rows)
        collections, sub_brands = _get_child_brands(db, "Xerjoff")
        assert len(collections) == 1
        assert collections[0].state == "catalog_only"
        assert collections[0].entity_id is None

    def test_tracked_child_has_tracked_state(self):
        rows = [
            ("xerjoff - join the club", "collection", "brand-xerjoff---join-the-club", "Xerjoff - Join the Club"),
        ]
        db = _make_db_with_rows(rows)
        collections, _ = _get_child_brands(db, "Xerjoff")
        assert collections[0].state == "tracked"
        assert collections[0].entity_id == "brand-xerjoff---join-the-club"

    # B — non-parent brand returns empty lists
    def test_non_parent_brand_returns_empty(self):
        db = _make_db_with_rows([])
        collections, sub_brands = _get_child_brands(db, "Creed")
        assert collections == []
        assert sub_brands == []

    # C — DB exception is non-fatal
    def test_db_exception_returns_empty(self):
        db = MagicMock()
        db.execute.side_effect = Exception("DB error")
        collections, sub_brands = _get_child_brands(db, "Xerjoff")
        assert collections == []
        assert sub_brands == []

    # D — routing by node_type
    def test_collection_routed_to_collections_list(self):
        rows = [("x - a", "collection", None, "X - A")]
        db = _make_db_with_rows(rows)
        collections, sub_brands = _get_child_brands(db, "X")
        assert len(collections) == 1
        assert sub_brands == []

    def test_sub_brand_routed_to_sub_brands_list(self):
        rows = [("x - b", "sub_brand", None, "X - B")]
        db = _make_db_with_rows(rows)
        collections, sub_brands = _get_child_brands(db, "X")
        assert collections == []
        assert len(sub_brands) == 1

    # J — display name from entity_market when tracked
    def test_uses_entity_market_canonical_name_when_tracked(self):
        rows = [("xerjoff - join the club", "collection", "brand-xerjoff---join-the-club", "Xerjoff - Join the Club")]
        db = _make_db_with_rows(rows)
        collections, _ = _get_child_brands(db, "Xerjoff")
        assert collections[0].canonical_name == "Xerjoff - Join the Club"

    # K — display name from resolver_brands when untracked
    def test_uses_resolver_canonical_name_when_untracked(self):
        rows = [("xerjoff - xj oud attars", "collection", None, "Xerjoff - XJ Oud Attars")]
        db = _make_db_with_rows(rows)
        collections, _ = _get_child_brands(db, "Xerjoff")
        assert collections[0].canonical_name == "Xerjoff - XJ Oud Attars"


# ---------------------------------------------------------------------------
# E–H — _get_parent_entity_id
# ---------------------------------------------------------------------------

class TestGetParentEntityId:
    # E — returns entity_id when parent is tracked
    def test_returns_entity_id_when_parent_tracked(self):
        db = _make_db_with_one_row(("brand-xerjoff",))
        result = _get_parent_entity_id(db, "xerjoff")
        assert result == "brand-xerjoff"

    # F — returns None when parent absent
    def test_returns_none_when_parent_absent(self):
        db = _make_db_with_one_row(None)
        result = _get_parent_entity_id(db, "unknown brand xyz")
        assert result is None

    # G — returns None when parent_brand_normalized is None
    def test_returns_none_when_normalized_is_none(self):
        db = MagicMock()
        result = _get_parent_entity_id(db, None)
        assert result is None
        db.execute.assert_not_called()

    # H — DB exception is non-fatal
    def test_db_exception_returns_none(self):
        db = MagicMock()
        db.execute.side_effect = Exception("DB error")
        result = _get_parent_entity_id(db, "xerjoff")
        assert result is None


# ---------------------------------------------------------------------------
# I — BrandEntityDetail default values for new KB-CAT1-C fields
# ---------------------------------------------------------------------------

class TestBrandEntityDetailDefaults:
    def test_new_fields_default_to_empty(self):
        detail = BrandEntityDetail(
            id="brand-test",
            canonical_name="Test Brand",
            state="tracked",
        )
        assert detail.parent_entity_id is None
        assert detail.child_collections == []
        assert detail.child_sub_brands == []

    def test_child_brand_node_model(self):
        node = ChildBrandNode(
            canonical_name="Xerjoff - Join the Club",
            node_type="collection",
            entity_id="brand-xerjoff---join-the-club",
            state="tracked",
        )
        assert node.canonical_name == "Xerjoff - Join the Club"
        assert node.node_type == "collection"
        assert node.entity_id == "brand-xerjoff---join-the-club"
        assert node.state == "tracked"

    def test_child_brand_node_defaults(self):
        node = ChildBrandNode(
            canonical_name="Xerjoff - XJ Oud Attars",
            node_type="collection",
        )
        assert node.entity_id is None
        assert node.state == "catalog_only"

    def test_brand_entity_detail_accepts_child_nodes(self):
        detail = BrandEntityDetail(
            id="brand-xerjoff",
            canonical_name="Xerjoff",
            state="tracked",
            node_type="brand",
            parent_entity_id=None,
            child_collections=[
                ChildBrandNode(
                    canonical_name="Xerjoff - Join the Club",
                    node_type="collection",
                    entity_id="brand-xerjoff---join-the-club",
                    state="tracked",
                ),
            ],
            child_sub_brands=[
                ChildBrandNode(
                    canonical_name="Xerjoff - Casamorati",
                    node_type="sub_brand",
                    entity_id="brand-xerjoff---casamorati",
                    state="tracked",
                ),
            ],
        )
        assert len(detail.child_collections) == 1
        assert len(detail.child_sub_brands) == 1
        assert detail.child_collections[0].node_type == "collection"
        assert detail.child_sub_brands[0].node_type == "sub_brand"
