"""Unit tests for Phase I7.5 — Entity Role Classification.

Tests cover:
  - Designer original classification (exact names + aliases)
  - Niche original classification (exact names + aliases + accent variants)
  - Normalization (case, accents, punctuation, whitespace)
  - Unknown fallback
  - None / empty inputs
  - ROLE_LABELS and RENDERABLE_ROLES exports
"""

import pytest

from perfume_trend_sdk.analysis.topic_intelligence.entity_role import (
    classify_entity_role,
    ROLE_LABELS,
    RENDERABLE_ROLES,
)


# ---------------------------------------------------------------------------
# Designer originals
# ---------------------------------------------------------------------------

class TestDesignerOriginals:
    def test_dior(self):
        assert classify_entity_role("Dior") == "designer_original"

    def test_christian_dior(self):
        assert classify_entity_role("Christian Dior") == "designer_original"

    def test_chanel(self):
        assert classify_entity_role("Chanel") == "designer_original"

    def test_ysl_abbreviation(self):
        assert classify_entity_role("YSL") == "designer_original"

    def test_yves_saint_laurent_full(self):
        assert classify_entity_role("Yves Saint Laurent") == "designer_original"

    def test_yves_saint_laurent_lowercase(self):
        assert classify_entity_role("yves saint laurent") == "designer_original"

    def test_givenchy(self):
        assert classify_entity_role("Givenchy") == "designer_original"

    def test_gucci(self):
        assert classify_entity_role("Gucci") == "designer_original"

    def test_prada(self):
        assert classify_entity_role("Prada") == "designer_original"

    def test_giorgio_armani(self):
        assert classify_entity_role("Giorgio Armani") == "designer_original"

    def test_armani_short(self):
        assert classify_entity_role("Armani") == "designer_original"

    def test_versace(self):
        assert classify_entity_role("Versace") == "designer_original"

    def test_burberry(self):
        assert classify_entity_role("Burberry") == "designer_original"

    def test_hugo_boss(self):
        assert classify_entity_role("Hugo Boss") == "designer_original"

    def test_tom_ford(self):
        assert classify_entity_role("Tom Ford") == "designer_original"

    def test_valentino(self):
        assert classify_entity_role("Valentino") == "designer_original"

    def test_hermes_ascii(self):
        # No accent
        assert classify_entity_role("Hermes") == "designer_original"

    def test_hermes_accented(self):
        # With accent
        assert classify_entity_role("Hermès") == "designer_original"

    def test_cartier(self):
        assert classify_entity_role("Cartier") == "designer_original"

    def test_montblanc(self):
        assert classify_entity_role("Montblanc") == "designer_original"

    def test_jean_paul_gaultier(self):
        assert classify_entity_role("Jean Paul Gaultier") == "designer_original"

    def test_dolce_gabbana_ampersand(self):
        assert classify_entity_role("Dolce & Gabbana") == "designer_original"

    def test_dolce_gabbana_and_word(self):
        assert classify_entity_role("Dolce and Gabbana") == "designer_original"

    def test_dg_abbreviation(self):
        assert classify_entity_role("D&G") == "designer_original"

    def test_paco_rabanne(self):
        assert classify_entity_role("Paco Rabanne") == "designer_original"

    def test_rabanne_short(self):
        assert classify_entity_role("Rabanne") == "designer_original"

    def test_viktor_and_rolf_ampersand(self):
        assert classify_entity_role("Viktor&Rolf") == "designer_original"

    def test_viktor_and_rolf_spaced(self):
        assert classify_entity_role("Viktor & Rolf") == "designer_original"

    def test_carolina_herrera(self):
        assert classify_entity_role("Carolina Herrera") == "designer_original"

    def test_mugler(self):
        assert classify_entity_role("Mugler") == "designer_original"

    def test_calvin_klein(self):
        assert classify_entity_role("Calvin Klein") == "designer_original"

    def test_ralph_lauren(self):
        assert classify_entity_role("Ralph Lauren") == "designer_original"


# ---------------------------------------------------------------------------
# Niche originals
# ---------------------------------------------------------------------------

class TestNicheOriginals:
    def test_creed(self):
        assert classify_entity_role("Creed") == "niche_original"

    def test_house_of_creed(self):
        assert classify_entity_role("House of Creed") == "niche_original"

    def test_maison_francis_kurkdjian(self):
        assert classify_entity_role("Maison Francis Kurkdjian") == "niche_original"

    def test_mfk_abbreviation(self):
        assert classify_entity_role("MFK") == "niche_original"

    def test_parfums_de_marly(self):
        assert classify_entity_role("Parfums de Marly") == "niche_original"

    def test_xerjoff(self):
        assert classify_entity_role("Xerjoff") == "niche_original"

    def test_roja_parfums(self):
        assert classify_entity_role("Roja Parfums") == "niche_original"

    def test_roja_dove(self):
        assert classify_entity_role("Roja Dove") == "niche_original"

    def test_amouage(self):
        assert classify_entity_role("Amouage") == "niche_original"

    def test_initio(self):
        assert classify_entity_role("Initio") == "niche_original"

    def test_nishane(self):
        assert classify_entity_role("Nishane") == "niche_original"

    def test_byredo(self):
        assert classify_entity_role("Byredo") == "niche_original"

    def test_le_labo(self):
        assert classify_entity_role("Le Labo") == "niche_original"

    def test_diptyque(self):
        assert classify_entity_role("Diptyque") == "niche_original"

    def test_memo_paris(self):
        assert classify_entity_role("Memo Paris") == "niche_original"

    def test_serge_lutens(self):
        assert classify_entity_role("Serge Lutens") == "niche_original"

    def test_frederic_malle_ascii(self):
        assert classify_entity_role("Frederic Malle") == "niche_original"

    def test_frederic_malle_accented(self):
        assert classify_entity_role("Frédéric Malle") == "niche_original"

    def test_penhaligons_apostrophe(self):
        assert classify_entity_role("Penhaligon's") == "niche_original"

    def test_penhaligons_no_apostrophe(self):
        assert classify_entity_role("Penhaligons") == "niche_original"

    def test_clive_christian(self):
        assert classify_entity_role("Clive Christian") == "niche_original"

    def test_orto_parisi(self):
        assert classify_entity_role("Orto Parisi") == "niche_original"

    def test_tiziana_terenzi(self):
        assert classify_entity_role("Tiziana Terenzi") == "niche_original"

    def test_kilian(self):
        assert classify_entity_role("Kilian") == "niche_original"

    def test_by_kilian(self):
        assert classify_entity_role("By Kilian") == "niche_original"

    def test_bdk_parfums(self):
        assert classify_entity_role("BDK Parfums") == "niche_original"

    def test_ex_nihilo(self):
        assert classify_entity_role("Ex Nihilo") == "niche_original"

    def test_mancera(self):
        assert classify_entity_role("Mancera") == "niche_original"

    def test_montale(self):
        assert classify_entity_role("Montale") == "niche_original"

    def test_maison_crivelli(self):
        assert classify_entity_role("Maison Crivelli") == "niche_original"

    def test_vilhelm_parfumerie(self):
        assert classify_entity_role("Vilhelm Parfumerie") == "niche_original"

    def test_juliette_has_a_gun(self):
        assert classify_entity_role("Juliette Has A Gun") == "niche_original"

    def test_etat_libre_dorange(self):
        assert classify_entity_role("Etat Libre d'Orange") == "niche_original"

    def test_nasomatto(self):
        assert classify_entity_role("Nasomatto") == "niche_original"

    def test_jo_malone(self):
        assert classify_entity_role("Jo Malone") == "niche_original"

    def test_jo_malone_london(self):
        assert classify_entity_role("Jo Malone London") == "niche_original"


# ---------------------------------------------------------------------------
# Normalization edge cases
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_all_caps(self):
        assert classify_entity_role("DIOR") == "designer_original"

    def test_mixed_case(self):
        assert classify_entity_role("dIoR") == "designer_original"

    def test_leading_trailing_whitespace(self):
        assert classify_entity_role("  Creed  ") == "niche_original"

    def test_extra_internal_whitespace(self):
        assert classify_entity_role("Maison  Francis  Kurkdjian") == "niche_original"

    def test_accent_stripping_hermes(self):
        # Both with and without accent should match
        assert classify_entity_role("Hermès") == "designer_original"
        assert classify_entity_role("Hermes") == "designer_original"

    def test_accent_stripping_frederic_malle(self):
        assert classify_entity_role("Frédéric Malle") == "niche_original"
        assert classify_entity_role("Frederic Malle") == "niche_original"

    def test_apostrophe_penhaligons(self):
        assert classify_entity_role("Penhaligon's") == "niche_original"
        assert classify_entity_role("Penhaligons") == "niche_original"

    def test_ampersand_normalization(self):
        # "D&G" apostrophe stripped → "d g" → matches "d g" in norm set
        assert classify_entity_role("D&G") == "designer_original"

    def test_etat_libre_apostrophe(self):
        assert classify_entity_role("Etat Libre d'Orange") == "niche_original"


# ---------------------------------------------------------------------------
# Unknown / unrecognised brands
# ---------------------------------------------------------------------------

class TestUnknown:
    def test_unknown_brand(self):
        assert classify_entity_role("Some Unknown Brand") == "unknown"

    def test_empty_string(self):
        assert classify_entity_role("") == "unknown"

    def test_none_brand(self):
        assert classify_entity_role(None) == "unknown"

    def test_whitespace_only(self):
        assert classify_entity_role("   ") == "unknown"

    def test_generic_fragrance_name(self):
        # A clone-tier brand that is not yet in our lists
        assert classify_entity_role("Armaf Club De Nuit") == "unknown"

    def test_zara(self):
        # Zara is a mass-market retailer, not a prestige fragrance house
        assert classify_entity_role("Zara") == "unknown"


# ---------------------------------------------------------------------------
# perfume_name argument (reserved, currently ignored)
# ---------------------------------------------------------------------------

class TestPerfumeNameArgument:
    def test_brand_takes_precedence(self):
        # brand known → should classify from brand regardless of perfume name
        assert classify_entity_role("Creed", "Aventus") == "niche_original"

    def test_unknown_brand_with_perfume_name(self):
        assert classify_entity_role("Unknown House", "Some Fragrance") == "unknown"

    def test_none_brand_with_perfume_name(self):
        assert classify_entity_role(None, "Aventus") == "unknown"


# ---------------------------------------------------------------------------
# ROLE_LABELS and RENDERABLE_ROLES
# ---------------------------------------------------------------------------

class TestExports:
    def test_all_roles_in_labels(self):
        for role in ("designer_original", "niche_original", "original",
                     "clone_positioned", "inspired_alternative", "flanker", "unknown"):
            assert role in ROLE_LABELS

    def test_unknown_label_is_empty_string(self):
        assert ROLE_LABELS["unknown"] == ""

    def test_designer_original_label(self):
        assert ROLE_LABELS["designer_original"] == "Designer Original"

    def test_niche_original_label(self):
        assert ROLE_LABELS["niche_original"] == "Niche Original"

    def test_unknown_not_in_renderable_roles(self):
        assert "unknown" not in RENDERABLE_ROLES

    def test_all_non_unknown_in_renderable(self):
        for role in ("designer_original", "niche_original", "original",
                     "clone_positioned", "inspired_alternative", "flanker"):
            assert role in RENDERABLE_ROLES
