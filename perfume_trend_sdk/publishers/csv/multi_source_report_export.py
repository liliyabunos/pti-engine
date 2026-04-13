from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional


class MultiSourceCSVExporter:
    """Export multi-source report data to analyst-oriented CSV files.

    Produces up to three files per export:
        <stem>_perfumes.csv  — ranked perfume rows
        <stem>_notes.csv     — note momentum rows
        <stem>_sources.csv   — source breakdown rows

    All files are written to the same directory as output_path.
    """

    name = "multi_source_csv_exporter"
    version = "1.0"

    def export(
        self,
        *,
        ranked_perfumes: List[Dict[str, Any]],
        note_results: List[Dict[str, Any]],
        source_breakdown: Dict[str, Any],
        output_path: str,
    ) -> Dict[str, str]:
        """Write CSV files and return a dict of {sheet_name: file_path}.

        Args:
            ranked_perfumes: From aggregator.rank_perfumes().
            note_results: From scorers.note_momentum.build_note_results().
            source_breakdown: From aggregator.aggregate_cross_source().
            output_path: Base path — stem is used to derive sibling file names.
                         e.g. "outputs/reports/multi_source_report.md"
                         → "outputs/reports/multi_source_report_perfumes.csv"

        Returns:
            Dict mapping sheet name → absolute file path string.
        """
        base = Path(output_path)
        base.parent.mkdir(parents=True, exist_ok=True)
        stem = base.stem

        out: Dict[str, str] = {}

        # ── perfumes ─────────────────────────────────────────────────────────
        perfumes_path = base.parent / f"{stem}_perfumes.csv"
        self._write_perfumes(ranked_perfumes, str(perfumes_path))
        out["perfumes"] = str(perfumes_path)

        # ── notes ─────────────────────────────────────────────────────────────
        notes_path = base.parent / f"{stem}_notes.csv"
        self._write_notes(note_results, str(notes_path))
        out["notes"] = str(notes_path)

        # ── sources ───────────────────────────────────────────────────────────
        sources_path = base.parent / f"{stem}_sources.csv"
        self._write_sources(source_breakdown, str(sources_path))
        out["sources"] = str(sources_path)

        return out

    # ------------------------------------------------------------------
    # Sheet writers
    # ------------------------------------------------------------------

    def _write_perfumes(
        self, ranked_perfumes: List[Dict[str, Any]], path: str
    ) -> None:
        fieldnames = [
            "rank", "name", "total_mentions", "weighted_score",
            "direction", "top_source_1", "top_source_2",
            "youtube_mentions", "tiktok_mentions", "reddit_mentions",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in ranked_perfumes:
                by = row.get("by_source", {})
                sources = row.get("top_sources", [])
                writer.writerow(
                    {
                        "rank": row["rank"],
                        "name": row["name"],
                        "total_mentions": row["total_mentions"],
                        "weighted_score": round(row["weighted_score"], 4),
                        "direction": row["direction"],
                        "top_source_1": sources[0] if len(sources) > 0 else "",
                        "top_source_2": sources[1] if len(sources) > 1 else "",
                        "youtube_mentions": by.get("YouTube", 0),
                        "tiktok_mentions": by.get("TikTok", 0),
                        "reddit_mentions": by.get("Reddit", 0),
                    }
                )

    def _write_notes(
        self, note_results: List[Dict[str, Any]], path: str
    ) -> None:
        fieldnames = ["rank", "note", "score", "direction", "drivers"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for i, result in enumerate(note_results, 1):
                writer.writerow(
                    {
                        "rank": i,
                        "note": result["note"],
                        "score": round(result["score"], 4),
                        "direction": result["direction"],
                        "drivers": "; ".join(result.get("drivers", [])),
                    }
                )

    def _write_sources(
        self, source_breakdown: Dict[str, Any], path: str
    ) -> None:
        fieldnames = ["source", "item_count", "mention_count"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for source, data in sorted(source_breakdown.items()):
                writer.writerow(
                    {
                        "source": source,
                        "item_count": data["item_count"],
                        "mention_count": data["mention_count"],
                    }
                )
