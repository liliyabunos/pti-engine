from __future__ import annotations

import pytest

from perfume_trend_sdk.analysis.market_signals.detector import (
    BreakoutDetector,
    DEFAULT_THRESHOLDS,
)


def _snap(
    entity_id: str = "Parfums de Marly Delina",
    score: float = 30.0,
    momentum: float = 1.0,
    acceleration: float = 0.0,
    mention_count: float = 3.0,
) -> dict:
    return {
        "entity_id": entity_id,
        "composite_market_score": score,
        "momentum": momentum,
        "acceleration": acceleration,
        "mention_count": mention_count,
    }


DATE = "2026-04-10"


@pytest.fixture
def detector() -> BreakoutDetector:
    return BreakoutDetector()


# ---------------------------------------------------------------------------
# new_entry
# ---------------------------------------------------------------------------

def test_new_entry_when_no_prev_and_has_mentions(detector: BreakoutDetector) -> None:
    signals = detector.detect(_snap(mention_count=3.0), previous=None, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "new_entry" in types


def test_no_new_entry_when_no_prev_and_no_mentions(detector: BreakoutDetector) -> None:
    signals = detector.detect(_snap(mention_count=0.0), previous=None, detected_at=DATE)
    assert signals == []


def test_new_entry_stops_further_detection(detector: BreakoutDetector) -> None:
    """On first appearance, only new_entry is returned — no other signals."""
    snap = _snap(score=100.0, momentum=10.0, mention_count=5.0)
    signals = detector.detect(snap, previous=None, detected_at=DATE)
    assert len(signals) == 1
    assert signals[0]["signal_type"] == "new_entry"


# ---------------------------------------------------------------------------
# breakout
# ---------------------------------------------------------------------------

def test_breakout_detected_when_score_surges(detector: BreakoutDetector) -> None:
    cur = _snap(score=45.0)
    prev = _snap(score=20.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" in types


def test_breakout_not_detected_when_score_below_min(detector: BreakoutDetector) -> None:
    cur = _snap(score=10.0)  # below breakout_min_score=20
    prev = _snap(score=5.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" not in types


def test_breakout_not_detected_when_growth_below_threshold(detector: BreakoutDetector) -> None:
    cur = _snap(score=25.0)
    prev = _snap(score=24.0)  # growth = 4% < 50%
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" not in types


def test_breakout_from_zero_prev(detector: BreakoutDetector) -> None:
    """Score appearing from 0 counts as infinite growth → breakout."""
    cur = _snap(score=25.0)
    prev = _snap(score=0.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" in types


def test_breakout_includes_growth_pct_in_details(detector: BreakoutDetector) -> None:
    cur = _snap(score=45.0)
    prev = _snap(score=20.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    breakout = next(s for s in signals if s["signal_type"] == "breakout")
    assert "growth_pct" in breakout["metadata"]
    assert breakout["metadata"]["growth_pct"] > 0


# ---------------------------------------------------------------------------
# acceleration_spike
# ---------------------------------------------------------------------------

def test_acceleration_spike_detected_when_momentum_high(detector: BreakoutDetector) -> None:
    cur = _snap(score=30.0, momentum=2.0, acceleration=1.0)
    prev = _snap(score=20.0, momentum=1.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "acceleration_spike" in types


def test_acceleration_spike_not_detected_when_momentum_low(detector: BreakoutDetector) -> None:
    cur = _snap(score=30.0, momentum=1.0, acceleration=0.1)
    prev = _snap(score=28.0, momentum=0.9)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "acceleration_spike" not in types


def test_acceleration_spike_includes_momentum_in_details(detector: BreakoutDetector) -> None:
    cur = _snap(momentum=2.0, acceleration=1.2)
    prev = _snap()
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    spike = next((s for s in signals if s["signal_type"] == "acceleration_spike"), None)
    assert spike is not None
    assert "momentum" in spike["metadata"]


# ---------------------------------------------------------------------------
# reversal
# ---------------------------------------------------------------------------

def test_reversal_detected_when_score_drops_sharply(detector: BreakoutDetector) -> None:
    cur = _snap(score=10.0)
    prev = _snap(score=40.0)  # 75% drop → reversal
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "reversal" in types


def test_reversal_not_detected_when_prev_score_low(detector: BreakoutDetector) -> None:
    cur = _snap(score=5.0)
    prev = _snap(score=10.0)  # below reversal_prev_min_score=15
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "reversal" not in types


def test_reversal_not_detected_when_drop_small(detector: BreakoutDetector) -> None:
    cur = _snap(score=35.0)
    prev = _snap(score=40.0)  # 12.5% drop < 40%
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "reversal" not in types


def test_reversal_includes_drop_pct_in_details(detector: BreakoutDetector) -> None:
    cur = _snap(score=10.0)
    prev = _snap(score=40.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    rev = next(s for s in signals if s["signal_type"] == "reversal")
    assert "drop_pct" in rev["metadata"]
    assert rev["metadata"]["drop_pct"] > 0


# ---------------------------------------------------------------------------
# detect_batch
# ---------------------------------------------------------------------------

def test_detect_batch_processes_multiple_entities(detector: BreakoutDetector) -> None:
    snapshots = [
        _snap("Entity A", score=50.0, momentum=2.0, mention_count=5.0),
        _snap("Entity B", score=10.0, mention_count=0.0),
    ]
    prev = {
        "Entity A": _snap("Entity A", score=20.0),
    }
    signals = detector.detect_batch(snapshots, prev, DATE)
    entity_ids = {s["entity_id"] for s in signals}
    assert "Entity A" in entity_ids
    # Entity B has no prev and no mentions → no signals


def test_detect_batch_returns_empty_when_no_signals(detector: BreakoutDetector) -> None:
    snapshots = [_snap(score=5.0, momentum=0.5, mention_count=0.0)]
    signals = detector.detect_batch(snapshots, {}, DATE)
    assert signals == []


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------

def test_custom_thresholds_applied(monkeypatch) -> None:
    strict = {**DEFAULT_THRESHOLDS, "breakout_min_score": 100.0}
    detector = BreakoutDetector(thresholds=strict)
    cur = _snap(score=50.0)
    prev = _snap(score=10.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" not in types  # 50 < 100 → not a breakout under strict threshold


def test_signal_entity_id_matches_input(detector: BreakoutDetector) -> None:
    snap = _snap("My Special Perfume", mention_count=5.0)
    signals = detector.detect(snap, previous=None, detected_at=DATE)
    assert all(s["entity_id"] == "My Special Perfume" for s in signals)


def test_signal_detected_at_matches_date(detector: BreakoutDetector) -> None:
    snap = _snap(mention_count=4.0)
    signals = detector.detect(snap, previous=None, detected_at="2026-01-15")
    assert all(s["detected_at"] == "2026-01-15" for s in signals)


# ---------------------------------------------------------------------------
# Risk #3 — TikTok false breakout suppression
#
# TikTok produces fast spikes: 1 viral video → huge engagement but low
# mention_count (1.3 — single-platform weight).  breakout_min_mentions=2.0
# must suppress these single-item spikes.
# ---------------------------------------------------------------------------

def test_single_tiktok_video_breakout_suppressed(detector: BreakoutDetector) -> None:
    """
    One TikTok video → mention_count = 1.3 (platform weight).
    Score may be high from engagement, but breakout must be suppressed
    because 1.3 < breakout_min_mentions=2.0.
    """
    # mention_count=1.3 simulates a single TikTok post at platform weight 1.3×
    cur = _snap(score=55.0, momentum=3.0, mention_count=1.3)
    prev = _snap(score=10.0, momentum=1.0, mention_count=0.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" not in types, (
        "Single TikTok video (mention_count=1.3) must not produce a breakout — "
        f"signals fired: {types}"
    )


def test_two_tiktok_videos_can_breakout(detector: BreakoutDetector) -> None:
    """
    Two TikTok videos → mention_count = 2.6 (2 × 1.3).
    This meets breakout_min_mentions=2.0, so breakout is allowed when
    score and growth also qualify.
    """
    cur = _snap(score=55.0, momentum=2.0, mention_count=2.6)
    prev = _snap(score=10.0, momentum=1.0, mention_count=0.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" in types, (
        "Two TikTok videos (mention_count=2.6) should qualify for breakout — "
        f"signals fired: {types}"
    )


def test_one_tiktok_one_youtube_can_breakout(detector: BreakoutDetector) -> None:
    """
    One TikTok (1.3) + one YouTube (1.2) → mention_count = 2.5.
    Meets the threshold — cross-platform breakout must fire.
    """
    cur = _snap(score=50.0, momentum=2.0, mention_count=2.5)
    prev = _snap(score=10.0, momentum=1.0, mention_count=0.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "breakout" in types, (
        "TikTok + YouTube combined (mention_count=2.5) should qualify for breakout — "
        f"signals fired: {types}"
    )


def test_single_tiktok_acceleration_spike_still_fires(detector: BreakoutDetector) -> None:
    """
    acceleration_spike has no mention_count gate — it is momentum-driven.
    A single viral TikTok with high momentum must still produce an
    acceleration_spike even when breakout is suppressed.
    """
    cur = _snap(score=30.0, momentum=2.5, acceleration=1.5, mention_count=1.3)
    prev = _snap(score=20.0, momentum=1.0, mention_count=0.0)
    signals = detector.detect(cur, previous=prev, detected_at=DATE)
    types = [s["signal_type"] for s in signals]
    assert "acceleration_spike" in types
    assert "breakout" not in types
