from __future__ import annotations

import json

import pytest

from perfume_trend_sdk.extractors.note_mentions.extractor import NoteExtractor
from perfume_trend_sdk.scorers.note_momentum.scorer import (
    NoteMomentumScorer,
    build_note_results,
    compute_trend_delta,
    top_notes,
    trend_direction,
)


# ---------------------------------------------------------------------------
# NoteExtractor tests
# ---------------------------------------------------------------------------


def test_note_extractor_detects_known_notes():
    extractor = NoteExtractor()
    results = extractor.extract("I love vanilla and amber in this perfume")
    note_names = [r["note"] for r in results]
    assert "vanilla" in note_names
    assert "amber" in note_names


def test_note_extractor_empty_text():
    extractor = NoteExtractor()
    assert extractor.extract("") == []
    assert extractor.extract(None) == []  # type: ignore[arg-type]


def test_note_extractor_no_known_notes():
    extractor = NoteExtractor()
    results = extractor.extract("this content has no note keywords at all")
    assert results == []


def test_note_extractor_base_confidence():
    extractor = NoteExtractor()
    results = extractor.extract("vanilla")
    assert results[0]["confidence"] == 0.7
    assert results[0]["official_note_bonus"] == 0


def test_note_extractor_official_boost():
    extractor = NoteExtractor(official_notes={"vanilla", "rose"})
    results = extractor.extract("vanilla and rose notes")
    by_note = {r["note"]: r for r in results}
    assert by_note["vanilla"]["confidence"] == 0.9
    assert by_note["vanilla"]["official_note_bonus"] == 1
    assert by_note["rose"]["confidence"] == 0.9


def test_note_extractor_non_official_not_boosted():
    extractor = NoteExtractor(official_notes={"vanilla"})
    results = extractor.extract("amber and vanilla")
    by_note = {r["note"]: r for r in results}
    assert by_note["vanilla"]["official_note_bonus"] == 1
    assert by_note["amber"]["official_note_bonus"] == 0
    assert by_note["amber"]["confidence"] == 0.7


def test_note_extractor_no_duplicates():
    extractor = NoteExtractor()
    results = extractor.extract("vanilla vanilla vanilla")
    note_names = [r["note"] for r in results]
    assert note_names.count("vanilla") == 1


def test_note_extractor_multiword():
    extractor = NoteExtractor()
    results = extractor.extract("I smell lily of the valley today")
    note_names = [r["note"] for r in results]
    assert "lily of the valley" in note_names


def test_note_extractor_from_enrichment_registry():
    registry = {
        "Parfums de Marly Delina": {
            "official_notes": {
                "top": ["bergamot", "lychee"],
                "middle": ["rose"],
                "base": ["musk"],
            }
        }
    }
    extractor = NoteExtractor.from_enrichment_registry(registry)
    results = extractor.extract("bergamot and amber scent")
    by_note = {r["note"]: r for r in results}
    assert by_note["bergamot"]["official_note_bonus"] == 1
    assert by_note["amber"]["official_note_bonus"] == 0


# ---------------------------------------------------------------------------
# NoteMomentumScorer tests
# ---------------------------------------------------------------------------


def _make_signal(item_id: str, perfume_names=None) -> dict:
    entities = [
        {"entity_type": "perfume", "canonical_name": n, "entity_id": "1"}
        for n in (perfume_names or [])
    ]
    return {
        "content_item_id": item_id,
        "resolved_entities_json": json.dumps(entities),
    }


def _make_item(item_id: str, text: str, views: int = 0, likes: int = 0) -> dict:
    return {
        "id": item_id,
        "text_content": text,
        "engagement": {"views": views, "likes": likes},
    }


def test_scorer_detects_notes_in_content():
    items = [_make_item("v1", "this perfume has vanilla and amber notes")]
    signals = [_make_signal("v1")]
    scores = NoteMomentumScorer().score(content_items=items, resolved_signals=signals)
    assert "vanilla" in scores
    assert "amber" in scores


def test_scorer_mention_count():
    items = [
        _make_item("v1", "vanilla"),
        _make_item("v2", "vanilla"),
        _make_item("v3", "amber"),
    ]
    signals = [_make_signal(i) for i in ("v1", "v2", "v3")]
    scores = NoteMomentumScorer().score(content_items=items, resolved_signals=signals)
    assert scores["vanilla"]["mention_count"] == 2
    assert scores["amber"]["mention_count"] == 1


def test_scorer_formula_no_engagement_no_bonus():
    """With 1 mention, 0 engagement, 0 bonus: score = 1*0.6 + 0*0.3 + 0*0.1 = 0.6"""
    items = [_make_item("v1", "vanilla", views=0, likes=0)]
    signals = [_make_signal("v1")]
    scores = NoteMomentumScorer().score(content_items=items, resolved_signals=signals)
    assert scores["vanilla"]["note_score"] == pytest.approx(0.6, abs=1e-4)


def test_scorer_official_note_bonus():
    registry = {
        "Delina": {
            "official_notes": {"top": ["rose"], "middle": [], "base": []}
        }
    }
    items = [_make_item("v1", "rose and amber")]
    signals = [_make_signal("v1")]
    scores = NoteMomentumScorer().score(
        content_items=items,
        resolved_signals=signals,
        enrichment_registry=registry,
    )
    assert scores["rose"]["official_note_bonus"] == 1
    # bonus contributes 0.1 to score
    assert scores["rose"]["note_score"] > scores["amber"]["note_score"]


def test_scorer_note_to_perfume_mapping():
    items = [_make_item("v1", "vanilla scent")]
    signals = [_make_signal("v1", perfume_names=["Parfums de Marly Delina"])]
    scores = NoteMomentumScorer().score(content_items=items, resolved_signals=signals)
    assert "Parfums de Marly Delina" in scores["vanilla"]["perfumes"]


def test_scorer_empty_inputs():
    scores = NoteMomentumScorer().score(content_items=[], resolved_signals=[])
    assert scores == {}


def test_scorer_signal_with_no_matching_item():
    signals = [_make_signal("v_missing")]
    scores = NoteMomentumScorer().score(
        content_items=[], resolved_signals=signals
    )
    assert scores == {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_top_notes_returns_n():
    scores = {
        "vanilla": {"note_score": 5.0, "mention_count": 5, "engagement_weight": 0, "official_note_bonus": 1, "perfumes": []},
        "amber": {"note_score": 3.0, "mention_count": 3, "engagement_weight": 0, "official_note_bonus": 0, "perfumes": []},
        "rose": {"note_score": 1.0, "mention_count": 1, "engagement_weight": 0, "official_note_bonus": 0, "perfumes": []},
    }
    result = top_notes(scores, n=2)
    assert len(result) == 2
    assert result[0][0] == "vanilla"
    assert result[1][0] == "amber"


def test_trend_direction():
    assert trend_direction(3.0) == "↑"
    assert trend_direction(1.0) == "→"
    assert trend_direction(0.2) == "↓"
    assert trend_direction(2.0) == "↑"
    assert trend_direction(0.5) == "→"


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


def test_drivers_empty_when_below_thresholds():
    """1 mention, 0 engagement, no top-perfume link → no drivers."""
    items = [_make_item("v1", "vanilla", views=0, likes=0)]
    signals = [_make_signal("v1")]
    scores = NoteMomentumScorer(
        engagement_threshold=0.001,
        frequency_threshold=3,
    ).score(content_items=items, resolved_signals=signals)
    assert scores["vanilla"]["drivers"] == []


def test_driver_high_mention_frequency():
    items = [_make_item(f"v{i}", "vanilla") for i in range(4)]
    signals = [_make_signal(f"v{i}") for i in range(4)]
    scores = NoteMomentumScorer(frequency_threshold=3).score(
        content_items=items, resolved_signals=signals
    )
    assert "high mention frequency" in scores["vanilla"]["drivers"]


def test_driver_not_added_when_frequency_below_threshold():
    items = [_make_item("v1", "vanilla"), _make_item("v2", "vanilla")]
    signals = [_make_signal("v1"), _make_signal("v2")]
    scores = NoteMomentumScorer(frequency_threshold=3).score(
        content_items=items, resolved_signals=signals
    )
    assert "high mention frequency" not in scores["vanilla"]["drivers"]


def test_driver_high_engagement():
    # 2M views → engagement_weight = (2_000_000 * 0.6) / 1_000_000 = 1.2 > 0.001
    items = [_make_item("v1", "vanilla", views=2_000_000, likes=0)]
    signals = [_make_signal("v1")]
    scores = NoteMomentumScorer(engagement_threshold=0.001).score(
        content_items=items, resolved_signals=signals
    )
    assert "high engagement" in scores["vanilla"]["drivers"]


def test_driver_not_added_when_engagement_below_threshold():
    items = [_make_item("v1", "vanilla", views=0, likes=0)]
    signals = [_make_signal("v1")]
    scores = NoteMomentumScorer(engagement_threshold=0.001).score(
        content_items=items, resolved_signals=signals
    )
    assert "high engagement" not in scores["vanilla"]["drivers"]


def test_driver_present_in_top_trending_perfumes():
    """vanilla linked to the most-mentioned perfume → driver fires."""
    items = [_make_item("v1", "vanilla")]
    signals = [_make_signal("v1", perfume_names=["Parfums de Marly Delina"])]
    # top_perfumes_n=1 → Delina is top-1
    scores = NoteMomentumScorer(top_perfumes_n=1).score(
        content_items=items, resolved_signals=signals
    )
    assert "present in top trending perfumes" in scores["vanilla"]["drivers"]


def test_driver_not_added_when_perfume_not_in_top_n():
    """vanilla linked to a low-count perfume; Delina dominates top-1 → driver absent for vanilla."""
    items = [
        _make_item("v1", "vanilla"),
        _make_item("v2", "rose"),
        _make_item("v3", "rose"),   # extra rose mention so Delina appears twice
    ]
    # Delina mentioned in v2+v3 (count=2); "Unknown Niche" only in v1 (count=1)
    signals = [
        _make_signal("v1", perfume_names=["Unknown Niche"]),
        _make_signal("v2", perfume_names=["Parfums de Marly Delina"]),
        _make_signal("v3", perfume_names=["Parfums de Marly Delina"]),
    ]
    scores = NoteMomentumScorer(top_perfumes_n=1).score(
        content_items=items, resolved_signals=signals
    )
    # top-1 = Delina; vanilla is linked to Unknown Niche (not in top-1)
    assert "present in top trending perfumes" not in scores["vanilla"]["drivers"]
    # rose is linked to Delina (in top-1)
    assert "present in top trending perfumes" in scores["rose"]["drivers"]


def test_driver_all_three_present():
    items = [_make_item(f"v{i}", "vanilla", views=2_000_000) for i in range(5)]
    signals = [
        _make_signal(f"v{i}", perfume_names=["Parfums de Marly Delina"])
        for i in range(5)
    ]
    scores = NoteMomentumScorer(
        engagement_threshold=0.001,
        frequency_threshold=3,
        top_perfumes_n=5,
    ).score(content_items=items, resolved_signals=signals)
    drivers = scores["vanilla"]["drivers"]
    assert "high engagement" in drivers
    assert "present in top trending perfumes" in drivers
    assert "high mention frequency" in drivers


def test_drivers_key_always_present():
    """drivers list must be present even when empty."""
    items = [_make_item("v1", "vanilla")]
    signals = [_make_signal("v1")]
    scores = NoteMomentumScorer().score(content_items=items, resolved_signals=signals)
    assert "drivers" in scores["vanilla"]
    assert isinstance(scores["vanilla"]["drivers"], list)


# ---------------------------------------------------------------------------
# build_note_results
# ---------------------------------------------------------------------------


def _full_score(val: float, drivers=None) -> dict:
    return {
        "note_score": val,
        "mention_count": 1,
        "engagement_weight": 0.0,
        "official_note_bonus": 0,
        "perfumes": [],
        "drivers": drivers or [],
    }


def test_build_note_results_shape():
    scores = {"vanilla": _full_score(3.0, ["high engagement"])}
    results = build_note_results(scores)
    assert len(results) == 1
    r = results[0]
    assert set(r.keys()) == {"note", "score", "direction", "drivers"}


def test_build_note_results_fields():
    scores = {"vanilla": _full_score(3.0, ["high mention frequency"])}
    results = build_note_results(scores)
    r = results[0]
    assert r["note"] == "vanilla"
    assert r["score"] == 3.0
    assert r["drivers"] == ["high mention frequency"]


def test_build_note_results_ranked_by_score():
    scores = {
        "rose": _full_score(1.0),
        "vanilla": _full_score(5.0),
        "amber": _full_score(3.0),
    }
    results = build_note_results(scores)
    assert [r["note"] for r in results] == ["vanilla", "amber", "rose"]


def test_build_note_results_respects_n():
    scores = {f"note_{i}": _full_score(float(i)) for i in range(20)}
    results = build_note_results(scores, n=5)
    assert len(results) == 5


def test_build_note_results_direction_from_delta():
    scores = {
        "vanilla": _full_score(2.0),
        "amber": _full_score(3.0),
    }
    deltas = compute_trend_delta(scores, {"vanilla": _full_score(1.0), "amber": _full_score(5.0)})
    results = build_note_results(scores, deltas)
    by_note = {r["note"]: r for r in results}
    assert by_note["vanilla"]["direction"] == "up"
    assert by_note["amber"]["direction"] == "down"


def test_build_note_results_heuristic_direction_without_delta():
    scores = {
        "vanilla": _full_score(3.0),   # >= 2.0 → up
        "amber": _full_score(1.0),     # >= 0.5 → flat
        "rose": _full_score(0.1),      # < 0.5  → down
    }
    results = build_note_results(scores, n=10)
    by_note = {r["note"]: r for r in results}
    assert by_note["vanilla"]["direction"] == "up"
    assert by_note["amber"]["direction"] == "flat"
    assert by_note["rose"]["direction"] == "down"


def test_build_note_results_empty():
    assert build_note_results({}) == []
