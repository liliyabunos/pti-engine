from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownPublisher


def _make_signal(item_id: str, perfume: str = "") -> dict:
    entities = (
        [{"entity_type": "perfume", "canonical_name": perfume, "entity_id": "1"}]
        if perfume
        else []
    )
    return {
        "content_item_id": item_id,
        "resolved_entities_json": json.dumps(entities),
    }


def _make_item(item_id: str, text: str = "", title: str = "Test") -> dict:
    return {
        "id": item_id,
        "text_content": text,
        "title": title,
        "source_url": "https://example.com",
        "published_at": "2026-04-09T00:00:00",
        "engagement": {"views": 5000, "likes": 200},
    }


def test_report_includes_notes_section(tmp_path):
    publisher = WeeklyMarkdownPublisher()
    out = str(tmp_path / "report.md")

    publisher.publish(
        content_items=[_make_item("v1", text="vanilla and amber notes")],
        resolved_signals=[_make_signal("v1", perfume="Parfums de Marly Delina")],
        output_path=out,
    )

    content = Path(out).read_text(encoding="utf-8")
    assert "## Top Notes This Week" in content


def test_report_notes_section_with_precomputed_scores(tmp_path):
    note_scores = {
        "vanilla": {
            "note_score": 5.0,
            "mention_count": 5,
            "engagement_weight": 0.01,
            "official_note_bonus": 1,
            "perfumes": ["Parfums de Marly Delina"],
        },
        "amber": {
            "note_score": 2.5,
            "mention_count": 3,
            "engagement_weight": 0.005,
            "official_note_bonus": 0,
            "perfumes": [],
        },
    }
    out = str(tmp_path / "report.md")

    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
    )

    content = Path(out).read_text(encoding="utf-8")
    assert "## Top Notes This Week" in content
    assert "Vanilla" in content
    assert "Amber" in content


def test_report_note_scores_ranked_by_score(tmp_path):
    note_scores = {
        "rose": {"note_score": 1.0, "mention_count": 1, "engagement_weight": 0, "official_note_bonus": 0, "perfumes": []},
        "vanilla": {"note_score": 5.0, "mention_count": 5, "engagement_weight": 0, "official_note_bonus": 1, "perfumes": []},
        "amber": {"note_score": 3.0, "mention_count": 3, "engagement_weight": 0, "official_note_bonus": 0, "perfumes": []},
    }
    out = str(tmp_path / "report.md")

    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
    )

    content = Path(out).read_text(encoding="utf-8")
    vanilla_pos = content.index("Vanilla")
    amber_pos = content.index("Amber")
    rose_pos = content.index("Rose")
    assert vanilla_pos < amber_pos < rose_pos


def test_report_note_includes_direction_arrow(tmp_path):
    note_scores = {
        "vanilla": {"note_score": 4.0, "mention_count": 4, "engagement_weight": 0, "official_note_bonus": 1, "perfumes": []},
        "oud": {"note_score": 0.6, "mention_count": 1, "engagement_weight": 0, "official_note_bonus": 0, "perfumes": []},
        "rose": {"note_score": 0.1, "mention_count": 1, "engagement_weight": 0, "official_note_bonus": 0, "perfumes": []},
    }
    out = str(tmp_path / "report.md")

    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
    )

    content = Path(out).read_text(encoding="utf-8")
    assert "↑" in content   # vanilla score >= 2.0
    assert "→" in content   # oud score >= 0.5
    assert "↓" in content   # rose score < 0.5


def test_report_note_includes_perfume_association(tmp_path):
    note_scores = {
        "vanilla": {
            "note_score": 3.0,
            "mention_count": 3,
            "engagement_weight": 0,
            "official_note_bonus": 1,
            "perfumes": ["Parfums de Marly Delina", "Tom Ford Tobacco Vanille"],
        },
    }
    out = str(tmp_path / "report.md")

    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
    )

    content = Path(out).read_text(encoding="utf-8")
    assert "Parfums de Marly Delina" in content


def test_report_no_notes_fallback(tmp_path):
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores={},
    )
    content = Path(out).read_text(encoding="utf-8")
    assert "No note data available" in content


def test_report_still_has_top_perfumes_section(tmp_path):
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
    )
    content = Path(out).read_text(encoding="utf-8")
    assert "## Top Mentioned Perfumes" in content
    assert "## Top Notes This Week" in content
    assert "## Resolved Video Mentions" in content


def test_report_drivers_rendered_as_sub_bullets(tmp_path):
    note_scores = {
        "vanilla": {
            "note_score": 3.0,
            "mention_count": 3,
            "engagement_weight": 0.5,
            "official_note_bonus": 1,
            "perfumes": ["Parfums de Marly Delina"],
            "drivers": ["high engagement", "present in top trending perfumes"],
        },
    }
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
    )
    content = Path(out).read_text(encoding="utf-8")

    lines = content.splitlines()
    vanilla_idx = next(i for i, l in enumerate(lines) if "Vanilla" in l)
    sub_lines = lines[vanilla_idx + 1 :]

    # drivers rendered as indented bullet points below the note heading
    assert any("- high engagement" in l for l in sub_lines)
    assert any("- present in top trending perfumes" in l for l in sub_lines)


def test_report_perfume_association_as_sub_bullet(tmp_path):
    note_scores = {
        "vanilla": {
            "note_score": 3.0,
            "mention_count": 3,
            "engagement_weight": 0,
            "official_note_bonus": 0,
            "perfumes": ["Parfums de Marly Delina"],
            "drivers": [],
        },
    }
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
    )
    content = Path(out).read_text(encoding="utf-8")
    lines = content.splitlines()
    vanilla_idx = next(i for i, l in enumerate(lines) if "Vanilla" in l)
    sub_lines = lines[vanilla_idx + 1 :]
    assert any("present in:" in l and "Parfums de Marly Delina" in l for l in sub_lines)


def test_report_note_heading_format(tmp_path):
    """Note heading: '1. Vanilla ↑ (+2.00)' — rank, name, arrow, delta."""
    note_scores = {
        "vanilla": {
            "note_score": 3.0,
            "mention_count": 3,
            "engagement_weight": 0,
            "official_note_bonus": 0,
            "perfumes": [],
            "drivers": [],
        },
    }
    previous = {
        "vanilla": {
            "note_score": 1.0,
            "mention_count": 1,
            "engagement_weight": 0,
            "official_note_bonus": 0,
            "perfumes": [],
            "drivers": [],
        },
    }
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
        previous_note_scores=previous,
    )
    content = Path(out).read_text(encoding="utf-8")
    lines = content.splitlines()
    vanilla_line = next(l for l in lines if "Vanilla" in l)
    assert "1." in vanilla_line
    assert "↑" in vanilla_line
    assert "+2.00" in vanilla_line


def test_report_no_driver_sub_bullets_when_empty(tmp_path):
    note_scores = {
        "amber": {
            "note_score": 1.0,
            "mention_count": 1,
            "engagement_weight": 0,
            "official_note_bonus": 0,
            "perfumes": [],
            "drivers": [],
        },
    }
    out = str(tmp_path / "report.md")
    WeeklyMarkdownPublisher().publish(
        content_items=[],
        resolved_signals=[],
        output_path=out,
        note_scores=note_scores,
    )
    content = Path(out).read_text(encoding="utf-8")
    lines = content.splitlines()
    amber_idx = next(i for i, l in enumerate(lines) if "Amber" in l)
    # next non-empty line after amber heading should not be a driver sub-bullet
    sub_lines = [l for l in lines[amber_idx + 1:] if l.strip()]
    # first sub-line (if any) must not be a driver — either a perfume bullet or a new section
    if sub_lines:
        assert "high engagement" not in sub_lines[0]
        assert "high mention frequency" not in sub_lines[0]
