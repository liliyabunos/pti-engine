from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.workflows.build_architecture_review import run_review

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "architecture_review_inputs.json"
)

REQUIRED_SECTIONS = [
    "Current State",
    "Observed Bottlenecks",
    "PostgreSQL Evaluation",
    "docker-compose Evaluation",
    "Recommendation",
    "Reasoning",
]


@pytest.fixture(scope="module")
def fixture_inputs() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_run_review_produces_markdown_file(tmp_path: Path, fixture_inputs: dict) -> None:
    out = str(tmp_path / "architecture_review.md")
    outputs = run_review(inputs=fixture_inputs, output_path=out)

    assert Path(out).exists()
    assert "markdown" in outputs
    assert outputs["markdown"] == out


def test_run_review_returns_recommendation_key(tmp_path: Path, fixture_inputs: dict) -> None:
    out = str(tmp_path / "architecture_review.md")
    outputs = run_review(inputs=fixture_inputs, output_path=out)

    assert "recommendation" in outputs
    assert outputs["recommendation"] in {
        "stay_on_sqlite_venv",
        "move_to_postgresql_only",
        "move_to_postgresql_and_compose",
    }


def test_run_review_fixture_recommends_stay_on_sqlite(
    tmp_path: Path, fixture_inputs: dict
) -> None:
    out = str(tmp_path / "architecture_review.md")
    outputs = run_review(inputs=fixture_inputs, output_path=out)

    assert outputs["recommendation"] == "stay_on_sqlite_venv"


def test_run_review_content_has_required_sections(
    tmp_path: Path, fixture_inputs: dict
) -> None:
    out = str(tmp_path / "architecture_review.md")
    run_review(inputs=fixture_inputs, output_path=out)

    content = Path(out).read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in content, f"Missing section: {section}"


def test_run_review_recommendation_near_top(
    tmp_path: Path, fixture_inputs: dict
) -> None:
    """Recommendation must appear within the first 500 characters."""
    out = str(tmp_path / "architecture_review.md")
    run_review(inputs=fixture_inputs, output_path=out)

    content = Path(out).read_text(encoding="utf-8")
    top = content[:500]
    assert "Recommendation" in top or "stay_on_sqlite_venv" in top


def test_run_review_creates_parent_directories(tmp_path: Path, fixture_inputs: dict) -> None:
    nested = str(tmp_path / "deep" / "nested" / "review.md")
    run_review(inputs=fixture_inputs, output_path=nested)
    assert Path(nested).exists()


def test_run_review_is_deterministic(tmp_path: Path, fixture_inputs: dict) -> None:
    out1 = str(tmp_path / "review1.md")
    out2 = str(tmp_path / "review2.md")
    r1 = run_review(inputs=fixture_inputs, output_path=out1)
    r2 = run_review(inputs=fixture_inputs, output_path=out2)

    assert r1["recommendation"] == r2["recommendation"]


def test_run_review_high_load_inputs_recommend_postgresql(tmp_path: Path) -> None:
    inputs = {
        "enabled_sources": ["youtube", "tiktok", "reddit"],
        "scheduled_workflows": ["ingest_yt", "ingest_tt", "ingest_rd"],
        "report_stack": ["markdown", "csv", "multi_source"],
        "ui_or_api_planned": True,
        "concurrent_writes_expected": True,
        "vps_deployment_planned": False,
        "local_vps_parity_painful": False,
        "multiple_services_planned": False,
        "run_frequency": "scheduled",
        "storage_backend": "sqlite",
        "environment_mode": "local",
        "workflow_stack": [],
    }
    out = str(tmp_path / "review_pg.md")
    outputs = run_review(inputs=inputs, output_path=out)

    assert outputs["recommendation"] == "move_to_postgresql_only"


def test_run_review_full_load_inputs_recommend_compose(tmp_path: Path) -> None:
    inputs = {
        "enabled_sources": ["youtube", "tiktok", "reddit"],
        "scheduled_workflows": ["ingest_yt", "ingest_tt", "ingest_rd"],
        "report_stack": ["markdown", "csv", "multi_source"],
        "ui_or_api_planned": True,
        "concurrent_writes_expected": True,
        "vps_deployment_planned": True,
        "local_vps_parity_painful": True,
        "multiple_services_planned": True,
        "long_running_workflows": True,
        "run_frequency": "scheduled",
        "storage_backend": "sqlite",
        "environment_mode": "local",
        "workflow_stack": [],
    }
    out = str(tmp_path / "review_compose.md")
    outputs = run_review(inputs=inputs, output_path=out)

    assert outputs["recommendation"] == "move_to_postgresql_and_compose"


def test_run_review_empty_inputs_stay_on_sqlite(tmp_path: Path) -> None:
    out = str(tmp_path / "review_empty.md")
    outputs = run_review(inputs={}, output_path=out)

    assert outputs["recommendation"] == "stay_on_sqlite_venv"
    assert Path(out).exists()


def test_run_review_markdown_includes_sources_from_input(
    tmp_path: Path, fixture_inputs: dict
) -> None:
    out = str(tmp_path / "review.md")
    run_review(inputs=fixture_inputs, output_path=out)

    content = Path(out).read_text(encoding="utf-8")
    for source in fixture_inputs.get("enabled_sources", []):
        assert source in content


def test_run_review_assumptions_present_when_estimates_given(
    tmp_path: Path, fixture_inputs: dict
) -> None:
    out = str(tmp_path / "review.md")
    run_review(inputs=fixture_inputs, output_path=out)

    content = Path(out).read_text(encoding="utf-8")
    assert "Assumptions" in content


def test_run_review_large_row_count_adds_bottleneck(tmp_path: Path) -> None:
    inputs = {
        "raw_item_count_estimate": 30_000,
        "normalized_item_count_estimate": 28_000,
        "signal_item_count_estimate": 25_000,
    }
    out = str(tmp_path / "review_large.md")
    run_review(inputs=inputs, output_path=out)

    content = Path(out).read_text(encoding="utf-8")
    # Bottleneck about volume should appear
    assert "storage" in content.lower() or "rows" in content.lower()
