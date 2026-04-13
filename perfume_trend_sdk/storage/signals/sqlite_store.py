from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List


class SignalStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resolved_signals (
                    content_item_id TEXT PRIMARY KEY,
                    resolver_version TEXT NOT NULL,
                    resolved_entities_json TEXT NOT NULL,
                    unresolved_mentions_json TEXT NOT NULL,
                    alias_candidates_json TEXT NOT NULL
                )
                """
            )
            # Ensure unique index exists for DBs that were created with the
            # legacy autoincrement schema (e.g. market_dev.db from dev_backfill).
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_rs_content_item_id
                ON resolved_signals(content_item_id)
                """
            )

    def save_resolved_signals(self, items: List[Dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO resolved_signals (
                    content_item_id,
                    resolver_version,
                    resolved_entities_json,
                    unresolved_mentions_json,
                    alias_candidates_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(content_item_id) DO UPDATE SET
                    resolver_version = excluded.resolver_version,
                    resolved_entities_json = excluded.resolved_entities_json,
                    unresolved_mentions_json = excluded.unresolved_mentions_json,
                    alias_candidates_json = excluded.alias_candidates_json
                """,
                [
                    (
                        item["content_item_id"],
                        item["resolver_version"],
                        json.dumps(item.get("resolved_entities", []), ensure_ascii=False),
                        json.dumps(item.get("unresolved_mentions", []), ensure_ascii=False),
                        json.dumps(item.get("alias_candidates", []), ensure_ascii=False),
                    )
                    for item in items
                ],
            )

    def list_resolved_signals(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT content_item_id, resolver_version, resolved_entities_json
                FROM resolved_signals
                """
            ).fetchall()
            return [dict(r) for r in rows]
