import json
import sqlite3
from pathlib import Path

from perfume_trend_sdk.core.models.unified_signal import UnifiedSignal


class SQLiteUnifiedStore:
    def __init__(self, db_path: str = "outputs/unified.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.init_db()

    def init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS unified_signals (
                    item_id TEXT PRIMARY KEY,
                    perfumes_json TEXT,
                    brands_json TEXT,
                    raw_mentions_json TEXT,
                    ai_perfumes_json TEXT,
                    ai_brands_json TEXT,
                    ai_notes_json TEXT,
                    ai_sentiment TEXT,
                    ai_confidence REAL,
                    source_type TEXT,
                    channel_name TEXT,
                    influence_score REAL,
                    credibility_score REAL
                )
            """)

    def write_unified(self, signals: list) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for signal in signals:
                conn.execute(
                    """
                    INSERT INTO unified_signals (
                        item_id, perfumes_json, brands_json, raw_mentions_json,
                        ai_perfumes_json, ai_brands_json, ai_notes_json,
                        ai_sentiment, ai_confidence,
                        source_type, channel_name, influence_score, credibility_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        perfumes_json     = excluded.perfumes_json,
                        brands_json       = excluded.brands_json,
                        raw_mentions_json = excluded.raw_mentions_json,
                        ai_perfumes_json  = excluded.ai_perfumes_json,
                        ai_brands_json    = excluded.ai_brands_json,
                        ai_notes_json     = excluded.ai_notes_json,
                        ai_sentiment      = excluded.ai_sentiment,
                        ai_confidence     = excluded.ai_confidence,
                        source_type       = excluded.source_type,
                        channel_name      = excluded.channel_name,
                        influence_score   = excluded.influence_score,
                        credibility_score = excluded.credibility_score
                    """,
                    (
                        signal.item_id,
                        json.dumps(signal.perfumes, ensure_ascii=False),
                        json.dumps(signal.brands, ensure_ascii=False),
                        json.dumps(signal.raw_mentions, ensure_ascii=False),
                        json.dumps(signal.ai_perfumes, ensure_ascii=False),
                        json.dumps(signal.ai_brands, ensure_ascii=False),
                        json.dumps(signal.ai_notes, ensure_ascii=False),
                        signal.ai_sentiment,
                        signal.ai_confidence,
                        signal.source_type,
                        signal.channel_name,
                        signal.influence_score,
                        signal.credibility_score,
                    ),
                )
