"""SIG-QA1 Batch 2 Guard Tests — 12 confirmed false-positive entities

All 12 entities confirmed false-positive via full RS inspection (2026-05-19).
RS evidence brand context rate: 0% across all rows for every entity.

Guard structure: each phrase requires its brand token in ±10-token proximity.

Entities covered:
  White Musk (W.Dressroom)              — Type B note/ingredient
  Black Pepper (Demeter)                — Type B note/ingredient
  Apple Blossom (Auric Blends)          — Type B note/ingredient
  Bitter Orange (Zara)                  — Type B note/ingredient
  Earl Grey (Teone Reinthal)            — Type B note/ingredient
  Earl Grey Tea (Demeter)               — Type B note/ingredient
  Black Jeans (Versace)                 — Type C ordinary noun
  Black Suit (Ramon Monegal)            — Type C ordinary noun
  Green Tea (Coty)                      — Type D generic descriptor
  Hair Perfume (Balmain)                — Type D generic descriptor
  Bath & Body (Marbert)                 — Type D generic descriptor
  Be Cool (Avon)                        — Type D generic descriptor

Test suites:
  N1–N12  each phrase BLOCKED without brand token nearby
  P1–P12  each phrase RESOLVES with brand token nearby
  R1      Creed Aventus unaffected
  R2      Orange Blossom (Angela Flanders) guard still active (SIG-QA1-REPAIR regression)
  R3      Men's Cologne (Coty) guard still active (RES-AMB-MENSCOL regression)
  R4      "bath and body" variant also blocked without marbert
  R5      "bath and body" variant resolves with marbert
  G1      All 12 new phrases present in _AMBIGUOUS_PHRASE_GUARD
  G2      Brand tokens correct for each phrase
  G3      Guard entries are list of frozensets
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import (
    PerfumeResolver,
    _AMBIGUOUS_PHRASE_GUARD,
)
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolver_with_aliases(alias_map: Dict[str, Dict[str, Any]]) -> PerfumeResolver:
    store = MagicMock()
    store.get_perfume_by_alias.side_effect = lambda phrase: alias_map.get(phrase)
    return PerfumeResolver(store=store)


def _make_entity(perfume_id: int, canonical_name: str) -> Dict[str, Any]:
    return {
        "perfume_id": perfume_id,
        "canonical_name": canonical_name,
        "confidence": 1.0,
        "match_type": "exact",
    }


def _names(results: List[Dict[str, Any]]) -> List[str]:
    return [r["canonical_name"] for r in results]


# Alias map: all 12 batch-2 entities + their brand tokens + regressions
_TEST_ALIASES: Dict[str, Dict[str, Any]] = {
    # SIG-QA1-BATCH2 entities (normalized forms)
    "white musk":       _make_entity(8001, "White Musk"),
    "black pepper":     _make_entity(8002, "Black Pepper"),
    "apple blossom":    _make_entity(8003, "Apple Blossom"),
    "bitter orange":    _make_entity(8004, "Bitter Orange"),
    "earl grey":        _make_entity(8005, "Earl Grey"),
    "earl grey tea":    _make_entity(8006, "Earl Grey Tea"),
    "black jeans":      _make_entity(8007, "Black Jeans"),
    "black suit":       _make_entity(8008, "Black Suit"),
    "green tea":        _make_entity(8009, "Green Tea"),
    "hair perfume":     _make_entity(8010, "Hair Perfume"),
    "bath body":        _make_entity(8011, "Bath & Body"),   # normalize_text("Bath & Body")
    "bath and body":    _make_entity(8011, "Bath & Body"),   # alias variant
    "be cool":          _make_entity(8012, "Be Cool"),
    # Brand context tokens
    "dressroom":        _make_entity(9001, "W.Dressroom Brand"),
    "demeter":          _make_entity(9002, "Demeter Brand"),
    "auric":            _make_entity(9003, "Auric Blends Brand"),
    "zara":             _make_entity(9004, "Zara Brand"),
    "teone":            _make_entity(9005, "Teone Reinthal Brand"),
    "reinthal":         _make_entity(9005, "Teone Reinthal Brand"),
    "versace":          _make_entity(9006, "Versace Brand"),
    "monegal":          _make_entity(9007, "Ramon Monegal Brand"),
    "coty":             _make_entity(9008, "Coty Brand"),
    "balmain":          _make_entity(9009, "Balmain Brand"),
    "marbert":          _make_entity(9010, "Marbert Brand"),
    "avon":             _make_entity(9011, "Avon Brand"),
    # Regression — SIG-QA1-REPAIR (Orange Blossom guard)
    "orange blossom":   _make_entity(7001, "Orange Blossom"),
    "angela":           _make_entity(7002, "Angela Flanders Brand"),
    "flanders":         _make_entity(7002, "Angela Flanders Brand"),
    # Regression — Men's Cologne guard
    "men cologne":      _make_entity(7003, "Men's Cologne"),
    # Legit perfume
    "creed aventus":    _make_entity(2001, "Creed Aventus"),
}


def _resolver() -> PerfumeResolver:
    return _make_resolver_with_aliases(_TEST_ALIASES)


# ---------------------------------------------------------------------------
# N — Negative: phrases BLOCKED without brand token nearby
# ---------------------------------------------------------------------------

class TestNegativeCasesBatch2:

    def test_N1_white_musk_blocked_without_dressroom(self):
        """'white musk' in note description — no W.Dressroom context."""
        r = _resolver()
        results = r.resolve_text("I love fragrances with white musk in the base notes")
        assert "White Musk" not in _names(results)

    def test_N1b_white_musk_blocked_in_note_list(self):
        """'white musk' in ingredient list — no brand context."""
        r = _resolver()
        results = r.resolve_text("top notes citrus heart jasmine white musk base woods")
        assert "White Musk" not in _names(results)

    def test_N2_black_pepper_blocked_without_demeter(self):
        """'black pepper' as note descriptor — no Demeter context."""
        r = _resolver()
        results = r.resolve_text("this cologne opens with black pepper and bergamot")
        assert "Black Pepper" not in _names(results)

    def test_N3_apple_blossom_blocked_without_auric(self):
        """'apple blossom' as floral note — no Auric Blends context."""
        r = _resolver()
        results = r.resolve_text("the spring scent has apple blossom and white tea")
        assert "Apple Blossom" not in _names(results)

    def test_N4_bitter_orange_blocked_without_zara(self):
        """'bitter orange' as citrus top note — no Zara context."""
        r = _resolver()
        results = r.resolve_text("bitter orange is a common top note in fougere fragrances")
        assert "Bitter Orange" not in _names(results)

    def test_N5_earl_grey_blocked_without_teone(self):
        """'earl grey' as tea flavor descriptor — no Teone Reinthal context."""
        r = _resolver()
        results = r.resolve_text("I love fragrances that smell like earl grey tea bergamot and cream")
        assert "Earl Grey" not in _names(results)

    def test_N6_earl_grey_tea_blocked_without_demeter(self):
        """'earl grey tea' as flavor note — no Demeter context."""
        r = _resolver()
        results = r.resolve_text("looking for something that smells like earl grey tea")
        assert "Earl Grey Tea" not in _names(results)

    def test_N7_black_jeans_blocked_without_versace(self):
        """'black jeans' as clothing item description — no Versace context."""
        r = _resolver()
        results = r.resolve_text("wearing black jeans and a white shirt what cologne to wear")
        assert "Black Jeans" not in _names(results)

    def test_N8_black_suit_blocked_without_monegal(self):
        """'black suit' as outfit descriptor — no Ramon Monegal context."""
        r = _resolver()
        results = r.resolve_text("recommendations for a black suit business meeting fragrance")
        assert "Black Suit" not in _names(results)

    def test_N9_green_tea_blocked_without_coty(self):
        """'green tea' as wellness/flavor descriptor — no Coty context."""
        r = _resolver()
        results = r.resolve_text("this smells like green tea and fresh cut grass very clean")
        assert "Green Tea" not in _names(results)

    def test_N10_hair_perfume_blocked_without_balmain(self):
        """'hair perfume' as product category — no Balmain context."""
        r = _resolver()
        results = r.resolve_text("looking for the best hair perfume for everyday use")
        assert "Hair Perfume" not in _names(results)

    def test_N11_bath_body_blocked_without_marbert(self):
        """'Bath & Body' (normalizes to 'bath body') — no Marbert context."""
        r = _resolver()
        results = r.resolve_text("picked up a new bath body set from the store")
        assert "Bath & Body" not in _names(results)

    def test_N11b_bath_body_blocked_in_retail_context(self):
        """'bath and body' in Bath & Body Works retail context — no Marbert."""
        r = _resolver()
        results = r.resolve_text("bath and body works released a new candle collection")
        assert "Bath & Body" not in _names(results)

    def test_N12_be_cool_blocked_without_avon(self):
        """'be cool' as lifestyle phrase — no Avon context."""
        r = _resolver()
        results = r.resolve_text("just be cool and wear whatever fragrance you like")
        assert "Be Cool" not in _names(results)


# ---------------------------------------------------------------------------
# P — Positive: phrases RESOLVE when brand token is nearby
# ---------------------------------------------------------------------------

class TestPositiveCasesBatch2:

    def test_P1_white_musk_resolves_with_dressroom(self):
        """'white musk' with 'dressroom' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("w dressroom white musk is a clean fresh floral")
        assert "White Musk" in _names(results)

    def test_P2_black_pepper_resolves_with_demeter(self):
        """'black pepper' with 'demeter' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("demeter black pepper is exactly what it smells like")
        assert "Black Pepper" in _names(results)

    def test_P3_apple_blossom_resolves_with_auric(self):
        """'apple blossom' with 'auric' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("auric blends apple blossom is a sweet spring fragrance")
        assert "Apple Blossom" in _names(results)

    def test_P4_bitter_orange_resolves_with_zara(self):
        """'bitter orange' with 'zara' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("zara bitter orange is a fresh summer scent")
        assert "Bitter Orange" in _names(results)

    def test_P5_earl_grey_resolves_with_teone(self):
        """'earl grey' with 'teone' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("teone reinthal earl grey is a unique natural perfume")
        assert "Earl Grey" in _names(results)

    def test_P5b_earl_grey_resolves_with_reinthal(self):
        """'earl grey' with 'reinthal' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("reviewed the reinthal earl grey scent today")
        assert "Earl Grey" in _names(results)

    def test_P6_earl_grey_tea_resolves_with_demeter(self):
        """'earl grey tea' with 'demeter' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("demeter earl grey tea is spot on for bergamot lovers")
        assert "Earl Grey Tea" in _names(results)

    def test_P7_black_jeans_resolves_with_versace(self):
        """'black jeans' with 'versace' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("versace black jeans is a classic 90s fragrance")
        assert "Black Jeans" in _names(results)

    def test_P8_black_suit_resolves_with_monegal(self):
        """'black suit' with 'monegal' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("monegal black suit is an understated masculine scent")
        assert "Black Suit" in _names(results)

    def test_P9_green_tea_resolves_with_coty(self):
        """'green tea' with 'coty' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("coty green tea is a classic affordable fragrance")
        assert "Green Tea" in _names(results)

    def test_P10_hair_perfume_resolves_with_balmain(self):
        """'hair perfume' with 'balmain' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("balmain hair perfume is great for keeping hair fresh")
        assert "Hair Perfume" in _names(results)

    def test_P11_bath_body_resolves_with_marbert(self):
        """'Bath & Body' (normalized) with 'marbert' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("marbert bath body is a classic european scent")
        assert "Bath & Body" in _names(results)

    def test_P11b_bath_and_body_resolves_with_marbert(self):
        """'bath and body' variant with 'marbert' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("marbert bath and body has been around for decades")
        assert "Bath & Body" in _names(results)

    def test_P12_be_cool_resolves_with_avon(self):
        """'be cool' with 'avon' nearby resolves correctly."""
        r = _resolver()
        results = r.resolve_text("avon be cool is a fresh sporty cologne for summer")
        assert "Be Cool" in _names(results)


# ---------------------------------------------------------------------------
# R — Regression tests
# ---------------------------------------------------------------------------

class TestRegressionBatch2:

    def test_R1_creed_aventus_unaffected(self):
        """Creed Aventus resolves normally — no guards affect it."""
        r = _resolver()
        results = r.resolve_text("creed aventus is the best fragrance ever made")
        assert "Creed Aventus" in _names(results)

    def test_R2_orange_blossom_guard_still_active(self):
        """Orange Blossom (Angela Flanders) SIG-QA1-REPAIR guard remains active."""
        r = _resolver()
        results = r.resolve_text("notes of orange blossom and sandalwood are beautiful together")
        assert "Orange Blossom" not in _names(results)

    def test_R2b_orange_blossom_resolves_with_angela_flanders(self):
        """Orange Blossom still resolves when Angela Flanders tokens present."""
        r = _resolver()
        results = r.resolve_text("angela flanders orange blossom is a lovely floral")
        assert "Orange Blossom" in _names(results)

    def test_R3_mens_cologne_guard_still_active(self):
        """Men's Cologne (Coty) RES-AMB-MENSCOL guard remains active."""
        r = _resolver()
        results = r.resolve_text("best men cologne recommendations for work")
        assert "Men's Cologne" not in _names(results)

    def test_R4_bath_and_body_variant_blocked(self):
        """'bath and body' variant blocked without marbert (R4 alias-variant guard)."""
        r = _resolver()
        results = r.resolve_text("I got a great bath and body gift set for Christmas")
        assert "Bath & Body" not in _names(results)

    def test_R5_bath_and_body_variant_resolves_with_marbert(self):
        """'bath and body' variant resolves when marbert present (R5)."""
        r = _resolver()
        results = r.resolve_text("the marbert bath and body range smells wonderful")
        assert "Bath & Body" in _names(results)


# ---------------------------------------------------------------------------
# G — Guard structure tests
# ---------------------------------------------------------------------------

class TestGuardStructureBatch2:

    _BATCH2_PHRASES = {
        "white musk",
        "black pepper",
        "apple blossom",
        "bitter orange",
        "earl grey",
        "earl grey tea",
        "black jeans",
        "black suit",
        "green tea",
        "hair perfume",
        "bath body",
        "bath and body",
        "be cool",
    }

    def test_G1_all_batch2_phrases_in_guard(self):
        """All 13 Batch 2 guard phrases present in _AMBIGUOUS_PHRASE_GUARD."""
        missing = self._BATCH2_PHRASES - set(_AMBIGUOUS_PHRASE_GUARD.keys())
        assert not missing, f"Missing guard phrases: {missing}"

    def test_G2_white_musk_requires_dressroom(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["white musk"]
        tokens = set().union(*guard)
        assert "dressroom" in tokens

    def test_G2_black_pepper_requires_demeter(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["black pepper"]
        tokens = set().union(*guard)
        assert "demeter" in tokens

    def test_G2_apple_blossom_requires_auric(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["apple blossom"]
        tokens = set().union(*guard)
        assert "auric" in tokens

    def test_G2_bitter_orange_requires_zara(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["bitter orange"]
        tokens = set().union(*guard)
        assert "zara" in tokens

    def test_G2_earl_grey_requires_teone_or_reinthal(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["earl grey"]
        tokens = set().union(*guard)
        assert "teone" in tokens or "reinthal" in tokens

    def test_G2_earl_grey_tea_requires_demeter(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["earl grey tea"]
        tokens = set().union(*guard)
        assert "demeter" in tokens

    def test_G2_black_jeans_requires_versace(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["black jeans"]
        tokens = set().union(*guard)
        assert "versace" in tokens

    def test_G2_black_suit_requires_monegal(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["black suit"]
        tokens = set().union(*guard)
        assert "monegal" in tokens

    def test_G2_green_tea_requires_coty(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["green tea"]
        tokens = set().union(*guard)
        assert "coty" in tokens

    def test_G2_hair_perfume_requires_balmain(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["hair perfume"]
        tokens = set().union(*guard)
        assert "balmain" in tokens

    def test_G2_bath_body_requires_marbert(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["bath body"]
        tokens = set().union(*guard)
        assert "marbert" in tokens

    def test_G2_bath_and_body_requires_marbert(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["bath and body"]
        tokens = set().union(*guard)
        assert "marbert" in tokens

    def test_G2_be_cool_requires_avon(self):
        guard = _AMBIGUOUS_PHRASE_GUARD["be cool"]
        tokens = set().union(*guard)
        assert "avon" in tokens

    def test_G3_guard_entries_are_list_of_frozensets(self):
        """Each Batch 2 guard entry is a list of frozensets."""
        for phrase in self._BATCH2_PHRASES:
            entry = _AMBIGUOUS_PHRASE_GUARD[phrase]
            assert isinstance(entry, list), f"{phrase}: expected list"
            for token_set in entry:
                assert isinstance(token_set, frozenset), f"{phrase}: expected frozenset"
