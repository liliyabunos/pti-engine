from __future__ import annotations

"""
SQLAlchemy-backed storage implementations for the ingestion pipeline.

These are drop-in replacements for the legacy sqlite3 stores:
  - NormalizedContentStore  (replaces storage/normalized/sqlite_store.py)
  - SignalStore             (replaces storage/signals/sqlite_store.py)
  - UnifiedSignalStore      (replaces storage/unified/sqlite_store.py)

All use sqlalchemy.text() with named parameters (:param) so they work
transparently with both SQLite (dev) and PostgreSQL (production).

The ON CONFLICT ... DO UPDATE syntax is supported by:
  - PostgreSQL 9.5+
  - SQLite 3.24+  (2018-06-04)

Usage::

    from perfume_trend_sdk.storage.postgres.db import get_engine
    from perfume_trend_sdk.storage.postgres.postgres_store import (
        NormalizedContentStore, SignalStore, UnifiedSignalStore,
    )

    engine = get_engine()
    store = NormalizedContentStore(engine)
    store.init_schema()
    store.save_content_items([...])
"""

import json
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# NormalizedContentStore
# ---------------------------------------------------------------------------

class NormalizedContentStore:
    """Stores canonical_content_items for ingested content (YouTube, Reddit, …).

    Replaces perfume_trend_sdk/storage/normalized/sqlite_store.py.
    The table schema is identical; only the driver is different.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def init_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS canonical_content_items (
                    id                  TEXT PRIMARY KEY,
                    schema_version      TEXT NOT NULL,
                    source_platform     TEXT NOT NULL,
                    source_account_id   TEXT,
                    source_account_handle TEXT,
                    source_account_type TEXT,
                    source_url          TEXT NOT NULL,
                    external_content_id TEXT,
                    published_at        TEXT NOT NULL,
                    collected_at        TEXT NOT NULL,
                    content_type        TEXT NOT NULL,
                    title               TEXT,
                    caption             TEXT,
                    text_content        TEXT,
                    hashtags_json       TEXT NOT NULL,
                    mentions_raw_json   TEXT NOT NULL,
                    media_metadata_json TEXT NOT NULL,
                    engagement_json     TEXT NOT NULL,
                    language            TEXT,
                    region              TEXT NOT NULL,
                    raw_payload_ref     TEXT NOT NULL,
                    normalizer_version  TEXT NOT NULL,
                    query               TEXT
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_cci_platform_date
                    ON canonical_content_items(source_platform, published_at)
            """))

    def save_content_items(self, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        with self.engine.begin() as conn:
            for item in items:
                conn.execute(text("""
                    INSERT INTO canonical_content_items (
                        id, schema_version, source_platform,
                        source_account_id, source_account_handle, source_account_type,
                        source_url, external_content_id, published_at, collected_at,
                        content_type, title, caption, text_content,
                        hashtags_json, mentions_raw_json, media_metadata_json,
                        engagement_json, language, region,
                        raw_payload_ref, normalizer_version, query
                    )
                    VALUES (
                        :id, :schema_version, :source_platform,
                        :source_account_id, :source_account_handle, :source_account_type,
                        :source_url, :external_content_id, :published_at, :collected_at,
                        :content_type, :title, :caption, :text_content,
                        :hashtags_json, :mentions_raw_json, :media_metadata_json,
                        :engagement_json, :language, :region,
                        :raw_payload_ref, :normalizer_version, :query
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        schema_version      = EXCLUDED.schema_version,
                        source_platform     = EXCLUDED.source_platform,
                        source_account_id   = EXCLUDED.source_account_id,
                        source_account_handle = EXCLUDED.source_account_handle,
                        source_account_type = EXCLUDED.source_account_type,
                        source_url          = EXCLUDED.source_url,
                        external_content_id = EXCLUDED.external_content_id,
                        published_at        = EXCLUDED.published_at,
                        collected_at        = EXCLUDED.collected_at,
                        content_type        = EXCLUDED.content_type,
                        title               = EXCLUDED.title,
                        caption             = EXCLUDED.caption,
                        text_content        = EXCLUDED.text_content,
                        hashtags_json       = EXCLUDED.hashtags_json,
                        mentions_raw_json   = EXCLUDED.mentions_raw_json,
                        media_metadata_json = EXCLUDED.media_metadata_json,
                        engagement_json     = EXCLUDED.engagement_json,
                        language            = EXCLUDED.language,
                        region              = EXCLUDED.region,
                        raw_payload_ref     = EXCLUDED.raw_payload_ref,
                        normalizer_version  = EXCLUDED.normalizer_version,
                        query               = EXCLUDED.query
                """), {
                    "id":                    item["id"],
                    "schema_version":        item["schema_version"],
                    "source_platform":       item["source_platform"],
                    "source_account_id":     item.get("source_account_id"),
                    "source_account_handle": item.get("source_account_handle"),
                    "source_account_type":   item.get("source_account_type"),
                    "source_url":            item["source_url"],
                    "external_content_id":   item.get("external_content_id"),
                    "published_at":          item["published_at"],
                    "collected_at":          item["collected_at"],
                    "content_type":          item["content_type"],
                    "title":                 item.get("title"),
                    "caption":               item.get("caption"),
                    "text_content":          item.get("text_content"),
                    "hashtags_json":         json.dumps(item.get("hashtags", []), ensure_ascii=False),
                    "mentions_raw_json":     json.dumps(item.get("mentions_raw", []), ensure_ascii=False),
                    "media_metadata_json":   json.dumps(item.get("media_metadata", {}), ensure_ascii=False),
                    "engagement_json":       json.dumps(item.get("engagement", {}), ensure_ascii=False),
                    "language":              item.get("language"),
                    "region":                item["region"],
                    "raw_payload_ref":       item["raw_payload_ref"],
                    "normalizer_version":    item["normalizer_version"],
                    "query":                 item.get("query"),
                })

    def list_content_items(self) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, title, text_content, source_url, published_at, query, engagement_json
                FROM canonical_content_items
                ORDER BY published_at DESC
            """)).fetchall()
            return [dict(r._mapping) for r in rows]

    def list_content_items_full(self) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, title, text_content, source_url, published_at, query,
                       source_platform, source_account_handle, content_type,
                       engagement_json, media_metadata_json
                FROM canonical_content_items
                ORDER BY published_at DESC
            """)).fetchall()
            return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# SignalStore
# ---------------------------------------------------------------------------

class SignalStore:
    """Stores resolved_signals produced by PerfumeResolver.

    Replaces perfume_trend_sdk/storage/signals/sqlite_store.py.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def init_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS resolved_signals (
                    content_item_id         TEXT PRIMARY KEY,
                    resolver_version        TEXT NOT NULL,
                    resolved_entities_json  TEXT NOT NULL,
                    unresolved_mentions_json TEXT NOT NULL,
                    alias_candidates_json   TEXT NOT NULL
                )
            """))
            # content_item_id is already PK (unique index auto-created).
            # Additional index on resolved_entities_json is not practical — use
            # the ORM entity_mentions table for entity-based lookups instead.
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_rs_resolver_version
                    ON resolved_signals(resolver_version)
            """))

    def save_resolved_signals(self, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        with self.engine.begin() as conn:
            for item in items:
                conn.execute(text("""
                    INSERT INTO resolved_signals (
                        content_item_id,
                        resolver_version,
                        resolved_entities_json,
                        unresolved_mentions_json,
                        alias_candidates_json
                    )
                    VALUES (
                        :content_item_id,
                        :resolver_version,
                        :resolved_entities_json,
                        :unresolved_mentions_json,
                        :alias_candidates_json
                    )
                    ON CONFLICT(content_item_id) DO UPDATE SET
                        resolver_version         = EXCLUDED.resolver_version,
                        resolved_entities_json   = EXCLUDED.resolved_entities_json,
                        unresolved_mentions_json = EXCLUDED.unresolved_mentions_json,
                        alias_candidates_json    = EXCLUDED.alias_candidates_json
                """), {
                    "content_item_id":          item["content_item_id"],
                    "resolver_version":         item["resolver_version"],
                    "resolved_entities_json":   json.dumps(item.get("resolved_entities", []), ensure_ascii=False),
                    "unresolved_mentions_json": json.dumps(item.get("unresolved_mentions", []), ensure_ascii=False),
                    "alias_candidates_json":    json.dumps(item.get("alias_candidates", []), ensure_ascii=False),
                })

    def list_resolved_signals(self) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT content_item_id, resolver_version, resolved_entities_json
                FROM resolved_signals
            """)).fetchall()
            return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# UnifiedSignalStore
# ---------------------------------------------------------------------------

class UnifiedSignalStore:
    """Stores unified signals (rule-based + AI extraction results).

    Replaces perfume_trend_sdk/storage/unified/sqlite_store.py.
    Fixes the legacy INSERT OR REPLACE with proper ON CONFLICT DO UPDATE.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def init_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS unified_signals (
                    item_id           TEXT PRIMARY KEY,
                    perfumes_json     TEXT,
                    brands_json       TEXT,
                    raw_mentions_json TEXT,
                    ai_perfumes_json  TEXT,
                    ai_brands_json    TEXT,
                    ai_notes_json     TEXT,
                    ai_sentiment      TEXT,
                    ai_confidence     REAL,
                    source_type       TEXT,
                    channel_name      TEXT,
                    influence_score   REAL,
                    credibility_score REAL
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_us_source_type
                    ON unified_signals(source_type)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_us_channel
                    ON unified_signals(channel_name)
            """))

    def write_unified(self, signals: list) -> None:
        if not signals:
            return
        with self.engine.begin() as conn:
            for signal in signals:
                conn.execute(text("""
                    INSERT INTO unified_signals (
                        item_id, perfumes_json, brands_json, raw_mentions_json,
                        ai_perfumes_json, ai_brands_json, ai_notes_json,
                        ai_sentiment, ai_confidence,
                        source_type, channel_name, influence_score, credibility_score
                    )
                    VALUES (
                        :item_id, :perfumes_json, :brands_json, :raw_mentions_json,
                        :ai_perfumes_json, :ai_brands_json, :ai_notes_json,
                        :ai_sentiment, :ai_confidence,
                        :source_type, :channel_name, :influence_score, :credibility_score
                    )
                    ON CONFLICT(item_id) DO UPDATE SET
                        perfumes_json     = EXCLUDED.perfumes_json,
                        brands_json       = EXCLUDED.brands_json,
                        raw_mentions_json = EXCLUDED.raw_mentions_json,
                        ai_perfumes_json  = EXCLUDED.ai_perfumes_json,
                        ai_brands_json    = EXCLUDED.ai_brands_json,
                        ai_notes_json     = EXCLUDED.ai_notes_json,
                        ai_sentiment      = EXCLUDED.ai_sentiment,
                        ai_confidence     = EXCLUDED.ai_confidence,
                        source_type       = EXCLUDED.source_type,
                        channel_name      = EXCLUDED.channel_name,
                        influence_score   = EXCLUDED.influence_score,
                        credibility_score = EXCLUDED.credibility_score
                """), {
                    "item_id":           signal.item_id,
                    "perfumes_json":     json.dumps(signal.perfumes, ensure_ascii=False),
                    "brands_json":       json.dumps(signal.brands, ensure_ascii=False),
                    "raw_mentions_json": json.dumps(signal.raw_mentions, ensure_ascii=False),
                    "ai_perfumes_json":  json.dumps(signal.ai_perfumes, ensure_ascii=False),
                    "ai_brands_json":    json.dumps(signal.ai_brands, ensure_ascii=False),
                    "ai_notes_json":     json.dumps(signal.ai_notes, ensure_ascii=False),
                    "ai_sentiment":      signal.ai_sentiment,
                    "ai_confidence":     signal.ai_confidence,
                    "source_type":       signal.source_type,
                    "channel_name":      signal.channel_name,
                    "influence_score":   signal.influence_score,
                    "credibility_score": signal.credibility_score,
                })
