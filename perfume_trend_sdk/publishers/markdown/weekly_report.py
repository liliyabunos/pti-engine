from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from perfume_trend_sdk.scorers.trend_score.scorer import build_trend_counts
from perfume_trend_sdk.scorers.note_momentum.scorer import (
    NoteMomentumScorer,
    build_note_results,
    compute_trend_delta,
)

_ARROW = {"up": "↑", "down": "↓", "flat": "→"}


class WeeklyMarkdownPublisher:
    name = "markdown_weekly_report"
    version = "1.0"

    def publish(
        self,
        *,
        content_items: List[Dict[str, Any]],
        resolved_signals: List[Dict[str, Any]],
        output_path: str,
        note_scores: Optional[Dict[str, Dict[str, Any]]] = None,
        previous_note_scores: Optional[Dict[str, Dict[str, Any]]] = None,
        enrichment_registry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Generate weekly markdown trend report.

        Args:
            content_items: Normalized content items.
            resolved_signals: Resolved signals from SignalStore.
            output_path: Path to write the markdown file.
            note_scores: Pre-computed note scores from NoteMomentumScorer.
                         If None, scores are computed from content_items internally.
            previous_note_scores: Note scores from the previous period.
                         When provided, trend arrows (↑→↓) are based on real
                         period-over-period delta instead of absolute score heuristics.
                         Load with load_note_scores(); save current scores with
                         save_note_scores() at the end of each run.
            enrichment_registry: Optional enrichment data for computing note_scores
                                 internally (passed to NoteMomentumScorer).
        """
        content_map = {item["id"]: item for item in content_items}

        trend_counts = build_trend_counts(resolved_signals)
        top_perfumes = trend_counts.most_common(20)

        # Compute note scores if not provided
        if note_scores is None:
            note_scores = NoteMomentumScorer().score(
                content_items=content_items,
                resolved_signals=resolved_signals,
                enrichment_registry=enrichment_registry,
            )

        # Compute deltas when history is available
        deltas: Optional[Dict[str, Dict[str, Any]]] = None
        if previous_note_scores is not None:
            deltas = compute_trend_delta(note_scores, previous_note_scores)

        note_results = build_note_results(note_scores, deltas, n=10)

        report_rows: List[str] = []
        for signal in resolved_signals:
            entities = json.loads(signal["resolved_entities_json"])
            if not entities:
                continue

            content_item = content_map.get(signal["content_item_id"])
            title = content_item["title"] if content_item else "(unknown title)"
            url = content_item["source_url"] if content_item else ""
            published_at = content_item["published_at"] if content_item else ""

            for entity in entities:
                perfume_name = entity["canonical_name"]
                report_rows.append(
                    f"- **{perfume_name}** — {title} — {published_at} — {url}"
                )

        lines: List[str] = []
        lines.append("# Weekly Perfume Trend Report")
        lines.append("")

        lines.append("## Top Mentioned Perfumes")
        lines.append("")
        if top_perfumes:
            for name, count in top_perfumes:
                lines.append(f"- {name}: {count}")
        else:
            lines.append("- No resolved perfumes found")
        lines.append("")

        lines.append("## Top Notes This Week")
        if deltas is not None:
            lines.append("_Trend direction based on period-over-period delta_")
        else:
            lines.append("_Trend direction based on absolute score (no prior period data)_")
        lines.append("")

        if note_results:
            for rank, result in enumerate(note_results, 1):
                arrow = _ARROW[result["direction"]]
                score = result["score"]
                drivers = result["drivers"]
                perfumes = note_scores.get(result["note"], {}).get("perfumes", [])

                delta_display = f"(score: {score:.2f})"
                if deltas is not None and result["note"] in deltas:
                    delta_val = deltas[result["note"]]["delta"]
                    delta_display = (
                        f"(+{delta_val:.2f})" if delta_val >= 0 else f"({delta_val:.2f})"
                    )

                lines.append(f"{rank}. {result['note'].title()} {arrow} {delta_display}")

                for driver in drivers:
                    lines.append(f"   - {driver}")

                if perfumes:
                    lines.append(f"   - present in: {', '.join(perfumes[:3])}")

                lines.append("")
        else:
            lines.append("- No note data available")
        lines.append("")

        lines.append("## Resolved Video Mentions")
        lines.append("")
        lines.extend(report_rows or ["- No resolved video mentions"])

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("\n".join(lines), encoding="utf-8")
