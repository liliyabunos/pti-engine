import json

from dotenv import load_dotenv

load_dotenv()
import sqlite3

from perfume_trend_sdk.core.models.unified_signal import UnifiedSignal
from perfume_trend_sdk.publishers.json.publisher import JsonPublisher
from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownReportPublisher
from perfume_trend_sdk.scorers.trend_score.scorer import TrendScorer


def run_build_weekly_report() -> dict:
    with sqlite3.connect("outputs/unified.db") as conn:
        rows = conn.execute(
            """
            SELECT item_id, perfumes_json, brands_json, raw_mentions_json,
                   ai_perfumes_json, ai_brands_json, ai_notes_json,
                   ai_sentiment, ai_confidence,
                   source_type, channel_name, influence_score, credibility_score
            FROM unified_signals
            """
        ).fetchall()

    unified_signals = [
        UnifiedSignal(
            item_id=row[0],
            perfumes=json.loads(row[1]),
            brands=json.loads(row[2]),
            raw_mentions=json.loads(row[3]),
            ai_perfumes=json.loads(row[4]) if row[4] else [],
            ai_brands=json.loads(row[5]) if row[5] else [],
            ai_notes=json.loads(row[6]) if row[6] else [],
            ai_sentiment=row[7],
            ai_confidence=row[8],
            source_type=row[9],
            channel_name=row[10],
            influence_score=row[11],
            credibility_score=row[12],
        )
        for row in rows
    ]

    scorer = TrendScorer()
    trend_summary = scorer.score(unified_signals)

    WeeklyMarkdownReportPublisher().publish(
        trend_summary=trend_summary,
        output_path="outputs/reports/weekly_report.md",
    )

    payload = {
        "total_unified_items": len(unified_signals),
        "trend_summary": trend_summary,
        "status": "ok",
    }

    JsonPublisher().publish(payload, "outputs/build_weekly_report_result.json")

    return payload
