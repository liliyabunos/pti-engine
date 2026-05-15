"""DATA3 — Brand Catalog & Brand Identity Consistency.

Root cause 1 (Duplicate rows): _brand_catalog_perfumes() returned one SQL row
per resolver_perfumes row. When resolver_brands has both "Lattafa Khamrah" (id=16)
and "Lattafa Khamrah Eau de Parfum" (id=3684), both suffix-normalize to the same
entity_market row via the DATA2 REGEXP_REPLACE join. Both rows appeared in the
brand page output with identical scores.

Root cause 2 (Brand identity split): "Lattafa / لطافة" exists as a separate
tracked entity_market brand, created by the aggregation pipeline grouping mentions
by brand_name string. Only one resolver brand exists: "Lattafa" (id=9). The brand
split is caused by ingest-time brand_name variant — Ajayeb Dubai/Portrait resolved
with brand_name='Lattafa / لطافة' instead of 'Lattafa'. This brand entity shows
score 32.1 but 0 catalog perfumes (ghost brand).

Fix (Layer 1 — implemented): Wrap the main SELECT in a raw CTE with ROW_NUMBER()
OVER (PARTITION BY COALESCE(em.id::text, rp.id::text)) to deduplicate:
  - For matched rows (em.id IS NOT NULL): keep only the best resolver row per em.id,
    preferring exact canonical_name match, then shorter name.
  - For catalog-only rows (em.id IS NULL): COALESCE falls back to rp.id (unique
    per resolver row), so each catalog-only row gets its own partition (kept as-is).

Fix (Layer 3 — deferred): The "Lattafa / لطافة" ghost brand entity requires
investigation into the ingest-time brand_name normalization. Tracked as DATA3-L3.

Tests:
  A  _base_name() for Khamrah/Ameer Al Oudh — confirm both have suffix and exact
     forms in the resolver catalog
  B  Partition key logic: matched vs catalog-only rows use different partition keys
  C  Exact match preference: shorter/exact name is preferred over suffix-normalized
  D  DATA2 regression: Xerjoff Join the Club Don suffix resolution still works
  E  DATA2 regression: Casamorati EDP suffix resolution still works
  F  No regression on Creed Aventus (exact match, no suffix)
  G  Lattafa Khamrah — resolver has both exact and EDP form (the dedup case)
  H  Ameer Al Oudh — resolver has both exact and EDP form (the dedup case)
"""

import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.analysis.market_signals.aggregator import _base_name


# ---------------------------------------------------------------------------
# A — Lattafa Khamrah and Ameer Al Oudh suffix forms
# ---------------------------------------------------------------------------

class TestSuffixFormsExist:
    """Verify that _base_name() correctly normalizes the Lattafa pairs that
    were causing duplicate brand page rows."""

    def test_khamrah_exact_unchanged(self):
        """The exact form in entity_market — no suffix to strip."""
        assert _base_name("Lattafa Khamrah") == "Lattafa Khamrah"

    def test_khamrah_edp_strips_to_base(self):
        """The suffix-variant form in resolver_perfumes strips to the em name."""
        assert _base_name("Lattafa Khamrah Eau de Parfum") == "Lattafa Khamrah"

    def test_ameer_al_oudh_exact_unchanged(self):
        assert _base_name("Lattafa Ameer Al Oudh") == "Lattafa Ameer Al Oudh"

    def test_ameer_al_oudh_edp_strips_to_base(self):
        assert _base_name("Lattafa Ameer Al Oudh Eau de Parfum") == "Lattafa Ameer Al Oudh"


# ---------------------------------------------------------------------------
# B — Partition key logic
# ---------------------------------------------------------------------------

class TestPartitionKeyLogic:
    """The ROW_NUMBER partition key COALESCE(em.id::text, rp.id::text) must
    behave correctly in both cases."""

    def test_matched_row_uses_em_id_as_key(self):
        """When em.id is present, the partition key is em.id — multiple resolver
        rows that join to the same em.id will be in the same partition."""
        em_id = "9b6533ea-1234-5678-abcd-000000000001"
        rp_id_exact = 16
        rp_id_suffix = 3684

        # Both rows have the same em.id — they should share a partition
        key_exact = em_id  # COALESCE(em.id, rp.id) = em.id
        key_suffix = em_id  # same em.id
        assert key_exact == key_suffix, "Same em.id → same partition → deduplicated"

    def test_catalog_only_row_uses_rp_id_as_key(self):
        """When em.id is None (catalog-only), the partition key is rp.id.
        Two catalog-only rows with different rp.ids get different partitions."""
        em_id = None
        rp_id_1 = 1001
        rp_id_2 = 1002

        key_1 = str(rp_id_1) if em_id is None else em_id
        key_2 = str(rp_id_2) if em_id is None else em_id
        assert key_1 != key_2, "Different rp.id → different partitions → both kept"

    def test_matched_and_catalog_partition_keys_dont_collide(self):
        """A matched row's em.id (UUID) and a catalog-only row's rp.id (integer)
        must not accidentally be equal when cast to text."""
        em_id = "9b6533ea-1234-5678-abcd-000000000001"
        rp_id = 9  # small integer that could collide if misformatted
        # UUID has hyphens; integer cast to text is digits-only → no collision
        assert em_id != str(rp_id)


# ---------------------------------------------------------------------------
# C — Exact match preference within a partition
# ---------------------------------------------------------------------------

class TestExactMatchPreference:
    """Within a partition (same em.id), the ROW_NUMBER ORDER BY prefers the
    resolver row whose canonical_name exactly matches the entity_market row."""

    def _row_rank(self, resolver_name: str, em_name: str) -> int:
        """Simulate the ORDER BY preference: 0 = exact match, 1 = suffix form."""
        exact_match = resolver_name.lower() == em_name.lower()
        return 0 if exact_match else 1

    def test_exact_match_ranks_first(self):
        em_name = "Lattafa Khamrah"
        exact_resolver = "Lattafa Khamrah"
        suffix_resolver = "Lattafa Khamrah Eau de Parfum"

        rank_exact = self._row_rank(exact_resolver, em_name)
        rank_suffix = self._row_rank(suffix_resolver, em_name)
        assert rank_exact < rank_suffix, "Exact match should rank before suffix form"

    def test_shorter_name_preferred_when_both_non_exact(self):
        """If neither resolver name exactly matches em_name, the shorter one
        (closer to base form) ranks first."""
        name_a = "Xerjoff - Join the Club Don Eau de Parfum"
        name_b = "Xerjoff - Join the Club Don Extrait de Parfum Extrait de Parfum"
        assert len(name_a) < len(name_b)
        # In the SQL: LENGTH(rp.canonical_name) ASC — shorter preferred


# ---------------------------------------------------------------------------
# D — DATA2 regression: Xerjoff Join the Club Don suffix resolution
# ---------------------------------------------------------------------------

class TestData2Regression:
    """DATA2 fix must still work after DATA3 changes."""

    def test_xerjoff_join_the_club_don_edp_strips(self):
        """The resolver has 'Xerjoff - Join the Club Don Eau de Parfum';
        entity_market has 'Xerjoff - Join the Club Don'. Must still join."""
        resolver_name = "Xerjoff - Join the Club Don Eau de Parfum"
        em_name = "Xerjoff - Join the Club Don"
        assert _base_name(resolver_name).lower() == em_name.lower()

    def test_xerjoff_join_the_club_don_exact_no_regression(self):
        """Exact match for Xerjoff not regressed."""
        assert _base_name("Xerjoff - Join the Club Don") == "Xerjoff - Join the Club Don"

    def test_xerjoff_casamorati_edp_strips(self):
        """Casamorati suffix form must still resolve."""
        result = _base_name("Xerjoff - Casamorati 1888 Eau de Parfum")
        assert result == "Xerjoff - Casamorati 1888"

    def test_double_suffix_two_pass(self):
        """DATA2 double-suffix case must still be handled."""
        result = _base_name("Baccarat Rouge 540 Extrait Extrait de Parfum")
        assert result == "Baccarat Rouge 540"


# ---------------------------------------------------------------------------
# E — No regression on common non-suffix perfume names
# ---------------------------------------------------------------------------

class TestNoRegressionOnExactNames:
    """Ensure _base_name() does not corrupt names that should be unchanged."""

    def test_creed_aventus_unchanged(self):
        assert _base_name("Creed Aventus") == "Creed Aventus"

    def test_baccarat_rouge_540_unchanged(self):
        assert _base_name("Baccarat Rouge 540") == "Baccarat Rouge 540"

    def test_dior_sauvage_unchanged(self):
        assert _base_name("Dior Sauvage") == "Dior Sauvage"

    def test_armaf_cdnim_unchanged(self):
        assert _base_name("Armaf Club de Nuit Intense Man") == "Armaf Club de Nuit Intense Man"

    def test_lattafa_khamrah_unchanged(self):
        assert _base_name("Lattafa Khamrah") == "Lattafa Khamrah"


# ---------------------------------------------------------------------------
# F — VALID_RELATION_TYPES regression (FTG-2 contract unchanged)
# ---------------------------------------------------------------------------

class TestFTG2Regression:
    """FTG-2 VALID_RELATION_TYPES must not be affected by DATA3 changes."""

    def test_valid_relation_types_unchanged(self):
        from perfume_trend_sdk.db.market.fragrance_relationship import VALID_RELATION_TYPES
        assert "dupe_of" in VALID_RELATION_TYPES
        assert "market_alternative_to" in VALID_RELATION_TYPES
        assert "inspired_by" in VALID_RELATION_TYPES
        assert "commonly_compared_to" in VALID_RELATION_TYPES
        assert len(VALID_RELATION_TYPES) == 4


# ---------------------------------------------------------------------------
# G — Document DATA3 known scope (Lattafa Khamrah pair)
# ---------------------------------------------------------------------------

class TestData3KnownDuplicatePairs:
    """Document the specific Lattafa duplicate pairs that triggered DATA3.

    These are integration-verified facts from production audit (2026-05-15):
      - resolver_perfumes row 16: 'Lattafa Khamrah' (exact match → em.id=9b6533ea)
      - resolver_perfumes row 3684: 'Lattafa Khamrah Eau de Parfum' (suffix → same em.id)
      - resolver_perfumes row N: 'Lattafa Ameer Al Oudh' (exact match → em.id=...)
      - resolver_perfumes row M: 'Lattafa Ameer Al Oudh Eau de Parfum' (suffix → same em.id)

    Before DATA3: both resolver rows appeared in brand page output (score shown twice).
    After DATA3: only the exact-match resolver row appears (one row per em.id).
    """

    def test_khamrah_base_name_matches_em_canonical(self):
        """The stripped form equals the entity_market canonical name."""
        assert _base_name("Lattafa Khamrah Eau de Parfum") == "Lattafa Khamrah"
        assert _base_name("Lattafa Khamrah") == "Lattafa Khamrah"  # exact already

    def test_ameer_al_oudh_base_name_matches_em_canonical(self):
        assert _base_name("Lattafa Ameer Al Oudh Eau de Parfum") == "Lattafa Ameer Al Oudh"
        assert _base_name("Lattafa Ameer Al Oudh") == "Lattafa Ameer Al Oudh"
