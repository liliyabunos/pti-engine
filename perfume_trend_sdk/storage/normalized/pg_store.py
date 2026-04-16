from __future__ import annotations

"""
Postgres backend for canonical_content_items.

Drop-in replacement for NormalizedContentStore when DATABASE_URL is set.
Uses psycopg2 directly — same SQL surface as the SQLite store, just %s
placeholders and a persistent connection instead of sqlite3.
"""

import json
from typing import Any, Dict, List


class PgNormalizedContentStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self.database_url)

    def init_schema(self) -> None:
        # Table created by Alembic migration 007 — nothing to do here.
        pass

    def save_content_items(self, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        sql = """
            INSERT INTO canonical_content_items (
                id, schema_version, source_platform, source_account_id, source_account_handle,
                source_account_type, source_url, external_content_id, published_at, collected_at,
                content_type, title, caption, text_content, hashtags_json, mentions_raw_json,
                media_metadata_json, engagement_json, language, region, raw_payload_ref,
                normalizer_version, query
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                schema_version        = EXCLUDED.schema_version,
                source_platform       = EXCLUDED.source_platform,
                source_account_id     = EXCLUDED.source_account_id,
                source_account_handle = EXCLUDED.source_account_handle,
                source_account_type   = EXCLUDED.source_account_type,
                source_url            = EXCLUDED.source_url,
                external_content_id   = EXCLUDED.external_content_id,
                published_at          = EXCLUDED.published_at,
                collected_at          = EXCLUDED.collected_at,
                content_type          = EXCLUDED.content_type,
                title                 = EXCLUDED.title,
                caption               = EXCLUDED.caption,
                text_content          = EXCLUDED.text_content,
                hashtags_json         = EXCLUDED.hashtags_json,
                mentions_raw_json     = EXCLUDED.mentions_raw_json,
                media_metadata_json   = EXCLUDED.media_metadata_json,
                engagement_json       = EXCLUDED.engagement_json,
                language              = EXCLUDED.language,
                region                = EXCLUDED.region,
                raw_payload_ref       = EXCLUDED.raw_payload_ref,
                normalizer_version    = EXCLUDED.normalizer_version,
                query                 = EXCLUDED.query
        """
        rows = [
            (
                item["id"],
                item["schema_version"],
                item["source_platform"],
                item.get("source_account_id"),
                item.get("source_account_handle"),
                item.get("source_account_type"),
                item["source_url"],
                item.get("external_content_id"),
                item["published_at"],
                item["collected_at"],
                item["content_type"],
                item.get("title"),
                item.get("caption"),
                item.get("text_content"),
                json.dumps(item.get("hashtags", []), ensure_ascii=False),
                json.dumps(item.get("mentions_raw", []), ensure_ascii=False),
                json.dumps(item.get("media_metadata", {}), ensure_ascii=False),
                json.dumps(item.get("engagement", {}), ensure_ascii=False),
                item.get("language"),
                item["region"],
                item["raw_payload_ref"],
                item["normalizer_version"],
                item.get("query"),
            )
            for item in items
        ]
        import psycopg2.extras
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_batch(cur, sql, rows, page_size=100)
        finally:
            conn.close()
