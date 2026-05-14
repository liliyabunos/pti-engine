"""FTG-1/KB1-MIN — Brand Profiles canonical classification tests.

Tests cover:
  - brand_tier_override parameter in classify_entity_role
  - DB-backed tier takes precedence over frozensets when provided
  - Frozenset fallback when brand_tier_override is None (backward-compatible)
  - Tier-to-role mapping: designer → designer_original, niche → niche_original,
    indie → niche_original, clone_house → unknown, celebrity → unknown
  - Dupe map still takes precedence over brand_tier_override (step 1 always runs first)
  - Khamrah regression unaffected (KB0 still correct)
  - get_brand_tier handles None / empty safely (unit, no real DB)
  - No regressions on existing covered examples
"""

import pytest
from unittest.mock import MagicMock, patch

from perfume_trend_sdk.analysis.topic_intelligence.entity_role import (
    classify_entity_role,
    get_dupe_profile,
)


# ---------------------------------------------------------------------------
# brand_tier_override → role mapping
# ---------------------------------------------------------------------------

class TestBrandTierOverride:
    """Tests that brand_tier_override drives entity role when provided."""

    def test_designer_tier_returns_designer_original(self):
        assert classify_entity_role("SomeBrand", brand_tier_override="designer") == "designer_original"

    def test_niche_tier_returns_niche_original(self):
        assert classify_entity_role("SomeBrand", brand_tier_override="niche") == "niche_original"

    def test_indie_tier_returns_niche_original(self):
        # indie houses are niche-tier for entity role purposes
        assert classify_entity_role("SomeBrand", brand_tier_override="indie") == "niche_original"

    def test_clone_house_tier_returns_unknown(self):
        # no entity role for clone_house yet — dupe map handles per-product
        assert classify_entity_role("Armaf", brand_tier_override="clone_house") == "unknown"

    def test_celebrity_tier_returns_unknown(self):
        assert classify_entity_role("Ariana Grande", brand_tier_override="celebrity") == "unknown"

    def test_override_supersedes_frozenset_for_designer(self):
        """Brand in designer frozenset gets designer_original via override too — consistent."""
        assert classify_entity_role("Dior", brand_tier_override="designer") == "designer_original"

    def test_override_supersedes_frozenset_for_niche(self):
        assert classify_entity_role("Creed", brand_tier_override="niche") == "niche_original"

    def test_unknown_brand_with_designer_override_returns_designer_original(self):
        """Brand NOT in any frozenset gets classified via DB override."""
        assert classify_entity_role("Totally Unknown House XYZ", brand_tier_override="designer") == "designer_original"

    def test_unknown_brand_with_niche_override_returns_niche_original(self):
        assert classify_entity_role("Totally Unknown House XYZ", brand_tier_override="niche") == "niche_original"

    def test_none_override_falls_back_to_frozenset_designer(self):
        """None override → frozenset path → designer_original for known designer."""
        assert classify_entity_role("Dior", brand_tier_override=None) == "designer_original"

    def test_none_override_falls_back_to_frozenset_niche(self):
        """None override → frozenset path → niche_original for known niche."""
        assert classify_entity_role("Creed", brand_tier_override=None) == "niche_original"

    def test_none_override_unknown_brand_returns_unknown(self):
        """None override + brand not in frozensets → unknown."""
        assert classify_entity_role("Totally Unknown House XYZ", brand_tier_override=None) == "unknown"


# ---------------------------------------------------------------------------
# Dupe map takes precedence over brand_tier_override (step 1 always first)
# ---------------------------------------------------------------------------

class TestDupeMapBeforeTierOverride:
    """Dupe map check must fire before brand_tier_override is consulted."""

    def test_cdnim_dupe_wins_over_designer_override(self):
        """Armaf CDNIM is dupe_alternative regardless of brand_tier_override."""
        role = classify_entity_role(
            "Armaf",
            perfume_name="Armaf Club de Nuit Intense Man",
            brand_tier_override="designer",  # hypothetical wrong override
        )
        assert role == "dupe_alternative"

    def test_cdnim_dupe_wins_over_clone_house_override(self):
        role = classify_entity_role(
            "Armaf",
            perfume_name="Armaf Club de Nuit Intense Man",
            brand_tier_override="clone_house",
        )
        assert role == "dupe_alternative"

    def test_montblanc_explorer_dupe_wins_over_designer_override(self):
        role = classify_entity_role(
            "Montblanc",
            perfume_name="Montblanc Explorer",
            brand_tier_override="designer",
        )
        assert role == "designer_alternative"

    def test_ariana_cloud_dupe_wins_over_celebrity_override(self):
        role = classify_entity_role(
            "Ariana Grande",
            perfume_name="Ariana Grande Cloud",
            brand_tier_override="celebrity",
        )
        assert role == "celebrity_alternative"


# ---------------------------------------------------------------------------
# KB0 Khamrah regression (unchanged by FTG-1)
# ---------------------------------------------------------------------------

class TestKhamrahRegressionFTG1:
    """Ensure KB0 Khamrah fix is not broken by FTG-1 changes."""

    def test_khamrah_is_not_br540_with_no_override(self):
        dupe = get_dupe_profile("Lattafa", "Lattafa Khamrah")
        assert dupe is not None
        assert dupe.reference_original != "Maison Francis Kurkdjian Baccarat Rouge 540"

    def test_khamrah_is_angels_share_with_no_override(self):
        role = classify_entity_role("Lattafa", "Lattafa Khamrah")
        assert role == "dupe_alternative"
        dupe = get_dupe_profile("Lattafa", "Lattafa Khamrah")
        assert dupe.reference_original == "Kilian Angels' Share"

    def test_khamrah_with_clone_house_override_still_dupe_alternative(self):
        """Even if DB returns clone_house for Lattafa, dupe map fires first."""
        role = classify_entity_role(
            "Lattafa",
            perfume_name="Lattafa Khamrah",
            brand_tier_override="clone_house",
        )
        assert role == "dupe_alternative"


# ---------------------------------------------------------------------------
# Backward compatibility — existing frozenset behavior preserved
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing classify_entity_role call signature (no override) must work unchanged."""

    def test_dior_no_override_arg(self):
        assert classify_entity_role("Dior") == "designer_original"

    def test_creed_no_override_arg(self):
        assert classify_entity_role("Creed") == "niche_original"

    def test_byredo_no_override_arg(self):
        assert classify_entity_role("Byredo") == "niche_original"

    def test_armaf_no_override_arg(self):
        # Armaf not in any frozenset (removed at Phase 5) → unknown
        assert classify_entity_role("Armaf") == "unknown"

    def test_unknown_brand_no_override_arg(self):
        assert classify_entity_role("Totally Unknown XYZ") == "unknown"

    def test_none_brand_no_override_arg(self):
        assert classify_entity_role(None) == "unknown"


# ---------------------------------------------------------------------------
# get_brand_tier safe-call tests (unit, no real DB)
# ---------------------------------------------------------------------------

class TestGetBrandTierSafety:
    """get_brand_tier should be safe to call with None/empty/exception."""

    def test_none_brand_name_returns_none(self):
        from perfume_trend_sdk.db.market.brand_profile import get_brand_tier
        mock_db = MagicMock()
        assert get_brand_tier(mock_db, None) is None

    def test_empty_brand_name_returns_none(self):
        from perfume_trend_sdk.db.market.brand_profile import get_brand_tier
        mock_db = MagicMock()
        assert get_brand_tier(mock_db, "") is None

    def test_db_exception_returns_none(self):
        """If DB raises, get_brand_tier returns None (non-fatal fallback)."""
        from perfume_trend_sdk.db.market.brand_profile import get_brand_tier
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB connection error")
        result = get_brand_tier(mock_db, "Creed")
        assert result is None

    def test_db_miss_returns_none(self):
        """Brand not in DB → None."""
        from perfume_trend_sdk.db.market.brand_profile import get_brand_tier
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        result = get_brand_tier(mock_db, "Unknown Brand")
        assert result is None

    def test_db_hit_returns_tier(self):
        """Brand in DB → tier string."""
        from perfume_trend_sdk.db.market.brand_profile import get_brand_tier
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = ("niche",)
        result = get_brand_tier(mock_db, "Creed")
        assert result == "niche"

    def test_db_hit_designer_returns_designer(self):
        from perfume_trend_sdk.db.market.brand_profile import get_brand_tier
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = ("designer",)
        result = get_brand_tier(mock_db, "Dior")
        assert result == "designer"
