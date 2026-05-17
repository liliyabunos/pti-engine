"""RES-AMB1 / RES-AMB2 / RES-AMB3 — Ambiguous Perfume Phrase Guard Unit Tests.

RES-AMB1 Tests:
  N1   "two" blocked as single-word alias (Knize Two fix)
  N2   "i am obsessed with this" does NOT resolve to I Am / Juicy Couture
  N3   "right now this fragrance is trending" does NOT resolve to Right Now
  N4   "scent of the day post" does NOT resolve to Scent of Liu·Jo
  N5   "the blue oud accords are nice" does NOT resolve to Blue Oud / Ajwaa
  N6   "peace love and fragrances" does NOT resolve to Peace, Love & / Juicy Couture
  N7   "i am getting two samples" — both "i am" and "two" blocked simultaneously
  P1   "I Am Juicy Couture is beautiful" DOES resolve (brand proximity met)
  P2   "I Am by Juicy Couture review" DOES resolve (brand proximity met)
  P3   "Ajwaa Perfumes Blue Oud review" DOES resolve (brand proximity met)
  P4   "Blue Oud by Ajwaa is incredible" DOES resolve (brand proximity met)
  P5   "Right Now West Third Brand smells" DOES resolve (brand proximity met)
  P6   "Peace Love Juicy Couture floral" DOES resolve (brand proximity met)
  R1   "Black Orchid Tom Ford" still resolves normally (no regression)
  R2   "Creed Aventus review" still resolves normally (no regression)
  R3   "Armaf Club de Nuit Intense Man" still resolves normally (no regression)
  R4   "Dior Sauvage EDT" still resolves normally (no regression)
  G1   _AMBIGUOUS_PHRASE_GUARD keys are normalized (no capitals or punctuation)
  G2   _check_brand_proximity returns True when brand token is before phrase
  G3   _check_brand_proximity returns True when brand token is after phrase
  G4   _check_brand_proximity returns False when brand token is outside window
  G5   _check_brand_proximity returns False when no brand tokens present
  G6   _check_brand_proximity handles multiple brand_token_sets (OR logic)
  G7   "two" is present in _BLOCKED_SINGLE_WORD_ALIASES

RES-AMB2 Tests (expansion batch — 2026-05-16):
  A1   "so you" blocked without Alia Touch proximity
  A1b  "TRYING THESE 6 ARABIAN PERFUMES SO YOU DON'T HAVE TO" blocked
  A2   "so you" resolves when Alia Touch brand is nearby
  A3   "you are" blocked without Geparlys proximity
  A3b  "what are you wearing today" blocked
  A4   "you are" resolves when Geparlys brand is nearby
  A5   "en route" blocked without Botanicae proximity
  A5b  "my Davidoff en route collection" blocked (Davidoff ≠ Botanicae)
  A6   "en route" resolves when Botanicae brand is nearby
  A7   "fragrance of summer" blocked without M. Asam proximity
  A7b  "this will be the fragrance of summer 2026" blocked
  A8   "fragrance of summer" resolves when asam brand is nearby
  A9   "one only" (normalized form of "one & only") blocked without Swiss Arabian
  A9b  "by the one only parfumer" blocked (creator tagline)
  A10  "one and only" blocked without Swiss Arabian proximity
  A10b "the one and only parfumer" variant blocked
  A11  "one only" resolves when Swiss Arabian brand is nearby
  A11b "one and only" resolves when Swiss Arabian brand is nearby
  A12  "good vibes" blocked without Ricarda proximity
  A12b "australia fragrance talk good vibes jeremyfragrance" blocked
  A13  "good vibes" resolves when Ricarda brand is nearby
  A14  RES-AMB2 guard phrases all present in _AMBIGUOUS_PHRASE_GUARD
  A15  RES-AMB1 phrases unaffected by RES-AMB2 additions (regression)

RES-AMB3 Tests (expansion batch — 2026-05-17):
  B1   "very well" blocked without Berdoues proximity
  B1b  "works very well with oud notes" blocked
  B2   "very well" resolves when Berdoues brand is nearby
  B3   "so happy" blocked without Flormar proximity
  B3b  "i am so happy with this purchase" blocked
  B4   "so happy" resolves when Flormar brand is nearby
  B5   "too feminine" blocked without Aigner proximity
  B5b  "this scent is too feminine for me" blocked
  B6   "too feminine" resolves when Aigner brand is nearby
  B7   "true icon" blocked without Aigner proximity
  B7b  "baccarat rouge is a true icon of perfumery" blocked
  B8   "true icon" resolves when Aigner brand is nearby
  B9   "first class" blocked without Aigner proximity
  B9b  "creed aventus is first class all the way" blocked
  B10  "first class" resolves when Aigner brand is nearby
  B11  "so so" blocked unconditionally (in _BLOCKED_MULTI_TOKEN_PHRASES)
  B11b "it was so so disappointing" blocked (evaluative phrase)
  B12  _BLOCKED_MULTI_TOKEN_PHRASES includes "so so"
  B13  RES-AMB3 guard phrases all present in _AMBIGUOUS_PHRASE_GUARD
  B14  RES-AMB1 + RES-AMB2 phrases unaffected by RES-AMB3 (regression)
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import (
    PerfumeResolver,
    _AMBIGUOUS_PHRASE_GUARD,
    _BLOCKED_MULTI_TOKEN_PHRASES,
    _BLOCKED_SINGLE_WORD_ALIASES,
    _check_brand_proximity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolver_with_aliases(alias_map: Dict[str, Dict[str, Any]]) -> PerfumeResolver:
    """Return a PerfumeResolver whose store returns results from alias_map."""
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


# Core alias_map covering the 6 ambiguous entities + a few legit ones.
# Normalized forms used as keys (lowercase, stripped punctuation).
_TEST_ALIASES: Dict[str, Dict[str, Any]] = {
    # Ambiguous — require brand proximity (RES-AMB1)
    "i am":              _make_entity(1001, "I Am"),
    "i am juicy couture": _make_entity(1001, "I Am"),
    "right now":         _make_entity(1002, "Right Now"),
    "scent of":          _make_entity(1003, "Scent of"),
    "blue oud":          _make_entity(1004, "Blue Oud"),
    "peace love":        _make_entity(1005, "Peace, Love &"),
    # Knize Two — only alias is single-word "two" (blocked via _BLOCKED list)
    "two":               _make_entity(1006, "Knize Two Eau de Toilette"),
    "knize two":         _make_entity(1006, "Knize Two Eau de Toilette"),
    # Ambiguous — require brand proximity (RES-AMB2)
    "so you":            _make_entity(2010, "So You"),
    "you are":           _make_entity(2011, "You Are"),
    "en route":          _make_entity(2012, "En Route"),
    "fragrance of summer": _make_entity(2013, "Fragrance of Summer"),
    "one only":          _make_entity(2014, "One & Only"),
    "one and only":      _make_entity(2014, "One & Only"),
    "good vibes":        _make_entity(2015, "Good Vibes"),
    # Brand proximity triggers (RES-AMB2)
    "alia touch":        _make_entity(3010, "Alia Touch Brand"),
    "alia":              _make_entity(3010, "Alia Touch Brand"),
    "touch":             _make_entity(3010, "Alia Touch Brand"),
    "geparlys":          _make_entity(3011, "Geparlys Brand"),
    "botanicae":         _make_entity(3012, "Botanicae Brand"),
    "asam":              _make_entity(3013, "M. Asam Brand"),
    "m asam":            _make_entity(3013, "M. Asam Brand"),
    "swiss arabian":     _make_entity(3014, "Swiss Arabian Brand"),
    "swiss":             _make_entity(3014, "Swiss Arabian Brand"),
    "arabian":           _make_entity(3014, "Swiss Arabian Brand"),
    "ricarda":           _make_entity(3015, "Ricarda M. Brand"),
    # Ambiguous — require brand proximity (RES-AMB3)
    "very well":         _make_entity(3101, "Very Well"),
    "so happy":          _make_entity(3102, "So Happy"),
    "too feminine":      _make_entity(3103, "Too Feminine"),
    "true icon":         _make_entity(3104, "True Icon"),
    "first class":       _make_entity(3105, "First Class"),
    "so so":             _make_entity(3106, "So...? So...?"),
    # Brand proximity triggers (RES-AMB3)
    "berdoues":          _make_entity(4101, "Berdoues Brand"),
    "flormar":           _make_entity(4102, "Flormar Brand"),
    "aigner":            _make_entity(4103, "Aigner Brand"),
    # Legitimate well-specific aliases
    "black orchid":      _make_entity(2001, "Black Orchid"),
    "tom ford black orchid": _make_entity(2001, "Black Orchid"),
    "creed aventus":     _make_entity(2002, "Creed Aventus"),
    "armaf club de nuit intense man": _make_entity(2003, "Armaf Club de Nuit Intense Man"),
    "dior sauvage":      _make_entity(2004, "Dior Sauvage"),
    "sauvage":           _make_entity(2004, "Dior Sauvage"),
    "juicy couture":     _make_entity(1007, "Juicy Couture"),
    "west third brand":  _make_entity(1008, "West Third Brand"),
    "ajwaa perfumes":    _make_entity(1009, "Ajwaa Perfumes"),
    "ajwaa":             _make_entity(1009, "Ajwaa Perfumes"),
}


def _resolver() -> PerfumeResolver:
    return _make_resolver_with_aliases(_TEST_ALIASES)


def _names(results: List[Dict[str, Any]]) -> List[str]:
    return [r["canonical_name"] for r in results]


# ---------------------------------------------------------------------------
# N — Negative tests: ambiguous phrases BLOCKED without brand proximity
# ---------------------------------------------------------------------------

class TestNegativeCases:
    def test_N1_two_blocked_single_word(self):
        """'two' is in _BLOCKED_SINGLE_WORD_ALIASES → never resolves."""
        r = _resolver()
        results = r.resolve_text("I bought two fragrances today")
        assert "Knize Two Eau de Toilette" not in _names(results)

    def test_N1b_two_blocked_in_numerical_context(self):
        r = _resolver()
        results = r.resolve_text("these two scents are my favorite")
        assert "Knize Two Eau de Toilette" not in _names(results)

    def test_N2_i_am_blocked_without_brand(self):
        """'I am obsessed with this' must NOT fire I Am entity."""
        r = _resolver()
        results = r.resolve_text("i am obsessed with this new fragrance")
        assert "I Am" not in _names(results)

    def test_N2b_i_am_blocked_reddit_post_opener(self):
        r = _resolver()
        results = r.resolve_text("i am new to the hobby and looking for recommendations")
        assert "I Am" not in _names(results)

    def test_N3_right_now_blocked_without_brand(self):
        """'right now this is trending' must NOT fire Right Now entity."""
        r = _resolver()
        results = r.resolve_text("right now this is the most hyped fragrance")
        assert "Right Now" not in _names(results)

    def test_N4_scent_of_blocked_without_brand(self):
        """'scent of the day' must NOT fire Scent of entity."""
        r = _resolver()
        results = r.resolve_text("scent of the day post from my collection")
        assert "Scent of" not in _names(results)

    def test_N4b_scent_of_blocked_in_description(self):
        r = _resolver()
        results = r.resolve_text("the scent of fresh bergamot is amazing")
        assert "Scent of" not in _names(results)

    def test_N5_blue_oud_blocked_without_ajwaa(self):
        """'blue oud' without 'ajwaa' must NOT fire Ajwaa Blue Oud entity."""
        r = _resolver()
        results = r.resolve_text("the blue oud accords in this fragrance are stunning")
        assert "Blue Oud" not in _names(results)

    def test_N5b_blue_oud_blocked_for_other_brands(self):
        """Lattafa Opulent Blue Oud context — 'blue oud' must not fire Ajwaa entity."""
        r = _resolver()
        results = r.resolve_text("lattafa opulent blue oud is a great clone")
        assert "Blue Oud" not in _names(results)

    def test_N6_peace_love_blocked_without_brand(self):
        """'peace love' without Juicy Couture nearby must NOT fire entity."""
        r = _resolver()
        results = r.resolve_text("spreading peace love and good scents everywhere")
        assert "Peace, Love &" not in _names(results)

    def test_N7_both_blocked_simultaneously(self):
        """'i am getting two samples' — both 'i am' and 'two' blocked."""
        r = _resolver()
        results = r.resolve_text("i am getting two samples next week")
        assert "I Am" not in _names(results)
        assert "Knize Two Eau de Toilette" not in _names(results)


# ---------------------------------------------------------------------------
# P — Positive tests: ambiguous phrases ALLOWED with brand proximity
# ---------------------------------------------------------------------------

class TestPositiveCases:
    def test_P1_i_am_resolves_with_juicy_couture(self):
        """'I Am Juicy Couture is beautiful' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("I Am Juicy Couture is beautiful")
        assert "I Am" in _names(results)

    def test_P2_i_am_resolves_with_brand_after(self):
        """'I Am by Juicy Couture review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("i am by juicy couture review")
        assert "I Am" in _names(results)

    def test_P3_blue_oud_resolves_with_ajwaa_before(self):
        """'Ajwaa Perfumes Blue Oud review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("ajwaa perfumes blue oud review incredible longevity")
        assert "Blue Oud" in _names(results)

    def test_P4_blue_oud_resolves_with_ajwaa_after(self):
        """'Blue Oud by Ajwaa is incredible' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("blue oud by ajwaa is incredible")
        assert "Blue Oud" in _names(results)

    def test_P5_right_now_resolves_with_brand(self):
        """'Right Now West Third Brand' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("right now west third brand has amazing projection")
        assert "Right Now" in _names(results)

    def test_P6_peace_love_resolves_with_juicy_couture(self):
        """'Peace Love Juicy Couture floral' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("peace love juicy couture floral review")
        assert "Peace, Love &" in _names(results)

    def test_P6b_peace_love_resolves_with_couture_after(self):
        r = _resolver()
        results = r.resolve_text("peace love is by juicy couture and smells amazing")
        assert "Peace, Love &" in _names(results)


# ---------------------------------------------------------------------------
# R — Regression tests: legitimate specific aliases still resolve
# ---------------------------------------------------------------------------

class TestRegressionCases:
    def test_R1_black_orchid_unaffected(self):
        """Black Orchid / Tom Ford — not in guard, must resolve normally."""
        r = _resolver()
        results = r.resolve_text("Black Orchid Tom Ford is a masterpiece")
        assert "Black Orchid" in _names(results)

    def test_R2_creed_aventus_unaffected(self):
        r = _resolver()
        results = r.resolve_text("Creed Aventus is the king of fragrances")
        assert "Creed Aventus" in _names(results)

    def test_R3_armaf_cdnim_unaffected(self):
        r = _resolver()
        results = r.resolve_text("armaf club de nuit intense man review")
        assert "Armaf Club de Nuit Intense Man" in _names(results)

    def test_R4_dior_sauvage_unaffected(self):
        r = _resolver()
        results = r.resolve_text("Dior Sauvage EDT worth buying?")
        assert "Dior Sauvage" in _names(results)

    def test_R5_no_false_positives_in_review_text(self):
        """A generic fragrance review with 'scent of' and 'i am' — both blocked."""
        text = (
            "i am really enjoying this hobby. the scent of bergamot opens beautifully. "
            "right now i think this is my favorite, peace love and all that."
        )
        r = _resolver()
        results = r.resolve_text(text)
        assert "I Am" not in _names(results)
        assert "Scent of" not in _names(results)
        assert "Right Now" not in _names(results)
        assert "Peace, Love &" not in _names(results)


# ---------------------------------------------------------------------------
# G — Guard implementation unit tests
# ---------------------------------------------------------------------------

class TestGuardStructure:
    def test_G1_guard_keys_are_normalized(self):
        """All keys in _AMBIGUOUS_PHRASE_GUARD must be lowercase with no punctuation."""
        import re
        for key in _AMBIGUOUS_PHRASE_GUARD:
            assert key == key.lower(), f"Key not lowercase: {key!r}"
            assert re.search(r"[^\w\s]", key) is None, f"Key has punctuation: {key!r}"

    def test_G2_brand_proximity_true_when_brand_before(self):
        tokens = ["juicy", "couture", "i", "am", "is", "beautiful"]
        # phrase "i am" is at indices [2, 3], match_start=2, match_end=4
        result = _check_brand_proximity(
            tokens, match_start=2, match_end=4,
            brand_token_sets=[frozenset({"juicy", "couture"})],
        )
        assert result is True

    def test_G3_brand_proximity_true_when_brand_after(self):
        tokens = ["i", "am", "by", "juicy", "couture"]
        result = _check_brand_proximity(
            tokens, match_start=0, match_end=2,
            brand_token_sets=[frozenset({"juicy", "couture"})],
        )
        assert result is True

    def test_G4_brand_proximity_false_when_outside_window(self):
        # "juicy" is 15 tokens away from the match — outside window=10
        tokens = (
            ["i", "am"]
            + ["x"] * 13
            + ["juicy", "couture"]
        )
        result = _check_brand_proximity(
            tokens, match_start=0, match_end=2,
            brand_token_sets=[frozenset({"juicy", "couture"})],
            window=10,
        )
        assert result is False

    def test_G5_brand_proximity_false_when_no_brand_tokens(self):
        tokens = ["i", "am", "obsessed", "with", "this", "scent"]
        result = _check_brand_proximity(
            tokens, match_start=0, match_end=2,
            brand_token_sets=[frozenset({"juicy", "couture"})],
        )
        assert result is False

    def test_G6_brand_proximity_or_logic_across_sets(self):
        """Multiple brand_token_sets — any match is sufficient."""
        tokens = ["blue", "oud", "by", "ajwaa", "is", "great"]
        # Two sets: Ajwaa OR Juicy Couture — Ajwaa is present
        result = _check_brand_proximity(
            tokens, match_start=0, match_end=2,
            brand_token_sets=[
                frozenset({"juicy", "couture"}),
                frozenset({"ajwaa"}),
            ],
        )
        assert result is True

    def test_G7_two_in_blocked_single_word_aliases(self):
        assert "two" in _BLOCKED_SINGLE_WORD_ALIASES

    def test_G8_guard_seeds_present(self):
        expected_phrases = {"i am", "right now", "scent of", "blue oud", "peace love"}
        for phrase in expected_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, f"Missing guard for {phrase!r}"

    def test_G9_guard_brand_token_sets_are_frozensets(self):
        for phrase, sets in _AMBIGUOUS_PHRASE_GUARD.items():
            assert isinstance(sets, list), f"Value for {phrase!r} must be a list"
            for s in sets:
                assert isinstance(s, frozenset), f"Inner sets for {phrase!r} must be frozensets"


# ---------------------------------------------------------------------------
# A — RES-AMB2 Negative tests: ambiguous phrases BLOCKED without brand proximity
# ---------------------------------------------------------------------------

class TestNegativeCasesAMB2:
    def test_A1_so_you_blocked_without_alia_touch(self):
        """'so you' without Alia Touch context must NOT fire So You entity."""
        r = _resolver()
        results = r.resolve_text("so you think this fragrance is too expensive")
        assert "So You" not in _names(results)

    def test_A1b_so_you_blocked_in_youtube_title_phrase(self):
        """'TRYING THESE 6 ARABIAN PERFUMES SO YOU DON'T HAVE TO' — blocked."""
        r = _resolver()
        results = r.resolve_text("trying these 6 arabian perfumes so you dont have to")
        assert "So You" not in _names(results)

    def test_A3_you_are_blocked_without_geparlys(self):
        """'you are' without Geparlys context must NOT fire You Are entity."""
        r = _resolver()
        results = r.resolve_text("you are going to love this fragrance")
        assert "You Are" not in _names(results)

    def test_A3b_you_are_blocked_in_casual_context(self):
        """'what are you wearing today' — blocked."""
        r = _resolver()
        results = r.resolve_text("what fragrance are you wearing today")
        # "you are" won't even match here since "are you" is different order,
        # but we also verify a direct "you are" phrase is blocked
        results2 = r.resolve_text("you are wrong about this fragrance being weak")
        assert "You Are" not in _names(results2)

    def test_A5_en_route_blocked_without_botanicae(self):
        """'en route' without Botanicae context must NOT fire En Route entity."""
        r = _resolver()
        results = r.resolve_text("i am en route to the mall to buy a new fragrance")
        assert "En Route" not in _names(results)

    def test_A5b_en_route_blocked_for_other_brands(self):
        """'my Davidoff en route collection' — Davidoff ≠ Botanicae, still blocked."""
        r = _resolver()
        results = r.resolve_text("my davidoff en route to the store review")
        assert "En Route" not in _names(results)

    def test_A7_fragrance_of_summer_blocked_without_asam(self):
        """'fragrance of summer' without M. Asam context must NOT fire entity."""
        r = _resolver()
        results = r.resolve_text("this will be the fragrance of summer 2026")
        assert "Fragrance of Summer" not in _names(results)

    def test_A7b_fragrance_of_summer_blocked_in_generic_review(self):
        """'the fragrance of summer vibes' — generic phrase, blocked."""
        r = _resolver()
        results = r.resolve_text("i love the fragrance of summer vibes this gives")
        assert "Fragrance of Summer" not in _names(results)

    def test_A9_one_only_blocked_without_swiss_arabian(self):
        """'one only' (normalized 'one & only') without Swiss Arabian must NOT fire."""
        r = _resolver()
        # "one & only" normalizes to "one only" (& → space, collapsed)
        results = r.resolve_text("he is the one only parfumer i trust completely")
        assert "One & Only" not in _names(results)

    def test_A9b_one_only_blocked_in_creator_tagline(self):
        """'by the one only parfumer' — creator tagline, blocked."""
        r = _resolver()
        results = r.resolve_text("by the one only parfumer in the game")
        assert "One & Only" not in _names(results)

    def test_A10_one_and_only_blocked_without_swiss_arabian(self):
        """'one and only' without Swiss Arabian must NOT fire One & Only entity."""
        r = _resolver()
        results = r.resolve_text("creed aventus is the one and only king of fragrances")
        assert "One & Only" not in _names(results)

    def test_A10b_one_and_only_blocked_variant(self):
        """'the one and only parfumer' — blocked without brand."""
        r = _resolver()
        results = r.resolve_text("the one and only fragrance channel worth watching")
        assert "One & Only" not in _names(results)

    def test_A12_good_vibes_blocked_without_ricarda(self):
        """'good vibes' without Ricarda context must NOT fire Good Vibes entity."""
        r = _resolver()
        results = r.resolve_text("this fragrance gives nothing but good vibes all day")
        assert "Good Vibes" not in _names(results)

    def test_A12b_good_vibes_blocked_in_jeremy_fragrance_title(self):
        """'australia fragrance talk good vibes jeremyfragrance' — blocked."""
        r = _resolver()
        results = r.resolve_text(
            "australia fragrance talk good vibes jeremyfragrance"
        )
        assert "Good Vibes" not in _names(results)


# ---------------------------------------------------------------------------
# A — RES-AMB2 Positive tests: ambiguous phrases ALLOWED with brand proximity
# ---------------------------------------------------------------------------

class TestPositiveCasesAMB2:
    def test_A2_so_you_resolves_with_alia_touch(self):
        """'so you by alia touch review' MUST resolve when brand is nearby."""
        r = _resolver()
        results = r.resolve_text("so you by alia touch is an incredible oriental")
        assert "So You" in _names(results)

    def test_A4_you_are_resolves_with_geparlys(self):
        """'you are geparlys fragrance review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("you are by geparlys is a great budget fragrance")
        assert "You Are" in _names(results)

    def test_A6_en_route_resolves_with_botanicae(self):
        """'en route botanicae review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("en route by botanicae smells like a forest walk")
        assert "En Route" in _names(results)

    def test_A8_fragrance_of_summer_resolves_with_asam(self):
        """'fragrance of summer m asam review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("fragrance of summer by asam is a hidden gem")
        assert "Fragrance of Summer" in _names(results)

    def test_A11_one_only_resolves_with_swiss_arabian(self):
        """'one only swiss arabian' — normalized 'one & only', MUST resolve."""
        r = _resolver()
        # "Swiss Arabian One & Only" → normalizes: "swiss arabian one only"
        results = r.resolve_text("swiss arabian one only is a powerhouse oud")
        assert "One & Only" in _names(results)

    def test_A11b_one_and_only_resolves_with_swiss_arabian(self):
        """'one and only swiss arabian' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("one and only from swiss arabian incredible sillage")
        assert "One & Only" in _names(results)

    def test_A13_good_vibes_resolves_with_ricarda(self):
        """'good vibes ricarda review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("good vibes by ricarda m is a summer must have")
        assert "Good Vibes" in _names(results)


# ---------------------------------------------------------------------------
# A14–A15 — RES-AMB2 guard seed presence + AMB1 regression
# ---------------------------------------------------------------------------

class TestGuardStructureAMB2:
    def test_A14_amb2_phrases_present_in_guard(self):
        """All RES-AMB2 guard phrases must be present in _AMBIGUOUS_PHRASE_GUARD."""
        expected = {
            "so you", "you are", "en route",
            "fragrance of summer",
            "one only", "one and only",
            "good vibes",
        }
        for phrase in expected:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"RES-AMB2 guard phrase missing: {phrase!r}"
            )

    def test_A15_amb1_phrases_unaffected_by_amb2(self):
        """RES-AMB1 guard phrases must still be present after AMB2 additions."""
        amb1_phrases = {"i am", "right now", "scent of", "blue oud", "peace love"}
        for phrase in amb1_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"RES-AMB1 guard phrase was removed: {phrase!r}"
            )

    def test_A15b_amb1_behavior_unchanged_i_am(self):
        """Confirm RES-AMB1 'i am' still blocked after AMB2 additions."""
        r = _resolver()
        results = r.resolve_text("i am really impressed by this flanker")
        assert "I Am" not in _names(results)

    def test_A15c_amb1_behavior_unchanged_scent_of(self):
        """Confirm RES-AMB1 'scent of' still blocked after AMB2 additions."""
        r = _resolver()
        results = r.resolve_text("the scent of oud is incredible")
        assert "Scent of" not in _names(results)

    def test_A15d_amb1_behavior_unchanged_peace_love(self):
        """Confirm RES-AMB1 'peace love' still blocked after AMB2 additions."""
        r = _resolver()
        results = r.resolve_text("spreading peace love and good vibes everywhere")
        assert "Peace, Love &" not in _names(results)
        assert "Good Vibes" not in _names(results)


# ---------------------------------------------------------------------------
# B — RES-AMB3 Negative tests: phrases BLOCKED without brand proximity
# ---------------------------------------------------------------------------

class TestNegativeCasesAMB3:
    def test_B1_very_well_blocked_without_berdoues(self):
        """'very well' without Berdoues context must NOT fire Very Well entity."""
        r = _resolver()
        results = r.resolve_text("this longevity works very well on my skin type")
        assert "Very Well" not in _names(results)

    def test_B1b_very_well_blocked_in_review_phrase(self):
        """'very well' as common review phrase — blocked."""
        r = _resolver()
        results = r.resolve_text("the sillage projects very well throughout the day")
        assert "Very Well" not in _names(results)

    def test_B3_so_happy_blocked_without_flormar(self):
        """'so happy' without Flormar context must NOT fire So Happy entity."""
        r = _resolver()
        results = r.resolve_text("i am so happy with this fragrance purchase")
        assert "So Happy" not in _names(results)

    def test_B3b_so_happy_blocked_in_conversational_context(self):
        """'so happy i found this blind buy' — blocked."""
        r = _resolver()
        results = r.resolve_text("so happy i found this blind buy at the mall")
        assert "So Happy" not in _names(results)

    def test_B5_too_feminine_blocked_without_aigner(self):
        """'too feminine' without Aigner context must NOT fire Too Feminine entity."""
        r = _resolver()
        results = r.resolve_text("this scent is too feminine for everyday male wear")
        assert "Too Feminine" not in _names(results)

    def test_B5b_too_feminine_blocked_in_opinion_phrase(self):
        """'found it too feminine for my taste' — blocked."""
        r = _resolver()
        results = r.resolve_text("i found it too feminine for my taste honestly")
        assert "Too Feminine" not in _names(results)

    def test_B7_true_icon_blocked_without_aigner(self):
        """'true icon' without Aigner context must NOT fire True Icon entity."""
        r = _resolver()
        results = r.resolve_text("baccarat rouge 540 is a true icon of modern perfumery")
        assert "True Icon" not in _names(results)

    def test_B7b_true_icon_blocked_in_superlative_context(self):
        """'creed aventus remains a true icon' — blocked."""
        r = _resolver()
        results = r.resolve_text("creed aventus remains a true icon of masculine fragrance")
        assert "True Icon" not in _names(results)

    def test_B9_first_class_blocked_without_aigner(self):
        """'first class' without Aigner context must NOT fire First Class entity."""
        r = _resolver()
        results = r.resolve_text("creed aventus is simply first class all the way")
        assert "First Class" not in _names(results)

    def test_B9b_first_class_blocked_in_quality_descriptor(self):
        """'this is first class longevity' — blocked."""
        r = _resolver()
        results = r.resolve_text("the performance of this fragrance is first class")
        assert "First Class" not in _names(results)

    def test_B11_so_so_blocked_unconditionally(self):
        """'so so' (normalized So...? So...?) must NEVER fire — in _BLOCKED_MULTI_TOKEN_PHRASES."""
        r = _resolver()
        results = r.resolve_text("the longevity was so so disappointing on my skin")
        assert "So...? So...?" not in _names(results)

    def test_B11b_so_so_blocked_even_with_brand_context(self):
        """'so so' is unconditionally blocked even if some brand token appeared nearby."""
        r = _resolver()
        # Even with aigner nearby, "so so" should remain blocked
        results = r.resolve_text("this aigner flanker is so so compared to the original")
        assert "So...? So...?" not in _names(results)


# ---------------------------------------------------------------------------
# B — RES-AMB3 Positive tests: phrases ALLOWED with brand proximity
# ---------------------------------------------------------------------------

class TestPositiveCasesAMB3:
    def test_B2_very_well_resolves_with_berdoues(self):
        """'very well berdoues review' MUST resolve when brand is nearby."""
        r = _resolver()
        results = r.resolve_text("very well by berdoues is a hidden gem oriental")
        assert "Very Well" in _names(results)

    def test_B4_so_happy_resolves_with_flormar(self):
        """'so happy flormar review' MUST resolve when brand is nearby."""
        r = _resolver()
        results = r.resolve_text("so happy by flormar is surprisingly well blended")
        assert "So Happy" in _names(results)

    def test_B6_too_feminine_resolves_with_aigner(self):
        """'too feminine aigner review' MUST resolve when brand is nearby."""
        r = _resolver()
        results = r.resolve_text("aigner too feminine is a classic floral from the 90s")
        assert "Too Feminine" in _names(results)

    def test_B8_true_icon_resolves_with_aigner(self):
        """'true icon aigner review' MUST resolve when brand is nearby."""
        r = _resolver()
        results = r.resolve_text("aigner true icon smells like a timeless fougere")
        assert "True Icon" in _names(results)

    def test_B10_first_class_resolves_with_aigner(self):
        """'first class aigner review' MUST resolve when brand is nearby."""
        r = _resolver()
        results = r.resolve_text("aigner first class is the best budget option")
        assert "First Class" in _names(results)


# ---------------------------------------------------------------------------
# B12–B14 — RES-AMB3 structure checks + regression
# ---------------------------------------------------------------------------

class TestGuardStructureAMB3:
    def test_B12_blocked_multi_token_phrases_has_so_so(self):
        """'so so' must be in _BLOCKED_MULTI_TOKEN_PHRASES."""
        assert "so so" in _BLOCKED_MULTI_TOKEN_PHRASES, (
            "'so so' (normalized So...? So...?) missing from _BLOCKED_MULTI_TOKEN_PHRASES"
        )

    def test_B13_amb3_phrases_present_in_guard(self):
        """All RES-AMB3 guard phrases must be present in _AMBIGUOUS_PHRASE_GUARD."""
        expected = {
            "very well", "so happy", "too feminine", "true icon", "first class",
        }
        for phrase in expected:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"RES-AMB3 guard phrase missing: {phrase!r}"
            )

    def test_B14_amb1_amb2_phrases_unaffected_by_amb3(self):
        """RES-AMB1 + RES-AMB2 guard phrases must still be present after AMB3."""
        prior_phrases = {
            # RES-AMB1
            "i am", "right now", "scent of", "blue oud", "peace love",
            # RES-AMB2
            "so you", "you are", "en route", "fragrance of summer",
            "one only", "one and only", "good vibes",
        }
        for phrase in prior_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"Prior guard phrase was removed: {phrase!r}"
            )

    def test_B14b_amb1_behavior_unchanged_i_am(self):
        """RES-AMB1 'i am' still blocked after AMB3 additions."""
        r = _resolver()
        results = r.resolve_text("i am really happy with this flanker")
        assert "I Am" not in _names(results)

    def test_B14c_amb2_behavior_unchanged_good_vibes(self):
        """RES-AMB2 'good vibes' still blocked after AMB3 additions."""
        r = _resolver()
        results = r.resolve_text("this fragrance gives nothing but good vibes all day")
        assert "Good Vibes" not in _names(results)
