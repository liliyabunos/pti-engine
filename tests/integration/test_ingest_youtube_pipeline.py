from pathlib import Path

from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv


def test_local_youtube_like_pipeline(tmp_path: Path) -> None:
    db_path = tmp_path / "pti.sqlite"
    csv_path = tmp_path / "seed.csv"

    csv_path.write_text(
        "\n".join(
            [
                "fragrance_id,brand_name,perfume_name,source",
                "fr_001,Parfums de Marly,Delina,kaggle",
            ]
        ),
        encoding="utf-8",
    )

    ingest_seed_csv(csv_path, db_path)

    raw_item = {
        "fetched_at": "2026-04-08T10:00:00Z",
        "query": "delina perfume",
        "search_item": {
            "id": {"videoId": "abc123"},
            "snippet": {
                "channelId": "channel_1",
                "channelTitle": "Perfume Creator",
                "publishedAt": "2026-04-01T10:00:00Z",
                "title": "Best Delina perfume review",
                "description": "Today we talk about Parfums de Marly Delina",
                "thumbnails": {},
            },
        },
        "video_details": {
            "statistics": {
                "viewCount": "1200",
                "likeCount": "55",
                "commentCount": "12",
            }
        },
    }

    normalizer = SocialContentNormalizer()
    normalized = normalizer.normalize_youtube_item(raw_item, raw_payload_ref="fake/ref.json")

    normalized_store = NormalizedContentStore(str(db_path))
    normalized_store.init_schema()
    normalized_store.save_content_items([normalized])

    resolver = PerfumeResolver(str(db_path))
    resolved = resolver.resolve_content_item(normalized)

    signal_store = SignalStore(str(db_path))
    signal_store.init_schema()
    signal_store.save_resolved_signals([resolved])

    rows = signal_store.list_resolved_signals()
    assert len(rows) == 1
    assert "Parfums de Marly Delina" in rows[0]["resolved_entities_json"]
