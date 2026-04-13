from __future__ import annotations

"""
Build Multi-Source Client Report — Phase 4C

Loads stored analytics and signals, aggregates cross-source,
and publishes a Markdown + CSV report.

Usage:
    python -m perfume_trend_sdk.workflows.build_multi_source_report \
        --db outputs/pti.db \
        --report-path outputs/reports/multi_source_report.md \
        --window "past 7 days"
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.publishers.markdown.multi_source_report import (
    MultiSourceMarkdownPublisher,
)
from perfume_trend_sdk.publishers.csv.multi_source_report_export import (
    MultiSourceCSVExporter,
)
from perfume_trend_sdk.publishers.multi_source.aggregator import (
    aggregate_cross_source,
    rank_perfumes,
)
from perfume_trend_sdk.scorers.note_momentum.scorer import (
    NoteMomentumScorer,
    build_note_results,
    load_note_scores,
    compute_trend_delta,
)
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore

logger = logging.getLogger(__name__)

_DEFAULT_CANDIDATES_PATH = "outputs/top_unresolved_candidates.json"


def _load_emerging_entities(path: str) -> List[Dict[str, Any]]:
    """Load top discovery candidates; return empty list if file missing."""
    src = Path(path)
    if not src.exists():
        return []
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def run_report(
    *,
    db_path: str,
    report_path: str = "outputs/reports/multi_source_report.md",
    window_label: str = "past 7 days",
    previous_scores_path: Optional[str] = None,
    candidates_path: str = _DEFAULT_CANDIDATES_PATH,
    skip_csv: bool = False,
) -> Dict[str, str]:
    """Build and write the multi-source client report.

    Args:
        db_path: Path to the SQLite database.
        report_path: Destination for the Markdown report.
        window_label: Human-readable period label shown in the report.
        previous_scores_path: Optional path to previous-period note scores JSON
                              (from save_note_scores). Enables delta-based direction.
        candidates_path: Path to top_unresolved_candidates.json for emerging entities.
        skip_csv: If True, skip CSV export.

    Returns:
        Dict of {output_type: file_path} for all files written.
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    logger.info(
        "report_build_started db=%s report_path=%s window=%s",
        db_path,
        report_path,
        window_label,
    )

    # ── Load stored data ──────────────────────────────────────────────────────
    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()
    content_items = normalized_store.list_content_items_full()

    signal_store = SignalStore(db_path)
    signal_store.init_schema()
    resolved_signals = signal_store.list_resolved_signals()

    # ── Cross-source aggregation ──────────────────────────────────────────────
    aggregated = aggregate_cross_source(content_items, resolved_signals)

    # Prepare simple list_content_items format for NoteMomentumScorer
    # (it needs id, text_content, engagement — all present in full rows)
    note_items = [
        {
            "id": item["id"],
            "text_content": item.get("text_content") or "",
            "engagement": _parse_engagement(item.get("engagement_json", "{}")),
        }
        for item in content_items
    ]

    note_scorer = NoteMomentumScorer()
    note_scores = note_scorer.score(
        content_items=note_items,
        resolved_signals=resolved_signals,
    )

    # Delta-based direction if previous scores available
    previous = load_note_scores(previous_scores_path) if previous_scores_path else {}
    deltas = compute_trend_delta(note_scores, previous) if previous else None
    note_results = build_note_results(note_scores, deltas, n=10)

    # Ranked perfumes (no previous mention-count baseline in v1 → all "new" or "flat")
    ranked = rank_perfumes(aggregated["perfumes"], n=20)

    # Emerging entities from discovery candidates
    emerging = _load_emerging_entities(candidates_path)

    sources_included = list(aggregated["source_breakdown"].keys())
    logger.info(
        "report_build_completed perfumes_included_count=%d notes_included_count=%d sources_included=%s",
        len(ranked),
        len(note_results),
        sources_included,
    )

    # ── Publish Markdown ──────────────────────────────────────────────────────
    md_publisher = MultiSourceMarkdownPublisher()
    md_publisher.publish(
        ranked_perfumes=ranked,
        note_results=note_results,
        source_breakdown=aggregated["source_breakdown"],
        creator_community=aggregated["creator_community"],
        emerging_entities=emerging or None,
        output_path=report_path,
        window_label=window_label,
        generated_at=generated_at,
    )
    logger.info("output_markdown_path=%s", report_path)
    print(f"Markdown report:   {report_path}")

    outputs: Dict[str, str] = {"markdown": report_path}

    # ── Publish CSV ───────────────────────────────────────────────────────────
    if not skip_csv:
        csv_exporter = MultiSourceCSVExporter()
        csv_paths = csv_exporter.export(
            ranked_perfumes=ranked,
            note_results=note_results,
            source_breakdown=aggregated["source_breakdown"],
            output_path=report_path,
        )
        outputs.update(csv_paths)
        for key, path in csv_paths.items():
            logger.info("output_csv_path key=%s path=%s", key, path)
            print(f"CSV ({key}):         {path}")

    # ── PDF path (scaffolded) ─────────────────────────────────────────────────
    # Full PDF automation is not required for v1. The Markdown report is
    # PDF-ready (clean headings, tables). To convert:
    #   pip install weasyprint
    #   weasyprint <(pandoc report.md -t html) report.pdf
    # OR:
    #   pandoc report.md --pdf-engine=wkhtmltopdf -o report.pdf
    pdf_path = report_path.replace(".md", ".pdf")
    outputs["pdf_scaffold"] = pdf_path
    logger.info("output_pdf_path=%s (scaffold only — convert from markdown)", pdf_path)
    print(f"PDF scaffold:      {pdf_path} (convert from markdown — not auto-generated in v1)")

    return outputs


def _parse_engagement(engagement_json: str) -> Dict[str, Any]:
    try:
        data = json.loads(engagement_json or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build multi-source PTI client report."
    )
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument(
        "--report-path",
        default="outputs/reports/multi_source_report.md",
        help="Output markdown path",
    )
    parser.add_argument(
        "--window",
        default="past 7 days",
        help="Human-readable reporting window label",
    )
    parser.add_argument(
        "--previous-scores",
        default=None,
        help="Path to previous-period note_scores JSON (for delta direction)",
    )
    parser.add_argument(
        "--candidates-path",
        default=_DEFAULT_CANDIDATES_PATH,
        help="Path to top_unresolved_candidates.json",
    )
    parser.add_argument(
        "--skip-csv",
        action="store_true",
        help="Skip CSV export",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.report_path) or ".", exist_ok=True)

    run_report(
        db_path=args.db,
        report_path=args.report_path,
        window_label=args.window,
        previous_scores_path=args.previous_scores,
        candidates_path=args.candidates_path,
        skip_csv=args.skip_csv,
    )


if __name__ == "__main__":
    main()
