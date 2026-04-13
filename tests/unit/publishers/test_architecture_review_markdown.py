from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.workflows.build_architecture_review import (
    ArchitectureReviewer,
    run_review,
)
from perfume_trend_sdk.publishers.markdown.architecture_review import (
    ArchitectureReviewPublisher,
)

FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "fixtures" / "architecture_review_inputs.json"
)

REQUIRED_SECTIONS = [
    "## 1. Current State",
    "## 2. Observed Bottlenecks",
    "## 3. PostgreSQL Evaluation",
    "## 4. docker-compose Evaluation",
    "## 5. Recommendation",
    "## 6. Reasoning",
]

VALID_RECOMMENDATIONS = {
    "stay_on_sqlite_venv",
    "move_to_postgresql_only",
    "move_to_postgresql_and_compose",
}


@pytest.fixture(scope="module")
def fixture_inputs() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def review(fixture_inputs: dict) -> dict:
    return ArchitectureReviewer().evaluate(fixture_inputs)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory, review: dict) -> str:
    out = str(tmp_path_factory.mktemp("arch") / "review.md")
    ArchitectureReviewPublisher().publish(
        review=review, output_path=out, generated_at="2026-04-10 00:00 UTC"
    )
    return Path(out).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Reviewer unit tests
# ---------------------------------------------------------------------------

def test_reviewer_returns_recommendation(review: dict) -> None:
    assert "recommendation" in review
    assert review["recommendation"] in VALID_RECOMMENDATIONS


def test_reviewer_recommendation_is_stable(fixture_inputs: dict) -> None:
    """Same inputs must always produce the same recommendation."""
    r1 = ArchitectureReviewer().evaluate(fixture_inputs)
    r2 = ArchitectureReviewer().evaluate(fixture_inputs)
    assert r1["recommendation"] == r2["recommendation"]


def test_fixture_recommendation_is_stay_on_sqlite(review: dict) -> None:
    """Fixture represents post-Phase-4C state: manual runs, no VPS, no API.
    Expected: stay_on_sqlite_venv."""
    assert review["recommendation"] == "stay_on_sqlite_venv"


def test_reviewer_postgres_score_present(review: dict) -> None:
    assert "postgres_score" in review
    assert isinstance(review["postgres_score"], int)
    assert 0 <= review["postgres_score"] <= review["postgres_max_score"]


def test_reviewer_compose_score_present(review: dict) -> None:
    assert "compose_score" in review
    assert isinstance(review["compose_score"], int)
    assert 0 <= review["compose_score"] <= review["compose_max_score"]


def test_reviewer_has_bottlenecks_list(review: dict) -> None:
    assert "bottlenecks" in review
    assert isinstance(review["bottlenecks"], list)


def test_reviewer_has_reasoning(review: dict) -> None:
    assert "reasoning" in review
    assert len(review["reasoning"]) > 50


def test_reviewer_has_re_evaluation_triggers(review: dict) -> None:
    assert "re_evaluation_triggers" in review
    assert len(review["re_evaluation_triggers"]) >= 1


def test_reviewer_has_assumptions(review: dict) -> None:
    assert "assumptions" in review
    assert isinstance(review["assumptions"], list)


# ---------------------------------------------------------------------------
# Score logic unit tests
# ---------------------------------------------------------------------------

def test_postgres_score_increases_with_sources() -> None:
    reviewer = ArchitectureReviewer()
    low = reviewer.evaluate({"enabled_sources": ["youtube"]})
    high = reviewer.evaluate({"enabled_sources": ["youtube", "tiktok", "reddit"]})
    assert high["postgres_score"] > low["postgres_score"]


def test_postgres_score_increases_with_scheduled_workflows() -> None:
    reviewer = ArchitectureReviewer()
    low = reviewer.evaluate({"scheduled_workflows": ["one"]})
    high = reviewer.evaluate({"scheduled_workflows": ["a", "b", "c"]})
    assert high["postgres_score"] > low["postgres_score"]


def test_postgres_score_increases_with_multisource_report() -> None:
    reviewer = ArchitectureReviewer()
    without = reviewer.evaluate({"report_stack": ["markdown"]})
    with_ = reviewer.evaluate({"report_stack": ["markdown", "csv", "multi_source"]})
    assert with_["postgres_score"] > without["postgres_score"]


def test_postgres_score_increases_with_ui_planned() -> None:
    reviewer = ArchitectureReviewer()
    without = reviewer.evaluate({})
    with_ = reviewer.evaluate({"ui_or_api_planned": True})
    assert with_["postgres_score"] > without["postgres_score"]


def test_postgres_score_increases_with_concurrent_writes() -> None:
    reviewer = ArchitectureReviewer()
    without = reviewer.evaluate({})
    with_ = reviewer.evaluate({"concurrent_writes_expected": True})
    assert with_["postgres_score"] > without["postgres_score"]


def test_compose_score_increases_when_postgres_score_high() -> None:
    reviewer = ArchitectureReviewer()
    low_pg = reviewer.evaluate({})
    high_pg = reviewer.evaluate({
        "enabled_sources": ["youtube", "tiktok", "reddit"],
        "scheduled_workflows": ["a", "b", "c"],
        "report_stack": ["multi_source"],
        "ui_or_api_planned": True,
        "concurrent_writes_expected": True,
    })
    assert high_pg["compose_score"] > low_pg["compose_score"]


def test_compose_score_increases_with_vps_planned() -> None:
    reviewer = ArchitectureReviewer()
    without = reviewer.evaluate({})
    with_ = reviewer.evaluate({"vps_deployment_planned": True})
    assert with_["compose_score"] > without["compose_score"]


def test_compose_score_increases_with_parity_pain() -> None:
    reviewer = ArchitectureReviewer()
    without = reviewer.evaluate({})
    with_ = reviewer.evaluate({"local_vps_parity_painful": True})
    assert with_["compose_score"] > without["compose_score"]


# ---------------------------------------------------------------------------
# Recommendation boundary tests
# ---------------------------------------------------------------------------

def test_low_scores_recommend_sqlite(review: dict) -> None:
    reviewer = ArchitectureReviewer()
    r = reviewer.evaluate({})
    assert r["recommendation"] == "stay_on_sqlite_venv"


def test_high_postgres_low_compose_recommends_postgresql_only() -> None:
    reviewer = ArchitectureReviewer()
    r = reviewer.evaluate({
        "enabled_sources": ["youtube", "tiktok", "reddit"],
        "scheduled_workflows": ["a", "b", "c"],
        "report_stack": ["multi_source"],
        "ui_or_api_planned": True,
        # compose triggers intentionally off
        "vps_deployment_planned": False,
        "local_vps_parity_painful": False,
        "multiple_services_planned": False,
    })
    assert r["postgres_score"] >= 3
    assert r["recommendation"] == "move_to_postgresql_only"


def test_high_both_scores_recommends_compose() -> None:
    reviewer = ArchitectureReviewer()
    r = reviewer.evaluate({
        "enabled_sources": ["youtube", "tiktok", "reddit"],
        "scheduled_workflows": ["a", "b", "c"],
        "report_stack": ["multi_source"],
        "ui_or_api_planned": True,
        "concurrent_writes_expected": True,
        "vps_deployment_planned": True,
        "local_vps_parity_painful": True,
        "multiple_services_planned": True,
    })
    assert r["postgres_score"] >= 3
    assert r["compose_score"] >= 3
    assert r["recommendation"] == "move_to_postgresql_and_compose"


def test_high_compose_only_still_recommends_sqlite() -> None:
    """docker-compose alone cannot justify PostgreSQL."""
    reviewer = ArchitectureReviewer()
    r = reviewer.evaluate({
        "vps_deployment_planned": True,
        "local_vps_parity_painful": True,
        "multiple_services_planned": True,
    })
    # Compose score may be non-zero but postgres score should be low
    assert r["postgres_score"] < 3
    assert r["recommendation"] == "stay_on_sqlite_venv"


# ---------------------------------------------------------------------------
# Markdown publisher tests
# ---------------------------------------------------------------------------

def test_rendered_has_all_required_sections(rendered: str) -> None:
    for section in REQUIRED_SECTIONS:
        assert section in rendered, f"Missing section: {section}"


def test_rendered_recommendation_in_header(rendered: str) -> None:
    assert "Recommendation:" in rendered


def test_rendered_recommendation_key_present(rendered: str) -> None:
    assert "stay_on_sqlite_venv" in rendered


def test_rendered_postgres_score_shown(rendered: str) -> None:
    assert "Score:" in rendered


def test_rendered_reasoning_non_empty(rendered: str) -> None:
    assert "## 6. Reasoning" in rendered
    # Reasoning section must have actual content
    idx = rendered.index("## 6. Reasoning")
    section_content = rendered[idx + len("## 6. Reasoning"):]
    assert len(section_content.strip()) > 20


def test_rendered_triggers_present(rendered: str) -> None:
    assert "Re-evaluate when:" in rendered


def test_rendered_assumptions_section_present_when_estimates_given(
    fixture_inputs: dict,
) -> None:
    """Fixture has estimated counts → Assumptions section must appear."""
    reviewer = ArchitectureReviewer()
    review = reviewer.evaluate(fixture_inputs)
    assert len(review["assumptions"]) > 0

    out_path = "/tmp/arch_review_test.md"
    ArchitectureReviewPublisher().publish(review=review, output_path=out_path)
    content = Path(out_path).read_text(encoding="utf-8")
    assert "## 7. Assumptions" in content


def test_rendered_no_assumptions_section_when_none(tmp_path) -> None:
    """When no assumptions are generated, section must be absent."""
    reviewer = ArchitectureReviewer()
    # Provide a minimal input with no estimated fields
    minimal = {"enabled_sources": ["youtube"]}
    review = reviewer.evaluate(minimal)
    # Manually clear assumptions
    review["assumptions"] = []

    out = str(tmp_path / "review.md")
    ArchitectureReviewPublisher().publish(review=review, output_path=out)
    content = Path(out).read_text(encoding="utf-8")
    assert "## 7. Assumptions" not in content


def test_rendered_file_is_valid_markdown_size(rendered: str) -> None:
    assert len(rendered) > 200


def test_generated_at_appears_in_header(rendered: str) -> None:
    assert "2026-04-10" in rendered


def test_no_jargon_postgresql_score_label_readable(rendered: str) -> None:
    """Score labels should be human-readable."""
    assert "Justified" in rendered or "Not yet justified" in rendered


def test_current_state_table_present(rendered: str) -> None:
    assert "Enabled sources" in rendered
    assert "Storage backend" in rendered
    assert "Operational mode" in rendered
