"""RES-AMB4 — Audit-Driven Ambiguous Phrase Guard Expansion Tests (2026-05-17).

RES-AMB-FIVE (2026-05-19): Bruno Fazzolari Five bare alias "five" added to
_BLOCKED_SINGLE_WORD_ALIASES. Numeric single-token alias collision confirmed via
26 RS rows: "my stepfather came in when I was five years old", "Five summer
colognes under 50$!", "FIVE DOLLARS at 5 below". Tests: F1-F4.

Entities guarded (all confirmed false-positive via production RS inspection):
  C1   "i will"          → I Will (Femascu) — future-tense construction; 140 false mentions
  C1b  RS evidence: "In this video, I will be reviewing..."
  C2   "very pretty"     → Very Pretty (Michael Kors) — descriptor; 0% MK brand hit in RS
  C2b  RS evidence: "very pretty and feminine bottle design review"
  C3   "so sexy"         → So Sexy! (Fiorucci) — exclamation; 0% Fiorucci brand hit
  C3b  RS evidence: "this is so sexy and masculine at the same time"
  C4   "day one"         → Day One (Smell Bent) — temporal phrase; wedding/fragrance posts
  C4b  RS evidence: "day one of wearing my new blind buy haul"
  C5   "best man"        → Best Man (Helena Rubinstein) — wedding speech + fragrance phrase
  C5b  RS evidence: Jeremy Fragrance "best man fragrance" + Reddit wedding speech context
  C6   "you you"         → You & You (Puig) — normalize_text("You & You"); conversational
  C6b  "you and you"     alias also blocked
  C6c  RS evidence: Reddit conversational phrase + wedding post artifact
  C7   "jasmine rose"    → Jasmine & Rose (Primark) — note/ingredient description
  C7b  "jasmine and rose" alias also blocked
  C7c  RS evidence: Heretic Rhubarb review — "jasmine and rose notes combine"
  C8   "cedar wood"      → Cedar Wood (Monotheme) — note name; 0% Monotheme brand hit
  C8b  RS evidence: Heretic Rhubarb review — "cedar wood" as a note
  P1   "i will femascu"  DOES resolve (brand nearby)
  P2   "michael kors very pretty" DOES resolve (both brand tokens nearby)
  P3   "fiorucci so sexy" DOES resolve (brand nearby)
  P4   "day one smell bent" DOES resolve (both tokens nearby)
  P5   "helena rubinstein best man" DOES resolve (both brand tokens nearby)
  P6   "you you puig" DOES resolve (brand nearby)
  P7   "jasmine rose primark" DOES resolve (brand nearby)
  P8   "cedar wood monotheme" DOES resolve (brand nearby)
  R1   Creed Aventus unaffected by RES-AMB4
  R2   Dior Sauvage unaffected by RES-AMB4
  R3   RES-AMB1/2/3 phrases all still present after AMB4 additions
  G1   All RES-AMB4 guard phrases present in _AMBIGUOUS_PHRASE_GUARD
  G2   Brand token requirement: both tokens required for 2-token brands
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


# Aliases covering all 8 RES-AMB4 entities + legit ones for regression
_TEST_ALIASES: Dict[str, Dict[str, Any]] = {
    # RES-AMB4 ambiguous entities
    "i will":             _make_entity(4001, "I Will"),
    "very pretty":        _make_entity(4002, "Very Pretty"),
    "so sexy":            _make_entity(4003, "So Sexy!"),
    "day one":            _make_entity(4004, "Day One"),
    "best man":           _make_entity(4005, "Best Man"),
    "you you":            _make_entity(4006, "You & You"),
    "you and you":        _make_entity(4006, "You & You"),
    "jasmine rose":       _make_entity(4007, "Jasmine & Rose"),
    "jasmine and rose":   _make_entity(4007, "Jasmine & Rose"),
    "cedar wood":         _make_entity(4008, "Cedar Wood"),
    # Brand context aliases (so proximity check resolves correctly)
    "femascu":            _make_entity(5001, "Femascu Brand"),
    "michael":            _make_entity(5002, "Michael Kors Brand"),
    "kors":               _make_entity(5002, "Michael Kors Brand"),
    "fiorucci":           _make_entity(5003, "Fiorucci Brand"),
    "smell":              _make_entity(5004, "Smell Bent Brand"),
    "bent":               _make_entity(5004, "Smell Bent Brand"),
    "helena":             _make_entity(5005, "Helena Rubinstein Brand"),
    "rubinstein":         _make_entity(5005, "Helena Rubinstein Brand"),
    "puig":               _make_entity(5006, "Puig Brand"),
    "primark":            _make_entity(5007, "Primark Brand"),
    "monotheme":          _make_entity(5008, "Monotheme Brand"),
    # Legitimate perfumes for regression
    "creed aventus":      _make_entity(2001, "Creed Aventus"),
    "dior sauvage":       _make_entity(2002, "Dior Sauvage"),
    "armaf club de nuit intense man": _make_entity(2003, "Armaf Club de Nuit Intense Man"),
    # RES-AMB-FIVE: bare alias + branded alias
    "five":                    _make_entity(4009, "Bruno Fazzolari Five"),
    "bruno fazzolari five":    _make_entity(4009, "Bruno Fazzolari Five"),
    "bruno fazzolari":         _make_entity(4009, "Bruno Fazzolari Five"),
    # Unrelated perfumes that contain guard words but should still resolve
    "i will" : _make_entity(4001, "I Will"),  # Must be blocked without femascu
}


def _resolver() -> PerfumeResolver:
    return _make_resolver_with_aliases(_TEST_ALIASES)


# ---------------------------------------------------------------------------
# C — Negative tests: phrases BLOCKED without brand proximity
# ---------------------------------------------------------------------------

class TestNegativeCasesAMB4:

    def test_C1_i_will_blocked_without_femascu(self):
        """'i will' without Femascu context must NOT fire I Will entity."""
        r = _resolver()
        results = r.resolve_text("in this video i will be reviewing 5 new fragrances")
        assert "I Will" not in _names(results)

    def test_C1b_i_will_blocked_in_typical_youtube_intro(self):
        """Typical YouTube reviewer intro — blocked."""
        r = _resolver()
        results = r.resolve_text("i will show you my top 10 fragrances of 2026")
        assert "I Will" not in _names(results)

    def test_C1c_i_will_blocked_in_future_tense_sentence(self):
        """Future-tense construction from RS evidence — blocked."""
        r = _resolver()
        results = r.resolve_text("today i will talk about blind buying niche fragrances")
        assert "I Will" not in _names(results)

    def test_C2_very_pretty_blocked_without_michael_kors(self):
        """'very pretty' without Michael Kors context must NOT fire Very Pretty entity."""
        r = _resolver()
        results = r.resolve_text("the bottle is very pretty and the scent is feminine")
        assert "Very Pretty" not in _names(results)

    def test_C2b_very_pretty_blocked_as_descriptor(self):
        """Descriptor usage from RS evidence — blocked."""
        r = _resolver()
        results = r.resolve_text("very pretty floral opening with a musky base")
        assert "Very Pretty" not in _names(results)

    def test_C2c_very_pretty_blocked_wrong_brand(self):
        """'very pretty' with Chanel in text (not Michael Kors) — still blocked."""
        r = _resolver()
        results = r.resolve_text("chanel no 5 is very pretty and feminine")
        assert "Very Pretty" not in _names(results)

    def test_C3_so_sexy_blocked_without_fiorucci(self):
        """'so sexy' without Fiorucci context must NOT fire So Sexy! entity."""
        r = _resolver()
        results = r.resolve_text("this fragrance is so sexy and masculine")
        assert "So Sexy!" not in _names(results)

    def test_C3b_so_sexy_blocked_in_youtube_title(self):
        """YouTube title exclamation — blocked."""
        r = _resolver()
        results = r.resolve_text("dior sauvage is so sexy for date night trust me")
        assert "So Sexy!" not in _names(results)

    def test_C4_day_one_blocked_without_smell_bent(self):
        """'day one' without Smell Bent context must NOT fire Day One entity."""
        r = _resolver()
        results = r.resolve_text("day one of wearing my new blind buy haul")
        assert "Day One" not in _names(results)

    def test_C4b_day_one_blocked_in_temporal_context(self):
        """Temporal phrase from RS evidence — blocked."""
        r = _resolver()
        results = r.resolve_text("this is my day one review after first application")
        assert "Day One" not in _names(results)

    def test_C4c_day_one_blocked_in_wedding_reddit(self):
        """Wedding planning Reddit context — blocked."""
        r = _resolver()
        results = r.resolve_text("looking for a fragrance for my wedding day one recommendation")
        assert "Day One" not in _names(results)

    def test_C5_best_man_blocked_without_helena_rubinstein(self):
        """'best man' without Helena Rubinstein context must NOT fire Best Man entity."""
        r = _resolver()
        results = r.resolve_text("what fragrance should the best man wear at a wedding")
        assert "Best Man" not in _names(results)

    def test_C5b_best_man_blocked_in_fragrance_phrase(self):
        """Jeremy Fragrance-style phrase from RS evidence — blocked."""
        r = _resolver()
        results = r.resolve_text("creed aventus is the best man fragrance ever made")
        assert "Best Man" not in _names(results)

    def test_C5c_best_man_blocked_in_wedding_speech_context(self):
        """Wedding speech Reddit context — blocked."""
        r = _resolver()
        results = r.resolve_text("i am the best man at my brothers wedding next month")
        assert "Best Man" not in _names(results)

    def test_C6_you_you_blocked_without_puig(self):
        """'you you' (normalize_text 'You & You') without Puig — blocked."""
        r = _resolver()
        # "You & You" normalizes to "you you" (& → space)
        results = r.resolve_text("i wore you you styling fragrance yesterday")  # no Puig
        assert "You & You" not in _names(results)

    def test_C6b_you_and_you_blocked_without_puig(self):
        """'you and you' alias also blocked without Puig."""
        r = _resolver()
        results = r.resolve_text("between you and you this fragrance is incredible")
        assert "You & You" not in _names(results)

    def test_C6c_you_you_blocked_in_reddit_conversation(self):
        """Conversational Reddit phrase from RS evidence — blocked."""
        r = _resolver()
        results = r.resolve_text("same fragrance works for you you said it smells fresh")
        assert "You & You" not in _names(results)

    def test_C7_jasmine_rose_blocked_without_primark(self):
        """'jasmine rose' (normalize_text 'Jasmine & Rose') without Primark — blocked."""
        r = _resolver()
        results = r.resolve_text("the jasmine rose and musk accord is beautiful here")
        assert "Jasmine & Rose" not in _names(results)

    def test_C7b_jasmine_and_rose_blocked_without_primark(self):
        """'jasmine and rose' alias also blocked without Primark."""
        r = _resolver()
        results = r.resolve_text("jasmine and rose notes combine in the heart of this scent")
        assert "Jasmine & Rose" not in _names(results)

    def test_C7c_jasmine_rose_blocked_as_note_description(self):
        """Note/ingredient description from RS (Heretic Rhubarb review) — blocked."""
        r = _resolver()
        results = r.resolve_text("heretic rhubarb has jasmine rose and pepper in the base")
        assert "Jasmine & Rose" not in _names(results)

    def test_C8_cedar_wood_blocked_without_monotheme(self):
        """'cedar wood' without Monotheme context must NOT fire Cedar Wood entity."""
        r = _resolver()
        results = r.resolve_text("the cedar wood note gives this great longevity")
        assert "Cedar Wood" not in _names(results)

    def test_C8b_cedar_wood_blocked_in_note_context(self):
        """Note name from RS (Heretic review) — blocked."""
        r = _resolver()
        results = r.resolve_text("cedar wood and vetiver ground this fragrance beautifully")
        assert "Cedar Wood" not in _names(results)

    def test_C8c_cedar_wood_blocked_with_other_brand(self):
        """'cedar wood' appearing alongside a different brand — still blocked."""
        r = _resolver()
        results = r.resolve_text("dior sauvage has cedar wood and ambroxan in the base")
        assert "Cedar Wood" not in _names(results)


# ---------------------------------------------------------------------------
# P — Positive tests: phrases RESOLVE when brand token is nearby
# ---------------------------------------------------------------------------

class TestPositiveCasesAMB4:

    def test_P1_i_will_resolves_with_femascu(self):
        """'i will femascu review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("i will review femascu i will today")
        assert "I Will" in _names(results)

    def test_P2_very_pretty_resolves_with_michael_kors(self):
        """'very pretty michael kors review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("michael kors very pretty is a must have for spring")
        assert "Very Pretty" in _names(results)

    def test_P2b_very_pretty_resolves_with_kors_only(self):
        """Both michael and kors are required — kors alone is sufficient as one token."""
        r = _resolver()
        results = r.resolve_text("very pretty by kors such a pretty bottle")
        assert "Very Pretty" in _names(results)

    def test_P3_so_sexy_resolves_with_fiorucci(self):
        """'so sexy fiorucci review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("fiorucci so sexy is genuinely a great summer fragrance")
        assert "So Sexy!" in _names(results)

    def test_P4_day_one_resolves_with_smell_bent(self):
        """'day one smell bent review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("smell bent day one is a unique concept fragrance")
        assert "Day One" in _names(results)

    def test_P4b_day_one_resolves_with_bent_only(self):
        """'day one by bent' MUST resolve — bent alone suffices."""
        r = _resolver()
        results = r.resolve_text("day one by bent is an interesting indie release")
        assert "Day One" in _names(results)

    def test_P5_best_man_resolves_with_helena_rubinstein(self):
        """'best man helena rubinstein review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("best man by helena rubinstein is an underrated gem")
        assert "Best Man" in _names(results)

    def test_P5b_best_man_resolves_with_rubinstein_only(self):
        """'best man rubinstein' — rubinstein alone suffices."""
        r = _resolver()
        results = r.resolve_text("rubinstein best man is surprisingly good for the price")
        assert "Best Man" in _names(results)

    def test_P6_you_you_resolves_with_puig(self):
        """'you you puig review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("puig you you is a refreshing summer option")
        assert "You & You" in _names(results)

    def test_P6b_you_and_you_resolves_with_puig(self):
        """'you and you puig review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("you and you by puig smells like a classic barbershop")
        assert "You & You" in _names(results)

    def test_P7_jasmine_rose_resolves_with_primark(self):
        """'jasmine rose primark' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("primark jasmine rose is a surprising budget find")
        assert "Jasmine & Rose" in _names(results)

    def test_P7b_jasmine_and_rose_resolves_with_primark(self):
        """'jasmine and rose primark' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("jasmine and rose from primark actually smells decent")
        assert "Jasmine & Rose" in _names(results)

    def test_P8_cedar_wood_resolves_with_monotheme(self):
        """'cedar wood monotheme review' MUST resolve."""
        r = _resolver()
        results = r.resolve_text("monotheme cedar wood is a dry aromatic woody fragrance")
        assert "Cedar Wood" in _names(results)


# ---------------------------------------------------------------------------
# R — Regression: legitimate perfumes unaffected
# ---------------------------------------------------------------------------

class TestRegressionAMB4:

    def test_R1_creed_aventus_unaffected(self):
        r = _resolver()
        results = r.resolve_text("creed aventus is still the king of fragrances")
        assert "Creed Aventus" in _names(results)

    def test_R2_dior_sauvage_unaffected(self):
        r = _resolver()
        results = r.resolve_text("dior sauvage best man fragrance for a wedding perhaps")
        assert "Dior Sauvage" in _names(results)
        assert "Best Man" not in _names(results)  # No Helena Rubinstein nearby

    def test_R3_multiple_guards_do_not_interfere(self):
        """A sentence with 'cedar wood' and 'very pretty' — neither fires without brand."""
        r = _resolver()
        results = r.resolve_text(
            "the cedar wood note is very pretty in this flanker release"
        )
        assert "Cedar Wood" not in _names(results)
        assert "Very Pretty" not in _names(results)

    def test_R4_armaf_cdnim_unaffected(self):
        r = _resolver()
        results = r.resolve_text("armaf club de nuit intense man is the best aventus clone")
        assert "Armaf Club de Nuit Intense Man" in _names(results)


# ---------------------------------------------------------------------------
# G — Guard structure validation
# ---------------------------------------------------------------------------

class TestGuardStructureAMB4:

    def test_G1_all_amb4_phrases_present_in_guard(self):
        """All RES-AMB4 guard phrases must be present in _AMBIGUOUS_PHRASE_GUARD."""
        expected = {
            "i will",
            "very pretty",
            "so sexy",
            "day one",
            "best man",
            "you you",
            "you and you",
            "jasmine rose",
            "jasmine and rose",
            "cedar wood",
        }
        for phrase in expected:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"RES-AMB4 guard phrase missing: {phrase!r}"
            )

    def test_G2_amb4_brand_token_sets_are_frozensets(self):
        """RES-AMB4 guard entries must use frozenset brand token sets."""
        amb4_phrases = [
            "i will", "very pretty", "so sexy", "day one", "best man",
            "you you", "you and you", "jasmine rose", "jasmine and rose", "cedar wood",
        ]
        for phrase in amb4_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD
            for token_set in _AMBIGUOUS_PHRASE_GUARD[phrase]:
                assert isinstance(token_set, frozenset), (
                    f"Brand token set for {phrase!r} must be frozenset"
                )

    def test_G3_amb1_phrases_still_present(self):
        """RES-AMB1 guard phrases must survive AMB4 additions."""
        amb1_phrases = {"i am", "right now", "scent of", "blue oud", "peace love"}
        for phrase in amb1_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"RES-AMB1 guard phrase removed: {phrase!r}"
            )

    def test_G4_amb2_phrases_still_present(self):
        """RES-AMB2 guard phrases must survive AMB4 additions."""
        amb2_phrases = {
            "so you", "you are", "en route", "fragrance of summer",
            "one only", "one and only", "good vibes",
        }
        for phrase in amb2_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"RES-AMB2 guard phrase removed: {phrase!r}"
            )

    def test_G5_amb3_phrases_still_present(self):
        """RES-AMB3 guard phrases must survive AMB4 additions."""
        amb3_phrases = {
            "very well", "so happy", "too feminine", "true icon", "first class",
        }
        for phrase in amb3_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"RES-AMB3 guard phrase removed: {phrase!r}"
            )

    def test_G6_michael_kors_any_token_sufficient(self):
        """'very pretty' + 'michael' alone resolves — guard uses ANY-token (set intersection).

        _check_brand_proximity does context & brand_tokens, so a single matching
        token satisfies the frozenset. 'michael' near 'very pretty' is a strong
        enough signal that the perfume is the intended referent.
        """
        r = _resolver()
        results = r.resolve_text("very pretty by michael is such a feminine scent")
        assert "Very Pretty" in _names(results)

    def test_G7_smell_bent_requires_both_tokens(self):
        """'day one' + 'smell' alone (no 'bent') should NOT resolve — both required."""
        r = _resolver()
        results = r.resolve_text("day one of testing this fragrance really smells good")
        assert "Day One" not in _names(results)


# ---------------------------------------------------------------------------
# RES-AMB-FIVE — Bruno Fazzolari Five bare numeric alias "five" tests
# ---------------------------------------------------------------------------

class TestRESAMBFive:
    """'five' is a single-word numeric alias — blocked unconditionally via
    _BLOCKED_SINGLE_WORD_ALIASES.  Branded multi-token aliases are unaffected.

    F1 — bare 'five' blocked in counting context
    F2 — bare 'five' blocked in ordinal context
    F3 — bare 'five' blocked in price context
    F4 — branded 'bruno fazzolari five' still resolves (multi-token unaffected)
    F5 — 'five' in _BLOCKED_SINGLE_WORD_ALIASES
    """

    def test_F1_five_blocked_counting_language(self):
        """'five' as a counting word must NOT fire Bruno Fazzolari Five."""
        r = _resolver()
        results = r.resolve_text("five summer colognes under fifty dollars you need to try")
        assert "Bruno Fazzolari Five" not in _names(results)

    def test_F2_five_blocked_ordinal_context(self):
        """'five years old' — numeric ordinal must NOT fire the entity."""
        r = _resolver()
        results = r.resolve_text("my stepfather came in when i was five years old")
        assert "Bruno Fazzolari Five" not in _names(results)

    def test_F3_five_blocked_price_context(self):
        """'five dollars' — price reference must NOT fire the entity."""
        r = _resolver()
        results = r.resolve_text("five dollars at 5 below is an amazing deal on this fragrance")
        assert "Bruno Fazzolari Five" not in _names(results)

    def test_F4_branded_alias_still_resolves(self):
        """'bruno fazzolari five' multi-token alias is NOT in blocklist — must resolve."""
        r = _resolver()
        results = r.resolve_text("today i am reviewing bruno fazzolari five eau de parfum")
        assert "Bruno Fazzolari Five" in _names(results)

    def test_F5_five_in_blocked_single_word_aliases(self):
        """'five' must be present in _BLOCKED_SINGLE_WORD_ALIASES."""
        assert "five" in _BLOCKED_SINGLE_WORD_ALIASES, (
            "'five' missing from _BLOCKED_SINGLE_WORD_ALIASES"
        )


# ---------------------------------------------------------------------------
# RES-AMB-MENSCOL — Men's Cologne (Coty) category-descriptor guard tests
# ---------------------------------------------------------------------------

# Extend _TEST_ALIASES to include Men's Cologne and Coty context token
_TEST_ALIASES["men cologne"] = _make_entity(4010, "Men's Cologne")
_TEST_ALIASES["men s cologne"] = _make_entity(4010, "Men's Cologne")
_TEST_ALIASES["coty"] = _make_entity(5010, "Coty Brand")
_TEST_ALIASES["coty men cologne"] = _make_entity(4010, "Men's Cologne")


class TestRESAMBMensCol:
    """RES-AMB-MENSCOL (2026-05-19) — Type G category descriptor collision.

    Men's Cologne (Coty) — "men's cologne" is a product-category descriptor used
    throughout fragrance content ("best men's cologne under $50", "men's cologne
    recommendations"). normalize_text() produces two forms:
      ASCII apostrophe (U+0027): stripped → "men cologne" (2 tokens)
      Unicode curly apostrophe (U+2019): becomes space → "men s cologne" (3 tokens)

    Both forms require "coty" in ±10-token context before resolving.
    Branded alias "coty men cologne" resolves correctly without guard.

    MC1  "men cologne" blocked in category-descriptor context
    MC2  "men cologne" blocked in recommendation context
    MC3  "men s cologne" (unicode form) blocked in generic context
    MC4  Branded "coty men cologne" resolves correctly
    MC5  "men cologne" with "coty" nearby resolves correctly
    MC6  "men s cologne" with "coty" nearby resolves correctly
    MC7  "men cologne" and "men s cologne" present in _AMBIGUOUS_PHRASE_GUARD
    MC8  Guard entries use frozenset({"coty"})
    """

    def test_MC1_men_cologne_blocked_category_context(self):
        """'men's cologne' as category language must NOT fire Men's Cologne (Coty)."""
        r = _make_resolver_with_aliases(_TEST_ALIASES)
        results = r.resolve_text(
            "what is the best men cologne under fifty dollars for date night"
        )
        assert "Men's Cologne" not in _names(results)

    def test_MC2_men_cologne_blocked_recommendation_context(self):
        """Recommendation-style category usage must NOT fire."""
        r = _make_resolver_with_aliases(_TEST_ALIASES)
        results = r.resolve_text(
            "top ten men cologne picks you should try this summer"
        )
        assert "Men's Cologne" not in _names(results)

    def test_MC3_men_s_cologne_blocked_generic_context(self):
        """Unicode apostrophe form 'men s cologne' must also be blocked."""
        r = _make_resolver_with_aliases(_TEST_ALIASES)
        results = r.resolve_text(
            "men s cologne recommendations for office wear in 2026"
        )
        assert "Men's Cologne" not in _names(results)

    def test_MC4_branded_coty_men_cologne_resolves(self):
        """'coty men cologne' branded alias must resolve regardless of guard."""
        r = _make_resolver_with_aliases(_TEST_ALIASES)
        results = r.resolve_text(
            "reviewing coty men cologne the classic drugstore pick"
        )
        assert "Men's Cologne" in _names(results)

    def test_MC5_men_cologne_resolves_with_coty_nearby(self):
        """'men cologne' with 'coty' in ±10-token window MUST resolve."""
        r = _make_resolver_with_aliases(_TEST_ALIASES)
        results = r.resolve_text(
            "the coty men cologne is surprisingly pleasant for the price"
        )
        assert "Men's Cologne" in _names(results)

    def test_MC6_men_s_cologne_resolves_with_coty_nearby(self):
        """'men s cologne' with 'coty' nearby MUST resolve."""
        r = _make_resolver_with_aliases(_TEST_ALIASES)
        results = r.resolve_text(
            "coty men s cologne has a classic soapy barbershop profile"
        )
        assert "Men's Cologne" in _names(results)

    def test_MC7_guard_phrases_present_in_ambiguous_phrase_guard(self):
        """Both normalized forms must be present in _AMBIGUOUS_PHRASE_GUARD."""
        assert "men cologne" in _AMBIGUOUS_PHRASE_GUARD, (
            "'men cologne' missing from _AMBIGUOUS_PHRASE_GUARD"
        )
        assert "men s cologne" in _AMBIGUOUS_PHRASE_GUARD, (
            "'men s cologne' missing from _AMBIGUOUS_PHRASE_GUARD"
        )

    def test_MC8_guard_uses_coty_frozenset(self):
        """Both guard entries must require frozenset({"coty"})."""
        for phrase in ("men cologne", "men s cologne"):
            assert phrase in _AMBIGUOUS_PHRASE_GUARD
            token_sets = _AMBIGUOUS_PHRASE_GUARD[phrase]
            assert len(token_sets) == 1
            assert frozenset({"coty"}) in token_sets, (
                f"Guard for {phrase!r} must require coty token"
            )
