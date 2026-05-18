"""SIG-ID1 — Cross-Brand Attribution Correction: Brand Proximity Suppression Tests.

Tests for SIG-ID1 components:
  1. Bare-alias conflicting-brand suppression in PerfumeResolver.resolve_text()
  2. _AMBIGUOUS_PHRASE_GUARD entries for known cross-brand collision pairs
  3. _is_bare_alias() helper
  4. _conflicting_brand_in_window() helper
  5. brand_name present in alias cache (PgResolverStore mock)
  6. Regression: all prior RES-AMB tests unaffected

Test naming:
  N  = Negative (suppressed — wrong brand nearby)
  P  = Positive (resolves — correct brand present, no conflicting brand, or brand-qualified alias)
  G  = Guard structure (AMBIGUOUS_PHRASE_GUARD entries)
  H  = Helper unit tests (_is_bare_alias, _conflicting_brand_in_window)
  R  = Regression (prior phases unaffected)
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import (
    PerfumeResolver,
    _AMBIGUOUS_PHRASE_GUARD,
    _is_bare_alias,
    _conflicting_brand_in_window,
)
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolver(
    alias_map: Dict[str, Dict[str, Any]],
    brand_token_map: Optional[Dict[str, str]] = None,
) -> PerfumeResolver:
    """Build a resolver with mocked store and optional brand_token_map."""
    store = MagicMock()
    store.get_perfume_by_alias.side_effect = lambda phrase: alias_map.get(phrase)
    store.get_brand_token_map.return_value = brand_token_map or {}
    resolver = PerfumeResolver(store=store)
    resolver._brand_token_map = brand_token_map or {}
    return resolver


def _make_entity(
    perfume_id: int,
    canonical_name: str,
    brand_name: str = "",
) -> Dict[str, Any]:
    return {
        "perfume_id": perfume_id,
        "canonical_name": canonical_name,
        "brand_name": brand_name,
        "confidence": 1.0,
        "match_type": "exact",
    }


def _names(results: List[Dict[str, Any]]) -> List[str]:
    return [r["canonical_name"] for r in results]


# ---------------------------------------------------------------------------
# Core alias map — Oriflame Amber Elixir is the SIG-ID1 production case
# ---------------------------------------------------------------------------

_ALIASES: Dict[str, Dict[str, Any]] = {
    # SIG-ID1 production case: bare alias that fires for Oriflame
    "amber elixir":         _make_entity(700, "Amber Elixir", "Oriflame"),
    # Brand-qualified alias — should always resolve
    "oriflame amber elixir":_make_entity(700, "Amber Elixir", "Oriflame"),
    # Additional collision pairs from SIG-ID1 guard
    "champaca":             _make_entity(701, "Champaca", "Comme des Garcons"),
    "gardenia":             _make_entity(702, "Gardenia", "Isabey"),
    "hindu kush":           _make_entity(703, "Hindu Kush", "Mancera"),
    "rose oud":             _make_entity(704, "Rose Oud", "Alexandre"),
    # Legitimate entities for regression
    "creed aventus":        _make_entity(1, "Creed Aventus", "Creed"),
    "dior sauvage":         _make_entity(2, "Dior Sauvage", "Dior"),
    "baccarat rouge 540":   _make_entity(3, "Baccarat Rouge 540", "Maison Francis Kurkdjian"),
    # RES-AMB1/2/3/4 regression entries
    "i am":                 _make_entity(10, "I Am Juicy Couture", "Juicy Couture"),
    "i will":               _make_entity(11, "I Will", "Femascu"),
    "good vibes":           _make_entity(12, "Good Vibes", "Ricarda M."),
    "very well":            _make_entity(13, "Very Well", "Berdoues"),
    "cedar wood":           _make_entity(14, "Cedar Wood", "Monotheme"),
}

# Brand token map: normalized brand token → canonical brand name
_BRAND_TOKEN_MAP: Dict[str, str] = {
    "vertus":     "Vertus",
    "oriflame":   "Oriflame",
    "garcons":    "Comme des Garcons",
    "ormonde":    "Ormonde Jayne",
    "jayne":      "Ormonde Jayne",
    "isabey":     "Isabey",
    "micallef":   "M. Micallef",
    "mancera":    "Mancera",
    "profumo":    "La Via Del Profumo",
    "alexandre":  "Alexandre.J",
    "nicolai":    "Parfums de Nicolai",
    "gallivant":  "Gallivant",
    "widian":     "Widian",
    "creed":      "Creed",
    "dior":       "Dior",
    "femascu":    "Femascu",
    "berdoues":   "Berdoues",
    "monotheme":  "Monotheme",
    "primark":    "Primark",
}


# ---------------------------------------------------------------------------
# N — Negative cases: bare alias + conflicting brand → suppressed
# ---------------------------------------------------------------------------

class TestNegativeCasesSIGID1:
    """Bare alias + conflicting brand in context → resolution suppressed."""

    def test_n1_amber_elixir_vertus_context_suppressed(self):
        """'amber elixir' near 'vertus' → suppressed (wrong brand; Vertus not in catalog)."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        # Context: text describes Vertus Amber Elixir
        results = resolver.resolve_text("vertus amber elixir is a fantastic warm scent")
        assert "Amber Elixir" not in _names(results), (
            "Oriflame Amber Elixir must not resolve when 'vertus' is in context"
        )

    def test_n2_amber_elixir_vertus_brand_at_start(self):
        """Production evidence: 'Vertus Amber Elixir' at start of YouTube description."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("Vertus Amber Elixir is one of my favorites this week")
        assert "Amber Elixir" not in _names(results)

    def test_n3_amber_elixir_vertus_brand_after(self):
        """'amber elixir by vertus' → suppressed."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("this is amber elixir by vertus")
        assert "Amber Elixir" not in _names(results)

    def test_n4_champaca_ormonde_jayne_context(self):
        """'champaca' near 'ormonde' + 'jayne' → Comme des Garcons suppressed."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("ormonde jayne champaca is divine on my skin")
        assert "Champaca" not in _names(results)

    def test_n5_gardenia_micallef_context(self):
        """'gardenia' near 'micallef' → Isabey suppressed."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("i am wearing micallef gardenia today")
        assert "Gardenia" not in _names(results)

    def test_n6_hindu_kush_profumo_context(self):
        """'hindu kush' near 'profumo' → Mancera suppressed."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("profumo hindu kush is smoky and warm")
        assert "Hindu Kush" not in _names(results)

    def test_n7_rose_oud_nicolai_context(self):
        """'rose oud' near 'nicolai' → Alexandre suppressed."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("parfums de nicolai rose oud vintage")
        assert "Rose Oud" not in _names(results)

    def test_n8_bare_alias_no_resolve_when_different_brand_in_window(self):
        """Generic: any bare alias suppressed when different brand token appears nearby."""
        # creed aventus has a branded alias; use it as context control
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        # 'dior' token near 'amber elixir' → suppressed (dior ≠ oriflame)
        results = resolver.resolve_text("dior amber elixir review for warm weather")
        # Dior is not Oriflame, so Oriflame Amber Elixir should be suppressed
        assert "Amber Elixir" not in _names(results)


# ---------------------------------------------------------------------------
# P — Positive cases: resolves correctly
# ---------------------------------------------------------------------------

class TestPositiveCasesSIGID1:
    """Bare alias resolves when no conflicting brand is nearby."""

    def test_p1_amber_elixir_oriflame_context_resolves(self):
        """'amber elixir' + 'oriflame' in context → resolves (correct brand = no suppression).

        The _AMBIGUOUS_PHRASE_GUARD requires oriflame nearby; when oriflame IS nearby
        the guard passes and the bare-alias check sees the correct brand → no suppression.
        The brand-qualified alias 'oriflame amber elixir' also works directly.
        """
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("oriflame amber elixir review unboxing")
        assert "Amber Elixir" in _names(results)

    def test_p2_oriflame_brand_qualified_alias_always_resolves(self):
        """'oriflame amber elixir' → always resolves (brand in alias)."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("oriflame amber elixir is a great option")
        assert "Amber Elixir" in _names(results)

    def test_p3_amber_elixir_correct_brand_oriflame_in_context(self):
        """'amber elixir' near 'oriflame' → resolves (same brand = no suppression)."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("oriflame amber elixir is their best offering")
        # The alias here is 'oriflame amber elixir' (brand-qualified), or
        # 'amber elixir' with 'oriflame' in context — either way resolves
        assert "Amber Elixir" in _names(results)

    def test_p4_creed_aventus_unaffected(self):
        """Creed Aventus resolves normally — SIG-ID1 does not affect brand-qualified aliases."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("creed aventus is the GOAT of fragrances")
        assert "Creed Aventus" in _names(results)

    def test_p5_dior_sauvage_unaffected(self):
        """Dior Sauvage resolves normally."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("dior sauvage elixir vs the original")
        assert "Dior Sauvage" in _names(results)

    def test_p6_no_brand_token_map_no_suppression(self):
        """When brand_token_map is empty (SQLite store), bare-alias suppression never fires.

        Graceful degradation: SQLite store has no get_brand_token_map(); _brand_token_map
        defaults to {} and the bare-alias conflicting-brand check is skipped.
        Uses an alias NOT in _AMBIGUOUS_PHRASE_GUARD so the guard doesn't interfere.
        """
        # creed aventus has no conflicting brand in the text, and is not in the
        # ambiguous phrase guard — it should always resolve regardless of token map
        resolver = _make_resolver(_ALIASES, brand_token_map={})
        results = resolver.resolve_text("creed aventus is the best")
        assert "Creed Aventus" in _names(results)

    def test_p7_bare_alias_resolves_when_same_brand_nearby(self):
        """'amber elixir' near 'oriflame' → correct brand nearby → no suppression."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        # 'oriflame' IS in the brand token map as Oriflame — same as entity_brand
        results = resolver.resolve_text("this is oriflame amber elixir unboxing")
        assert "Amber Elixir" in _names(results)

    def test_p8_baccarat_rouge_resolves(self):
        """Baccarat Rouge 540 is unaffected."""
        resolver = _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)
        results = resolver.resolve_text("baccarat rouge 540 smells incredible")
        assert "Baccarat Rouge 540" in _names(results)


# ---------------------------------------------------------------------------
# H — Helper function unit tests
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    """Unit tests for _is_bare_alias and _conflicting_brand_in_window."""

    def test_h1_is_bare_alias_true_when_brand_absent(self):
        assert _is_bare_alias("amber elixir", "Oriflame") is True

    def test_h2_is_bare_alias_false_when_brand_present(self):
        assert _is_bare_alias("oriflame amber elixir", "Oriflame") is False

    def test_h3_is_bare_alias_case_insensitive(self):
        # _is_bare_alias expects pre-normalized (lowercase) alias_text as it
        # receives from resolve_text's sliding-window normalized tokens.
        # normalize_text("Amber Elixir") → "amber elixir"
        from perfume_trend_sdk.utils.alias_generator import normalize_text
        assert _is_bare_alias(normalize_text("Amber Elixir"), "Oriflame") is True
        assert _is_bare_alias(normalize_text("Oriflame Amber Elixir"), "Oriflame") is False

    def test_h4_is_bare_alias_multi_token_brand(self):
        assert _is_bare_alias("aventus", "Creed") is True
        assert _is_bare_alias("creed aventus", "Creed") is False

    def test_h5_is_bare_alias_accent_normalized_brand(self):
        # normalize_text strips accents; "Comme des Garcons" becomes "comme des garcons"
        assert _is_bare_alias("champaca", "Comme des Garcons") is True
        assert _is_bare_alias("garcons champaca", "Comme des Garcons") is False

    def test_h6_conflicting_brand_found_in_window(self):
        tokens = "vertus amber elixir warm weather".split()
        # phrase is tokens[1:3] ("amber elixir"), match_start=1, match_end=3
        result = _conflicting_brand_in_window(
            tokens, match_start=1, match_end=3,
            entity_brand_name="Oriflame",
            brand_token_map={"vertus": "Vertus", "oriflame": "Oriflame"},
        )
        assert result == "Vertus"

    def test_h7_conflicting_brand_not_found_when_same_brand(self):
        tokens = "oriflame amber elixir review".split()
        result = _conflicting_brand_in_window(
            tokens, match_start=1, match_end=3,
            entity_brand_name="Oriflame",
            brand_token_map={"vertus": "Vertus", "oriflame": "Oriflame"},
        )
        assert result is None  # oriflame = same brand, not conflicting

    def test_h8_conflicting_brand_respects_window_boundary(self):
        # Brand token "vertus" is 12 tokens after match_end — outside window=10
        # match_start=0, match_end=2, hi=2+10=12; "vertus" at index 14 → excluded
        tokens = ["amber", "elixir"] + (["word"] * 12) + ["vertus"]
        result = _conflicting_brand_in_window(
            tokens, match_start=0, match_end=2,
            entity_brand_name="Oriflame",
            brand_token_map={"vertus": "Vertus"},
            window=10,
        )
        assert result is None  # 12 tokens after end > window=10, so excluded

    def test_h9_conflicting_brand_within_window(self):
        # Brand token "vertus" is 9 tokens before match — inside window=10
        tokens = ["vertus"] + (["word"] * 8) + ["amber", "elixir"]
        result = _conflicting_brand_in_window(
            tokens, match_start=9, match_end=11,
            entity_brand_name="Oriflame",
            brand_token_map={"vertus": "Vertus"},
            window=10,
        )
        assert result == "Vertus"

    def test_h10_no_brand_token_in_context(self):
        tokens = "a nice warm scent amber elixir".split()
        result = _conflicting_brand_in_window(
            tokens, match_start=4, match_end=6,
            entity_brand_name="Oriflame",
            brand_token_map={"vertus": "Vertus"},
        )
        assert result is None


# ---------------------------------------------------------------------------
# G — Guard structure tests
# ---------------------------------------------------------------------------

class TestGuardStructureSIGID1:
    """Verify _AMBIGUOUS_PHRASE_GUARD has all SIG-ID1 entries."""

    def test_g1_amber_elixir_guard_present(self):
        assert "amber elixir" in _AMBIGUOUS_PHRASE_GUARD
        guard = _AMBIGUOUS_PHRASE_GUARD["amber elixir"]
        assert any("oriflame" in s for s in guard)

    def test_g2_champaca_guard_present(self):
        assert "champaca" in _AMBIGUOUS_PHRASE_GUARD
        guard = _AMBIGUOUS_PHRASE_GUARD["champaca"]
        # Should have 2 frozensets for 2 competing brands
        assert len(guard) >= 2

    def test_g3_gardenia_guard_present(self):
        assert "gardenia" in _AMBIGUOUS_PHRASE_GUARD
        guard = _AMBIGUOUS_PHRASE_GUARD["gardenia"]
        assert any("isabey" in s for s in guard)
        assert any("micallef" in s for s in guard)

    def test_g4_hindu_kush_guard_present(self):
        assert "hindu kush" in _AMBIGUOUS_PHRASE_GUARD
        guard = _AMBIGUOUS_PHRASE_GUARD["hindu kush"]
        assert any("mancera" in s for s in guard)
        assert any("profumo" in s for s in guard)

    def test_g5_rose_oud_guard_present(self):
        assert "rose oud" in _AMBIGUOUS_PHRASE_GUARD
        guard = _AMBIGUOUS_PHRASE_GUARD["rose oud"]
        assert any("alexandre" in s for s in guard)
        assert any("nicolai" in s for s in guard)

    def test_g6_london_eau_de_parfum_guard_present(self):
        assert "london eau de parfum" in _AMBIGUOUS_PHRASE_GUARD
        guard = _AMBIGUOUS_PHRASE_GUARD["london eau de parfum"]
        assert any("gallivant" in s for s in guard)
        assert any("widian" in s for s in guard)

    def test_g7_new_york_intense_guard_present(self):
        assert "new york intense" in _AMBIGUOUS_PHRASE_GUARD
        guard = _AMBIGUOUS_PHRASE_GUARD["new york intense"]
        assert any("nicolai" in s for s in guard)

    def test_g8_all_sig_id1_guards_use_frozensets(self):
        sig_id1_guards = [
            "amber elixir", "champaca", "gardenia", "hindu kush",
            "rose oud", "london eau de parfum", "new york intense",
        ]
        for phrase in sig_id1_guards:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, f"Missing guard for {phrase!r}"
            for s in _AMBIGUOUS_PHRASE_GUARD[phrase]:
                assert isinstance(s, frozenset), f"Guard for {phrase!r} must use frozensets"

    def test_g9_prior_res_amb_guards_still_present(self):
        """SIG-ID1 additions must not remove any prior RES-AMB guard entries."""
        prior_phrases = [
            "i am", "right now", "scent of", "blue oud", "peace love",  # RES-AMB1
            "so you", "you are", "en route", "fragrance of summer",      # RES-AMB2
            "good vibes", "one only", "one and only",
            "very well", "so happy", "too feminine", "true icon",        # RES-AMB3
            "first class",
            "i will", "very pretty", "so sexy", "day one",              # RES-AMB4
            "best man", "you you", "jasmine rose", "cedar wood",
            "pure luxury", "on the rocks", "enjoy the day",             # SIG-QA1-REPAIR
            "orange blossom", "revolution perfume",
        ]
        for phrase in prior_phrases:
            assert phrase in _AMBIGUOUS_PHRASE_GUARD, (
                f"Prior guard {phrase!r} was removed — regression!"
            )


# ---------------------------------------------------------------------------
# R — Regression tests
# ---------------------------------------------------------------------------

class TestRegressionSIGID1:
    """SIG-ID1 must not break any previously working resolution or guard."""

    def _resolver(self):
        return _make_resolver(_ALIASES, _BRAND_TOKEN_MAP)

    def test_r1_creed_aventus_still_resolves(self):
        results = self._resolver().resolve_text("creed aventus is my favorite")
        assert "Creed Aventus" in _names(results)

    def test_r2_dior_sauvage_still_resolves(self):
        results = self._resolver().resolve_text("dior sauvage elixir 2026")
        assert "Dior Sauvage" in _names(results)

    def test_r3_i_am_guard_still_fires(self):
        """RES-AMB1 'i am' guard still blocks without 'juicy couture' context."""
        results = self._resolver().resolve_text("i am wearing my new blind buy today")
        assert "I Am Juicy Couture" not in _names(results)

    def test_r4_i_will_guard_still_fires(self):
        """RES-AMB4 'i will' guard still blocks without 'femascu' context."""
        results = self._resolver().resolve_text("in this video i will be reviewing")
        assert "I Will" not in _names(results)

    def test_r5_good_vibes_guard_still_fires(self):
        """RES-AMB2 'good vibes' guard still blocks without 'ricarda' context."""
        results = self._resolver().resolve_text("sending good vibes to everyone")
        assert "Good Vibes" not in _names(results)

    def test_r6_very_well_guard_still_fires(self):
        """RES-AMB3 'very well' guard still blocks without 'berdoues' context."""
        results = self._resolver().resolve_text("this performer played very well tonight")
        assert "Very Well" not in _names(results)

    def test_r7_cedar_wood_guard_still_fires(self):
        """SIG-QA1-REPAIR 'cedar wood' guard still blocks without 'monotheme' context."""
        results = self._resolver().resolve_text("a cedar wood and sandalwood base note blend")
        assert "Cedar Wood" not in _names(results)

    def test_r8_baccarat_rouge_540_unaffected(self):
        results = self._resolver().resolve_text("baccarat rouge 540 is iconic in the fragrance community")
        assert "Baccarat Rouge 540" in _names(results)


# ---------------------------------------------------------------------------
# HV — Harvest candidate generation tests (_compute_candidates pure function)
# ---------------------------------------------------------------------------

class TestHarvestCandidateGeneration:
    """Tests for _compute_candidates() pure function and _UPSERT_SQL SET semantics.

    No DB required — _compute_candidates is fully deterministic given raw RS rows.
    """

    @staticmethod
    def _import_harvest():
        """Lazy import to keep test file loadable even if psycopg2 not installed."""
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "harvest_unresolved_brand_signals",
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "scripts" / "harvest_unresolved_brand_signals.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _make_rs_rows(self, phrases_list, rs_date="2026-05-18"):
        """Build a list of (unresolved_json, rs_date) RS rows."""
        import json
        from datetime import date
        d = date.fromisoformat(rs_date)
        return [(json.dumps(phrases), d) for phrases in phrases_list]

    def test_hv1_vertus_candidate_created(self):
        """'vertus amber elixir' → brand_token='vertus' candidate created."""
        mod = self._import_harvest()
        brand_token_map = {"vertus": "Vertus"}
        rs_rows = self._make_rs_rows([["vertus amber elixir", "some other phrase"]])
        result = mod._compute_candidates(
            rs_rows,
            brand_token_map=brand_token_map,
            existing_aliases=frozenset(),
            blocked_phrases=frozenset(),
            min_occurrences=1,
        )
        assert ("vertus amber elixir", "vertus") in result, (
            "Expected 'vertus amber elixir' with brand_token='vertus' in candidates"
        )
        rec = result[("vertus amber elixir", "vertus")]
        assert rec["occurrences"] == 1
        assert rec["brand_canonical"] == "Vertus"

    def test_hv2_rerun_deterministic(self):
        """Running _compute_candidates twice with same RS rows → same occurrence_count.

        This verifies the full-history recompute design: the function is deterministic,
        so running it twice on the same input yields identical output. The pipeline's
        SET upsert guarantees the DB is also idempotent.
        """
        mod = self._import_harvest()
        brand_token_map = {"vertus": "Vertus"}
        rs_rows = self._make_rs_rows([
            ["vertus amber elixir"],
            ["vertus amber elixir"],
        ])
        result1 = mod._compute_candidates(
            rs_rows, brand_token_map, frozenset(), frozenset(), min_occurrences=1
        )
        result2 = mod._compute_candidates(
            rs_rows, brand_token_map, frozenset(), frozenset(), min_occurrences=1
        )
        key = ("vertus amber elixir", "vertus")
        assert result1[key]["occurrences"] == result2[key]["occurrences"], (
            "_compute_candidates must be deterministic (same input → same output)"
        )

    def test_hv3_one_rs_row_one_occurrence(self):
        """A single RS row contributes exactly 1 occurrence per phrase.

        Verifies the non-additive design: no matter how many times the same phrase
        appears in one RS row's unresolved_json list, it counts as 1 occurrence per
        RS row (seen_in_source deduplication for source_count; phrase occurrence is
        1 per appearance in the phrases list, not per RS row).
        """
        mod = self._import_harvest()
        brand_token_map = {"vertus": "Vertus"}
        # One RS row with the phrase appearing once
        rs_rows = self._make_rs_rows([["vertus amber elixir"]])
        result = mod._compute_candidates(
            rs_rows, brand_token_map, frozenset(), frozenset(), min_occurrences=1
        )
        key = ("vertus amber elixir", "vertus")
        assert result[key]["occurrences"] == 1
        assert result[key]["sources"] == 1, (
            "source_count must equal distinct RS rows containing the phrase"
        )

    def test_hv4_min_occurrences_filter(self):
        """Phrase with 1 occurrence is excluded when min_occurrences=2."""
        mod = self._import_harvest()
        brand_token_map = {"vertus": "Vertus"}
        rs_rows = self._make_rs_rows([["vertus amber elixir"]])  # 1 occurrence
        result = mod._compute_candidates(
            rs_rows, brand_token_map, frozenset(), frozenset(), min_occurrences=2
        )
        assert ("vertus amber elixir", "vertus") not in result, (
            "Single-occurrence phrase must be filtered out when min_occurrences=2"
        )

    def test_hv5_phrase_in_existing_aliases_excluded(self):
        """Phrase already in resolver_aliases (existing_aliases) is excluded from candidates."""
        mod = self._import_harvest()
        brand_token_map = {"vertus": "Vertus"}
        rs_rows = self._make_rs_rows([["vertus amber elixir"]])
        # Simulate phrase already resolved (in resolver_aliases)
        existing_aliases = frozenset(["vertus amber elixir"])
        result = mod._compute_candidates(
            rs_rows, brand_token_map, existing_aliases, frozenset(), min_occurrences=1
        )
        assert ("vertus amber elixir", "vertus") not in result, (
            "Phrase already in resolver_aliases must not appear as a candidate"
        )

    def test_hv6_upsert_sql_uses_set_semantics(self):
        """_UPSERT_SQL uses SET occurrence_count = EXCLUDED.occurrence_count, not additive.

        Verifies the string constant so a future edit that accidentally introduces
        '+' accumulation is caught immediately.
        """
        mod = self._import_harvest()
        upsert = mod._UPSERT_SQL
        # Must contain SET semantics (EXCLUDED.occurrence_count assigned, not summed)
        assert "occurrence_count = EXCLUDED.occurrence_count" in upsert, (
            "_UPSERT_SQL must SET occurrence_count = EXCLUDED.occurrence_count (not accumulate)"
        )
        # Must NOT use additive pattern
        assert "occurrence_count +" not in upsert, (
            "_UPSERT_SQL must not use additive accumulation (occurrence_count +)"
        )
        assert "GREATEST" not in upsert.split("last_seen")[0].split("first_seen")[0], (
            "_UPSERT_SQL must not use GREATEST on occurrence_count"
        )


# ---------------------------------------------------------------------------
# SIG-ID1A — Signal Candidate Queue Quality Calibration tests
# ---------------------------------------------------------------------------

class TestSIGID1AFilters:
    """Tests for SIG-ID1A filtering rules added to _compute_candidates().

    F1 = single-token filter (bare brand names excluded)
    F2 = trailing stop-word filter (sentence fragments excluded)
    F3 = _HARVEST_CONTEXT_SKIP_TOKENS (generic-word brand anchors excluded)
    F4 = brand-name-only filter (phrase == normalized brand name excluded)
    SK = _SKIP_TOKENS extension (plural generic tokens excluded from brand_token_map)
    DS = Dossier seed (dossier brand_token produces product candidates)
    """

    @staticmethod
    def _import_harvest():
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "harvest_unresolved_brand_signals",
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "scripts" / "harvest_unresolved_brand_signals.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _make_rs_rows(self, phrases_list, rs_date="2026-05-18"):
        import json
        from datetime import date
        d = date.fromisoformat(rs_date)
        return [(json.dumps(phrases), d) for phrases in phrases_list]

    # ── F1: single-token filter ──────────────────────────────────────────────

    def test_f1_single_token_byredo_excluded(self):
        """Bare brand name 'byredo' (1 token) must be excluded."""
        mod = self._import_harvest()
        btm = {"byredo": "Byredo"}
        rs_rows = self._make_rs_rows([["byredo"] * 5])  # 5 occurrences but 1 token
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("byredo", "byredo") not in result

    def test_f1_single_token_kilian_excluded(self):
        """Bare brand name 'kilian' (1 token) must be excluded."""
        mod = self._import_harvest()
        btm = {"kilian": "Kilian"}
        rs_rows = self._make_rs_rows([["kilian"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("kilian", "kilian") not in result

    def test_f1_two_token_phrase_not_excluded(self):
        """2-token phrase like 'kilian angels' passes single-token filter."""
        mod = self._import_harvest()
        btm = {"kilian": "Kilian"}
        rs_rows = self._make_rs_rows([["kilian angels"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("kilian angels", "kilian") in result

    # ── F2: trailing stop-word filter ─────────────────────────────────────────

    def test_f2_fragrances_that_excluded(self):
        """'fragrances that' ends in stop word 'that' → sentence fragment, excluded.
        Note: 'fragrances' is now in _SKIP_TOKENS so has no brand_token — this tests
        a phrase with a valid brand token but a stop-word tail."""
        mod = self._import_harvest()
        btm = {"kilian": "Kilian"}
        rs_rows = self._make_rs_rows([["kilian that"] * 5])  # "that" is trailing stop
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("kilian that", "kilian") not in result

    def test_f2_phrase_ending_in_for_excluded(self):
        """Phrase ending in 'for' is a sentence fragment → excluded."""
        mod = self._import_harvest()
        btm = {"kilian": "Kilian"}
        rs_rows = self._make_rs_rows([["kilian for"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("kilian for", "kilian") not in result

    def test_f2_phrase_not_ending_in_stop_word_passes(self):
        """'kilian angels share' ends in 'share' (not a stop word) → passes."""
        mod = self._import_harvest()
        btm = {"kilian": "Kilian"}
        rs_rows = self._make_rs_rows([["kilian angels share"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("kilian angels share", "kilian") in result

    # ── F3: _HARVEST_CONTEXT_SKIP_TOKENS ──────────────────────────────────────

    def test_f3_signature_scent_excluded_by_context_skip(self):
        """'signature' in _HARVEST_CONTEXT_SKIP_TOKENS → (phrase, 'signature') excluded."""
        mod = self._import_harvest()
        assert "signature" in mod._HARVEST_CONTEXT_SKIP_TOKENS
        btm = {"signature": "Signature Royale"}
        rs_rows = self._make_rs_rows([["signature scent"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("signature scent", "signature") not in result

    def test_f3_little_bit_excluded(self):
        """'little' in _HARVEST_CONTEXT_SKIP_TOKENS → (phrase, 'little') excluded."""
        mod = self._import_harvest()
        btm = {"little": "Little and Grim"}
        rs_rows = self._make_rs_rows([["little bit"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("little bit", "little") not in result

    def test_f3_elixir_le_male_elixir_excluded(self):
        """'le male elixir' → 'elixir' in _HARVEST_CONTEXT_SKIP_TOKENS → excluded.
        This removes false attribution to Elixir Attar when phrase is about JPG Le Male Elixir."""
        mod = self._import_harvest()
        assert "elixir" in mod._HARVEST_CONTEXT_SKIP_TOKENS
        btm = {"elixir": "Elixir Attar"}
        rs_rows = self._make_rs_rows([["le male elixir"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("le male elixir", "elixir") not in result

    def test_f3_floral_phrase_excluded(self):
        """'floral' in _HARVEST_CONTEXT_SKIP_TOKENS → (phrase, 'floral') excluded."""
        mod = self._import_harvest()
        btm = {"floral": "Floral 4 Seasons"}
        rs_rows = self._make_rs_rows([["white floral"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("white floral", "floral") not in result

    def test_f3_non_skip_token_dossier_passes(self):
        """'dossier' is NOT in _HARVEST_CONTEXT_SKIP_TOKENS → passes."""
        mod = self._import_harvest()
        assert "dossier" not in mod._HARVEST_CONTEXT_SKIP_TOKENS
        btm = {"dossier": "Dossier"}
        rs_rows = self._make_rs_rows([["dossier floral marshmallow"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("dossier floral marshmallow", "dossier") in result

    # ── F4: brand-name-only filter ────────────────────────────────────────────

    def test_f4_jean_paul_gaultier_excluded(self):
        """'jean paul gaultier' == normalize('Jean Paul Gaultier') → brand-name-only, excluded."""
        mod = self._import_harvest()
        btm = {"gaultier": "Jean Paul Gaultier"}
        rs_rows = self._make_rs_rows([["jean paul gaultier"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("jean paul gaultier", "gaultier") not in result

    def test_f4_dolce_gabbana_excluded(self):
        """'dolce gabbana' == normalize('Dolce & Gabbana') → brand-name-only, excluded."""
        mod = self._import_harvest()
        btm = {"gabbana": "Dolce & Gabbana"}
        rs_rows = self._make_rs_rows([["dolce gabbana"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("dolce gabbana", "gabbana") not in result

    def test_f4_brand_plus_product_passes(self):
        """'gaultier le male' has product qualifier beyond brand name → passes."""
        mod = self._import_harvest()
        btm = {"gaultier": "Jean Paul Gaultier"}
        rs_rows = self._make_rs_rows([["gaultier le male"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("gaultier le male", "gaultier") in result

    # ── SK: _SKIP_TOKENS plural extensions ────────────────────────────────────

    def test_sk_fragrances_in_skip_tokens(self):
        """'fragrances' must be in _SKIP_TOKENS (not usable as brand token)."""
        mod = self._import_harvest()
        assert "fragrances" in mod._SKIP_TOKENS

    def test_sk_perfumes_in_skip_tokens(self):
        """'perfumes' must be in _SKIP_TOKENS."""
        mod = self._import_harvest()
        assert "perfumes" in mod._SKIP_TOKENS

    def test_sk_scents_in_skip_tokens(self):
        """'scents' must be in _SKIP_TOKENS."""
        mod = self._import_harvest()
        assert "scents" in mod._SKIP_TOKENS

    def test_sk_colognes_in_skip_tokens(self):
        """'colognes' must be in _SKIP_TOKENS."""
        mod = self._import_harvest()
        assert "colognes" in mod._SKIP_TOKENS

    # ── DS: Dossier brand produces product candidates ─────────────────────────

    def test_ds_dossier_floral_marshmallow_candidate(self):
        """After Dossier is in brand_token_map, 'dossier floral marshmallow' surfaces."""
        mod = self._import_harvest()
        # Simulate brand_token_map after Dossier added to resolver_brands
        btm = {"dossier": "Dossier", "floral": "Floral 4 Seasons"}
        rs_rows = self._make_rs_rows([
            ["dossier floral marshmallow", "smelling dossier floral marshmallow"],
            ["dossier floral marshmallow"],
        ])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 2)
        # dossier token: passes all filters, brand_canonical="Dossier"
        assert ("dossier floral marshmallow", "dossier") in result
        # floral token: in _HARVEST_CONTEXT_SKIP_TOKENS → filtered out
        assert ("dossier floral marshmallow", "floral") not in result

    def test_ds_dossier_musky_gaiac_candidate(self):
        """'dossier musky gaiac' surfaces with brand_token='dossier'."""
        mod = self._import_harvest()
        btm = {"dossier": "Dossier"}
        rs_rows = self._make_rs_rows([["dossier musky gaiac"] * 2])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 2)
        assert ("dossier musky gaiac", "dossier") in result

    # ── Structure tests ───────────────────────────────────────────────────────

    def test_structure_harvest_context_skip_tokens_are_frozenset(self):
        """_HARVEST_CONTEXT_SKIP_TOKENS must be a frozenset and non-empty."""
        mod = self._import_harvest()
        assert isinstance(mod._HARVEST_CONTEXT_SKIP_TOKENS, frozenset)
        assert len(mod._HARVEST_CONTEXT_SKIP_TOKENS) >= 20

    def test_structure_trailing_stop_words_are_frozenset(self):
        """_TRAILING_STOP_WORDS must be a frozenset and include key stop words."""
        mod = self._import_harvest()
        assert isinstance(mod._TRAILING_STOP_WORDS, frozenset)
        for word in ["that", "for", "and", "or", "in", "i", "the", "de"]:
            assert word in mod._TRAILING_STOP_WORDS, f"{word!r} must be in _TRAILING_STOP_WORDS"

    def test_structure_vertus_amber_elixir_survives_all_filters(self):
        """'vertus amber elixir' must survive all SIG-ID1A filters unchanged."""
        mod = self._import_harvest()
        assert "vertus" not in mod._SKIP_TOKENS
        assert "vertus" not in mod._HARVEST_CONTEXT_SKIP_TOKENS
        btm = {"vertus": "Vertus"}
        # 2 tokens → passes single-token filter
        # last token 'elixir' not in _TRAILING_STOP_WORDS
        # 'vertus' not in _HARVEST_CONTEXT_SKIP_TOKENS
        # 'vertus amber elixir' != normalize('Vertus') = 'vertus'
        rs_rows = self._make_rs_rows([
            ["vertus amber elixir", "other phrase"],
            ["vertus amber elixir"],
        ])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 2)
        assert ("vertus amber elixir", "vertus") in result
        assert result[("vertus amber elixir", "vertus")]["occurrences"] == 2


# ---------------------------------------------------------------------------
# F5 — Minimum-distinctiveness filter + _BRIDGE_WORDS tests
# ---------------------------------------------------------------------------

class TestMinimumDistinctivenessFilter:
    """Tests for SIG-ID1A filter 5: brand-name-subset (minimum-distinctiveness) check.

    After removing bridge words, _SKIP_TOKENS, and _HARVEST_CONTEXT_SKIP_TOKENS,
    if remaining tokens ⊆ brand name tokens → phrase is a partial brand name with
    no product qualifier → excluded.

    Positive cases (should be EXCLUDED):
        F5N1  "paul gaultier" ⊆ "jean paul gaultier"
        F5N2  "maison francis" ⊆ "maison francis kurkdjian"
        F5N3  "saint laurent" ⊆ "yves saint laurent"
        F5N4  "by lattafa" → by=bridge → {"lattafa"} ⊆ {"lattafa"}
        F5N5  "de chanel" → de=bridge → {"chanel"} ⊆ {"chanel"}
        F5N6  "louis vuitton" ⊆ "louis vuitton" (exact brand match via subset)
        F5N7  "lattafa perfumes" → perfumes=_SKIP_TOKEN → {"lattafa"} ⊆ {"lattafa"}
        F5N8  "francis kurkdjian" ⊆ "maison francis kurkdjian"
        F5N9  "al maghribi" → al=bridge → {"maghribi"} ⊆ {"ahmed al maghribi"}

    Negative cases (should be KEPT — have genuine product qualifier):
        F5P1  "burberry goddess" — "goddess" ∉ {"burberry"}
        F5P2  "chanel chance" — "chance" ∉ {"chanel"}
        F5P3  "arabiyat prestige" — "prestige" ∉ {"arabiyat"}
        F5P4  "valentino born in roma" — "born"/"roma" ∉ {"valentino"}
        F5P5  "clive christian" — "christian" IS in {"clive", "christian"};
              but "christian louboutin" is a different brand → subset check
              should not filter because btm maps "christian" → "Clive Christian",
              not "Christian Louboutin" (brand mismatch guards are separate)
        F5P6  "dossier musky gaiac" — "musky"/"gaiac" ∉ {"dossier"}

    Structure:
        F5S1  _BRIDGE_WORDS is a frozenset
        F5S2  expected bridge words present
        F5S3  "vertus amber elixir" survives filter 5
    """

    @staticmethod
    def _import_harvest():
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "harvest_unresolved_brand_signals",
            pathlib.Path(__file__).resolve().parent.parent.parent
            / "scripts" / "harvest_unresolved_brand_signals.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _make_rs_rows(self, phrases_list, rs_date="2026-05-18"):
        import json
        from datetime import date
        d = date.fromisoformat(rs_date)
        return [(json.dumps(phrases), d) for phrases in phrases_list]

    # ── Negative cases (filtered OUT) ─────────────────────────────────────────

    def test_f5n1_paul_gaultier_excluded(self):
        """'paul gaultier' tokens ⊆ 'jean paul gaultier' → excluded."""
        mod = self._import_harvest()
        btm = {"gaultier": "Jean Paul Gaultier"}
        rs_rows = self._make_rs_rows([["paul gaultier"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("paul gaultier", "gaultier") not in result, (
            "'paul gaultier' should be filtered as partial brand name subset"
        )

    def test_f5n2_maison_francis_excluded(self):
        """'maison francis' tokens ⊆ 'maison francis kurkdjian' → excluded."""
        mod = self._import_harvest()
        btm = {"kurkdjian": "Maison Francis Kurkdjian"}
        rs_rows = self._make_rs_rows([["maison francis"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("maison francis", "kurkdjian") not in result, (
            "'maison francis' should be filtered as partial brand name subset of MFK"
        )

    def test_f5n3_saint_laurent_excluded(self):
        """'saint laurent' tokens ⊆ 'yves saint laurent' → excluded."""
        mod = self._import_harvest()
        btm = {"laurent": "Yves Saint Laurent"}
        rs_rows = self._make_rs_rows([["saint laurent"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("saint laurent", "laurent") not in result, (
            "'saint laurent' should be filtered as partial brand name subset of YSL"
        )

    def test_f5n4_by_lattafa_excluded(self):
        """'by lattafa' → 'by' is bridge word → distinctive={'lattafa'} ⊆ {'lattafa'} → excluded."""
        mod = self._import_harvest()
        btm = {"lattafa": "Lattafa"}
        rs_rows = self._make_rs_rows([["by lattafa"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("by lattafa", "lattafa") not in result, (
            "'by lattafa' should be filtered: 'by' is bridge, leaving only brand token"
        )

    def test_f5n5_de_chanel_excluded(self):
        """'de chanel' → 'de' is bridge word → distinctive={'chanel'} ⊆ {'chanel'} → excluded."""
        mod = self._import_harvest()
        btm = {"chanel": "Chanel"}
        rs_rows = self._make_rs_rows([["de chanel"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("de chanel", "chanel") not in result, (
            "'de chanel' should be filtered: 'de' is bridge, leaving only brand token"
        )

    def test_f5n6_francis_kurkdjian_excluded(self):
        """'francis kurkdjian' tokens ⊆ 'maison francis kurkdjian' → excluded."""
        mod = self._import_harvest()
        btm = {"kurkdjian": "Maison Francis Kurkdjian"}
        rs_rows = self._make_rs_rows([["francis kurkdjian"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("francis kurkdjian", "kurkdjian") not in result, (
            "'francis kurkdjian' should be filtered as partial brand subset"
        )

    def test_f5n7_lattafa_perfumes_excluded(self):
        """'lattafa perfumes' → 'perfumes' in _SKIP_TOKENS → distinctive={'lattafa'} ⊆ {'lattafa'}."""
        mod = self._import_harvest()
        assert "perfumes" in mod._SKIP_TOKENS
        btm = {"lattafa": "Lattafa"}
        rs_rows = self._make_rs_rows([["lattafa perfumes"] * 5])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("lattafa perfumes", "lattafa") not in result, (
            "'lattafa perfumes' should be filtered: perfumes is skip token, leaving brand-only"
        )

    # ── Positive cases (KEPT — have genuine product qualifier) ────────────────

    def test_f5p1_burberry_goddess_kept(self):
        """'burberry goddess' → 'goddess' ∉ brand tokens → has product qualifier → kept."""
        mod = self._import_harvest()
        btm = {"burberry": "Burberry"}
        rs_rows = self._make_rs_rows([["burberry goddess"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("burberry goddess", "burberry") in result, (
            "'burberry goddess' should be kept: 'goddess' is a genuine product qualifier"
        )

    def test_f5p2_chanel_chance_kept(self):
        """'chanel chance' → 'chance' ∉ {'chanel'} → has product qualifier → kept."""
        mod = self._import_harvest()
        btm = {"chanel": "Chanel"}
        rs_rows = self._make_rs_rows([["chanel chance"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("chanel chance", "chanel") in result, (
            "'chanel chance' should be kept: 'chance' is a genuine product qualifier"
        )

    def test_f5p3_arabiyat_prestige_kept(self):
        """'arabiyat prestige' with brand 'Arabiyat' → 'prestige' ∉ {'arabiyat'} → kept.

        'prestige' is in _HARVEST_CONTEXT_SKIP_TOKENS but is NOT stripped from
        the distinctiveness check — it's a genuine product qualifier token here.
        Only _BRIDGE_WORDS | _SKIP_TOKENS are stripped; _HARVEST_CONTEXT_SKIP_TOKENS
        only blocks the brand anchor role, not the product-qualifier detection.
        """
        mod = self._import_harvest()
        btm = {"arabiyat": "Arabiyat"}
        rs_rows = self._make_rs_rows([["arabiyat prestige"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("arabiyat prestige", "arabiyat") in result, (
            "'arabiyat prestige' should be kept: 'prestige' is a genuine product qualifier"
        )

    def test_f5p4_dossier_musky_gaiac_kept(self):
        """'dossier musky gaiac' → 'musky'/'gaiac' ∉ {'dossier'} → kept."""
        mod = self._import_harvest()
        btm = {"dossier": "Dossier"}
        rs_rows = self._make_rs_rows([["dossier musky gaiac"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("dossier musky gaiac", "dossier") in result

    def test_f5p5_valentino_born_in_roma_kept(self):
        """'valentino born in roma' → 'born'/'roma' ∉ {'valentino'} → kept.
        Note: 'in' is a bridge word but 'born' and 'roma' are product qualifiers."""
        mod = self._import_harvest()
        btm = {"valentino": "Valentino"}
        rs_rows = self._make_rs_rows([["valentino born in roma"] * 3])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 1)
        assert ("valentino born in roma", "valentino") in result, (
            "'valentino born in roma' should be kept: 'born' and 'roma' are product qualifiers"
        )

    # ── Structure tests ───────────────────────────────────────────────────────

    def test_f5s1_bridge_words_is_frozenset(self):
        """_BRIDGE_WORDS must be a frozenset."""
        mod = self._import_harvest()
        assert hasattr(mod, "_BRIDGE_WORDS")
        assert isinstance(mod._BRIDGE_WORDS, frozenset)
        assert len(mod._BRIDGE_WORDS) >= 10

    def test_f5s2_expected_bridge_words_present(self):
        """Expected bridge words present in _BRIDGE_WORDS."""
        mod = self._import_harvest()
        for word in ["by", "from", "de", "du", "le", "la", "for", "of", "in", "the", "al"]:
            assert word in mod._BRIDGE_WORDS, f"{word!r} must be in _BRIDGE_WORDS"

    def test_f5s3_vertus_amber_elixir_survives_filter5(self):
        """'vertus amber elixir' must survive filter 5: 'amber'/'elixir' ∉ {'vertus'}."""
        mod = self._import_harvest()
        btm = {"vertus": "Vertus"}
        rs_rows = self._make_rs_rows([
            ["vertus amber elixir"],
            ["vertus amber elixir"],
        ])
        result = mod._compute_candidates(rs_rows, btm, frozenset(), frozenset(), 2)
        assert ("vertus amber elixir", "vertus") in result, (
            "'vertus amber elixir' should survive filter 5 — has product qualifier tokens"
        )
