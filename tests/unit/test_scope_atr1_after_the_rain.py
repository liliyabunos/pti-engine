"""SCOPE-ATR1 — After the Rain (Declaration Grooming) Out-of-Scope Guard Tests

Scope decision (2026-05-19): Declaration Grooming "After the Rain" is a shaving soap +
aftershave splash — non-perfume grooming product. Company went EOB 2026-01-31.
Bare alias "after the rain" requires "declaration" or "grooming" in ±10-token context.

RS evidence: 2 rows — FemFragLab content likely about Solstice Scents "After the Rain" EDP
(a real perfume, not in entity_market). SIG-ID1 Class 2 (Wrong Identity) pattern.

Test suites:
  N1–N3  "after the rain" blocked without declaration/grooming context
  P1–P2  "after the rain" resolves with declaration or grooming context
  P3     Branded full-name alias still resolves correctly
  R1     Creed Aventus unaffected (regression)
  R2     Orange Blossom (Angela Flanders) guard still active (regression)
  R3     Be Cool (Avon) guard still active (regression)
  G1     "after the rain" present in _AMBIGUOUS_PHRASE_GUARD
  G2     Guard requires "declaration" or "grooming" tokens
  G3     Guard entry is list of frozensets
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


_TEST_ALIASES: Dict[str, Dict[str, Any]] = {
    # The guarded bare alias
    "after the rain":                     _make_entity(5001, "After the Rain"),
    # Branded full-name alias (always active)
    "declaration grooming after the rain": _make_entity(5001, "After the Rain"),
    # Brand context tokens
    "declaration":                         _make_entity(9001, "Declaration Grooming Brand"),
    "grooming":                            _make_entity(9002, "Declaration Grooming Brand"),
    # Regression entries
    "creed aventus":                       _make_entity(2001, "Creed Aventus"),
    "orange blossom":                      _make_entity(7001, "Orange Blossom"),
    "angela":                              _make_entity(7002, "Angela Flanders Brand"),
    "be cool":                             _make_entity(8012, "Be Cool"),
    "avon":                                _make_entity(9011, "Avon Brand"),
}


def _resolver() -> PerfumeResolver:
    return _make_resolver_with_aliases(_TEST_ALIASES)


# ---------------------------------------------------------------------------
# N — Negative: bare phrase BLOCKED without brand token
# ---------------------------------------------------------------------------

class TestNegativeCasesATR1:

    def test_N1_after_the_rain_blocked_in_femfraglab_context(self):
        """FemFragLab collection post — 'after the rain' as scent name in generic context."""
        r = _resolver()
        results = r.resolve_text(
            "ranking and reviewing my full bottle collection after the rain is such a beautiful scent"
        )
        assert "After the Rain" not in _names(results)

    def test_N2_after_the_rain_blocked_in_weather_description(self):
        """Literal weather phrase — no brand context."""
        r = _resolver()
        results = r.resolve_text("the smell after the rain on a summer morning is incredible")
        assert "After the Rain" not in _names(results)

    def test_N3_after_the_rain_blocked_in_fragrance_review(self):
        """Fragrance review post without Declaration Grooming mention."""
        r = _resolver()
        results = r.resolve_text("I love the fresh petrichor after the rain notes in this perfume")
        assert "After the Rain" not in _names(results)


# ---------------------------------------------------------------------------
# P — Positive: resolves WITH brand token in context
# ---------------------------------------------------------------------------

class TestPositiveCasesATR1:

    def test_P1_after_the_rain_resolves_with_declaration_token(self):
        """'declaration' within proximity — resolves correctly."""
        r = _resolver()
        results = r.resolve_text("declaration grooming after the rain soap review")
        assert "After the Rain" in _names(results)

    def test_P2_after_the_rain_resolves_with_grooming_token(self):
        """'grooming' within proximity — resolves correctly."""
        r = _resolver()
        results = r.resolve_text("the after the rain grooming soap is sold out")
        assert "After the Rain" in _names(results)

    def test_P3_branded_full_name_alias_resolves_always(self):
        """Full branded alias 'declaration grooming after the rain' resolves directly."""
        r = _resolver()
        results = r.resolve_text("declaration grooming after the rain is a legendary soap")
        assert "After the Rain" in _names(results)


# ---------------------------------------------------------------------------
# R — Regression: existing guards unaffected
# ---------------------------------------------------------------------------

class TestRegressionATR1:

    def test_R1_creed_aventus_unaffected(self):
        """Creed Aventus resolves normally — not impacted by ATR1 guard."""
        r = _resolver()
        results = r.resolve_text("creed aventus is the benchmark fragrance")
        assert "Creed Aventus" in _names(results)

    def test_R2_orange_blossom_guard_still_active(self):
        """Orange Blossom (Angela Flanders) guard unaffected — SIG-QA1-REPAIR regression."""
        r = _resolver()
        results = r.resolve_text("I love orange blossom as a top note in my fragrances")
        assert "Orange Blossom" not in _names(results)

    def test_R3_be_cool_guard_still_active(self):
        """Be Cool (Avon) guard unaffected — SIG-QA1-BATCH2 regression."""
        r = _resolver()
        results = r.resolve_text("stay calm and be cool this summer vibes")
        assert "Be Cool" not in _names(results)


# ---------------------------------------------------------------------------
# G — Guard structure invariants
# ---------------------------------------------------------------------------

class TestGuardStructureATR1:

    def test_G1_after_the_rain_in_guard(self):
        """'after the rain' must be present in _AMBIGUOUS_PHRASE_GUARD."""
        assert "after the rain" in _AMBIGUOUS_PHRASE_GUARD

    def test_G2_guard_requires_declaration_or_grooming(self):
        """Guard must require 'declaration' or 'grooming' brand tokens."""
        sets = _AMBIGUOUS_PHRASE_GUARD["after the rain"]
        all_tokens = set()
        for fs in sets:
            all_tokens |= fs
        assert "declaration" in all_tokens or "grooming" in all_tokens, (
            f"Expected 'declaration' or 'grooming' in guard tokens, got: {all_tokens}"
        )

    def test_G3_guard_entry_is_list_of_frozensets(self):
        """Guard value must be a list of frozensets."""
        val = _AMBIGUOUS_PHRASE_GUARD["after the rain"]
        assert isinstance(val, list)
        for fs in val:
            assert isinstance(fs, frozenset)
