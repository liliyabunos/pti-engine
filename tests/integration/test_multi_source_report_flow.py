from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv
from perfume_trend_sdk.workflows.build_multi_source_report import run_report

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "multi_source_report_inputs.json"
YT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "tiktok_post_raw.json"
REDDIT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "reddit_post_raw.json"


@pytest.fixture(scope="module")
def fixture_inputs() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _seed_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "pti_ms.sqlite")
    csv_path = tmp_path / "seed.csv"
    csv_path.write_text(
        "\n".join([
            "fragrance_id,brand_name,perfume_name,source",
            "fr_001,Parfums de Marly,Delina,kaggle",
            "fr_002,Maison Francis Kurkdjian,Baccarat Rouge 540,kaggle",
        ]),
        encoding="utf-8",
    )
    ingest_seed_csv(csv_path, db_path)
    return db_path


def _populate_stores(db_path: str, fixture_inputs: dict) -> None:
    """Insert fixture content items and resolved signals into SQLite."""
    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()
    # Insert items with the extra columns the full query needs
    # Re-build items to include all required fields for save_content_items
    full_items = []
    for item in fixture_inputs["content_items"]:
        full_items.append({
            "id": item["id"],
            "schema_version": "1.0",
            "source_platform": item.get("source_platform", "other"),
            "source_account_id": None,
            "source_account_handle": item.get("source_account_handle"),
            "source_account_type": "creator",
            "source_url": item.get("source_url", ""),
            "external_content_id": item["id"],
            "published_at": item.get("published_at", ""),
            "collected_at": "2026-04-10T00:00:00+00:00",
            "content_type": item.get("content_type", "video"),
            "title": item.get("title"),
            "caption": None,
            "text_content": item.get("text_content"),
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": json.loads(item.get("media_metadata_json", "{}")),
            "engagement": json.loads(item.get("engagement_json", "{}")),
            "language": None,
            "region": "US",
            "raw_payload_ref": f"data/raw/test/{item['id']}.json",
            "normalizer_version": "1.0",
            "query": item.get("query"),
        })
    normalized_store.save_content_items(full_items)

    signal_store = SignalStore(db_path)
    signal_store.init_schema()
    signals_to_save = []
    for sig in fixture_inputs["resolved_signals"]:
        entities = json.loads(sig["resolved_entities_json"])
        signals_to_save.append({
            "content_item_id": sig["content_item_id"],
            "resolver_version": sig["resolver_version"],
            "resolved_entities": entities,
            "unresolved_mentions": [],
            "alias_candidates": [],
        })
    signal_store.save_resolved_signals(signals_to_save)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_run_report_produces_markdown(tmp_path: Path, fixture_inputs: dict) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    outputs = run_report(db_path=db_path, report_path=out)

    assert Path(out).exists()
    assert "markdown" in outputs
    assert outputs["markdown"] == out


def test_run_report_produces_csv_files(tmp_path: Path, fixture_inputs: dict) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    outputs = run_report(db_path=db_path, report_path=out)

    assert "perfumes" in outputs
    assert "notes" in outputs
    assert "sources" in outputs
    for key in ("perfumes", "notes", "sources"):
        assert Path(outputs[key]).exists()


def test_report_content_has_required_sections(tmp_path: Path, fixture_inputs: dict) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    run_report(db_path=db_path, report_path=out)

    content = Path(out).read_text(encoding="utf-8")
    for section in [
        "Executive Summary",
        "Top Trending Perfumes",
        "Top Notes This Period",
        "Source Breakdown",
        "Community vs Creator Signal",
        "Emerging Entities",
        "Opportunity / Risk Summary",
    ]:
        assert section in content, f"Missing section: {section}"


def test_report_aggregates_delina_across_sources(tmp_path: Path, fixture_inputs: dict) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    run_report(db_path=db_path, report_path=out)

    content = Path(out).read_text(encoding="utf-8")
    assert "Parfums de Marly Delina" in content


def test_csv_perfumes_top_row_is_most_mentioned(tmp_path: Path, fixture_inputs: dict) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    outputs = run_report(db_path=db_path, report_path=out)

    with open(outputs["perfumes"], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) >= 1
    assert rows[0]["rank"] == "1"
    assert int(rows[0]["total_mentions"]) >= int(rows[-1]["total_mentions"])


def test_report_source_breakdown_shows_all_three_platforms(
    tmp_path: Path, fixture_inputs: dict
) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    run_report(db_path=db_path, report_path=out)

    content = Path(out).read_text(encoding="utf-8")
    assert "YouTube" in content
    assert "TikTok" in content
    assert "Reddit" in content


def test_report_community_vs_creator_classification(
    tmp_path: Path, fixture_inputs: dict
) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    run_report(db_path=db_path, report_path=out)

    content = Path(out).read_text(encoding="utf-8")
    # Must name the signal type
    assert any(
        term in content
        for term in ("creator-led", "community-led", "mixed", "Creator-Led", "Community-Led", "Mixed")
    )


def test_run_report_skip_csv(tmp_path: Path, fixture_inputs: dict) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    out = str(tmp_path / "multi_report.md")
    outputs = run_report(db_path=db_path, report_path=out, skip_csv=True)

    assert "markdown" in outputs
    assert "perfumes" not in outputs


def test_run_report_with_emerging_entities(tmp_path: Path, fixture_inputs: dict) -> None:
    db_path = _seed_db(tmp_path)
    _populate_stores(db_path, fixture_inputs)

    # Write a candidates file
    candidates_path = str(tmp_path / "candidates.json")
    candidates = fixture_inputs["emerging_entities"]
    Path(candidates_path).write_text(json.dumps(candidates), encoding="utf-8")

    out = str(tmp_path / "multi_report.md")
    run_report(db_path=db_path, report_path=out, candidates_path=candidates_path)

    content = Path(out).read_text(encoding="utf-8")
    assert "lattafa khamrah" in content


def test_run_report_handles_empty_db(tmp_path: Path) -> None:
    """Report must not crash on an empty database — produce an empty-state report."""
    db_path = str(tmp_path / "empty.sqlite")
    out = str(tmp_path / "empty_report.md")

    # No data seeded — just init schema
    NormalizedContentStore(db_path).init_schema()
    SignalStore(db_path).init_schema()

    outputs = run_report(db_path=db_path, report_path=out, skip_csv=True)
    assert Path(out).exists()
    content = Path(out).read_text(encoding="utf-8")
    assert "Executive Summary" in content
