from __future__ import annotations

"""
Build Architecture Review — Infrastructure Decision Gate

Evaluates whether PTI SDK should stay on SQLite + venv or move to
PostgreSQL and/or docker-compose, based on current operational state.

This is a decision artifact, NOT an automatic migration trigger.

Usage:
    python -m perfume_trend_sdk.workflows.build_architecture_review \
        --input tests/fixtures/architecture_review_inputs.json \
        --output outputs/reports/architecture_review.md
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from perfume_trend_sdk.publishers.markdown.architecture_review import (
    ArchitectureReviewPublisher,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class ArchitectureReviewer:
    """Deterministic rule-based evaluator for infrastructure decisions.

    All scoring logic is explicit and inspectable — no heuristics that
    hide reasoning from the operator.
    """

    POSTGRES_MAX = 5
    COMPOSE_MAX = 5

    def evaluate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run the full evaluation against the provided inputs dict.

        Returns a review dict consumed by ArchitectureReviewPublisher.
        """
        postgres_score, postgres_factors = self._score_postgres(inputs)
        compose_score, compose_factors = self._score_compose(inputs, postgres_score)

        recommendation = self._recommend(postgres_score, compose_score)
        bottlenecks = self._identify_bottlenecks(inputs)
        reasoning, triggers = self._build_reasoning(
            recommendation, inputs, postgres_score, compose_score
        )
        assumptions = self._collect_assumptions(inputs)

        return {
            "inputs": inputs,
            "postgres_score": postgres_score,
            "postgres_max_score": self.POSTGRES_MAX,
            "postgres_factors": postgres_factors,
            "compose_score": compose_score,
            "compose_max_score": self.COMPOSE_MAX,
            "compose_factors": compose_factors,
            "recommendation": recommendation,
            "bottlenecks": bottlenecks,
            "reasoning": reasoning,
            "re_evaluation_triggers": triggers,
            "assumptions": assumptions,
        }

    # ------------------------------------------------------------------
    # PostgreSQL scoring
    # ------------------------------------------------------------------

    def _score_postgres(
        self, inputs: Dict[str, Any]
    ) -> Tuple[int, List[str]]:
        score = 0
        factors: List[str] = []

        sources = inputs.get("enabled_sources", [])
        if len(sources) >= 3:
            score += 1
            factors.append(
                f"+1 — {len(sources)} sources active (≥3 threshold): "
                f"{', '.join(sources)}"
            )

        scheduled = inputs.get("scheduled_workflows", [])
        if len(scheduled) >= 3:
            score += 1
            factors.append(
                f"+1 — {len(scheduled)} scheduled workflows (≥3 threshold)"
            )

        report_stack = inputs.get("report_stack", [])
        multi_source_active = "multi_source" in report_stack
        if multi_source_active:
            score += 1
            factors.append(
                "+1 — multi-source report stack active (cross-source joins needed)"
            )

        if inputs.get("ui_or_api_planned"):
            score += 1
            factors.append(
                "+1 — UI or API layer planned (stable query performance required)"
            )

        if inputs.get("concurrent_writes_expected") or inputs.get(
            "long_running_workflows"
        ):
            score += 1
            factors.append(
                "+1 — concurrent or long-running workflows expected "
                "(SQLite write locking becomes a concern)"
            )

        return score, factors

    # ------------------------------------------------------------------
    # docker-compose scoring
    # ------------------------------------------------------------------

    def _score_compose(
        self, inputs: Dict[str, Any], postgres_score: int
    ) -> Tuple[int, List[str]]:
        score = 0
        factors: List[str] = []

        if postgres_score >= 3:
            score += 1
            factors.append(
                f"+1 — PostgreSQL score is {postgres_score} (≥3), "
                "compose is the natural delivery vehicle for Postgres"
            )

        if inputs.get("multiple_services_planned"):
            score += 1
            factors.append(
                "+1 — multiple services planned (API, worker, DB, etc.)"
            )

        if inputs.get("local_vps_parity_painful"):
            score += 1
            factors.append(
                "+1 — local/VPS environment parity is becoming painful to maintain"
            )

        if inputs.get("vps_deployment_planned"):
            score += 1
            factors.append(
                "+1 — VPS deployment planned (reproducible startup needed)"
            )

        if inputs.get("ui_or_api_planned") and inputs.get(
            "vps_deployment_planned"
        ):
            score += 1
            factors.append(
                "+1 — UI/API + VPS together require one-command reproducible stack"
            )

        return score, factors

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _recommend(self, postgres_score: int, compose_score: int) -> str:
        """
        Rules:
          postgres < 3 and compose < 3  → stay_on_sqlite_venv
          postgres >= 3 and compose < 3 → move_to_postgresql_only
          postgres >= 3 and compose >= 3 → move_to_postgresql_and_compose
          (edge: compose high but postgres low → stay; compose alone is not enough)
        """
        if postgres_score >= 3 and compose_score >= 3:
            return "move_to_postgresql_and_compose"
        if postgres_score >= 3:
            return "move_to_postgresql_only"
        return "stay_on_sqlite_venv"

    # ------------------------------------------------------------------
    # Bottlenecks
    # ------------------------------------------------------------------

    def _identify_bottlenecks(self, inputs: Dict[str, Any]) -> List[str]:
        bottlenecks: List[str] = []

        raw = inputs.get("raw_item_count_estimate", 0)
        normalized = inputs.get("normalized_item_count_estimate", 0)
        signals = inputs.get("signal_item_count_estimate", 0)
        total = raw + normalized + signals
        if total > 50_000:
            bottlenecks.append(
                f"Storage volume is large ({total:,} estimated rows across raw/"
                "normalized/signals). SQLite may become slow for analytics queries."
            )

        if inputs.get("concurrent_writes_expected"):
            bottlenecks.append(
                "Concurrent writes are expected. SQLite's file-level locking "
                "will serialize all writes and risk contention."
            )

        if inputs.get("long_running_workflows"):
            bottlenecks.append(
                "Long-running workflows can hold the SQLite write lock for "
                "extended periods, blocking all other writes."
            )

        sources = inputs.get("enabled_sources", [])
        if len(sources) >= 3 and inputs.get("run_frequency") in (
            "hourly", "continuous", "scheduled"
        ):
            bottlenecks.append(
                f"{len(sources)} sources running at '{inputs['run_frequency']}' "
                "frequency will grow history volume quickly. Plan a data retention "
                "or archival strategy."
            )

        if inputs.get("local_vps_parity_painful"):
            bottlenecks.append(
                "Local and VPS environments diverge without a reproducible setup. "
                "This creates 'works on my machine' deployment risk."
            )

        if not bottlenecks:
            pass  # caller handles empty list gracefully

        return bottlenecks

    # ------------------------------------------------------------------
    # Reasoning + re-evaluation triggers
    # ------------------------------------------------------------------

    def _build_reasoning(
        self,
        recommendation: str,
        inputs: Dict[str, Any],
        postgres_score: int,
        compose_score: int,
    ) -> Tuple[str, List[str]]:
        sources = inputs.get("enabled_sources", [])
        freq = inputs.get("run_frequency", "manual")
        mode = inputs.get("environment_mode", "local")

        if recommendation == "stay_on_sqlite_venv":
            reasoning = (
                f"The system currently has {len(sources)} source(s) running at "
                f"'{freq}' frequency in '{mode}' mode. "
                "All workflows are run manually from a virtual environment. "
                "SQLite handles the current data volume without contention, "
                "and the single-process execution model means write locking is not "
                "a concern. There is no planned UI, API, or VPS deployment that "
                "would require a more robust database or a reproducible container stack. "
                f"PostgreSQL score is {postgres_score}/5 and docker-compose score is "
                f"{compose_score}/5 — both below the threshold for action. "
                "Introducing either technology now would add infrastructure overhead "
                "without a corresponding operational benefit."
            )
            triggers = [
                "Scheduled (cron / CI) runs begin — move from manual to automated",
                "A second operator or process needs concurrent database access",
                "UI or API layer is planned (requires stable, queryable backend)",
                "VPS or cloud deployment is needed (reproducibility becomes critical)",
                "SQLite write locks begin to slow or block workflows in practice",
                "Raw + normalized + signal row count exceeds ~50,000 rows",
            ]

        elif recommendation == "move_to_postgresql_only":
            reasoning = (
                f"The system now has {len(sources)} source(s) and a multi-source "
                "report stack that performs cross-source aggregation joins. "
                f"PostgreSQL score reached {postgres_score}/5 — above the action "
                "threshold. SQLite can still handle the current volume but the "
                "trajectory points toward workloads where SQLite's limitations "
                "(write locking, lack of concurrent access, limited query optimizer) "
                "will become operational friction. "
                f"docker-compose score is {compose_score}/5 — below threshold. "
                "A straight SQLite → PostgreSQL migration is appropriate before "
                "introducing container orchestration, which would add complexity "
                "without a corresponding need at this stage."
            )
            triggers = [
                "VPS deployment is needed — add docker-compose at that point",
                "Second service (API, worker, dashboard) is introduced",
                "Local/VPS parity becomes painful to maintain manually",
                "Team grows beyond one operator running workflows",
            ]

        else:  # move_to_postgresql_and_compose
            reasoning = (
                f"The system has {len(sources)} source(s), a multi-source report stack, "
                "and both a PostgreSQL need and a docker-compose need confirmed by scoring. "
                f"PostgreSQL score: {postgres_score}/5. docker-compose score: {compose_score}/5. "
                "Moving to PostgreSQL resolves write-lock and query-performance concerns. "
                "Adding docker-compose provides one-command reproducible startup "
                "across local and VPS environments, which is needed given the planned "
                "deployment and/or multi-service growth. Both changes should be made "
                "together to avoid two separate migration cycles."
            )
            triggers = [
                "A managed database service (RDS, Cloud SQL) replaces self-hosted Postgres",
                "Kubernetes or a container orchestration platform is evaluated",
                "Team size or external access patterns change significantly",
            ]

        return reasoning, triggers

    # ------------------------------------------------------------------
    # Assumptions
    # ------------------------------------------------------------------

    def _collect_assumptions(self, inputs: Dict[str, Any]) -> List[str]:
        assumptions: List[str] = []

        estimated_keys = [
            ("raw_item_count_estimate", "raw item count"),
            ("normalized_item_count_estimate", "normalized item count"),
            ("signal_item_count_estimate", "signal item count"),
        ]
        for key, label in estimated_keys:
            if key in inputs:
                assumptions.append(
                    f"{label.capitalize()} is an estimate ({inputs[key]:,} rows) "
                    "— not measured from the live database. Re-run with a "
                    "`SELECT COUNT(*)` query to get actual figures."
                )

        if inputs.get("run_frequency") == "manual":
            assumptions.append(
                "Run frequency is 'manual'. If automated scheduling is introduced, "
                "re-run this review — that is a high-weight PostgreSQL trigger."
            )

        if not inputs.get("ui_or_api_planned"):
            assumptions.append(
                "No UI or API is planned. If this changes, PostgreSQL becomes "
                "significantly more justified."
            )

        if not inputs.get("vps_deployment_planned"):
            assumptions.append(
                "No VPS deployment is planned. If deployment is introduced, "
                "docker-compose justification rises substantially."
            )

        if "scheduled_workflows" not in inputs or not inputs["scheduled_workflows"]:
            assumptions.append(
                "Scheduled workflow count is missing or zero. "
                "This review assumes all workflows are run manually."
            )

        return assumptions


# ---------------------------------------------------------------------------
# run_review entry point
# ---------------------------------------------------------------------------

def run_review(
    *,
    inputs: Dict[str, Any],
    output_path: str = "outputs/reports/architecture_review.md",
) -> Dict[str, str]:
    """Evaluate infrastructure decision gate and write Markdown review.

    Args:
        inputs: Dict matching the architecture_review_inputs fixture shape.
        output_path: Destination for the Markdown report.

    Returns:
        Dict of {output_type: file_path} for all files written.
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    logger.info(
        "architecture_review_started output_path=%s sources=%s",
        output_path,
        inputs.get("enabled_sources", []),
    )

    reviewer = ArchitectureReviewer()
    review = reviewer.evaluate(inputs)

    recommendation = review["recommendation"]
    logger.info(
        "recommendation_selected recommendation=%s postgres_score=%s compose_score=%s",
        recommendation,
        review["postgres_score"],
        review["compose_score"],
    )

    publisher = ArchitectureReviewPublisher()
    publisher.publish(review=review, output_path=output_path, generated_at=generated_at)

    logger.info(
        "architecture_review_completed output_path=%s recommendation=%s",
        output_path,
        recommendation,
    )
    print(f"Architecture review: {output_path}")
    print(f"Recommendation:      {recommendation}")

    return {"markdown": output_path, "recommendation": recommendation}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build PTI SDK infrastructure decision-gate review."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to JSON inputs file (see tests/fixtures/architecture_review_inputs.json)",
    )
    parser.add_argument(
        "--output",
        default="outputs/reports/architecture_review.md",
        help="Output Markdown path",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {args.input}")

    inputs = json.loads(input_path.read_text(encoding="utf-8"))
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    run_review(inputs=inputs, output_path=args.output)


if __name__ == "__main__":
    main()
