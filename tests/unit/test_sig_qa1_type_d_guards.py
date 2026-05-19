"""SIG-QA1 Type D Guard Tests — Feel Good / Come Together / Bride To Be / Day to Day

All 4 entities confirmed false-positive via full RS inspection (2026-05-19).
RS evidence brand context rate: 0% across all rows for every entity.

Guard structure: each phrase requires its brand token in ±10-token proximity
before resolving.

Test suites:
  N1   "feel good" BLOCKED without "esprit" nearby
  N2   "come together" BLOCKED without "vintner" nearby
  N3   "bride to be" BLOCKED without "primark" nearby
  N4   "day to day" BLOCKED without "primark" nearby
  P1   "feel good" RESOLVES with "esprit" nearby
  P2   "come together" RESOLVES with "vintner" nearby
  P3   "bride to be" RESOLVES with "primark" nearby
  P4   "day to day" RESOLVES with "primark" nearby
  R1   Creed Aventus unaffected
  R2   Jasmine & Rose (Primark) guard still active (RES-AMB4 regression)
  R3   Bride To Be and Day to Day guards coexist with Jasmine & Rose guard
  G1   All 4 new phrases present in _AMBIGUOUS_PHRASE_GUARD
  G2   Brand tokens are correct for each phrase
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


# Test alias map covering all 4 Type D entities + brand tokens + regressions
_TEST_ALIASES: Dict[str, Dict[str, Any]] = {
    # SIG-QA1 Type D ambiguous entities
    "feel good":         _make_entity(6001, "Feel Good"),
    "come together":     _make_entity(6002, "Come Together"),
    "bride to be":       _make_entity(6003, "Bride To Be"),
    "day to day":        _make_entity(6004, "Day to Day"),
    # Brand context tokens (so proximity resolves correctly in positive tests)
    "esprit":            _make_entity(7001, "Esprit Brand"),
    "vintner":           _make_entity(7002, "Vintner Brand"),
    "primark":           _make_entity(7003, "Primark Brand"),
    # RES-AMB4 regression — Jasmine & Rose (Primark) — different guard
    "jasmine rose":      _make_entity(4007, "Jasmine & Rose"),
    "jasmine and rose":  _make_entity(4007, "Jasmine & Rose"),
    # Legit perfumes for regression tests
    "creed aventus":     _make_entity(2001, "Creed Aventus"),
    "dior sauvage":      _make_entity(2002, "Dior Sauvage"),
}


def _resolver() -> PerfumeResolver:
    return _make_resolver_with_aliases(_TEST_ALIASES)


# ---------------------------------------------------------------------------
# N — Negative tests: phrases blocked without brand proximity
# ---------------------------------------------------------------------------

class TestNegativeCasesTypD:

    def test_N1a_feel_good_blocked_without_esprit(self):
        """'feel good' in generic fragrance prose — no Esprit context."""
        r = _resolver()
        results = r.resolve_text("good colognes that last all day but just smell feel good overall")
        assert "Feel Good" not in _names(results)

    def test_N1b_feel_good_blocked_in_fashion_video_title(self):
        """'feel good' used in lifestyle/fashion video title — no Esprit."""
        r = _resolver()
        results = r.resolve_text("spending money to feel good fashion and coach unboxing")
        assert "Feel Good" not in _names(results)

    def test_N1c_feel_good_blocked_in_emotional_support_post(self):
        """Reddit 'emotional support fragrances' post — 'feel good' as emotion."""
        r = _resolver()
        results = r.resolve_text("wearing fragrances that make me feel good is self care")
        assert "Feel Good" not in _names(results)

    def test_N2a_come_together_blocked_without_vintner(self):
        """'come together' in ingredient description — no Vintner's Reserve context."""
        r = _resolver()
        results = r.resolve_text(
            "lavender vanilla and orange blossom come together to create a beautiful floral scent"
        )
        assert "Come Together" not in _names(results)

    def test_N2b_come_together_blocked_in_wedding_context(self):
        """Reddit wedding context — 'come together' as generic phrase."""
        r = _resolver()
        results = r.resolve_text(
            "how did you feel when all the guests come together at the reception"
        )
        assert "Come Together" not in _names(results)

    def test_N2c_come_together_blocked_in_glp1_post(self):
        """Reddit GLP-1 and fragrance addiction post."""
        r = _resolver()
        results = r.resolve_text("all these hobby communities come together for people like us")
        assert "Come Together" not in _names(results)

    def test_N3a_bride_to_be_blocked_without_primark(self):
        """'bride to be' as wedding noun — no Primark context."""
        r = _resolver()
        results = r.resolve_text(
            "looking for a fragrance gift for the bride to be at the bachelorette party"
        )
        assert "Bride To Be" not in _names(results)

    def test_N3b_bride_to_be_blocked_in_gift_guide_video(self):
        """YouTube gift guide — 'bride to be' as recipient descriptor."""
        r = _resolver()
        results = r.resolve_text(
            "3 best perfumes for your fiance the bride to be in your life"
        )
        assert "Bride To Be" not in _names(results)

    def test_N3c_bride_to_be_blocked_in_wedding_planning(self):
        """Reddit wedding planning — 'bride-to-be' as social role."""
        r = _resolver()
        results = r.resolve_text("the bride to be asked for a specific fragrance theme")
        assert "Bride To Be" not in _names(results)

    def test_N4a_day_to_day_blocked_without_primark(self):
        """'day to day' as temporal/routine descriptor — no Primark context."""
        r = _resolver()
        results = r.resolve_text("what is your day to day go to fragrance for the office")
        assert "Day to Day" not in _names(results)

    def test_N4b_day_to_day_blocked_in_career_post(self):
        """Reddit career post — 'day to day' as routine descriptor."""
        r = _resolver()
        results = r.resolve_text(
            "starting as a marketing coordinator and my day to day involves fragrance sourcing"
        )
        assert "Day to Day" not in _names(results)

    def test_N4c_day_to_day_blocked_in_collection_discussion(self):
        """Fragrance collection discussion — 'day to day' as casual phrase."""
        r = _resolver()
        results = r.resolve_text("my simple day to day loyal selection fits the budget")
        assert "Day to Day" not in _names(results)


# ---------------------------------------------------------------------------
# P — Positive tests: phrases RESOLVE when brand token is present
# ---------------------------------------------------------------------------

class TestPositiveCasesTypeD:

    def test_P1_feel_good_resolves_with_esprit_nearby(self):
        """'feel good' with 'esprit' in proximity resolves correctly."""
        r = _resolver()
        results = r.resolve_text("esprit feel good is a classic 90s scent")
        assert "Feel Good" in _names(results)

    def test_P2_come_together_resolves_with_vintner_nearby(self):
        """'come together' with 'vintner' in proximity resolves correctly."""
        r = _resolver()
        results = r.resolve_text("vintner reserve come together smells of wine and berries")
        assert "Come Together" in _names(results)

    def test_P3_bride_to_be_resolves_with_primark_nearby(self):
        """'bride to be' with 'primark' in proximity resolves correctly."""
        r = _resolver()
        results = r.resolve_text("primark bride to be is a surprisingly nice floral")
        assert "Bride To Be" in _names(results)

    def test_P4_day_to_day_resolves_with_primark_nearby(self):
        """'day to day' with 'primark' in proximity resolves correctly."""
        r = _resolver()
        results = r.resolve_text("primark day to day smells clean and fresh for the price")
        assert "Day to Day" in _names(results)


# ---------------------------------------------------------------------------
# R — Regression tests
# ---------------------------------------------------------------------------

class TestRegressionTypeD:

    def test_R1_creed_aventus_unaffected(self):
        """Creed Aventus resolves normally."""
        r = _resolver()
        results = r.resolve_text("creed aventus is the best fragrance ever made")
        assert "Creed Aventus" in _names(results)

    def test_R2_jasmine_rose_guard_still_active(self):
        """Jasmine & Rose (Primark) guard from RES-AMB4 remains active without Primark."""
        r = _resolver()
        results = r.resolve_text("jasmine and rose notes combine beautifully in this perfume")
        assert "Jasmine & Rose" not in _names(results)

    def test_R3_jasmine_rose_resolves_with_primark(self):
        """Jasmine & Rose (Primark) still resolves when Primark is present."""
        r = _resolver()
        results = r.resolve_text("primark jasmine and rose is great value for the price")
        assert "Jasmine & Rose" in _names(results)

    def test_R4_day_to_day_and_bride_to_be_independent_guards(self):
        """Day to Day and Bride To Be use the same brand token but independent guards."""
        r = _resolver()
        # Both should be blocked without primark
        results = r.resolve_text("a day to day fragrance for the bride to be in my life")
        assert "Day to Day" not in _names(results)
        assert "Bride To Be" not in _names(results)

    def test_R5_dior_sauvage_unaffected(self):
        """Dior Sauvage resolves normally."""
        r = _resolver()
        results = r.resolve_text("dior sauvage is a great designer fragrance")
        assert "Dior Sauvage" in _names(results)


# ---------------------------------------------------------------------------
# G — Guard structure tests
# ---------------------------------------------------------------------------

class TestGuardStructureTypeD:

    def test_G1_all_four_phrases_in_guard(self):
        """All 4 Type D phrases are registered in _AMBIGUOUS_PHRASE_GUARD."""
        required = {"feel good", "come together", "bride to be", "day to day"}
        missing = required - set(_AMBIGUOUS_PHRASE_GUARD.keys())
        assert not missing, f"Missing guard phrases: {missing}"

    def test_G2_feel_good_requires_esprit(self):
        """feel good guard requires 'esprit' token."""
        guard = _AMBIGUOUS_PHRASE_GUARD["feel good"]
        brand_tokens = set().union(*guard)
        assert "esprit" in brand_tokens

    def test_G3_come_together_requires_vintner(self):
        """come together guard requires 'vintner' token."""
        guard = _AMBIGUOUS_PHRASE_GUARD["come together"]
        brand_tokens = set().union(*guard)
        assert "vintner" in brand_tokens

    def test_G4_bride_to_be_requires_primark(self):
        """bride to be guard requires 'primark' token."""
        guard = _AMBIGUOUS_PHRASE_GUARD["bride to be"]
        brand_tokens = set().union(*guard)
        assert "primark" in brand_tokens

    def test_G5_day_to_day_requires_primark(self):
        """day to day guard requires 'primark' token."""
        guard = _AMBIGUOUS_PHRASE_GUARD["day to day"]
        brand_tokens = set().union(*guard)
        assert "primark" in brand_tokens

    def test_G6_guard_is_list_of_frozensets(self):
        """Each guard entry is a list of frozensets (allows OR-of-AND logic)."""
        for phrase in ("feel good", "come together", "bride to be", "day to day"):
            entry = _AMBIGUOUS_PHRASE_GUARD[phrase]
            assert isinstance(entry, list), f"{phrase}: expected list"
            for token_set in entry:
                assert isinstance(token_set, frozenset), f"{phrase}: expected frozenset"
