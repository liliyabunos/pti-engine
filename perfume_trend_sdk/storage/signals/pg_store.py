from __future__ import annotations

"""
Postgres backend for resolved_signals.

Drop-in replacement for SignalStore when DATABASE_URL is set.
"""

import json
from typing import Any, Dict, List


class PgSignalStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self.database_url)

    def init_schema(self) -> None:
        # Table created by Alembic migration 007 — nothing to do here.
        pass

    def save_resolved_signals(self, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        sql = """
            INSERT INTO resolved_signals (
                content_item_id,
                resolver_version,
                resolved_entities_json,
                unresolved_mentions_json,
                alias_candidates_json
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (content_item_id) DO UPDATE SET
                resolver_version          = EXCLUDED.resolver_version,
                resolved_entities_json    = EXCLUDED.resolved_entities_json,
                unresolved_mentions_json  = EXCLUDED.unresolved_mentions_json,
                alias_candidates_json     = EXCLUDED.alias_candidates_json
        """
        # Deduplicate by content_item_id within this batch (keep last occurrence).
        # execute_batch sends rows in the same transaction; if the same content_item_id
        # appears twice, Postgres cannot resolve the ON CONFLICT within the batch and
        # crashes on the autoincrement PK instead.
        seen: dict = {}
        for item in items:
            seen[item["content_item_id"]] = item
        rows = [
            (
                item["content_item_id"],
                item["resolver_version"],
                json.dumps(item.get("resolved_entities", []), ensure_ascii=False),
                json.dumps(item.get("unresolved_mentions", []), ensure_ascii=False),
                json.dumps(item.get("alias_candidates", []), ensure_ascii=False),
            )
            for item in seen.values()
        ]
        import psycopg2.extras
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_batch(cur, sql, rows, page_size=100)
        finally:
            conn.close()
