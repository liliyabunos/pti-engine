"""RES-AMB1 — Ambiguous Perfume Phrase Guard Unit Tests.

Tests:
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
    # Ambiguous — require brand proximity
    "i am":              _make_entity(1001, "I Am"),
    "i am juicy couture": _make_entity(1001, "I Am"),
    "right now":         _make_entity(1002, "Right Now"),
    "scent of":          _make_entity(1003, "Scent of"),
    "blue oud":          _make_entity(1004, "Blue Oud"),
    "peace love":        _make_entity(1005, "Peace, Love &"),
    # Knize Two — only alias is single-word "two" (blocked via _BLOCKED list)
    "two":               _make_entity(1006, "Knize Two Eau de Toilette"),
    "knize two":         _make_entity(1006, "Knize Two Eau de Toilette"),
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
