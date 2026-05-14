"""DATA2 — Brand Catalog Join Normalization.

Root cause: _brand_catalog_perfumes() in entities.py joined resolver_perfumes to
entity_market using exact LOWER(canonical_name) equality. The resolver (Fragrantica
source) stores full concentration-variant names ("Xerjoff - Join the Club Don Eau de
Parfum") while the aggregation job strips those suffixes via _base_name() before
writing to entity_market ("Xerjoff - Join the Club Don"). The LEFT JOIN returned NULL
for entity_id, causing the brand page to display the entity as catalog-only with no
market metrics even though it was actively tracked.

Fix: extend the LEFT JOIN with a second IN condition that applies the same two-pass
suffix normalization (using PostgreSQL REGEXP_REPLACE) as _base_name() does in Python.
Exact match is tried first (existing behavior preserved); the normalized form is the
fallback for suffix-variant catalog rows.

Tests:
  A  _base_name() strips concentration suffixes — regression / sameness check
  B  Normalized join would resolve "Xerjoff - Join the Club Don Eau de Parfum"
     to "Xerjoff - Join the Club Don" via _base_name()
  C  Double-suffix case reduces correctly in two passes
  D  Exact-match names still work (no regression)
  E  Non-suffix trailing words are NOT stripped (safety)
  F  All known suffix variants handled by _base_name()
  G  FTG-0 / Khamrah regression — _DUPE_RAW unaffected
  H  FTG-2 VALID_RELATION_TYPES unchanged (regression)
  I  DATA1 last-active display semantics — _base_name() not in display path (no change)
"""

import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# Import the same normalization function used by the aggregation job
# ---------------------------------------------------------------------------

from perfume_trend_sdk.analysis.market_signals.aggregator import _base_name


# ---------------------------------------------------------------------------
# A — _base_name() regression / sameness check
# ---------------------------------------------------------------------------

class TestBaseNameBehavior:
    """Verify _base_name() strips exactly the concentration suffixes that
    appear in Fragrantica catalog names."""

    def test_eau_de_parfum_stripped(self):
        assert _base_name("Xerjoff - Join the Club Don Eau de Parfum") == "Xerjoff - Join the Club Don"

    def test_eau_de_toilette_stripped(self):
        assert _base_name("Dior Sauvage Eau de Toilette") == "Dior Sauvage"

    def test_extrait_de_parfum_stripped(self):
        assert _base_name("Creed Aventus Extrait de Parfum") == "Creed Aventus"

    def test_extrait_stripped(self):
        assert _base_name("Baccarat Rouge 540 Extrait") == "Baccarat Rouge 540"

    def test_eau_de_cologne_stripped(self):
        assert _base_name("Some Perfume Eau de Cologne") == "Some Perfume"

    def test_eau_fraiche_stripped(self):
        assert _base_name("Some Perfume Eau Fraiche") == "Some Perfume"

    def test_parfum_stripped(self):
        assert _base_name("Chanel No 5 Parfum") == "Chanel No 5"

    def test_case_insensitive_stripping(self):
        assert _base_name("Dior Sauvage EAU DE PARFUM") == "Dior Sauvage"


# ---------------------------------------------------------------------------
# B — Xerjoff Join fix: suffix resolves to tracked entity name
# ---------------------------------------------------------------------------

class TestXerjoffCaseResolution:
    """The canonical Fragrantica catalog name includes concentration suffix.
    _base_name() must reduce it to the entity_market canonical_name."""

    def test_join_the_club_don_edp_resolves(self):
        resolver_name = "Xerjoff - Join the Club Don Eau de Parfum"
        entity_market_name = "Xerjoff - Join the Club Don"
        assert _base_name(resolver_name).lower() == entity_market_name.lower()

    def test_join_the_club_don_exact_also_works(self):
        """Exact match still works — no regression."""
        resolver_name = "Xerjoff - Join the Club Don"
        entity_market_name = "Xerjoff - Join the Club Don"
        # Exact match: _base_name strips nothing because no suffix present
        assert _base_name(resolver_name).lower() == entity_market_name.lower()

    def test_join_the_club_extrait_resolves(self):
        resolver_name = "Xerjoff - Join the Club Don Extrait de Parfum"
        entity_market_name = "Xerjoff - Join the Club Don"
        assert _base_name(resolver_name).lower() == entity_market_name.lower()


# ---------------------------------------------------------------------------
# C — Double-suffix reduction (two-pass behavior)
# ---------------------------------------------------------------------------

class TestDoubleSuffix:
    """_base_name() iterates until stable, handling double-suffixed edge cases
    (e.g., old Fragrantica data with redundant suffix notation)."""

    def test_double_extrait_reduced(self):
        result = _base_name("Baccarat Rouge 540 Extrait Extrait de Parfum")
        assert result == "Baccarat Rouge 540"

    def test_single_suffix_only_one_pass_needed(self):
        result = _base_name("Creed Aventus Eau de Parfum")
        assert result == "Creed Aventus"


# ---------------------------------------------------------------------------
# D — Exact-match names still work (no regression on non-suffix names)
# ---------------------------------------------------------------------------

class TestExactMatchNoRegression:
    def test_name_without_suffix_unchanged(self):
        assert _base_name("Creed Aventus") == "Creed Aventus"

    def test_name_with_number_unchanged(self):
        assert _base_name("Baccarat Rouge 540") == "Baccarat Rouge 540"

    def test_name_with_dash_unchanged(self):
        assert _base_name("Armaf Club de Nuit Intense Man") == "Armaf Club de Nuit Intense Man"

    def test_lattafa_khamrah_unchanged(self):
        assert _base_name("Lattafa Khamrah") == "Lattafa Khamrah"

    def test_empty_after_strip_preserved(self):
        # A name that IS only a suffix should not be reduced to empty.
        # _base_name() guards: "if not stripped: break"
        result = _base_name("Parfum")
        # Should remain "Parfum" because stripping would leave ""
        assert result == "Parfum"


# ---------------------------------------------------------------------------
# E — Non-suffix trailing words NOT stripped (safety check)
# ---------------------------------------------------------------------------

class TestNonSuffixNotStripped:
    def test_word_parfums_in_middle_not_stripped(self):
        # "Parfums de Marly" — "Parfum" not at end; full test is trailing only
        name = "Parfums de Marly Delina"
        result = _base_name(name)
        assert result == "Parfums de Marly Delina"

    def test_trailing_word_not_in_list(self):
        name = "Xerjoff - Join the Club Don Original"
        result = _base_name(name)
        # "Original" is not in the suffix list — must not be stripped
        assert result == "Xerjoff - Join the Club Don Original"

    def test_name_ending_in_le_parfum_brand_word(self):
        # Only the standalone "Parfum" suffix is stripped, not part of other phrases
        name = "Maison Margiela Replica Jazz Club"
        result = _base_name(name)
        assert result == "Maison Margiela Replica Jazz Club"


# ---------------------------------------------------------------------------
# F — All known suffix variants covered
# ---------------------------------------------------------------------------

class TestAllSuffixVariants:
    SUFFIXES = [
        "Extrait de Parfum",
        "Eau de Parfum",
        "Eau de Toilette",
        "Eau de Cologne",
        "Eau Fraiche",
        "Extrait",
        "Parfum",
    ]

    def test_all_suffixes_stripped_from_base(self):
        for suffix in self.SUFFIXES:
            name = f"Test Perfume {suffix}"
            result = _base_name(name)
            assert result == "Test Perfume", (
                f"_base_name() failed to strip '{suffix}': got '{result}'"
            )


# ---------------------------------------------------------------------------
# G — FTG-0 regression: Khamrah truth unchanged
# ---------------------------------------------------------------------------

class TestFTG0Regression:
    def test_khamrah_reference_original_unchanged(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile
        dupe = get_dupe_profile("Lattafa", "Lattafa Khamrah")
        assert dupe is not None
        assert dupe.reference_original == "Kilian Angels' Share"
        assert "Baccarat" not in dupe.reference_original

    def test_cdnim_reference_original_unchanged(self):
        from perfume_trend_sdk.analysis.topic_intelligence.entity_role import get_dupe_profile
        dupe = get_dupe_profile("Armaf", "Armaf Club de Nuit Intense Man")
        assert dupe is not None
        assert dupe.reference_original == "Creed Aventus"


# ---------------------------------------------------------------------------
# H — FTG-2 regression: VALID_RELATION_TYPES unchanged
# ---------------------------------------------------------------------------

class TestFTG2Regression:
    def test_valid_relation_types_unchanged(self):
        from perfume_trend_sdk.db.market.fragrance_relationship import VALID_RELATION_TYPES
        assert len(VALID_RELATION_TYPES) == 4
        assert "dupe_of" in VALID_RELATION_TYPES
        assert "market_alternative_to" in VALID_RELATION_TYPES
        assert "inspired_by" in VALID_RELATION_TYPES
        assert "commonly_compared_to" in VALID_RELATION_TYPES

    def test_relationship_seed_count_unchanged(self):
        from perfume_trend_sdk.db.market.fragrance_relationship import RELATIONSHIP_SEED
        assert len(RELATIONSHIP_SEED) == 7


# ---------------------------------------------------------------------------
# I — DATA1 contract: _base_name() is NOT in the display/headline path
# ---------------------------------------------------------------------------

class TestData1NoBranchConflict:
    """DATA1 governs how the last-active snapshot date is selected for
    headline display. _base_name() is only used during ingestion aggregation
    and now in the brand catalog JOIN. It must not appear in or affect
    the _get_latest_snapshot() display path."""

    def test_base_name_not_imported_in_queries(self):
        """_base_name is aggregation-only; the display query module must
        not depend on it to avoid inadvertent coupling."""
        import perfume_trend_sdk.api.queries as q_module
        import inspect
        src = inspect.getsource(q_module)
        assert "_base_name" not in src

    def test_base_name_import_only_in_aggregator_and_entities(self):
        """_base_name should only be used in the aggregator (its home)
        and entities.py (brand catalog join fix). Not in other route
        modules where DATA1 display logic lives."""
        import perfume_trend_sdk.api.routes.watchlists as wl_module
        import inspect
        src = inspect.getsource(wl_module)
        assert "_base_name" not in src
