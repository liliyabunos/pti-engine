from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from perfume_trend_sdk.analysis.candidate_aggregator import aggregate_unresolved, save_top_candidates


DEFAULT_DB = "outputs/pti.db"
DEFAULT_OUTPUT = "outputs/top_unresolved_candidates.json"


def load_unresolved_rows(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT rs.unresolved_mentions_json, cci.source_platform AS source, cci.collected_at AS created_at
            FROM resolved_signals rs
            JOIN canonical_content_items cci ON rs.content_item_id = cci.id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    result = []
    for row in rows:
        mentions = json.loads(row["unresolved_mentions_json"] or "[]")
        for text in mentions:
            if text:
                result.append({
                    "normalized_text": text,
                    "source": row["source"] or "unknown",
                    "created_at": row["created_at"] or "",
                })
    return result


def run(db_path: str = DEFAULT_DB, output: str = DEFAULT_OUTPUT) -> None:
    rows = load_unresolved_rows(db_path)
    aggregated = aggregate_unresolved(rows)
    save_top_candidates(aggregated, path=output)

    print(f"Unresolved mentions processed: {len(rows)}")
    print(f"Unique candidates: {len(aggregated)}")
    print(f"Saved to: {output}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate unresolved mentions into candidate list.")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite DB path")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output JSON path")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    run(db_path=args.db, output=args.output)


if __name__ == "__main__":
    main()
