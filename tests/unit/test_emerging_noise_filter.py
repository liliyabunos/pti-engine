"""Unit tests for E3-C emerging signals noise filter.

Tests _is_noise_phrase() from the v2 emerging endpoint.
Checks:
  - All observed noise fragments from production are caught
  - All valid perfume/brand names are preserved
"""
from __future__ import annotations

import pytest

from perfume_trend_sdk.api.routes.emerging import _is_noise_phrase


# ---------------------------------------------------------------------------
# Noise cases — must return True
# ---------------------------------------------------------------------------

class TestIsNoisePhraseNoiseCases:
    """All of these should be filtered out."""

    # Explicit blocklist entries
    def test_game_of(self):
        assert _is_noise_phrase("game of") is True

    def test_minute_review(self):
        assert _is_noise_phrase("minute review") is True

    def test_full_review(self):
        assert _is_noise_phrase("full review") is True

    def test_honest_review(self):
        assert _is_noise_phrase("honest review") is True

    def test_first_impressions(self):
        assert _is_noise_phrase("first impressions") is True

    def test_fragrance_review(self):
        assert _is_noise_phrase("fragrance review") is True

    def test_perfume_review(self):
        assert _is_noise_phrase("perfume review") is True

    def test_top_fragrances(self):
        assert _is_noise_phrase("top fragrances") is True

    def test_best_fragrances(self):
        assert _is_noise_phrase("best fragrances") is True

    def test_wild_eau_so_extra(self):
        # Parallel overlap artefact from "Marc Jacobs Daisy Wild Eau So Extra"
        assert _is_noise_phrase("wild eau so extra") is True

    def test_daisy_wild_eau_so(self):
        assert _is_noise_phrase("daisy wild eau so") is True

    def test_jacobs_daisy_wild_eau(self):
        assert _is_noise_phrase("jacobs daisy wild eau") is True

    # E3-F: generic intent / recommendation phrases
    def test_buy_fragrances(self):
        assert _is_noise_phrase("buy fragrances") is True

    def test_smell_like(self):
        assert _is_noise_phrase("smell like") is True

    def test_need_in(self):
        assert _is_noise_phrase("need in") is True

    def test_under_100(self):
        assert _is_noise_phrase("under 100") is True

    def test_every_man_should(self):
        assert _is_noise_phrase("every man should") is True

    def test_fresh_summer_fragrances(self):
        assert _is_noise_phrase("fresh summer fragrances") is True

    def test_hyped_fragrances(self):
        assert _is_noise_phrase("hyped fragrances") is True

    def test_niche_fragrance(self):
        assert _is_noise_phrase("niche fragrance") is True

    def test_mother_day_fragrance(self):
        assert _is_noise_phrase("mother day fragrance") is True

    # Weak-ending guard — last token in _V2_WEAK_ENDINGS
    def test_ends_with_eau(self):
        assert _is_noise_phrase("marc jacobs daisy wild eau") is True

    def test_ends_with_with(self):
        assert _is_noise_phrase("armani stronger with") is True

    def test_ends_with_so(self):
        assert _is_noise_phrase("wild eau so") is True

    def test_ends_with_and(self):
        assert _is_noise_phrase("creed aventus and") is True

    def test_ends_with_of(self):
        assert _is_noise_phrase("game of") is True  # also in blocklist

    def test_ends_with_the(self):
        assert _is_noise_phrase("enter the") is True

    def test_ends_with_for(self):
        assert _is_noise_phrase("great gift for") is True

    def test_ends_with_review(self):
        assert _is_noise_phrase("creed aventus review") is True

    # Weak-starting guard — first token in _V2_WEAK_STARTS
    def test_starts_with_eau(self):
        assert _is_noise_phrase("eau so extra") is True

    def test_starts_with_with(self):
        assert _is_noise_phrase("with you intense") is True

    def test_starts_with_so(self):
        assert _is_noise_phrase("so extra pour homme") is True

    def test_starts_with_and(self):
        assert _is_noise_phrase("and i think it smells") is True

    def test_starts_with_of(self):
        assert _is_noise_phrase("of the year") is True

    def test_starts_with_the(self):
        assert _is_noise_phrase("the best summer") is True

    def test_starts_with_for(self):
        assert _is_noise_phrase("for the office") is True


# ---------------------------------------------------------------------------
# Valid names — must return False
# ---------------------------------------------------------------------------

class TestIsNoisePhraseValidNames:
    """All of these should be PRESERVED (return False)."""

    def test_marc_jacobs_daisy_wild(self):
        # last="wild", first="marc" — neither weak
        assert _is_noise_phrase("marc jacobs daisy wild") is False

    def test_armani_stronger_with_you(self):
        # last="you", first="armani" — neither weak
        assert _is_noise_phrase("armani stronger with you") is False

    def test_givenchy_gentleman_society(self):
        assert _is_noise_phrase("givenchy gentleman society") is False

    def test_jean_paul_gaultier(self):
        assert _is_noise_phrase("jean paul gaultier") is False

    def test_khadlaj_icon(self):
        assert _is_noise_phrase("khadlaj icon") is False

    def test_club_de_nuit_intense(self):
        # "intense" is not a weak token; "club" is not a weak start
        assert _is_noise_phrase("club de nuit intense") is False

    def test_baccarat_rouge_540_dupe(self):
        assert _is_noise_phrase("baccarat rouge 540 dupe") is False

    def test_creed_silver_mountain_water(self):
        # last="water", first="creed" — neither weak
        assert _is_noise_phrase("creed silver mountain water") is False

    def test_creed_aventus(self):
        assert _is_noise_phrase("creed aventus") is False

    def test_dior_sauvage(self):
        assert _is_noise_phrase("dior sauvage") is False

    def test_lattafa_yara(self):
        assert _is_noise_phrase("lattafa yara") is False

    def test_rasasi_hawas(self):
        assert _is_noise_phrase("rasasi hawas") is False

    def test_single_word_brand(self):
        # Single valid brand name — no weak tokens
        assert _is_noise_phrase("armani") is False

    def test_empty_string(self):
        # Edge case — empty string has no tokens → safe to pass
        assert _is_noise_phrase("") is False
