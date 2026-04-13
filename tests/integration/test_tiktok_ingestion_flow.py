from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "tiktok_post_raw.json"


@pytest.fixture
def raw_post() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def normalizer() -> SocialContentNormalizer:
    return SocialContentNormalizer()


def test_normalize_tiktok_item(normalizer: SocialContentNormalizer, raw_post: dict) -> None:
    result = normalizer.normalize_tiktok_item(raw_post, raw_payload_ref="fake/ref.json")
    assert result["source_platform"] == "tiktok"


def test_normalize_tiktok_engagement(normalizer: SocialContentNormalizer, raw_post: dict) -> None:
    result = normalizer.normalize_tiktok_item(raw_post, raw_payload_ref="fake/ref.json")
    assert result["engagement"]["views"] == 124300


def test_normalize_tiktok_hashtags(normalizer: SocialContentNormalizer, raw_post: dict) -> None:
    result = normalizer.normalize_tiktok_item(raw_post, raw_payload_ref="fake/ref.json")
    assert "perfume" in result["hashtags"]


def test_normalize_tiktok_text_content(normalizer: SocialContentNormalizer, raw_post: dict) -> None:
    result = normalizer.normalize_tiktok_item(raw_post, raw_payload_ref="fake/ref.json")
    assert result["text_content"] is not None
    assert "Delina" in result["text_content"]


# ---------------------------------------------------------------------------
# Risk #2 — entity name only in hashtags
# ---------------------------------------------------------------------------

def test_text_content_includes_hashtags(normalizer: SocialContentNormalizer, raw_post: dict) -> None:
    """Hashtags are appended to text_content so the resolver sees them."""
    result = normalizer.normalize_tiktok_item(raw_post, raw_payload_ref="fake/ref.json")
    # Fixture hashtags: perfume, fragrance, niche, delina, pdm
    assert "delina" in result["text_content"].lower()
    assert "pdm" in result["text_content"].lower()


def test_text_content_hashtag_only_caption(normalizer: SocialContentNormalizer) -> None:
    """When caption is empty, hashtags alone become text_content."""
    raw = {
        "id": "999",
        "desc": "",  # empty caption
        "createTime": 1712345678,
        "author": {"id": "u1", "uniqueId": "creator", "followerCount": 0, "verified": False},
        "stats": {"playCount": 5000, "diggCount": 100, "commentCount": 10, "shareCount": 5},
        "video": {"duration": 30},
        "challenges": [{"title": "delina"}, {"title": "pdm"}, {"title": "perfume"}],
    }
    result = normalizer.normalize_tiktok_item(raw, raw_payload_ref="fake/ref.json")
    assert result["text_content"] is not None
    assert "delina" in result["text_content"]
    assert "pdm" in result["text_content"]


def test_text_content_no_caption_no_hashtags_is_none(normalizer: SocialContentNormalizer) -> None:
    """No caption and no hashtags → text_content is None (not empty string)."""
    raw = {
        "id": "000",
        "desc": "",
        "createTime": 1712345678,
        "author": {"id": "u1", "uniqueId": "creator", "followerCount": 0, "verified": False},
        "stats": {"playCount": 1000, "diggCount": 10, "commentCount": 1, "shareCount": 0},
        "video": {"duration": 15},
        "challenges": [],
    }
    result = normalizer.normalize_tiktok_item(raw, raw_payload_ref="fake/ref.json")
    assert result["text_content"] is None


def test_hashtag_only_post_resolves_entity(tmp_path: Path) -> None:
    """
    Regression: TikTok post with entity name ONLY in a hashtag (empty caption)
    must still resolve to the correct perfume after normalization.

    Before the caption+hashtag merge this would produce text_content=None
    and the resolver would return zero matches.
    """
    db_path = tmp_path / "pti_hashtag.sqlite"
    csv_path = tmp_path / "seed.csv"

    csv_path.write_text(
        "\n".join([
            "fragrance_id,brand_name,perfume_name,source",
            "fr_001,Parfums de Marly,Delina,kaggle",
        ]),
        encoding="utf-8",
    )
    ingest_seed_csv(csv_path, db_path)

    raw = {
        "id": "hashtag_only_123",
        "desc": "",  # no caption text at all
        "createTime": 1712345678,
        "author": {"id": "u99", "uniqueId": "scenthunter", "followerCount": 12000, "verified": False},
        "stats": {"playCount": 80000, "diggCount": 3200, "commentCount": 95, "shareCount": 410},
        "video": {"duration": 28},
        "challenges": [{"title": "delina"}, {"title": "pdm"}, {"title": "perfume"}],
    }

    normalizer = SocialContentNormalizer()
    normalized = normalizer.normalize_tiktok_item(raw, raw_payload_ref="fake/hashtag/ref.json")

    # text_content must be non-empty (hashtags only)
    assert normalized["text_content"] is not None, "text_content must not be None for hashtag-only post"

    resolver = PerfumeResolver(str(db_path))
    resolved = resolver.resolve_content_item(normalized)

    assert resolved["resolved_entities"], (
        "Hashtag-only TikTok post must resolve at least one entity. "
        f"text_content={normalized['text_content']!r}"
    )
    assert any(
        "Delina" in e["canonical_name"] for e in resolved["resolved_entities"]
    ), f"Expected Delina in resolved entities: {resolved['resolved_entities']}"


def test_tiktok_full_pipeline(tmp_path: Path, raw_post: dict) -> None:
    """
    Full pipeline smoke test:
    fixture -> normalize -> resolve -> store -> list_resolved_signals has 1 row.

    Seeds fragrance_master with Delina from Parfums de Marly so the resolver
    can match it in the TikTok post caption.
    """
    db_path = tmp_path / "pti_tiktok.sqlite"
    csv_path = tmp_path / "seed.csv"

    # Seed fragrance master with Delina
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

    # Normalize raw TikTok fixture
    normalizer = SocialContentNormalizer()
    normalized = normalizer.normalize_tiktok_item(raw_post, raw_payload_ref="fake/tiktok/ref.json")

    # Store normalized item
    normalized_store = NormalizedContentStore(str(db_path))
    normalized_store.init_schema()
    normalized_store.save_content_items([normalized])

    # Resolve perfume mentions
    resolver = PerfumeResolver(str(db_path))
    resolved = resolver.resolve_content_item(normalized)

    # Store resolved signals
    signal_store = SignalStore(str(db_path))
    signal_store.init_schema()
    signal_store.save_resolved_signals([resolved])

    # Verify
    rows = signal_store.list_resolved_signals()
    assert len(rows) == 1
    assert "Parfums de Marly Delina" in rows[0]["resolved_entities_json"]
