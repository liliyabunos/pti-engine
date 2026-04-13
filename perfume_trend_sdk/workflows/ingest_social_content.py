import math
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.connectors.youtube.youtube_connector import YouTubeConnector
from perfume_trend_sdk.core.config.loader import load_app_config, load_yaml
from perfume_trend_sdk.core.config.sources.youtube import YouTubeSourceConfig
from perfume_trend_sdk.core.logging.logger import log_event
from perfume_trend_sdk.core.models.context import PipelineContext
from perfume_trend_sdk.core.models.fetch import FetchSessionResult
from perfume_trend_sdk.core.models.signal_builder import SignalBuilder
from perfume_trend_sdk.core.registry.module_registry import ModuleRegistry
from perfume_trend_sdk.extractors.brand_mentions.extractor import BrandMentionExtractor
from perfume_trend_sdk.extractors.perfume_mentions.extractor import PerfumeMentionExtractor
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.publishers.json.publisher import JsonPublisher
from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownReportPublisher
from perfume_trend_sdk.resolvers.perfume_identity.resolver import PerfumeIdentityResolver
from perfume_trend_sdk.scorers.trend_score.scorer import TrendScorer
from perfume_trend_sdk.analysis.source_intelligence.analyzer import SourceIntelligenceAnalyzer
from perfume_trend_sdk.extractors.ai_engines.router import get_extractor
from perfume_trend_sdk.storage.normalized.sqlite_store import SQLiteNormalizedStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SQLiteSignalsStore
from perfume_trend_sdk.storage.unified.sqlite_store import SQLiteUnifiedStore
from perfume_trend_sdk.resolver.resolver import resolve_text
from perfume_trend_sdk.db.mentions_repo import insert_mention
from perfume_trend_sdk.db.resolution_repo import insert_resolution
from perfume_trend_sdk.db.unresolved_repo import insert_unresolved
from perfume_trend_sdk.utils.normalization import normalize_text


def run_ingest_social_content() -> dict:
    app_config = load_app_config("configs/app.yaml")
    raw_config = load_yaml("configs/app.yaml")
    youtube_raw = raw_config.get("youtube", {})
    youtube_raw["api_key"] = os.getenv("YOUTUBE_API_KEY") or youtube_raw.get("api_key")
    youtube_config = YouTubeSourceConfig(**youtube_raw)

    context = PipelineContext(
        run_id=f"ingest_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}",
        workflow_name="ingest_social_content",
        started_at=datetime.utcnow(),
        environment=app_config.environment,
        schema_version=app_config.schema_version,
    )

    registry = ModuleRegistry()
    registry.register_connector("youtube", YouTubeConnector(youtube_config))

    log_event("INFO", "Pipeline started", run_id=context.run_id, workflow=context.workflow_name)

    connector = registry.get_connector("youtube")
    raw_result = connector.fetch()

    fetch_result = FetchSessionResult(
        source_name=connector.name,
        fetched_count=len(raw_result["items"]),
        raw_items=raw_result["items"],
    )

    log_event("INFO", "Fetch completed", run_id=context.run_id, fetched_count=fetch_result.fetched_count)

    source_analyzer = SourceIntelligenceAnalyzer()
    source_results = [
        source_analyzer.analyze(item)
        for item in raw_result["items"]
    ]
    log_event("INFO", "Source intelligence completed", run_id=context.run_id, source=fetch_result.source_name, count=len(source_results))

    raw_store = FilesystemRawStorage()
    raw_store.save_raw_batch(fetch_result.source_name, context.run_id, fetch_result.raw_items)
    log_event("INFO", "Raw payload stored", run_id=context.run_id, source=fetch_result.source_name, count=fetch_result.fetched_count)

    normalizer = SocialContentNormalizer()
    canonical_items = [
        normalizer.normalize(item)
        for item in fetch_result.raw_items
    ]

    log_event("INFO", "Normalization completed", run_id=context.run_id, source=fetch_result.source_name, normalized_count=len(canonical_items))

    for item, raw_item in zip(canonical_items, fetch_result.raw_items):
        text = item.text_content or item.title or ""

        normalized_text, _ = normalize_text(text)

        view_count = raw_item.get("view_count")
        weight = min(math.log10(view_count + 1), 5.0) if view_count else 0.1

        mention_id = insert_mention(
            raw_text=text,
            normalized_text=normalized_text,
            source="youtube",
            weight=weight,
        )

        result = resolve_text(text)

        if result["method"] == "unresolved":
            insert_unresolved(
                mention_id,
                result.get("candidate"),
                reason="low_confidence",
            )
        else:
            insert_resolution(mention_id, result)

    log_event("INFO", "Resolution stored", run_id=context.run_id, source=fetch_result.source_name, count=len(canonical_items))

    ai_config = raw_config.get("ai", {})
    ai_results = []
    if ai_config.get("enabled", False):
        ai_extractor = get_extractor(
            provider=ai_config.get("provider", "openai"),
            model=ai_config.get("model", "gpt-4o-mini"),
            temperature=ai_config.get("temperature", 0),
        )
        for item in canonical_items:
            text = f"{item.title}\n{item.text_content}"
            # ai_results.append(ai_extractor.extract(text))
        log_event("INFO", "AI extraction completed", run_id=context.run_id, source=fetch_result.source_name, count=len(ai_results))

    normalized_store = SQLiteNormalizedStore()
    normalized_store.write_normalized([item.model_dump() for item in canonical_items])
    log_event("INFO", "Normalized items stored", run_id=context.run_id, source=fetch_result.source_name, count=len(canonical_items))

    extractor = PerfumeMentionExtractor()
    extracted_results = [
        extractor.extract(item)
        for item in canonical_items
    ]

    log_event("INFO", "Extraction completed", run_id=context.run_id, source=fetch_result.source_name, extracted_count=len(extracted_results))

    signals_store = SQLiteSignalsStore()
    signals_store.write_signals(extracted_results)
    log_event("INFO", "Signals stored", run_id=context.run_id, source=fetch_result.source_name, count=len(extracted_results))

    resolver = PerfumeIdentityResolver()
    resolved_results = [
        resolver.resolve(result)
        for result in extracted_results
    ]

    log_event("INFO", "Resolution completed", run_id=context.run_id, source=fetch_result.source_name, resolved_count=len(resolved_results))

    brand_extractor = BrandMentionExtractor()
    brand_results = [
        brand_extractor.extract(item)
        for item in canonical_items
    ]

    log_event("INFO", "Brand extraction completed", run_id=context.run_id, source=fetch_result.source_name, extracted_count=len(brand_results))

    builder = SignalBuilder()
    ai_iter = ai_results if ai_results else [None] * len(extracted_results)
    source_iter = source_results if source_results else [None] * len(extracted_results)
    unified_signals = [
        builder.build(perfume_result, brand_result, resolved_result, ai_result, source_result)
        for perfume_result, brand_result, resolved_result, ai_result, source_result in zip(
            extracted_results,
            brand_results,
            resolved_results,
            ai_iter,
            source_iter,
        )
    ]

    log_event("INFO", "Unified signals built", run_id=context.run_id, source=fetch_result.source_name, unified_count=len(unified_signals))

    unified_store = SQLiteUnifiedStore()
    unified_store.write_unified(unified_signals)
    log_event("INFO", "Unified signals stored", run_id=context.run_id, source=fetch_result.source_name, count=len(unified_signals))

    scorer = TrendScorer()
    trend_summary = scorer.score(unified_signals)

    log_event("INFO", "Scoring completed", run_id=context.run_id, source=fetch_result.source_name, total_mentions=trend_summary["total_mentions"])

    markdown_publisher = WeeklyMarkdownReportPublisher()
    markdown_publisher.publish(
        trend_summary=trend_summary,
        output_path="outputs/reports/weekly_report.md",
    )
    log_event("INFO", "Weekly report generated", run_id=context.run_id, source=fetch_result.source_name)

    payload = {
        "run_id": context.run_id,
        "source": fetch_result.source_name,
        "fetched_count": fetch_result.fetched_count,
        "normalized_count": len(canonical_items),
        "extracted_count": len(extracted_results),
        "resolved_count": len(resolved_results),
        "brand_extracted_count": len(brand_results),
        "unified_count": len(unified_signals),
        "trend_summary": trend_summary,
        "source_results": source_results,
        "ai_results": ai_results,
        "status": "ok",
    }

    JsonPublisher().publish(payload, "outputs/ingest_social_content_result.json")

    return payload
