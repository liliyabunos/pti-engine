"""Unit tests for emerging signals subphrase suppression logic.

Tests _is_subphrase() and _suppress_subphrases() from the v2 emerging endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pytest

from perfume_trend_sdk.api.routes.emerging import _is_subphrase, _suppress_subphrases


# ---------------------------------------------------------------------------
# Minimal stub that satisfies the attribute access in _suppress_subphrases
# ---------------------------------------------------------------------------

@dataclass
class _StubRow:
    normalized_text: str
    emerging_score: float = 1.0
    id: int = 0
    display_name: str = ""
    candidate_type: str = "perfume"
    total_mentions: int = 1
    distinct_channels_count: int = 1
    weighted_channel_score: float = 1.0
    top_channel_title: Optional[str] = None
    top_channel_tier: Optional[str] = None
    first_seen: str = "2026-05-01"
    last_seen: str = "2026-05-01"
    days_active: int = 1
    is_in_resolver: bool = False
    is_in_entity_market: bool = False


def _rows(*texts_scores) -> List[_StubRow]:
    """Build a list of stubs from (text, score) pairs, pre-sorted as the endpoint does."""
    rows = [_StubRow(normalized_text=t, emerging_score=s) for t, s in texts_scores]
    # Mirror endpoint sort: score DESC, len DESC
    rows.sort(key=lambda r: (-r.emerging_score, -len(r.normalized_text)))
    return rows


# ---------------------------------------------------------------------------
# _is_subphrase tests
# ---------------------------------------------------------------------------

class TestIsSubphrase:
    def test_prefix_subphrase(self):
        assert _is_subphrase("jean paul", "jean paul gaultier") is True

    def test_suffix_subphrase(self):
        assert _is_subphrase("paul gaultier", "jean paul gaultier") is True

    def test_interior_subphrase(self):
        assert _is_subphrase("paul", "jean paul gaultier") is True

    def test_identical_not_subphrase(self):
        # same length → not a subphrase (equal, not strictly shorter)
        assert _is_subphrase("jean paul gaultier", "jean paul gaultier") is False

    def test_longer_not_subphrase(self):
        assert _is_subphrase("jean paul gaultier le beau", "jean paul gaultier") is False

    def test_armani_prefix(self):
        assert _is_subphrase("armani stronger", "armani stronger with you") is True

    def test_armani_middle(self):
        assert _is_subphrase("armani stronger with", "armani stronger with you") is True

    def test_unrelated_phrases(self):
        assert _is_subphrase("khadlaj icon", "jean paul gaultier") is False
        assert _is_subphrase("givenchy gentleman", "armani stronger with you") is False

    def test_single_word_in_multiword(self):
        assert _is_subphrase("stronger", "armani stronger with you") is True

    def test_empty_string(self):
        # Empty string splits to [] — 0-length prefix of anything; by convention False
        assert _is_subphrase("", "jean paul gaultier") is False


# ---------------------------------------------------------------------------
# _suppress_subphrases tests
# ---------------------------------------------------------------------------

class TestSuppressSubphrases:
    def test_jean_paul_gaultier(self):
        """jean paul and paul gaultier suppressed by jean paul gaultier."""
        rows = _rows(
            ("jean paul gaultier", 6.14),
            ("jean paul", 6.14),
            ("paul gaultier", 6.14),
        )
        result = _suppress_subphrases(rows)
        texts = [r.normalized_text for r in result]
        assert texts == ["jean paul gaultier"]

    def test_armani_stronger_with_you(self):
        """armani stronger / armani stronger with suppressed by armani stronger with you."""
        rows = _rows(
            ("armani stronger with you", 4.48),
            ("armani stronger with", 4.48),
            ("armani stronger", 4.48),
        )
        result = _suppress_subphrases(rows)
        texts = [r.normalized_text for r in result]
        assert texts == ["armani stronger with you"]

    def test_unrelated_kept(self):
        """Unrelated candidates are not suppressed."""
        rows = _rows(
            ("jean paul gaultier", 6.14),
            ("jean paul", 6.14),
            ("khadlaj icon", 5.03),
            ("givenchy gentleman society", 5.70),
        )
        result = _suppress_subphrases(rows)
        texts = [r.normalized_text for r in result]
        assert "jean paul gaultier" in texts
        assert "khadlaj icon" in texts
        assert "givenchy gentleman society" in texts
        assert "jean paul" not in texts

    def test_givenchy_subphrases(self):
        """givenchy gentleman and gentleman society suppressed by givenchy gentleman society."""
        rows = _rows(
            ("givenchy gentleman society", 5.70),
            ("givenchy gentleman", 5.70),
            ("gentleman society", 5.70),
        )
        result = _suppress_subphrases(rows)
        texts = [r.normalized_text for r in result]
        assert texts == ["givenchy gentleman society"]

    def test_higher_score_shorter_kept(self):
        """A shorter phrase with strictly higher score is NOT suppressed by a lower-score longer one."""
        rows = _rows(
            ("jean paul", 8.0),           # higher score → comes first after sort
            ("jean paul gaultier", 6.0),   # lower score → comes after
        )
        result = _suppress_subphrases(rows)
        texts = [r.normalized_text for r in result]
        # jean paul accepted first; jean paul gaultier is NOT a subphrase of jean paul → also kept
        assert "jean paul" in texts
        assert "jean paul gaultier" in texts

    def test_empty_input(self):
        assert _suppress_subphrases([]) == []

    def test_single_item(self):
        rows = _rows(("creed aventus", 5.0))
        assert len(_suppress_subphrases(rows)) == 1

    def test_realistic_top10(self):
        """Simulate the actual top-10 before and after suppression."""
        rows = _rows(
            ("jean paul gaultier", 6.143),
            ("jean paul", 6.143),
            ("paul gaultier", 6.143),
            ("givenchy gentleman society", 5.697),
            ("gentleman society", 5.697),
            ("givenchy gentleman", 5.697),
            ("khadlaj icon", 5.027),
            ("armani stronger with you", 4.480),
            ("armani stronger with", 4.480),
            ("armani stronger", 4.480),
        )
        result = _suppress_subphrases(rows)
        texts = [r.normalized_text for r in result]
        assert texts == [
            "jean paul gaultier",
            "givenchy gentleman society",
            "khadlaj icon",
            "armani stronger with you",
        ]
