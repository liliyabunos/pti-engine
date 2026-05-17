"""SIG-QA1-REPAIR — Source-Evidence Guard Tests (2026-05-17).

Guards added for 5 confirmed unsupported entities:

  N1   "pure luxury"           → Pure Luxury (Wolken Parfums) — Type D generic descriptor
  N1b  RS evidence: "smells like pure luxury" / "pure luxury floral" as adjective phrase
  N2   "on the rocks"          → On the Rocks (Wolken Parfums) — Type F partial-name collision
  N2b  RS evidence: sources discuss Kilian Apple Brandy on the Rocks; substring match
  N3   "enjoy the day"         → Enjoy the Day (Wolken Parfums) — Type D ordinary phrase
  N3b  RS evidence: r/weddingplanning "enjoy the day" in prose
  N4   "orange blossom"        → Orange Blossom (Angela Flanders) — Type B note/ingredient
  N4b  RS evidence: note-preference posts, Le Labo collection review, ingredient description
  N5   "revolution"            → Cire Trudon Revolution — Type C single-word ordinary alias
  N5b  RS evidence: "Fresh Cucumber Revolution?" YouTube title (rhetorical); Alkemia prose
  N5c  "revolution perfume"    — guarded variant
  N5d  "revolution eau de parfum" — guarded variant

  P1   "wolken pure luxury"       DOES resolve (wolken brand token nearby)
  P2   "wolken on the rocks"      DOES resolve (wolken brand token nearby)
  P3   "wolken enjoy the day"     DOES resolve (wolken brand token nearby)
  P4   "angela flanders orange blossom" DOES resolve (both brand tokens nearby)
  P5   "cire trudon revolution"   DOES resolve (branded full-name alias, not guarded)
  P6   "cire trudon revolution perfume" DOES resolve (cire+trudon nearby)

  R1   Creed Aventus unaffected
  R2   Kilian Apple Brandy on the Rocks unaffected (different entity, longer alias)
  G1   All SIG-QA1-REPAIR phrases present in _AMBIGUOUS_PHRASE_GUARD
  G2   "revolution" present in _BLOCKED_SINGLE_WORD_ALIASES
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import (
    PerfumeResolver,
    _AMBIGUOUS_PHRASE_GUARD,
    _BLOCKED_SINGLE_WORD_ALIASES,
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


_TEST_ALIASES: Dict[str, Dict[str, Any]] = {
    # SIG-QA1-REPAIR ambiguous entities
    "pure luxury":                  _make_entity(6001, "Pure Luxury"),
    "on the rocks":                 _make_entity(6002, "On the Rocks"),
    "enjoy the day":                _make_entity(6003, "Enjoy the Day"),
    "orange blossom":               _make_entity(6004, "Orange Blossom"),
    "revolution":                   _make_entity(6005, "Cire Trudon Revolution Eau de Parfum"),
    "revolution perfume":           _make_entity(6005, "Cire Trudon Revolution Eau de Parfum"),
    "revolution eau de parfum":     _make_entity(6005, "Cire Trudon Revolution Eau de Parfum"),
    "cire trudon revolution":       _make_entity(6005, "Cire Trudon Revolution Eau de Parfum"),
    "cire trudon revolution eau de parfum": _make_entity(6005, "Cire Trudon Revolution Eau de Parfum"),
    # Brand context tokens
    "wolken":                       _make_entity(7001, "Wolken Parfums Brand"),
    "angela":                       _make_entity(7002, "Angela Flanders Brand"),
    "flanders":                     _make_entity(7002, "Angela Flanders Brand"),
    "cire":                         _make_entity(7003, "Cire Trudon Brand"),
    "trudon":                       _make_entity(7003, "Cire Trudon Brand"),
    # Legit perfumes for regression
    "creed aventus":                _make_entity(2001, "Creed Aventus"),
    "apple brandy on the rocks":    _make_entity(2002, "Apple Brandy on the Rocks"),
    "kilian":                       _make_entity(2002, "Apple Brandy on the Rocks"),
    # Multi-word branded alias for Wolken perfumes
    "wolken parfums pure luxury":   _make_entity(6001, "Pure Luxury"),
    "wolken parfums on the rocks":  _make_entity(6002, "On the Rocks"),
    "wolken parfums enjoy the day": _make_entity(6003, "Enjoy the Day"),
    "angela flanders orange blossom": _make_entity(6004, "Orange Blossom"),
}


def _resolver() -> PerfumeResolver:
    return _make_resolver_with_aliases(_TEST_ALIASES)


# ---------------------------------------------------------------------------
# N — Negative tests: phrases BLOCKED without brand proximity
# ---------------------------------------------------------------------------

class TestNegativeCasesSIGQA1:

    def test_N1_pure_luxury_blocked_as_adjective(self):
        """'pure luxury' as adjective phrase must NOT fire Pure Luxury entity."""
        r = _resolver()
        assert "Pure Luxury" not in _names(r.resolve_text("this smells like pure luxury"))

    def test_N1b_pure_luxury_blocked_in_note_description(self):
        """'pure luxury floral' as descriptor — blocked."""
        r = _resolver()
        assert "Pure Luxury" not in _names(r.resolve_text("pure luxury floral scent perfect for summer"))

    def test_N1c_pure_luxury_blocked_in_review_prose(self):
        """Review prose RS evidence — blocked."""
        r = _resolver()
        assert "Pure Luxury" not in _names(r.resolve_text("honestly feels like pure luxury at this price point"))

    def test_N2_on_the_rocks_blocked_without_wolken(self):
        """'on the rocks' idiom must NOT fire On the Rocks entity without Wolken context."""
        r = _resolver()
        assert "On the Rocks" not in _names(r.resolve_text("apple brandy on the rocks is incredible"))

    def test_N2b_on_the_rocks_blocked_as_kilian_substring(self):
        """Type F: Kilian Apple Brandy on the Rocks content must not credit Wolken."""
        r = _resolver()
        results = r.resolve_text("just got kilian apple brandy on the rocks edp and it is stunning")
        assert "On the Rocks" not in _names(results)

    def test_N2c_on_the_rocks_blocked_as_idiom(self):
        """Common idiom — blocked."""
        r = _resolver()
        assert "On the Rocks" not in _names(r.resolve_text("served on the rocks with a citrus twist"))

    def test_N3_enjoy_the_day_blocked_in_prose(self):
        """'enjoy the day' in ordinary prose must NOT fire Enjoy the Day entity."""
        r = _resolver()
        assert "Enjoy the Day" not in _names(r.resolve_text("hope you enjoy the day everyone"))

    def test_N3b_enjoy_the_day_blocked_wedding_context(self):
        """Wedding prose RS evidence — blocked."""
        r = _resolver()
        assert "Enjoy the Day" not in _names(r.resolve_text("most important thing is to enjoy the day with your loved ones"))

    def test_N4_orange_blossom_blocked_as_note(self):
        """'orange blossom' as a note must NOT fire Angela Flanders Orange Blossom entity."""
        r = _resolver()
        assert "Orange Blossom" not in _names(r.resolve_text("i love orange blossom in my fragrances"))

    def test_N4b_orange_blossom_blocked_in_le_labo_review(self):
        """Le Labo collection review mentioning orange blossom note — blocked."""
        r = _resolver()
        assert "Orange Blossom" not in _names(
            r.resolve_text("le labo classic collection the scent opens with orange blossom and sandalwood")
        )

    def test_N4c_orange_blossom_blocked_in_note_preference(self):
        """Note-preference post RS evidence — blocked."""
        r = _resolver()
        assert "Orange Blossom" not in _names(
            r.resolve_text("note collectors what do you look for besides your chosen note orange blossom is my favorite")
        )

    def test_N4d_orange_blossom_blocked_in_ingredient_description(self):
        """Ingredient description — blocked."""
        r = _resolver()
        assert "Orange Blossom" not in _names(r.resolve_text("contains orange blossom neroli and white musk"))

    def test_N5_revolution_single_word_blocked(self):
        """Bare 'revolution' single-token alias must NOT fire Cire Trudon Revolution."""
        r = _resolver()
        assert "Cire Trudon Revolution Eau de Parfum" not in _names(
            r.resolve_text("this is a fresh cucumber revolution in the niche fragrance world")
        )

    def test_N5b_revolution_blocked_in_rhetorical_youtube_title(self):
        """Exact RS evidence: Khamrah Waha review title with rhetorical Revolution? — blocked."""
        r = _resolver()
        assert "Cire Trudon Revolution Eau de Parfum" not in _names(
            r.resolve_text("the fresh cucumber revolution better than og khamrah and qahwa")
        )

    def test_N5c_revolution_blocked_in_alkemia_prose(self):
        """Alkemia RS evidence: 'revolution' in ordinary prose — blocked."""
        r = _resolver()
        assert "Cire Trudon Revolution Eau de Parfum" not in _names(
            r.resolve_text("alkemia curious oddities this is truly a revolution in indie perfumery")
        )

    def test_N5d_revolution_perfume_blocked_without_cire_trudon(self):
        """'revolution perfume' without cire+trudon context — blocked."""
        r = _resolver()
        assert "Cire Trudon Revolution Eau de Parfum" not in _names(
            r.resolve_text("this is a revolution perfume genre entirely new aesthetic direction")
        )

    def test_N5e_revolution_edp_blocked_without_cire_trudon(self):
        """'revolution eau de parfum' without cire+trudon context — blocked."""
        r = _resolver()
        assert "Cire Trudon Revolution Eau de Parfum" not in _names(
            r.resolve_text("tried this revolution eau de parfum at the counter smells interesting")
        )


# ---------------------------------------------------------------------------
# P — Positive tests: brand-qualified mentions STILL resolve
# ---------------------------------------------------------------------------

class TestPositiveCasesSIGQA1:

    def test_P1_pure_luxury_resolves_with_wolken(self):
        """Wolken brand token nearby → Pure Luxury resolves."""
        r = _resolver()
        assert "Pure Luxury" in _names(r.resolve_text("just bought wolken pure luxury and it is stunning"))

    def test_P2_on_the_rocks_resolves_with_wolken(self):
        """Wolken brand token nearby → On the Rocks resolves."""
        r = _resolver()
        assert "On the Rocks" in _names(r.resolve_text("wolken on the rocks is surprisingly good"))

    def test_P3_enjoy_the_day_resolves_with_wolken(self):
        """Wolken brand token nearby → Enjoy the Day resolves."""
        r = _resolver()
        assert "Enjoy the Day" in _names(r.resolve_text("wolken enjoy the day has a beautiful citrus opening"))

    def test_P4_orange_blossom_resolves_with_angela_flanders(self):
        """angela + flanders nearby → Orange Blossom resolves."""
        r = _resolver()
        assert "Orange Blossom" in _names(
            r.resolve_text("angela flanders orange blossom is a beautiful soliflore")
        )

    def test_P4b_orange_blossom_resolves_with_both_brand_tokens(self):
        """Both brand tokens in wider window → Orange Blossom resolves."""
        r = _resolver()
        assert "Orange Blossom" in _names(
            r.resolve_text("i picked up the angela flanders collection and orange blossom was the standout")
        )

    def test_P5_cire_trudon_revolution_full_alias_resolves(self):
        """Full branded alias 'cire trudon revolution' (not in guard) → resolves."""
        r = _resolver()
        assert "Cire Trudon Revolution Eau de Parfum" in _names(
            r.resolve_text("finally tried cire trudon revolution and the leather notes are incredible")
        )

    def test_P6_revolution_perfume_resolves_with_cire_trudon(self):
        """'revolution perfume' with cire+trudon context → resolves."""
        r = _resolver()
        assert "Cire Trudon Revolution Eau de Parfum" in _names(
            r.resolve_text("cire trudon revolution perfume is a masterpiece of leather and incense")
        )


# ---------------------------------------------------------------------------
# R — Regression tests: unrelated entities unaffected
# ---------------------------------------------------------------------------

class TestRegressionSIGQA1:

    def test_R1_creed_aventus_unaffected(self):
        """Creed Aventus still resolves correctly."""
        r = _resolver()
        assert "Creed Aventus" in _names(r.resolve_text("creed aventus is the king of office fragrances"))

    def test_R2_kilian_apple_brandy_on_the_rocks_resolves(self):
        """Kilian Apple Brandy on the Rocks (longer alias) resolves via its own alias."""
        r = _resolver()
        results = r.resolve_text("kilian apple brandy on the rocks is worth the price")
        # The full alias 'apple brandy on the rocks' resolves; On the Rocks (Wolken) does NOT
        assert "Apple Brandy on the Rocks" in _names(results)
        assert "On the Rocks" not in _names(results)

    def test_R3_resmab4_phrases_still_guarded(self):
        """RES-AMB4 guards remain intact after SIG-QA1-REPAIR additions."""
        assert "i will" in _AMBIGUOUS_PHRASE_GUARD
        assert "cedar wood" in _AMBIGUOUS_PHRASE_GUARD
        assert "jasmine rose" in _AMBIGUOUS_PHRASE_GUARD

    def test_R4_resmab1_phrases_still_guarded(self):
        """RES-AMB1/2/3 guards remain intact."""
        assert "i am" in _AMBIGUOUS_PHRASE_GUARD
        assert "orange blossom" in _AMBIGUOUS_PHRASE_GUARD  # also added here
        assert "very well" in _AMBIGUOUS_PHRASE_GUARD


# ---------------------------------------------------------------------------
# G — Guard structure tests
# ---------------------------------------------------------------------------

class TestGuardStructureSIGQA1:

    def test_G1_all_phrase_guards_present(self):
        """All SIG-QA1-REPAIR phrase guards are registered."""
        expected = {
            "pure luxury", "on the rocks", "enjoy the day",
            "orange blossom", "revolution perfume", "revolution eau de parfum",
        }
        for phrase in expected:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, f"Missing guard: {phrase!r}"

    def test_G2_revolution_in_blocked_single_word(self):
        """'revolution' is registered in _BLOCKED_SINGLE_WORD_ALIASES."""
        assert "revolution" in _BLOCKED_SINGLE_WORD_ALIASES

    def test_G3_pure_luxury_requires_wolken(self):
        """pure luxury guard requires 'wolken' brand token."""
        token_sets = _AMBIGUOUS_PHRASE_GUARD["pure luxury"]
        brand_tokens = set().union(*token_sets)
        assert "wolken" in brand_tokens

    def test_G4_on_the_rocks_requires_wolken(self):
        """on the rocks guard requires 'wolken' brand token."""
        token_sets = _AMBIGUOUS_PHRASE_GUARD["on the rocks"]
        brand_tokens = set().union(*token_sets)
        assert "wolken" in brand_tokens

    def test_G5_enjoy_the_day_requires_wolken(self):
        """enjoy the day guard requires 'wolken' brand token."""
        token_sets = _AMBIGUOUS_PHRASE_GUARD["enjoy the day"]
        brand_tokens = set().union(*token_sets)
        assert "wolken" in brand_tokens

    def test_G6_orange_blossom_requires_angela_and_flanders(self):
        """orange blossom guard requires both 'angela' and 'flanders'."""
        token_sets = _AMBIGUOUS_PHRASE_GUARD["orange blossom"]
        brand_tokens = set().union(*token_sets)
        assert "angela" in brand_tokens
        assert "flanders" in brand_tokens

    def test_G7_revolution_perfume_requires_cire_and_trudon(self):
        """revolution perfume guard requires 'cire' and 'trudon'."""
        token_sets = _AMBIGUOUS_PHRASE_GUARD["revolution perfume"]
        brand_tokens = set().union(*token_sets)
        assert "cire" in brand_tokens
        assert "trudon" in brand_tokens
