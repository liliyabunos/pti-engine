from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from perfume_trend_sdk.connectors.youtube.youtube_connector import YouTubeConnector
from perfume_trend_sdk.core.config.loader import load_app_config, load_yaml
from perfume_trend_sdk.core.config.sources.youtube import YouTubeSourceConfig
from perfume_trend_sdk.core.logging.logger import log_event
from perfume_trend_sdk.core.models.context import PipelineContext
from perfume_trend_sdk.core.models.fetch import FetchSessionResult
from perfume_trend_sdk.core.registry.module_registry import ModuleRegistry
from perfume_trend_sdk.extractors.brand_mentions.extractor import BrandMentionExtractor
from perfume_trend_sdk.resolvers.perfume_identity.resolver import PerfumeIdentityResolver
from perfume_trend_sdk.extractors.perfume_mentions.extractor import PerfumeMentionExtractor
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.publishers.json.publisher import JsonPublisher
from perfume_trend_sdk.publishers.markdown.weekly_report import WeeklyMarkdownReportPublisher
from perfume_trend_sdk.scorers.trend_score.scorer import TrendScorer
from perfume_trend_sdk.core.models.signal_builder import SignalBuilder
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStore
from perfume_trend_sdk.storage.unified.sqlite_store import SQLiteUnifiedStore
from perfume_trend_sdk.storage.normalized.sqlite_store import SQLiteNormalizedStore
from perfume_trend_sdk.storage.signals.sqlite_store import SQLiteSignalsStore


def run_test_pipeline() -> dict:
    app_config = load_app_config("configs/app.yaml")
    raw_config = load_yaml("configs/app.yaml")
    youtube_config = YouTubeSourceConfig(**raw_config.get("youtube", {}))

    context = PipelineContext(
        run_id="run_test_001",
        workflow_name="test_pipeline",
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

    raw_store = FilesystemRawStore()
    raw_store.write_raw(fetch_result.source_name, raw_result)
    log_event("INFO", "Raw payload stored", run_id=context.run_id, source=fetch_result.source_name, count=fetch_result.fetched_count)

    normalizer = SocialContentNormalizer()
    canonical_items = [
        normalizer.normalize(item)
        for item in fetch_result.raw_items
    ]

    log_event("INFO", "Normalization completed", run_id=context.run_id, source=fetch_result.source_name, normalized_count=len(canonical_items))

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
    unified_signals = [
        builder.build(perfume_result, brand_result, resolved_result)
        for perfume_result, brand_result, resolved_result in zip(
            extracted_results,
            brand_results,
            resolved_results,
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

    publisher = JsonPublisher()
    payload = {
        "run_id": context.run_id,
        "source": fetch_result.source_name,
        "fetched_count": fetch_result.fetched_count,
        "normalized_count": len(canonical_items),
        "extracted_count": len(extracted_results),
        "resolved_count": len(resolved_results),
        "resolved_results": resolved_results,
        "brand_extracted_count": len(brand_results),
        "unified_count": len(unified_signals),
        "brand_results": brand_results,
        "trend_summary": trend_summary,
        "status": "ok",
    }
    publisher.publish(payload, "outputs/test_pipeline_result.json")

    return payload
