from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.scorers.note_momentum.scorer import (
    compute_trend_delta,
    direction_from_delta,
    load_note_scores,
    save_note_scores,
)
from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownPublisher


# ---------------------------------------------------------------------------
# compute_trend_delta
# ---------------------------------------------------------------------------

def _score(val: float) -> dict:
    return {"note_score": val, "mention_count": 1, "engagement_weight": 0.0,
            "official_note_bonus": 0, "perfumes": []}


def test_delta_positive():
    current = {"vanilla": _score(3.0)}
    previous = {"vanilla": _score(1.0)}
    deltas = compute_trend_delta(current, previous)
    assert deltas["vanilla"]["delta"] == pytest.approx(2.0)
    assert deltas["vanilla"]["direction"] == "up"


def test_delta_negative():
    current = {"vanilla": _score(1.0)}
    previous = {"vanilla": _score(3.0)}
    deltas = compute_trend_delta(current, previous)
    assert deltas["vanilla"]["delta"] == pytest.approx(-2.0)
    assert deltas["vanilla"]["direction"] == "down"


def test_delta_stable():
    current = {"amber": _score(1.0)}
    previous = {"amber": _score(1.0)}
    deltas = compute_trend_delta(current, previous)
    assert deltas["amber"]["delta"] == pytest.approx(0.0)
    assert deltas["amber"]["direction"] == "flat"


def test_delta_new_note_no_previous():
    """Note appears this period but was absent last period → previous_score = 0."""
    current = {"oud": _score(1.5)}
    previous = {}
    deltas = compute_trend_delta(current, previous)
    assert deltas["oud"]["previous_score"] == 0.0
    assert deltas["oud"]["delta"] == pytest.approx(1.5)
    assert deltas["oud"]["direction"] == "up"


def test_delta_disappeared_note():
    """Note was present last period but absent this period → current_score = 0."""
    current = {}
    previous = {"rose": _score(2.0)}
    deltas = compute_trend_delta(current, previous)
    assert deltas["rose"]["current_score"] == 0.0
    assert deltas["rose"]["delta"] == pytest.approx(-2.0)
    assert deltas["rose"]["direction"] == "down"


def test_delta_covers_union_of_both_periods():
    current = {"vanilla": _score(2.0), "amber": _score(1.0)}
    previous = {"amber": _score(0.5), "rose": _score(3.0)}
    deltas = compute_trend_delta(current, previous)
    assert set(deltas.keys()) == {"vanilla", "amber", "rose"}


def test_delta_above_dead_zone_is_up():
    current = {"amber": _score(1.1)}
    previous = {"amber": _score(1.0)}
    deltas = compute_trend_delta(current, previous)
    assert deltas["amber"]["direction"] == "up"


def test_delta_below_dead_zone_is_down():
    current = {"amber": _score(0.9)}
    previous = {"amber": _score(1.0)}
    deltas = compute_trend_delta(current, previous)
    assert deltas["amber"]["direction"] == "down"


def test_delta_within_dead_zone_is_flat():
    """abs(delta) < 0.05 → flat regardless of sign."""
    current = {"amber": _score(1.04)}
    previous = {"amber": _score(1.0)}
    deltas = compute_trend_delta(current, previous)
    assert deltas["amber"]["direction"] == "flat"

    current2 = {"amber": _score(0.96)}
    deltas2 = compute_trend_delta(current2, previous)
    assert deltas2["amber"]["direction"] == "flat"


def test_delta_empty_inputs():
    assert compute_trend_delta({}, {}) == {}


# ---------------------------------------------------------------------------
# direction_from_delta
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta,expected", [
    (1.0,   "up"),
    (0.05,  "up"),      # boundary: exactly 0.05 → up
    (0.049, "flat"),    # just inside dead zone
    (0.0,   "flat"),
    (-0.049, "flat"),   # just inside dead zone
    (-0.05,  "down"),   # boundary: exactly -0.05 → down
    (-1.0,   "down"),
])
def test_direction_from_delta(delta, expected):
    assert direction_from_delta(delta) == expected


# ---------------------------------------------------------------------------
# save_note_scores / load_note_scores
# ---------------------------------------------------------------------------

def test_save_and_load_round_trip(tmp_path):
    scores = {
        "vanilla": {"note_score": 3.5, "mention_count": 4, "engagement_weight": 0.01,
                    "official_note_bonus": 1, "perfumes": ["Delina", "Tobacco Vanille"]},
        "amber": {"note_score": 1.2, "mention_count": 2, "engagement_weight": 0.0,
                  "official_note_bonus": 0, "perfumes": []},
    }
    path = str(tmp_path / "note_scores.json")
    save_note_scores(scores, path)
    loaded = load_note_scores(path)

    assert loaded["vanilla"]["note_score"] == 3.5
    assert loaded["amber"]["note_score"] == 1.2
    assert "Delina" in loaded["vanilla"]["perfumes"]


def test_load_missing_file_returns_empty(tmp_path):
    result = load_note_scores(str(tmp_path / "nonexistent.json"))
    assert result == {}


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "deep" / "scores.json")
    save_note_scores({"vanilla": _score(1.0)}, path)
    assert Path(path).exists()


def test_load_corrupt_file_returns_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON", encoding="utf-8")
    assert load_note_scores(str(bad)) == {}


# ---------------------------------------------------------------------------
# Publisher uses real delta arrows
# ---------------------------------------------------------------------------

def test_report_uses_delta_direction_not_absolute(tmp_path):
    """When previous_note_scores provided, arrows must reflect delta, not abs score."""
    # vanilla: small absolute score but grew a lot → ↑
    # amber: large absolute score but shrank → ↓
    current_scores = {
        "vanilla": {"note_score": 0.8, "mention_count": 1, "engagement_weight": 0.0,
                    "official_note_bonus": 0, "perfumes": []},
        "amber": {"note_score": 3.0, "mention_count": 3, "engagement_weight": 0.0,
                  "official_note_bonus": 0, "perfumes": []},
    }
    previous_scores = {
        "vanilla": {"note_score": 0.1, "mention_count": 0, "engagement_weight": 0.0,
                    "official_note_bonus": 0, "perfumes": []},
        "amber": {"note_score": 5.0, "mention_count": 5, "engagement_weight": 0.0,
                  "official_note_bonus": 0, "perfumes": []},
    }

    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=current_scores,
        previous_note_scores=previous_scores,
    )

    content = Path(out).read_text(encoding="utf-8")

    # Find lines with note names
    lines = content.splitlines()
    vanilla_line = next(l for l in lines if "Vanilla" in l)
    amber_line = next(l for l in lines if "Amber" in l)

    assert "↑" in vanilla_line, f"Expected ↑ for growing vanilla, got: {vanilla_line}"
    assert "↓" in amber_line, f"Expected ↓ for shrinking amber, got: {amber_line}"


def test_report_shows_delta_value_in_parentheses(tmp_path):
    current_scores = {
        "vanilla": {"note_score": 3.0, "mention_count": 3, "engagement_weight": 0.0,
                    "official_note_bonus": 0, "perfumes": []},
    }
    previous_scores = {
        "vanilla": {"note_score": 1.0, "mention_count": 1, "engagement_weight": 0.0,
                    "official_note_bonus": 0, "perfumes": []},
    }
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=current_scores,
        previous_note_scores=previous_scores,
    )
    content = Path(out).read_text(encoding="utf-8")
    # delta = +2.00 should appear
    assert "+2.00" in content


def test_report_delta_header_note_when_history_provided(tmp_path):
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores={"vanilla": _score(1.0)},
        previous_note_scores={"vanilla": _score(0.5)},
    )
    content = Path(out).read_text(encoding="utf-8")
    assert "period-over-period delta" in content


def test_report_fallback_header_when_no_history(tmp_path):
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores={"vanilla": _score(3.0)},
    )
    content = Path(out).read_text(encoding="utf-8")
    assert "no prior period data" in content


def test_full_delta_pipeline(tmp_path):
    """Save scores from week 1, load as previous, score week 2, check deltas."""
    week1_scores = {
        "vanilla": {"note_score": 1.0, "mention_count": 1, "engagement_weight": 0.0,
                    "official_note_bonus": 0, "perfumes": ["Delina"]},
        "amber": {"note_score": 3.0, "mention_count": 3, "engagement_weight": 0.0,
                  "official_note_bonus": 0, "perfumes": []},
    }
    history_path = str(tmp_path / "week1_scores.json")
    save_note_scores(week1_scores, history_path)

    week2_scores = {
        "vanilla": {"note_score": 4.0, "mention_count": 4, "engagement_weight": 0.0,
                    "official_note_bonus": 1, "perfumes": ["Delina", "Tobacco Vanille"]},
        "amber": {"note_score": 1.0, "mention_count": 1, "engagement_weight": 0.0,
                  "official_note_bonus": 0, "perfumes": []},
        "oud": {"note_score": 2.0, "mention_count": 2, "engagement_weight": 0.0,
                "official_note_bonus": 0, "perfumes": []},
    }

    previous = load_note_scores(history_path)
    deltas = compute_trend_delta(week2_scores, previous)

    assert deltas["vanilla"]["direction"] == "up"
    assert deltas["amber"]["direction"] == "down"
    assert deltas["oud"]["direction"] == "up"   # new note, previous = 0
