from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.publishers.multi_source.aggregator import (
    aggregate_cross_source,
    build_executive_summary,
    build_opportunity_risk,
    classify_signal_type,
    rank_perfumes,
)
from perfume_trend_sdk.publishers.markdown.multi_source_report import (
    MultiSourceMarkdownPublisher,
)
from perfume_trend_sdk.publishers.csv.multi_source_report_export import (
    MultiSourceCSVExporter,
)

FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "fixtures" / "multi_source_report_inputs.json"
)


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def aggregated(fixture_data: dict) -> dict:
    return aggregate_cross_source(
        fixture_data["content_items"],
        fixture_data["resolved_signals"],
    )


@pytest.fixture(scope="module")
def ranked(aggregated: dict) -> list:
    return rank_perfumes(aggregated["perfumes"], n=20)


@pytest.fixture(scope="module")
def note_results() -> list:
    return [
        {"note": "vanilla", "score": 4.0, "direction": "up", "drivers": ["high engagement"]},
        {"note": "rose", "score": 2.5, "direction": "up", "drivers": []},
        {"note": "amber", "score": 1.0, "direction": "flat", "drivers": []},
    ]


# ---------------------------------------------------------------------------
# Aggregator unit tests
# ---------------------------------------------------------------------------

def test_aggregator_detects_all_perfumes(aggregated: dict) -> None:
    names = set(aggregated["perfumes"].keys())
    assert "Parfums de Marly Delina" in names
    assert "Maison Francis Kurkdjian Baccarat Rouge 540" in names


def test_aggregator_cross_source_mention_count(aggregated: dict) -> None:
    delina = aggregated["perfumes"]["Parfums de Marly Delina"]
    # appears in yt_001, yt_002, tt_001, rd_001 → 4 mentions
    assert delina["total_mentions"] == 4


def test_aggregator_source_attribution(aggregated: dict) -> None:
    delina = aggregated["perfumes"]["Parfums de Marly Delina"]
    # YouTube: yt_001 + yt_002, TikTok: tt_001, Reddit: rd_001
    assert delina["by_source"].get("YouTube", 0) == 2
    assert delina["by_source"].get("TikTok", 0) == 1
    assert delina["by_source"].get("Reddit", 0) == 1


def test_aggregator_source_breakdown_has_all_platforms(aggregated: dict) -> None:
    labels = set(aggregated["source_breakdown"].keys())
    assert "YouTube" in labels
    assert "TikTok" in labels
    assert "Reddit" in labels


def test_aggregator_creator_community_counts(aggregated: dict) -> None:
    cc = aggregated["creator_community"]
    # creator = youtube + tiktok items; community = reddit
    assert cc["creator_mentions"] > 0
    assert cc["community_mentions"] > 0


def test_aggregator_mixed_signals_for_delina(aggregated: dict) -> None:
    cc = aggregated["creator_community"]
    # Delina appears in both creator (YouTube/TikTok) and community (Reddit)
    assert "Parfums de Marly Delina" in cc["mixed_signals"]


def test_rank_perfumes_sorted_by_mentions(ranked: list) -> None:
    mentions = [r["total_mentions"] for r in ranked]
    assert mentions == sorted(mentions, reverse=True)


def test_rank_perfumes_has_required_keys(ranked: list) -> None:
    for row in ranked:
        assert "rank" in row
        assert "name" in row
        assert "total_mentions" in row
        assert "weighted_score" in row
        assert "by_source" in row
        assert "top_sources" in row
        assert "direction" in row


def test_classify_signal_type_creator_led() -> None:
    assert classify_signal_type(90, 10) == "creator-led"


def test_classify_signal_type_community_led() -> None:
    assert classify_signal_type(10, 90) == "community-led"


def test_classify_signal_type_mixed() -> None:
    assert classify_signal_type(50, 50) == "mixed"


def test_classify_signal_type_zero_total() -> None:
    assert classify_signal_type(0, 0) == "mixed"


def test_build_opportunity_risk_rising_is_opportunity() -> None:
    rows = [
        {"name": "Delina", "total_mentions": 4, "direction": "up"},
        {"name": "BR540", "total_mentions": 3, "direction": "new"},
        {"name": "Old Spice", "total_mentions": 2, "direction": "down"},
    ]
    result = build_opportunity_risk(rows)
    assert "Delina" in result["opportunities"]
    assert "BR540" in result["opportunities"]
    assert "Old Spice" in result["declining"]


def test_build_executive_summary_contains_key_info(
    ranked: list, note_results: list, aggregated: dict
) -> None:
    summary = build_executive_summary(
        ranked, note_results, "creator-led", aggregated["source_breakdown"]
    )
    assert "perfume" in summary.lower() or "Parfums" in summary
    assert "creator-led" in summary


# ---------------------------------------------------------------------------
# Markdown publisher
# ---------------------------------------------------------------------------

def _publish(tmp_path, ranked, note_results, aggregated, emerging=None) -> str:
    out = str(tmp_path / "report.md")
    MultiSourceMarkdownPublisher().publish(
        ranked_perfumes=ranked,
        note_results=note_results,
        source_breakdown=aggregated["source_breakdown"],
        creator_community=aggregated["creator_community"],
        emerging_entities=emerging,
        output_path=out,
    )
    return Path(out).read_text(encoding="utf-8")


def test_report_has_all_required_sections(
    tmp_path, ranked, note_results, aggregated, fixture_data
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated,
                       fixture_data["emerging_entities"])
    assert "## 1. Executive Summary" in content
    assert "## 2. Top Trending Perfumes" in content
    assert "## 3. Top Notes This Period" in content
    assert "## 4. Source Breakdown" in content
    assert "## 5. Community vs Creator Signal" in content
    assert "## 6. Emerging Entities" in content
    assert "## 7. Opportunity / Risk Summary" in content


def test_report_perfume_table_has_top_entry(
    tmp_path, ranked, note_results, aggregated
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated)
    assert "Parfums de Marly Delina" in content


def test_report_note_section_populated(
    tmp_path, ranked, note_results, aggregated
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated)
    assert "Vanilla" in content
    assert "Rose" in content


def test_report_source_breakdown_present(
    tmp_path, ranked, note_results, aggregated
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated)
    assert "YouTube" in content
    assert "TikTok" in content
    assert "Reddit" in content


def test_report_community_vs_creator_present(
    tmp_path, ranked, note_results, aggregated
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated)
    assert "Community vs Creator" in content
    assert "creator" in content.lower()


def test_report_emerging_entities_present(
    tmp_path, ranked, note_results, aggregated, fixture_data
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated,
                       fixture_data["emerging_entities"])
    assert "lattafa khamrah" in content


def test_report_emerging_entities_fallback_when_none(
    tmp_path, ranked, note_results, aggregated
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated, emerging=None)
    assert "## 6. Emerging Entities" in content
    assert "aggregate_candidates" in content  # fallback message


def test_report_opportunity_risk_section_present(
    tmp_path, ranked, note_results, aggregated
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated)
    assert "Launch Opportunities" in content
    assert "Oversaturation Risk" in content
    assert "Declining Profiles" in content


def test_report_direction_arrows_present(
    tmp_path, ranked, note_results, aggregated
) -> None:
    content = _publish(tmp_path, ranked, note_results, aggregated)
    # note_results has "up" notes → ↑ should appear
    assert "↑" in content


def test_report_is_valid_markdown_file(
    tmp_path, ranked, note_results, aggregated
) -> None:
    out = str(tmp_path / "report.md")
    MultiSourceMarkdownPublisher().publish(
        ranked_perfumes=ranked,
        note_results=note_results,
        source_breakdown=aggregated["source_breakdown"],
        creator_community=aggregated["creator_community"],
        output_path=out,
    )
    assert Path(out).exists()
    assert Path(out).stat().st_size > 100


# ---------------------------------------------------------------------------
# CSV exporter
# ---------------------------------------------------------------------------

def test_csv_export_produces_three_files(
    tmp_path, ranked, note_results, aggregated
) -> None:
    out = str(tmp_path / "report.md")
    paths = MultiSourceCSVExporter().export(
        ranked_perfumes=ranked,
        note_results=note_results,
        source_breakdown=aggregated["source_breakdown"],
        output_path=out,
    )
    assert "perfumes" in paths
    assert "notes" in paths
    assert "sources" in paths
    for path in paths.values():
        assert Path(path).exists()


def test_csv_perfumes_has_correct_columns(
    tmp_path, ranked, note_results, aggregated
) -> None:
    import csv
    out = str(tmp_path / "report.md")
    paths = MultiSourceCSVExporter().export(
        ranked_perfumes=ranked,
        note_results=note_results,
        source_breakdown=aggregated["source_breakdown"],
        output_path=out,
    )
    with open(paths["perfumes"], encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
    assert "rank" in headers
    assert "name" in headers
    assert "total_mentions" in headers
    assert "direction" in headers


def test_csv_notes_has_correct_columns(
    tmp_path, ranked, note_results, aggregated
) -> None:
    import csv
    out = str(tmp_path / "report.md")
    paths = MultiSourceCSVExporter().export(
        ranked_perfumes=ranked,
        note_results=note_results,
        source_breakdown=aggregated["source_breakdown"],
        output_path=out,
    )
    with open(paths["notes"], encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
    assert "note" in headers
    assert "score" in headers
    assert "direction" in headers


def test_csv_perfumes_top_row_is_delina(
    tmp_path, ranked, note_results, aggregated
) -> None:
    import csv
    out = str(tmp_path / "report.md")
    paths = MultiSourceCSVExporter().export(
        ranked_perfumes=ranked,
        note_results=note_results,
        source_breakdown=aggregated["source_breakdown"],
        output_path=out,
    )
    with open(paths["perfumes"], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["name"] == "Parfums de Marly Delina"
    assert rows[0]["rank"] == "1"
