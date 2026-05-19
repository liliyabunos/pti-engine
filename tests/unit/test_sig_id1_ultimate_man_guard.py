"""SIG-ID1 Class 2 — Ultimate Man (Korloff) Wrong Identity Guard Tests

Identity audit (2026-05-19): All 5 RS rows for "Ultimate Man" are Jeremy Fragrance
YouTube videos titled "Ultimate MAN Fragrance: #jeremyfragrance #fragrance #cologne
#perfume #parfum". Jeremy Fragrance has his own fragrance line "ULTIMATE" — those
videos reference his product, not Korloff's. Korloff brand context = 0%.

SIG-QA2 gate false-passed at score=0.540 (D2=1.0 from #fragrance hashtags, D1=0,
D4=0). Exposes PV-008-B2: brandless entity in high-fragrance-context source.

Guard: "ultimate man" requires "korloff" in ±10-token proximity to resolve.

Test suites:
  N1–N3  "ultimate man" blocked without korloff context (Jeremy Fragrance titles)
  P1–P2  "ultimate man" resolves with korloff context
  P3     Branded full-name alias "korloff ultimate man" resolves directly
  R1     Creed Aventus unaffected (regression)
  R2     Be Cool (Avon) guard still active (regression)
  R3     After the Rain (Declaration Grooming) guard still active (regression)
  G1     "ultimate man" present in _AMBIGUOUS_PHRASE_GUARD
  G2     Guard requires "korloff" token
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
    "ultimate man":              _make_entity(7701, "Ultimate Man"),
    # Branded full-name alias (always active)
    "korloff ultimate man":      _make_entity(7701, "Ultimate Man"),
    # Brand context token
    "korloff":                   _make_entity(9901, "Korloff Brand"),
    # Regression entries
    "creed aventus":             _make_entity(2001, "Creed Aventus"),
    "be cool":                   _make_entity(8012, "Be Cool"),
    "avon":                      _make_entity(9011, "Avon Brand"),
    "after the rain":            _make_entity(5001, "After the Rain"),
    "declaration":               _make_entity(9002, "Declaration Grooming Brand"),
}


def _resolver() -> PerfumeResolver:
    return _make_resolver_with_aliases(_TEST_ALIASES)


# ---------------------------------------------------------------------------
# N — Negative: bare phrase BLOCKED without korloff token
# ---------------------------------------------------------------------------

class TestNegativeCasesUltimateMan:

    def test_N1_ultimate_man_blocked_in_jeremy_fragrance_title(self):
        """Jeremy Fragrance YouTube title — 'ultimate man' without korloff context."""
        r = _resolver()
        results = r.resolve_text(
            "ultimate MAN fragrance jeremyfragrance fragrance cologne perfume parfum"
        )
        assert "Ultimate Man" not in _names(results)

    def test_N2_ultimate_man_blocked_in_generic_fragrance_review(self):
        """Generic fragrance review mentioning 'ultimate man' without brand context."""
        r = _resolver()
        results = r.resolve_text(
            "looking for the ultimate man fragrance for everyday wear"
        )
        assert "Ultimate Man" not in _names(results)

    def test_N3_ultimate_man_blocked_in_hashtag_content(self):
        """Hashtag-heavy content without Korloff mention."""
        r = _resolver()
        results = r.resolve_text(
            "this is the ultimate man scent #fragrance #cologne #perfume"
        )
        assert "Ultimate Man" not in _names(results)


# ---------------------------------------------------------------------------
# P — Positive: resolves WITH korloff token in context
# ---------------------------------------------------------------------------

class TestPositiveCasesUltimateMan:

    def test_P1_ultimate_man_resolves_with_korloff_token(self):
        """'korloff' within proximity — resolves correctly."""
        r = _resolver()
        results = r.resolve_text("korloff ultimate man review — strong projection")
        assert "Ultimate Man" in _names(results)

    def test_P2_ultimate_man_resolves_with_korloff_nearby(self):
        """'korloff' appearing near 'ultimate man' — resolves correctly."""
        r = _resolver()
        results = r.resolve_text("picked up korloff ultimate man at the duty free")
        assert "Ultimate Man" in _names(results)

    def test_P3_branded_full_name_alias_resolves_always(self):
        """Full branded alias 'korloff ultimate man' resolves directly."""
        r = _resolver()
        results = r.resolve_text("the korloff ultimate man is seriously underrated")
        assert "Ultimate Man" in _names(results)


# ---------------------------------------------------------------------------
# R — Regression: existing guards and entities unaffected
# ---------------------------------------------------------------------------

class TestRegressionUltimateMan:

    def test_R1_creed_aventus_unaffected(self):
        """Creed Aventus resolves normally — not impacted by Ultimate Man guard."""
        r = _resolver()
        results = r.resolve_text("creed aventus is the benchmark fragrance")
        assert "Creed Aventus" in _names(results)

    def test_R2_be_cool_guard_still_active(self):
        """Be Cool (Avon) guard unaffected — SIG-QA1-BATCH2 regression."""
        r = _resolver()
        results = r.resolve_text("stay calm and be cool this summer vibes")
        assert "Be Cool" not in _names(results)

    def test_R3_after_the_rain_guard_still_active(self):
        """After the Rain (Declaration Grooming) guard unaffected — SCOPE-ATR1 regression."""
        r = _resolver()
        results = r.resolve_text("the smell after the rain on a summer morning is incredible")
        assert "After the Rain" not in _names(results)


# ---------------------------------------------------------------------------
# G — Guard structure invariants
# ---------------------------------------------------------------------------

class TestGuardStructureUltimateMan:

    def test_G1_ultimate_man_in_guard(self):
        """'ultimate man' must be present in _AMBIGUOUS_PHRASE_GUARD."""
        assert "ultimate man" in _AMBIGUOUS_PHRASE_GUARD

    def test_G2_guard_requires_korloff(self):
        """Guard must require 'korloff' brand token."""
        sets = _AMBIGUOUS_PHRASE_GUARD["ultimate man"]
        all_tokens = set()
        for fs in sets:
            all_tokens |= fs
        assert "korloff" in all_tokens, (
            f"Expected 'korloff' in guard tokens, got: {all_tokens}"
        )

    def test_G3_guard_entry_is_list_of_frozensets(self):
        """Guard value must be a list of frozensets."""
        val = _AMBIGUOUS_PHRASE_GUARD["ultimate man"]
        assert isinstance(val, list)
        for fs in val:
            assert isinstance(fs, frozenset)
