"""Unit tests for Phase 5 — Dupe / Alternative Entity Role Mapping.

Tests cover:
  F1. Creed Aventus remains niche_original.
  F2. Armaf Club de Nuit Intense Man → dupe_alternative.
  F3. CDNIM alias forms resolve to dupe_alternative.
  F4. Baccarat Rouge 540 remains niche_original.
  F5. Zara Red Temptation → dupe_alternative (BR540 family).
  F6. Dupe/alternative entities do NOT receive niche_original.
  F7. Original entities can still show Alternative Demand opportunity.
  F8. Armaf brand alone → unknown (removed from niche list).
  F9. Lattafa brand alone → unknown (removed from niche list).
  F10. DupeProfile metadata correct (reference_original, dupe_family).
  F11. get_dupe_profile returns None for originals.
  F12. Role-aware narrative for dupe entities uses reference_original.
  F13. ROLE_LABELS covers all new roles.
  F14. New roles in RENDERABLE_ROLES.
"""

import pytest

from perfume_trend_sdk.analysis.topic_intelligence.entity_role import (
    classify_entity_role,
    get_dupe_profile,
    ROLE_LABELS,
    RENDERABLE_ROLES,
)
from perfume_trend_sdk.analysis.topic_intelligence.market_intelligence import (
    generate_market_intelligence,
    _build_narrative,
)
from perfume_trend_sdk.analysis.topic_intelligence.semantic import classify_entity_topics


# ---------------------------------------------------------------------------
# F1 — Originals remain correctly classified
# ---------------------------------------------------------------------------

class TestOriginalsUnchanged:
    """Phase 5 must not break Phase 2 original classifications."""

    def test_creed_aventus_is_niche_original(self):
        assert classify_entity_role("Creed", "Creed Aventus") == "niche_original"

    def test_creed_brand_alone_is_niche_original(self):
        assert classify_entity_role("Creed") == "niche_original"

    def test_baccarat_rouge_540_is_niche_original(self):
        assert classify_entity_role(
            "Maison Francis Kurkdjian",
            "Maison Francis Kurkdjian Baccarat Rouge 540",
        ) == "niche_original"

    def test_dior_sauvage_is_designer_original(self):
        assert classify_entity_role("Dior", "Dior Sauvage") == "designer_original"

    def test_chanel_bleu_is_designer_original(self):
        assert classify_entity_role("Chanel", "Chanel Bleu de Chanel") == "designer_original"

    def test_xerjoff_erba_pura_is_niche_original(self):
        assert classify_entity_role("Xerjoff", "Xerjoff Erba Pura") == "niche_original"


# ---------------------------------------------------------------------------
# F2 — Armaf Club de Nuit Intense Man → dupe_alternative
# ---------------------------------------------------------------------------

class TestCDNIM:
    """Armaf CDNIM is the canonical Aventus clone. Must classify as dupe_alternative."""

    def test_cdnim_full_name(self):
        assert classify_entity_role(
            "Armaf", "Armaf Club de Nuit Intense Man"
        ) == "dupe_alternative"

    def test_cdnim_without_brand_prefix(self):
        assert classify_entity_role(
            "Armaf", "Club de Nuit Intense Man"
        ) == "dupe_alternative"

    def test_cdnim_abbreviation(self):
        assert classify_entity_role("Armaf", "CDNIM") == "dupe_alternative"

    def test_cdnim_armaf_abbreviation(self):
        assert classify_entity_role("Armaf", "Armaf CDNIM") == "dupe_alternative"

    def test_cdnim_intense_short(self):
        assert classify_entity_role(
            "Armaf", "Armaf Club de Nuit Intense"
        ) == "dupe_alternative"

    def test_cdnim_is_not_niche_original(self):
        role = classify_entity_role("Armaf", "Armaf Club de Nuit Intense Man")
        assert role != "niche_original"

    def test_cdnim_is_not_designer_original(self):
        role = classify_entity_role("Armaf", "Armaf Club de Nuit Intense Man")
        assert role != "designer_original"

    def test_cdnim_is_not_unknown(self):
        role = classify_entity_role("Armaf", "Armaf Club de Nuit Intense Man")
        assert role != "unknown"


# ---------------------------------------------------------------------------
# F3 — Canonicalization guard: broad Armaf Club de Nuit (non-CDNIM) → unknown
# ---------------------------------------------------------------------------

class TestArmafBroadLine:
    """Broad 'Armaf Club de Nuit' line should not be labeled as niche_original.

    The resolver / alias layer is responsible for routing CDNIM-intent queries
    to 'Armaf Club de Nuit Intense Man'. Role classification here only ensures
    the broad line name does not get a false positive.
    """

    def test_broad_club_de_nuit_unknown(self):
        # The broad line name is not in the dupe map (CDNIM-specific entries are)
        assert classify_entity_role("Armaf", "Armaf Club de Nuit") == "unknown"

    def test_armaf_brand_alone_unknown(self):
        # F8: Armaf removed from _NICHE_ORIGINALS
        assert classify_entity_role("Armaf") == "unknown"

    def test_armaf_brand_is_not_niche_original(self):
        assert classify_entity_role("Armaf") != "niche_original"


# ---------------------------------------------------------------------------
# F4 — BR540 remains niche_original (not reclassified by dupe map)
# ---------------------------------------------------------------------------

class TestBR540Unchanged:
    def test_br540_is_niche_original(self):
        assert classify_entity_role(
            "Maison Francis Kurkdjian",
            "Maison Francis Kurkdjian Baccarat Rouge 540",
        ) == "niche_original"

    def test_br540_dupe_profile_is_none(self):
        profile = get_dupe_profile(
            "Maison Francis Kurkdjian",
            "Maison Francis Kurkdjian Baccarat Rouge 540",
        )
        assert profile is None


# ---------------------------------------------------------------------------
# F5 — Zara Red Temptation → dupe_alternative (BR540 family)
# ---------------------------------------------------------------------------

class TestZaraRedTemptation:
    def test_zara_red_temptation_is_dupe_alternative(self):
        assert classify_entity_role(
            "Zara", "Zara Red Temptation"
        ) == "dupe_alternative"

    def test_zara_red_temptation_reference(self):
        profile = get_dupe_profile("Zara", "Zara Red Temptation")
        assert profile is not None
        assert profile.reference_original == "Maison Francis Kurkdjian Baccarat Rouge 540"
        assert profile.dupe_family == "BR540 alternatives"

    def test_zara_brand_alone_is_unknown(self):
        assert classify_entity_role("Zara") == "unknown"


# ---------------------------------------------------------------------------
# F6 — Dupe entities do NOT receive niche_original
# ---------------------------------------------------------------------------

class TestDupeEntitiesNotNicheOriginal:
    @pytest.mark.parametrize("brand,name", [
        ("Armaf", "Armaf Club de Nuit Intense Man"),
        ("Armaf", "CDNIM"),
        ("Zara", "Zara Red Temptation"),
        ("Lattafa", "Lattafa Khamrah"),
    ])
    def test_dupe_entities_not_niche_original(self, brand, name):
        assert classify_entity_role(brand, name) != "niche_original"

    @pytest.mark.parametrize("brand,name", [
        ("Armaf", "Armaf Club de Nuit Intense Man"),
        ("Zara", "Zara Red Temptation"),
        ("Lattafa", "Lattafa Khamrah"),
    ])
    def test_dupe_entities_not_designer_original(self, brand, name):
        assert classify_entity_role(brand, name) != "designer_original"


# ---------------------------------------------------------------------------
# F7 — Originals can still show Alternative Demand opportunity
# ---------------------------------------------------------------------------

class TestOriginalsAlternativeDemandUnchanged:
    """Phase 3/4 behavior for originals is not affected by Phase 5."""

    def _profile_for_original(self, role: str):
        rows = [("topic", "dupe / alternative", 5, 0.5)]
        return classify_entity_topics(rows, entity_role=role)

    @pytest.mark.parametrize("role", ["niche_original", "designer_original"])
    def test_original_dupe_signal_in_intents(self, role):
        profile = self._profile_for_original(role)
        assert "alternative demand" in profile.intents
        assert "dupe / alternative" not in profile.differentiators

    @pytest.mark.parametrize("role,name", [
        ("niche_original", "Creed Aventus"),
        ("designer_original", "Dior Sauvage"),
    ])
    def test_original_gets_alternative_demand_opportunity(self, role, name):
        diff, _, intents = self._profile_for_original(role)
        intel = generate_market_intelligence(
            canonical_name=name,
            differentiators=diff,
            positioning=[],
            intents=intents,
            raw_queries=[],
            resolved_competitors=[],
            entity_role=role,
        )
        assert "alternative_demand" in intel.opportunities
        assert "dupe_market" not in intel.opportunities


# ---------------------------------------------------------------------------
# F8 / F9 — Armaf and Lattafa brand classifications
# ---------------------------------------------------------------------------

class TestMassMarketBrandsRemoved:
    """Brands removed from _NICHE_ORIGINALS in Phase 5."""

    def test_armaf_brand_is_unknown(self):
        assert classify_entity_role("Armaf") == "unknown"

    def test_lattafa_brand_is_unknown(self):
        assert classify_entity_role("Lattafa") == "unknown"

    def test_armaf_brand_is_not_niche(self):
        assert classify_entity_role("Armaf") != "niche_original"

    def test_lattafa_brand_is_not_niche(self):
        assert classify_entity_role("Lattafa") != "niche_original"


# ---------------------------------------------------------------------------
# F10 — DupeProfile metadata
# ---------------------------------------------------------------------------

class TestDupeProfileMetadata:
    def test_cdnim_profile_role(self):
        p = get_dupe_profile("Armaf", "Armaf Club de Nuit Intense Man")
        assert p is not None
        assert p.role == "dupe_alternative"

    def test_cdnim_profile_reference(self):
        p = get_dupe_profile("Armaf", "Armaf Club de Nuit Intense Man")
        assert p.reference_original == "Creed Aventus"

    def test_cdnim_profile_family(self):
        p = get_dupe_profile("Armaf", "Armaf Club de Nuit Intense Man")
        assert p.dupe_family == "Aventus alternatives"

    def test_montblanc_explorer_is_designer_alternative(self):
        assert classify_entity_role("Montblanc", "Montblanc Explorer") == "designer_alternative"

    def test_montblanc_explorer_profile(self):
        p = get_dupe_profile("Montblanc", "Montblanc Explorer")
        assert p is not None
        assert p.role == "designer_alternative"
        assert p.reference_original == "Creed Aventus"

    def test_montblanc_legend_is_designer_original(self):
        # Other Montblanc perfumes are not in dupe map → brand lookup → designer_original
        assert classify_entity_role("Montblanc", "Montblanc Legend") == "designer_original"

    def test_ariana_grande_cloud_is_celebrity_alternative(self):
        assert classify_entity_role(
            "Ariana Grande", "Ariana Grande Cloud"
        ) == "celebrity_alternative"

    def test_ariana_grande_cloud_profile(self):
        p = get_dupe_profile("Ariana Grande", "Ariana Grande Cloud")
        assert p is not None
        assert p.reference_original == "Maison Francis Kurkdjian Baccarat Rouge 540"
        assert p.dupe_family == "BR540 alternatives"


# ---------------------------------------------------------------------------
# F11 — get_dupe_profile returns None for originals
# ---------------------------------------------------------------------------

class TestGetDupeProfileNoneForOriginals:
    @pytest.mark.parametrize("brand,name", [
        ("Creed", "Creed Aventus"),
        ("Dior", "Dior Sauvage"),
        ("Maison Francis Kurkdjian", "Maison Francis Kurkdjian Baccarat Rouge 540"),
        ("Chanel", "Chanel No 5"),
        ("Xerjoff", "Xerjoff Erba Pura"),
    ])
    def test_no_profile_for_originals(self, brand, name):
        assert get_dupe_profile(brand, name) is None

    def test_none_canonical_returns_none(self):
        assert get_dupe_profile("Armaf", None) is None

    def test_unknown_perfume_returns_none(self):
        assert get_dupe_profile("SomeUnknown", "SomeUnknown Random Scent") is None


# ---------------------------------------------------------------------------
# F12 — Role-aware narrative for dupe entities
# ---------------------------------------------------------------------------

class TestDupeNarrative:
    def test_cdnim_narrative_mentions_creed_aventus(self):
        narr = _build_narrative(
            canonical_name="Armaf Club de Nuit Intense Man",
            differentiators=["dupe / alternative", "affordable"],
            positioning=[],
            intents=[],
            opportunities=["clone_market", "affordable_alt"],
            competitors=[],
            entity_role="dupe_alternative",
            reference_original="Creed Aventus",
        )
        assert "Creed Aventus" in narr
        assert "alternative" in narr.lower()
        assert "alternative / dupe positioning" not in narr

    def test_dupe_narrative_without_reference(self):
        narr = _build_narrative(
            canonical_name="Some Clone",
            differentiators=["dupe / alternative"],
            positioning=[],
            intents=[],
            opportunities=["clone_market"],
            competitors=[],
            entity_role="dupe_alternative",
            reference_original=None,
        )
        assert "alternative to a reference scent" in narr

    def test_designer_alternative_narrative(self):
        narr = _build_narrative(
            canonical_name="Montblanc Explorer",
            differentiators=[],
            positioning=[],
            intents=[],
            opportunities=[],
            competitors=[],
            entity_role="designer_alternative",
            reference_original="Creed Aventus",
        )
        assert "Creed Aventus" in narr

    def test_celebrity_alternative_narrative(self):
        narr = _build_narrative(
            canonical_name="Ariana Grande Cloud",
            differentiators=["compliment getter"],
            positioning=[],
            intents=[],
            opportunities=[],
            competitors=[],
            entity_role="celebrity_alternative",
            reference_original="Maison Francis Kurkdjian Baccarat Rouge 540",
        )
        assert "Maison Francis Kurkdjian Baccarat Rouge 540" in narr
        assert "compliment" in narr.lower()

    def test_generate_market_intelligence_e2e_cdnim(self):
        """Full pipeline: CDNIM gets role-aware narrative and clone_market opportunity."""
        from perfume_trend_sdk.analysis.topic_intelligence.semantic import classify_entity_topics
        rows = [
            ("topic", "dupe / alternative", 8, 0.6),
            ("topic", "affordable", 5, 0.4),
            ("topic", "compliment getter", 3, 0.5),
        ]
        profile = classify_entity_topics(rows, entity_role="dupe_alternative")
        # dupe / alternative stays in differentiators for non-originals
        assert "dupe / alternative" in profile.differentiators

        intel = generate_market_intelligence(
            canonical_name="Armaf Club de Nuit Intense Man",
            differentiators=profile.differentiators,
            positioning=profile.positioning,
            intents=profile.intents,
            raw_queries=[],
            resolved_competitors=[],
            entity_role="dupe_alternative",
            reference_original="Creed Aventus",
        )
        assert "clone_market" in intel.opportunities
        assert "Creed Aventus" in (intel.narrative or "")
        assert "niche_original" not in (intel.narrative or "")


# ---------------------------------------------------------------------------
# F13 / F14 — ROLE_LABELS and RENDERABLE_ROLES
# ---------------------------------------------------------------------------

class TestExports:
    def test_new_roles_in_role_labels(self):
        for role in ("dupe_alternative", "designer_alternative", "celebrity_alternative"):
            assert role in ROLE_LABELS
            assert ROLE_LABELS[role]  # non-empty label

    def test_dupe_alternative_label(self):
        assert ROLE_LABELS["dupe_alternative"] == "Dupe / Alternative"

    def test_designer_alternative_label(self):
        assert ROLE_LABELS["designer_alternative"] == "Designer Alternative"

    def test_celebrity_alternative_label(self):
        assert ROLE_LABELS["celebrity_alternative"] == "Celebrity Alternative"

    def test_new_roles_in_renderable(self):
        for role in ("dupe_alternative", "designer_alternative", "celebrity_alternative"):
            assert role in RENDERABLE_ROLES

    def test_unknown_not_in_renderable(self):
        assert "unknown" not in RENDERABLE_ROLES
