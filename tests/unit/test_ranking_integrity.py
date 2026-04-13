from __future__ import annotations

"""
Tests for Ranking Integrity — variant collapse + flood suppression.

Coverage:
  - variant_group_key(): concentration stripping for grouping
  - compute_effective_rank_score(): flood dampening thresholds
  - collapse_and_rank(): variant deduplication, metric merging, sort order
  - No regression for normal multi-source, multi-author entities
  - Signal propagation across collapsed variants
  - Traceability: variant_names / variant_entity_ids populated correctly
"""

import uuid
from dataclasses import dataclass
from typing import Optional

import pytest

from perfume_trend_sdk.analysis.ranking.variant_collapser import (
    FLOOD_AUTHOR_FLOOR,
    FLOOD_DAMPENING_FACTOR,
    CollapsedRow,
    collapse_and_rank,
    compute_effective_rank_score,
    variant_group_key,
)


# ---------------------------------------------------------------------------
# Lightweight stubs for EntityMarket and EntityTimeSeriesDaily
# (avoids importing ORM models in unit tests)
# ---------------------------------------------------------------------------

@dataclass
class _EM:
    """Stub for EntityMarket."""
    entity_id: str
    entity_type: str = "perfume"
    ticker: str = "TEST"
    canonical_name: str = ""
    brand_name: Optional[str] = None
    id: uuid.UUID = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.canonical_name == "":
            self.canonical_name = self.entity_id
        if self.id is None:
            self.id = uuid.uuid4()


@dataclass
class _SNAP:
    """Stub for EntityTimeSeriesDaily."""
    composite_market_score: float = 30.0
    mention_count: float = 1.0
    unique_authors: int = 1
    engagement_sum: float = 0.0
    growth_rate: float = 1.0
    momentum: float = 1.0
    acceleration: float = 0.0
    volatility: float = 0.0
    confidence_avg: float = 1.0
    date: object = None


# ---------------------------------------------------------------------------
# variant_group_key
# ---------------------------------------------------------------------------

class TestVariantGroupKey:
    def test_strips_eau_de_parfum(self):
        assert variant_group_key("Chanel Bleu de Chanel Eau de Parfum") == \
               variant_group_key("Chanel Bleu de Chanel")

    def test_strips_extrait_de_parfum(self):
        assert variant_group_key("MFK Baccarat Rouge 540 Extrait de Parfum") == \
               variant_group_key("MFK Baccarat Rouge 540")

    def test_strips_eau_de_toilette(self):
        assert variant_group_key("Dior Sauvage Eau de Toilette") == \
               variant_group_key("Dior Sauvage")

    def test_strips_edp_abbreviation(self):
        assert variant_group_key("Creed Aventus EDP") == \
               variant_group_key("Creed Aventus")

    def test_strips_parfum_suffix(self):
        assert variant_group_key("Tom Ford Black Orchid Parfum") == \
               variant_group_key("Tom Ford Black Orchid")

    def test_no_suffix_unchanged(self):
        key = variant_group_key("Dior Sauvage")
        assert key == "dior sauvage"

    def test_different_perfumes_different_keys(self):
        assert variant_group_key("Dior Sauvage") != variant_group_key("Creed Aventus")

    def test_elixir_not_stripped(self):
        """'Elixir' is not a concentration term — must not be stripped."""
        key_elixir = variant_group_key("Dior Sauvage Elixir")
        key_base = variant_group_key("Dior Sauvage")
        assert key_elixir != key_base

    def test_case_insensitive(self):
        assert variant_group_key("CHANEL BLEU DE CHANEL EAU DE PARFUM") == \
               variant_group_key("Chanel Bleu de Chanel")

    def test_dash_notation_stripped(self):
        assert variant_group_key("Philosykos - Eau de Parfum") == \
               variant_group_key("Philosykos")


# ---------------------------------------------------------------------------
# compute_effective_rank_score
# ---------------------------------------------------------------------------

class TestFloodDampening:
    def test_zero_authors_dampened(self):
        score, dampened = compute_effective_rank_score(30.0, 0)
        assert dampened is True
        assert score == pytest.approx(30.0 * FLOOD_DAMPENING_FACTOR)

    def test_one_author_dampened(self):
        score, dampened = compute_effective_rank_score(37.0, 1)
        assert dampened is True
        assert score == pytest.approx(37.0 * FLOOD_DAMPENING_FACTOR)

    def test_two_authors_not_dampened(self):
        score, dampened = compute_effective_rank_score(37.0, 2)
        assert dampened is False
        assert score == pytest.approx(37.0)

    def test_many_authors_not_dampened(self):
        score, dampened = compute_effective_rank_score(50.0, 10)
        assert dampened is False
        assert score == pytest.approx(50.0)

    def test_author_floor_constant_is_two(self):
        assert FLOOD_AUTHOR_FLOOR == 2

    def test_dampening_factor_is_point_six(self):
        assert FLOOD_DAMPENING_FACTOR == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# collapse_and_rank — variant collapsing
# ---------------------------------------------------------------------------

class TestVariantCollapsing:
    def test_chanel_bleu_variants_collapsed(self):
        """'Chanel Bleu de Chanel' and '... Eau de Parfum' → single row."""
        em1 = _EM("Chanel Bleu de Chanel", brand_name="Chanel")
        em2 = _EM("Chanel Bleu de Chanel Eau de Parfum", brand_name="Chanel")
        snap1 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)
        snap2 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em1, snap1), (em2, snap2)])

        assert len(result) == 1
        row = result[0]
        assert row.canonical_name == "Chanel Bleu de Chanel"
        assert row.mention_count == pytest.approx(4.0)   # 2 + 2
        assert row.composite_market_score == pytest.approx(37.0)  # max, not summed

    def test_initio_oud_variants_collapsed(self):
        """'Initio Oud for Greatness' and '... Eau de Parfum' → single row."""
        em1 = _EM("Initio Oud for Greatness")
        em2 = _EM("Initio Oud for Greatness Eau de Parfum")
        snap1 = _SNAP(composite_market_score=30.2, mention_count=1, unique_authors=1)
        snap2 = _SNAP(composite_market_score=30.2, mention_count=1, unique_authors=1)

        result = collapse_and_rank([(em1, snap1), (em2, snap2)])

        assert len(result) == 1
        row = result[0]
        assert row.canonical_name == "Initio Oud for Greatness"
        assert row.mention_count == pytest.approx(2.0)

    def test_different_perfumes_not_collapsed(self):
        """Entities with different base names are NOT merged — two rows returned."""
        em1 = _EM("Dior Sauvage Eau de Parfum")
        em2 = _EM("Creed Aventus Eau de Parfum")
        snap1 = _SNAP(composite_market_score=35.0, mention_count=3, unique_authors=3)
        snap2 = _SNAP(composite_market_score=30.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em1, snap1), (em2, snap2)])

        assert len(result) == 2
        # Each entity keeps its own canonical_name (no base-form renaming)
        names = {r.canonical_name for r in result}
        assert "Dior Sauvage Eau de Parfum" in names
        assert "Creed Aventus Eau de Parfum" in names
        # No variants were merged into either row
        for row in result:
            assert row.variant_names == []

    def test_single_entity_unchanged(self):
        """An entity with no variants passes through unchanged."""
        em = _EM("Parfums de Marly Delina", brand_name="Parfums de Marly")
        snap = _SNAP(composite_market_score=28.5, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em, snap)])

        assert len(result) == 1
        assert result[0].canonical_name == "Parfums de Marly Delina"
        assert result[0].variant_names == []

    def test_primary_elected_as_base_form(self):
        """When the base-form entity exists, it is elected as primary."""
        em_base = _EM("MFK Baccarat Rouge 540", brand_name="MFK")
        em_edp = _EM("MFK Baccarat Rouge 540 Eau de Parfum", brand_name="MFK")
        em_ext = _EM("MFK Baccarat Rouge 540 Extrait de Parfum", brand_name="MFK")
        snap_base = _SNAP(composite_market_score=28.0, mention_count=1, unique_authors=1)
        snap_edp = _SNAP(composite_market_score=30.0, mention_count=2, unique_authors=2)
        snap_ext = _SNAP(composite_market_score=25.0, mention_count=1, unique_authors=1)

        result = collapse_and_rank([
            (em_base, snap_base), (em_edp, snap_edp), (em_ext, snap_ext)
        ])

        assert len(result) == 1
        # Base form elected even though EDP has higher score
        assert result[0].canonical_name == "MFK Baccarat Rouge 540"

    def test_variant_traceability(self):
        """Collapsed variants appear in variant_names and variant_entity_ids."""
        em1 = _EM("Chanel Bleu de Chanel")
        em2 = _EM("Chanel Bleu de Chanel Eau de Parfum")
        snap1 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)
        snap2 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em1, snap1), (em2, snap2)])

        row = result[0]
        assert "Chanel Bleu de Chanel Eau de Parfum" in row.variant_names
        assert em2.entity_id in row.variant_entity_ids
        # Primary itself is NOT in variant lists
        assert "Chanel Bleu de Chanel" not in row.variant_names

    def test_elixir_not_confused_with_base(self):
        """'Dior Sauvage Elixir' and 'Dior Sauvage' are different perfumes."""
        em1 = _EM("Dior Sauvage")
        em2 = _EM("Dior Sauvage Elixir")
        snap1 = _SNAP(composite_market_score=35.0, mention_count=3, unique_authors=3)
        snap2 = _SNAP(composite_market_score=30.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em1, snap1), (em2, snap2)])

        assert len(result) == 2


# ---------------------------------------------------------------------------
# collapse_and_rank — flood suppression
# ---------------------------------------------------------------------------

class TestFloodSuppression:
    def test_single_author_entity_dampened(self):
        """Entity with unique_authors=1 gets dampened effective_rank_score."""
        em = _EM("Le Labo Rose 31 Eau de Parfum", brand_name="Le Labo")
        snap = _SNAP(composite_market_score=30.2, mention_count=1, unique_authors=1)

        result = collapse_and_rank([(em, snap)])

        assert result[0].is_flood_dampened is True
        assert result[0].effective_rank_score == pytest.approx(30.2 * 0.6)
        # Raw score preserved for display
        assert result[0].composite_market_score == pytest.approx(30.2)

    def test_multi_author_entity_not_dampened(self):
        """Entity with unique_authors=2 keeps full effective_rank_score."""
        em = _EM("Creed Aventus", brand_name="Creed")
        snap = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em, snap)])

        assert result[0].is_flood_dampened is False
        assert result[0].effective_rank_score == pytest.approx(37.0)

    def test_le_labo_flood_suppressed_behind_multi_author(self):
        """12 single-author Le Labo variants rank below a 2-author entity."""
        le_labo_entities = [
            (_EM(f"Le Labo Scent {i} Eau de Parfum"), _SNAP(30.2, 1.0, 1))
            for i in range(12)
        ]
        creed = (_EM("Creed Aventus"), _SNAP(30.2, 2.0, 2))

        result = collapse_and_rank([creed] + le_labo_entities)

        # Creed must rank first (no dampening)
        assert result[0].canonical_name == "Creed Aventus"
        assert result[0].is_flood_dampened is False
        # All Le Labo entries are dampened
        for row in result[1:]:
            assert row.is_flood_dampened is True

    def test_variant_collapse_uses_merged_unique_authors(self):
        """When variants are collapsed, max(unique_authors) determines dampening."""
        em1 = _EM("Chanel Bleu de Chanel")
        em2 = _EM("Chanel Bleu de Chanel Eau de Parfum")
        # em2 has ua=2 → merged group has max=2 → NO dampening
        snap1 = _SNAP(composite_market_score=30.0, mention_count=1, unique_authors=1)
        snap2 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em1, snap1), (em2, snap2)])

        assert result[0].unique_authors == 2
        assert result[0].is_flood_dampened is False

    def test_variant_collapse_with_both_single_author(self):
        """When all variants have ua=1, the merged group is still dampened."""
        em1 = _EM("Initio Oud for Greatness")
        em2 = _EM("Initio Oud for Greatness Eau de Parfum")
        snap1 = _SNAP(composite_market_score=30.2, mention_count=1, unique_authors=1)
        snap2 = _SNAP(composite_market_score=30.2, mention_count=1, unique_authors=1)

        result = collapse_and_rank([(em1, snap1), (em2, snap2)])

        row = result[0]
        assert row.unique_authors == 1
        assert row.is_flood_dampened is True
        assert row.mention_count == pytest.approx(2.0)  # mentions still summed


# ---------------------------------------------------------------------------
# Signal propagation
# ---------------------------------------------------------------------------

class TestSignalPropagation:
    def test_best_signal_propagated_to_collapsed_row(self):
        """The highest-strength signal among variants is used for the group."""
        em1 = _EM("Chanel Bleu de Chanel")
        em2 = _EM("Chanel Bleu de Chanel Eau de Parfum")
        snap1 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)
        snap2 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)

        # em2 has a stronger signal
        signal_map = {
            em1.id: ("new_entry", 25.0),
            em2.id: ("breakout", 40.0),
        }

        result = collapse_and_rank(
            [(em1, snap1), (em2, snap2)],
            latest_signal_map=signal_map,
        )

        row = result[0]
        assert row.latest_signal == "breakout"
        assert row.latest_signal_strength == pytest.approx(40.0)

    def test_no_signal_when_none_in_map(self):
        """Entities with no signal entry produce None signal fields."""
        em = _EM("Creed Aventus")
        snap = _SNAP(composite_market_score=30.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em, snap)], latest_signal_map={})

        assert result[0].latest_signal is None
        assert result[0].latest_signal_strength is None


# ---------------------------------------------------------------------------
# Rank ordering
# ---------------------------------------------------------------------------

class TestRankOrdering:
    def test_higher_effective_score_ranks_first(self):
        em1 = _EM("Creed Aventus")
        em2 = _EM("Dior Sauvage")
        snap1 = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)
        snap2 = _SNAP(composite_market_score=30.0, mention_count=2, unique_authors=2)

        result = collapse_and_rank([(em2, snap2), (em1, snap1)])

        assert result[0].canonical_name == "Creed Aventus"
        assert result[1].canonical_name == "Dior Sauvage"

    def test_dampened_entity_ranks_below_undampened_of_same_raw_score(self):
        """Single-author entity with score 37 ranks below multi-author at 37."""
        em_multi = _EM("Creed Aventus")
        em_single = _EM("Obscure Niche Eau de Parfum")
        snap_multi = _SNAP(composite_market_score=37.0, mention_count=2, unique_authors=2)
        snap_single = _SNAP(composite_market_score=37.0, mention_count=1, unique_authors=1)

        result = collapse_and_rank([(em_single, snap_single), (em_multi, snap_multi)])

        assert result[0].canonical_name == "Creed Aventus"
        assert result[0].is_flood_dampened is False
        assert result[1].is_flood_dampened is True

    def test_none_snap_excluded(self):
        """Entities with no snapshot row are excluded from the result."""
        em1 = _EM("Creed Aventus")
        em2 = _EM("Dior Sauvage")
        snap1 = _SNAP(composite_market_score=30.0, mention_count=1, unique_authors=1)

        result = collapse_and_rank([(em1, snap1), (em2, None)])

        assert len(result) == 1
        assert result[0].canonical_name == "Creed Aventus"

    def test_empty_input(self):
        result = collapse_and_rank([])
        assert result == []
