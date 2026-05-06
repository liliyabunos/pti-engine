"""Unit tests for Phase 3 — Demand Type Splitting + Entity Role Gating.

Tests cover:
  - semantic.py: "dupe / alternative" rerouted to intents for original roles
  - semantic.py: "dupe / alternative" stays in differentiators for unknown/clone roles
  - market_intelligence.py: opportunity flags are role-aware
  - market_intelligence.py: narrative copy is role-aware
  - End-to-end: originals never render dupe_market; never in Differentiators
"""

import pytest

from perfume_trend_sdk.analysis.topic_intelligence.semantic import classify_entity_topics
from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import (
    generate_market_intelligence,
    _build_opportunity_flags,
    _build_narrative,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rows(*topic_texts: str, occ: int = 5) -> list[tuple[str, str, int, float]]:
    """Build minimal (topic_type, topic_text, occ, avg_score) rows."""
    return [("topic", t, occ, 0.5) for t in topic_texts]


DUPE_ROW = _make_rows("dupe / alternative")

# ---------------------------------------------------------------------------
# semantic.py — routing tests
# ---------------------------------------------------------------------------

class TestSemanticDupeRouting:
    """'dupe / alternative' should be gated by entity_role."""

    # For original/reference entities → goes to intents, NOT differentiators
    @pytest.mark.parametrize("role", ["designer_original", "niche_original", "original"])
    def test_dupe_not_in_diff_for_originals(self, role):
        profile = classify_entity_topics(DUPE_ROW, entity_role=role)
        assert "dupe / alternative" not in profile.differentiators

    @pytest.mark.parametrize("role", ["designer_original", "niche_original", "original"])
    def test_dupe_routes_to_intents_for_originals(self, role):
        profile = classify_entity_topics(DUPE_ROW, entity_role=role)
        assert "alternative demand" in profile.intents

    # For unknown entity → stays in differentiators
    def test_dupe_stays_in_diff_for_unknown(self):
        profile = classify_entity_topics(DUPE_ROW, entity_role="unknown")
        assert "dupe / alternative" in profile.differentiators
        assert "alternative demand" not in profile.intents

    # For clone roles → stays in differentiators
    @pytest.mark.parametrize("role", ["clone_positioned", "inspired_alternative"])
    def test_dupe_stays_in_diff_for_clone_roles(self, role):
        profile = classify_entity_topics(DUPE_ROW, entity_role=role)
        assert "dupe / alternative" in profile.differentiators
        assert "alternative demand" not in profile.intents

    def test_other_differentiators_unaffected_for_originals(self):
        rows = _make_rows("dupe / alternative", "compliment getter", "longevity / projection")
        profile = classify_entity_topics(rows, entity_role="niche_original")
        # dupe removed from diff for originals
        assert "dupe / alternative" not in profile.differentiators
        # other differentiators preserved
        assert "compliment getter" in profile.differentiators
        assert "longevity / projection" in profile.differentiators
        # alternative demand in intents
        assert "alternative demand" in profile.intents

    def test_default_entity_role_is_unknown(self):
        """Without entity_role kwarg, behaves as unknown (backward compat)."""
        profile = classify_entity_topics(DUPE_ROW)
        assert "dupe / alternative" in profile.differentiators


# ---------------------------------------------------------------------------
# market_intelligence.py — opportunity flag tests
# ---------------------------------------------------------------------------

class TestOpportunityFlags:
    """_build_opportunity_flags should emit role-aware flags."""

    def test_original_with_alternative_demand_intent(self):
        # Semantic layer reroutes → diff is empty, intents has "alternative demand"
        flags = _build_opportunity_flags(
            differentiators=[],
            positioning=[],
            intents=["alternative demand"],
            entity_role="niche_original",
        )
        assert "alternative_demand" in flags
        assert "dupe_market" not in flags
        assert "clone_market" not in flags

    @pytest.mark.parametrize("role", ["designer_original", "niche_original", "original"])
    def test_original_roles_get_alternative_demand_flag(self, role):
        flags = _build_opportunity_flags(
            differentiators=[],
            positioning=[],
            intents=["alternative demand"],
            entity_role=role,
        )
        assert "alternative_demand" in flags

    def test_unknown_with_dupe_in_diff_gets_search_interest(self):
        flags = _build_opportunity_flags(
            differentiators=["dupe / alternative"],
            positioning=[],
            intents=[],
            entity_role="unknown",
        )
        assert "alternative_search_interest" in flags
        assert "dupe_market" not in flags
        assert "alternative_demand" not in flags

    @pytest.mark.parametrize("role", ["clone_positioned", "inspired_alternative"])
    def test_clone_roles_get_clone_market_flag(self, role):
        flags = _build_opportunity_flags(
            differentiators=["dupe / alternative"],
            positioning=[],
            intents=[],
            entity_role=role,
        )
        assert "clone_market" in flags
        assert "dupe_market" not in flags

    def test_no_dupe_signal_no_dupe_flags(self):
        flags = _build_opportunity_flags(
            differentiators=["compliment getter"],
            positioning=["niche fragrance"],
            intents=["review"],
            entity_role="niche_original",
        )
        assert "alternative_demand" not in flags
        assert "alternative_search_interest" not in flags
        assert "clone_market" not in flags
        assert "dupe_market" not in flags

    def test_no_double_flag_for_originals(self):
        """If both diff and intent contain signals (edge case), flag emitted once."""
        flags = _build_opportunity_flags(
            differentiators=["dupe / alternative"],
            positioning=[],
            intents=["alternative demand"],
            entity_role="niche_original",
        )
        assert flags.count("alternative_demand") == 1


# ---------------------------------------------------------------------------
# market_intelligence.py — narrative tests
# ---------------------------------------------------------------------------

class TestNarrative:
    """Narrative copy must be role-aware for dupe/alternative signals."""

    def test_original_narrative_uses_alternative_demand_copy(self):
        narrative = _build_narrative(
            canonical_name="Creed Aventus",
            differentiators=[],
            positioning=[],
            intents=["alternative demand"],
            opportunities=["alternative_demand"],
            competitors=[],
            entity_role="niche_original",
        )
        assert "alternative demand around this reference scent" in narrative
        # Must NOT contain old incorrect copy
        assert "alternative / dupe positioning" not in narrative
        assert "dupe positioning" not in narrative

    def test_unknown_narrative_uses_search_interest_copy(self):
        narrative = _build_narrative(
            canonical_name="Some Clone",
            differentiators=["dupe / alternative"],
            positioning=[],
            intents=[],
            opportunities=["alternative_search_interest"],
            competitors=[],
            entity_role="unknown",
        )
        assert "alternative-related search interest" in narrative
        assert "alternative / dupe positioning" not in narrative

    @pytest.mark.parametrize("role", ["clone_positioned", "inspired_alternative"])
    def test_clone_narrative_uses_alternative_positioning_copy(self, role):
        narrative = _build_narrative(
            canonical_name="Clone Brand X",
            differentiators=["dupe / alternative"],
            positioning=[],
            intents=[],
            opportunities=["clone_market"],
            competitors=[],
            entity_role=role,
        )
        assert "positioned as an alternative to a reference scent" in narrative
        assert "alternative / dupe positioning" not in narrative


# ---------------------------------------------------------------------------
# End-to-end: generate_market_intelligence
# ---------------------------------------------------------------------------

class TestGenerateMarketIntelligenceE2E:
    """Full pipeline: profile → intelligence, role-gated."""

    def _profile_for_original(self, role: str) -> tuple[list, list, list]:
        """Simulate what semantic.py returns for an original entity with dupe topic."""
        profile = classify_entity_topics(DUPE_ROW, entity_role=role)
        return profile.differentiators, profile.positioning, profile.intents

    @pytest.mark.parametrize("role,name", [
        ("niche_original", "Creed Aventus"),
        ("designer_original", "Dior Sauvage"),
        ("niche_original", "Baccarat Rouge 540"),
    ])
    def test_originals_never_get_dupe_market(self, role, name):
        diff, pos, intents = self._profile_for_original(role)
        intel = generate_market_intelligence(
            canonical_name=name,
            differentiators=diff,
            positioning=pos,
            intents=intents,
            raw_queries=[],
            resolved_competitors=[],
            entity_role=role,
        )
        assert "dupe_market" not in intel.opportunities
        assert "alternative / dupe positioning" not in (intel.narrative or "")

    @pytest.mark.parametrize("role,name", [
        ("niche_original", "Creed Aventus"),
        ("designer_original", "Dior Sauvage"),
        ("niche_original", "Baccarat Rouge 540"),
    ])
    def test_originals_get_alternative_demand(self, role, name):
        diff, pos, intents = self._profile_for_original(role)
        intel = generate_market_intelligence(
            canonical_name=name,
            differentiators=diff,
            positioning=pos,
            intents=intents,
            raw_queries=[],
            resolved_competitors=[],
            entity_role=role,
        )
        assert "alternative_demand" in intel.opportunities
        assert "alternative demand around this reference scent" in (intel.narrative or "")

    def test_unknown_entity_gets_search_interest_not_dupe_market(self):
        profile = classify_entity_topics(DUPE_ROW, entity_role="unknown")
        intel = generate_market_intelligence(
            canonical_name="Some Brand Oud",
            differentiators=profile.differentiators,
            positioning=profile.positioning,
            intents=profile.intents,
            raw_queries=[],
            resolved_competitors=[],
            entity_role="unknown",
        )
        assert "dupe_market" not in intel.opportunities
        assert "alternative_search_interest" in intel.opportunities
