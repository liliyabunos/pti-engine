from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List


class NormalizedContentStore:
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
                CREATE TABLE IF NOT EXISTS canonical_content_items (
                    id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    source_platform TEXT NOT NULL,
                    source_account_id TEXT NULL,
                    source_account_handle TEXT NULL,
                    source_account_type TEXT NULL,
                    source_url TEXT NOT NULL,
                    external_content_id TEXT NULL,
                    published_at TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    title TEXT NULL,
                    caption TEXT NULL,
                    text_content TEXT NULL,
                    hashtags_json TEXT NOT NULL,
                    mentions_raw_json TEXT NOT NULL,
                    media_metadata_json TEXT NOT NULL,
                    engagement_json TEXT NOT NULL,
                    language TEXT NULL,
                    region TEXT NOT NULL,
                    raw_payload_ref TEXT NOT NULL,
                    normalizer_version TEXT NOT NULL,
                    query TEXT NULL
                )
                """
            )

    def save_content_items(self, items: List[Dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO canonical_content_items (
                    id, schema_version, source_platform, source_account_id, source_account_handle,
                    source_account_type, source_url, external_content_id, published_at, collected_at,
                    content_type, title, caption, text_content, hashtags_json, mentions_raw_json,
                    media_metadata_json, engagement_json, language, region, raw_payload_ref,
                    normalizer_version, query
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    source_platform = excluded.source_platform,
                    source_account_id = excluded.source_account_id,
                    source_account_handle = excluded.source_account_handle,
                    source_account_type = excluded.source_account_type,
                    source_url = excluded.source_url,
                    external_content_id = excluded.external_content_id,
                    published_at = excluded.published_at,
                    collected_at = excluded.collected_at,
                    content_type = excluded.content_type,
                    title = excluded.title,
                    caption = excluded.caption,
                    text_content = excluded.text_content,
                    hashtags_json = excluded.hashtags_json,
                    mentions_raw_json = excluded.mentions_raw_json,
                    media_metadata_json = excluded.media_metadata_json,
                    engagement_json = excluded.engagement_json,
                    language = excluded.language,
                    region = excluded.region,
                    raw_payload_ref = excluded.raw_payload_ref,
                    normalizer_version = excluded.normalizer_version,
                    query = excluded.query
                """,
                [
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
                ],
            )

    def list_content_items(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, text_content, source_url, published_at, query, engagement_json
                FROM canonical_content_items
                ORDER BY published_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def list_content_items_full(self) -> List[Dict[str, Any]]:
        """Return all columns needed for cross-source aggregation and reporting.

        Includes source_platform and media_metadata_json in addition to the
        fields returned by list_content_items().
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, text_content, source_url, published_at, query,
                       source_platform, source_account_handle, content_type,
                       engagement_json, media_metadata_json
                FROM canonical_content_items
                ORDER BY published_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
