from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from perfume_trend_sdk.publishers.multi_source.aggregator import (
    build_executive_summary,
    build_opportunity_risk,
    classify_signal_type,
)

_ARROW = {"up": "↑", "down": "↓", "flat": "→", "new": "★"}
_DIR_LABEL = {"up": "↑ Rising", "down": "↓ Declining", "flat": "→ Stable", "new": "★ New"}


class MultiSourceMarkdownPublisher:
    """Publish a cross-source market intelligence report in Markdown.

    Consumes pre-aggregated data — no raw signals accessed here.
    All aggregation must happen in the caller before publish() is called.
    """

    name = "multi_source_markdown_publisher"
    version = "1.0"

    def publish(
        self,
        *,
        ranked_perfumes: List[Dict[str, Any]],
        note_results: List[Dict[str, Any]],
        source_breakdown: Dict[str, Any],
        creator_community: Dict[str, Any],
        emerging_entities: Optional[List[Dict[str, Any]]] = None,
        output_path: str,
        window_label: str = "past 7 days",
        generated_at: Optional[str] = None,
    ) -> None:
        """Write multi-source Markdown report to output_path.

        Args:
            ranked_perfumes: From aggregator.rank_perfumes().
            note_results: From scorers.note_momentum.build_note_results().
            source_breakdown: From aggregator.aggregate_cross_source().
            creator_community: From aggregator.aggregate_cross_source().
            emerging_entities: From discovery / unresolved aggregation (optional).
            output_path: Destination file path.
            window_label: Human-readable reporting window e.g. "past 7 days".
            generated_at: ISO timestamp; defaults to now UTC.
        """
        if generated_at is None:
            generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        signal_type = classify_signal_type(
            creator_community.get("creator_mentions", 0),
            creator_community.get("community_mentions", 0),
        )
        opp_risk = build_opportunity_risk(ranked_perfumes)
        summary = build_executive_summary(
            ranked_perfumes,
            note_results,
            signal_type,
            source_breakdown,
            window_label=window_label,
        )

        lines: List[str] = []

        # ── Header ──────────────────────────────────────────────────────────
        lines += [
            "# Perfume Trend Intelligence — Market Report",
            f"_Generated: {generated_at} · Period: {window_label}_",
            "",
        ]

        # ── 1. Executive Summary ─────────────────────────────────────────────
        lines += [
            "## 1. Executive Summary",
            "",
            summary,
            "",
        ]

        # ── 2. Top Trending Perfumes ─────────────────────────────────────────
        lines += [
            "## 2. Top Trending Perfumes",
            "",
            "| # | Perfume | Mentions | Score | Direction | Top Source(s) |",
            "|---|---------|----------|-------|-----------|---------------|",
        ]
        for row in ranked_perfumes[:20]:
            arrow = _ARROW.get(row["direction"], "→")
            sources = ", ".join(row["top_sources"][:2])
            lines.append(
                f"| {row['rank']} | {row['name']} | {row['total_mentions']} "
                f"| {row['weighted_score']:.2f} | {arrow} | {sources} |"
            )
        if not ranked_perfumes:
            lines.append("_No resolved perfumes found._")
        lines.append("")

        # ── 3. Top Notes This Period ─────────────────────────────────────────
        lines += [
            "## 3. Top Notes This Period",
            "",
        ]
        if note_results:
            lines += [
                "| # | Note | Score | Direction | Drivers |",
                "|---|------|-------|-----------|---------|",
            ]
            for i, result in enumerate(note_results[:10], 1):
                arrow = _ARROW.get(result["direction"], "→")
                drivers = "; ".join(result.get("drivers", []))
                lines.append(
                    f"| {i} | {result['note'].title()} | {result['score']:.2f} "
                    f"| {arrow} | {drivers or '—'} |"
                )
        else:
            lines.append("_No note data available._")
        lines.append("")

        # ── 4. Source Breakdown ──────────────────────────────────────────────
        lines += [
            "## 4. Source Breakdown",
            "",
            "| Source | Content Items | Perfume Mentions |",
            "|--------|--------------|-----------------|",
        ]
        for platform, data in sorted(source_breakdown.items()):
            lines.append(
                f"| {platform} | {data['item_count']} | {data['mention_count']} |"
            )
        if not source_breakdown:
            lines.append("_No source data available._")
        lines.append("")

        # ── 5. Community vs Creator Signal ───────────────────────────────────
        creator_m = creator_community.get("creator_mentions", 0)
        community_m = creator_community.get("community_mentions", 0)
        mixed = creator_community.get("mixed_signals", [])
        total_m = creator_m + community_m

        lines += ["## 5. Community vs Creator Signal", ""]
        lines.append(f"**Signal type:** {signal_type.title()}")
        lines.append("")
        lines.append(f"- Creator-led mentions (YouTube / TikTok): **{creator_m}**")
        lines.append(f"- Community-led mentions (Reddit): **{community_m}**")
        if total_m > 0:
            ratio = round(creator_m / total_m * 100)
            lines.append(f"- Creator share: **{ratio}%**")
        if mixed:
            lines.append(f"- Perfumes with both creator and community signal: {', '.join(mixed[:5])}")
        lines.append("")

        # ── 6. Emerging Entities ─────────────────────────────────────────────
        lines += ["## 6. Emerging Entities", ""]
        if emerging_entities:
            lines += [
                "| Candidate | Mentions | Sources |",
                "|-----------|----------|---------|",
            ]
            for ent in emerging_entities[:10]:
                lines.append(
                    f"| {ent.get('text', '—')} | {ent.get('count', 0)} "
                    f"| {ent.get('sources', 0)} |"
                )
        else:
            lines.append("_No emerging entity data available. Run aggregate_candidates workflow to populate._")
        lines.append("")

        # ── 7. Opportunity / Risk Summary ────────────────────────────────────
        lines += ["## 7. Opportunity / Risk Summary", ""]

        lines.append("**Launch Opportunities** _(rising or new, multi-source signal)_")
        if opp_risk["opportunities"]:
            for name in opp_risk["opportunities"]:
                lines.append(f"- {name}")
        else:
            lines.append("- None identified this period")
        lines.append("")

        lines.append("**Oversaturation Risk** _(very high volume — monitor for fatigue)_")
        if opp_risk["risks"]:
            for name in opp_risk["risks"]:
                lines.append(f"- {name}")
        else:
            lines.append("- None identified this period")
        lines.append("")

        lines.append("**Declining Profiles** _(falling signal — reduced promotion priority)_")
        if opp_risk["declining"]:
            for name in opp_risk["declining"]:
                lines.append(f"- {name}")
        else:
            lines.append("- None identified this period")
        lines.append("")

        # ── Footer ───────────────────────────────────────────────────────────
        lines += [
            "---",
            f"_Perfume Trend Intelligence SDK · Report v{self.version}_",
        ]

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("\n".join(lines), encoding="utf-8")
