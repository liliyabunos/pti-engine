from __future__ import annotations

"""
Architecture Review Markdown Publisher — Infrastructure Decision Gate

Produces a concise internal memo evaluating whether PTI SDK should remain
on SQLite + venv or move to PostgreSQL and/or docker-compose.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional


_RECOMMENDATION_LABELS = {
    "stay_on_sqlite_venv": "Stay on SQLite + venv (no infrastructure change needed)",
    "move_to_postgresql_only": "Move to PostgreSQL (keep venv / manual deployment)",
    "move_to_postgresql_and_compose": "Move to PostgreSQL + docker-compose",
}

_SECTION_DIVIDER = "\n---\n"


class ArchitectureReviewPublisher:
    """Publish an infrastructure decision-gate review as a Markdown memo."""

    name = "architecture_review_publisher"
    version = "1.0"

    def publish(
        self,
        *,
        review: Dict[str, Any],
        output_path: str,
        generated_at: str = "",
    ) -> None:
        """Write the review memo to output_path.

        Args:
            review: Output dict from ArchitectureReviewer.evaluate().
            output_path: Destination file path (will be created/overwritten).
            generated_at: ISO timestamp string shown in report header.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        content = self._render(review, generated_at)
        Path(output_path).write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self, review: Dict[str, Any], generated_at: str) -> str:
        sections: List[str] = []

        sections.append(self._header(review, generated_at))
        sections.append(self._section_current_state(review))
        sections.append(self._section_bottlenecks(review))
        sections.append(self._section_postgresql(review))
        sections.append(self._section_compose(review))
        sections.append(self._section_recommendation(review))
        sections.append(self._section_reasoning(review))
        if review.get("assumptions"):
            sections.append(self._section_assumptions(review))

        return "\n".join(sections)

    def _header(self, review: Dict[str, Any], generated_at: str) -> str:
        rec = review.get("recommendation", "unknown")
        label = _RECOMMENDATION_LABELS.get(rec, rec)
        ts = f"  \n*Generated: {generated_at}*" if generated_at else ""
        return (
            f"# PTI SDK — Infrastructure Decision Gate Review{ts}\n\n"
            f"> **Recommendation: {label}**\n"
        )

    def _section_current_state(self, r: Dict[str, Any]) -> str:
        inputs = r.get("inputs", {})
        sources = inputs.get("enabled_sources", [])
        workflows = inputs.get("workflow_stack", [])
        reports = inputs.get("report_stack", [])
        backend = inputs.get("storage_backend", "sqlite")
        mode = inputs.get("environment_mode", "local")
        freq = inputs.get("run_frequency", "manual")

        sources_str = ", ".join(sources) if sources else "none"
        workflows_str = ", ".join(workflows) if workflows else "none"
        reports_str = ", ".join(reports) if reports else "none"

        return (
            f"## 1. Current State\n\n"
            f"| Item | Value |\n"
            f"|------|-------|\n"
            f"| Enabled sources | {sources_str} |\n"
            f"| Workflow count | {len(workflows)} ({workflows_str}) |\n"
            f"| Report stack | {reports_str} |\n"
            f"| Storage backend | {backend} |\n"
            f"| Operational mode | {mode} |\n"
            f"| Run frequency | {freq} |\n"
        )

    def _section_bottlenecks(self, r: Dict[str, Any]) -> str:
        bottlenecks = r.get("bottlenecks", [])
        if not bottlenecks:
            body = "_No significant bottlenecks identified at current scale._"
        else:
            body = "\n".join(f"- {b}" for b in bottlenecks)
        return f"## 2. Observed Bottlenecks\n\n{body}\n"

    def _section_postgresql(self, r: Dict[str, Any]) -> str:
        score = r.get("postgres_score", 0)
        max_score = r.get("postgres_max_score", 5)
        factors = r.get("postgres_factors", [])
        verdict = "Justified" if score >= 3 else "Not yet justified"

        factors_str = (
            "\n".join(f"- {f}" for f in factors)
            if factors
            else "- No triggering factors active."
        )
        return (
            f"## 3. PostgreSQL Evaluation\n\n"
            f"**Score: {score} / {max_score} — {verdict}**\n\n"
            f"Triggering factors present:\n\n"
            f"{factors_str}\n"
        )

    def _section_compose(self, r: Dict[str, Any]) -> str:
        score = r.get("compose_score", 0)
        max_score = r.get("compose_max_score", 5)
        factors = r.get("compose_factors", [])
        verdict = "Justified" if score >= 3 else "Not yet justified"

        factors_str = (
            "\n".join(f"- {f}" for f in factors)
            if factors
            else "- No triggering factors active."
        )
        return (
            f"## 4. docker-compose Evaluation\n\n"
            f"**Score: {score} / {max_score} — {verdict}**\n\n"
            f"Triggering factors present:\n\n"
            f"{factors_str}\n"
        )

    def _section_recommendation(self, r: Dict[str, Any]) -> str:
        rec = r.get("recommendation", "unknown")
        label = _RECOMMENDATION_LABELS.get(rec, rec)
        return (
            f"## 5. Recommendation\n\n"
            f"**{label}**\n\n"
            f"Decision key: `{rec}`\n"
        )

    def _section_reasoning(self, r: Dict[str, Any]) -> str:
        reasoning = r.get("reasoning", "")
        triggers = r.get("re_evaluation_triggers", [])
        triggers_str = (
            "\n".join(f"- {t}" for t in triggers)
            if triggers
            else "- No specific triggers identified."
        )
        return (
            f"## 6. Reasoning\n\n"
            f"{reasoning}\n\n"
            f"**Re-evaluate when:**\n\n"
            f"{triggers_str}\n"
        )

    def _section_assumptions(self, r: Dict[str, Any]) -> str:
        assumptions = r.get("assumptions", [])
        body = "\n".join(f"- {a}" for a in assumptions)
        return (
            f"## 7. Assumptions\n\n"
            f"The following inputs were unavailable or estimated. "
            f"They are listed explicitly so the review can be repeated "
            f"with measured values when available.\n\n"
            f"{body}\n"
        )
