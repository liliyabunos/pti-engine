from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.connectors.reddit_watchlist.parser import RedditParser
from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.raw.filesystem import FilesystemRawStorage
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv
from perfume_trend_sdk.workflows.ingest_reddit_to_signals import (
    _classify_reddit_source,
    _compute_reddit_influence,
)

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "reddit_post_raw.json"


@pytest.fixture(scope="module")
def raw_post() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parsed(raw_post: dict) -> dict:
    return RedditParser().parse(raw_post)


@pytest.fixture(scope="module")
def normalized(raw_post: dict) -> dict:
    return SocialContentNormalizer().normalize_reddit_item(
        raw_post, raw_payload_ref="data/raw/reddit/test/00001.json"
    )


# ------------------------------------------------------------------
# Parser → Normalizer
# ------------------------------------------------------------------

def test_normalized_source_platform(normalized: dict) -> None:
    assert normalized["source_platform"] == "reddit"


def test_normalized_content_type(normalized: dict) -> None:
    assert normalized["content_type"] == "post"


def test_normalized_title_preserved(normalized: dict) -> None:
    assert normalized["title"] is not None
    assert "Delina" in normalized["title"]


def test_normalized_text_content_combines_title_and_selftext(normalized: dict) -> None:
    text = normalized["text_content"] or ""
    assert "Delina" in text           # from title
    assert "vanilla" in text          # from selftext
    assert "Baccarat Rouge 540" in text


def test_normalized_engagement_likes_from_score(normalized: dict) -> None:
    assert normalized["engagement"]["likes"] == 342


def test_normalized_engagement_comments(normalized: dict) -> None:
    assert normalized["engagement"]["comments"] == 87


def test_normalized_subreddit_in_media_metadata(normalized: dict) -> None:
    assert normalized["media_metadata"]["subreddit"] == "fragrance"


def test_normalized_raw_payload_ref(normalized: dict) -> None:
    assert normalized["raw_payload_ref"] == "data/raw/reddit/test/00001.json"


def test_normalized_has_id(normalized: dict) -> None:
    assert normalized["id"] == "abc123x"


def test_normalized_source_url_present(normalized: dict) -> None:
    assert normalized["source_url"].startswith("https://")


def test_normalized_account_handle_preserved(normalized: dict) -> None:
    assert normalized["source_account_handle"] == "fragrance_nerd_us"


# ------------------------------------------------------------------
# Source intelligence
# ------------------------------------------------------------------

def test_classify_reddit_source_is_community(normalized: dict) -> None:
    source_type = _classify_reddit_source(normalized)
    assert source_type == "community"


def test_compute_reddit_influence_uses_score_and_comments(normalized: dict) -> None:
    influence = _compute_reddit_influence(normalized)
    # score=342, comments=87 → 342*0.7 + 87*0.3 = 239.4 + 26.1 = 265.5
    assert influence == pytest.approx(265.5, rel=1e-3)


def test_compute_reddit_influence_zero_for_empty_item() -> None:
    assert _compute_reddit_influence({}) == 0.0


# ------------------------------------------------------------------
# End-to-end: fixture → normalize → resolve → store → verify
# ------------------------------------------------------------------

def test_reddit_full_pipeline(tmp_path: Path, raw_post: dict) -> None:
    """Full pipeline smoke test:
    fixture → normalize → resolve → store
    → resolved signal has Delina + unresolved text preserved for discovery.
    """
    db_path = str(tmp_path / "pti_reddit.sqlite")
    csv_path = tmp_path / "seed.csv"

    # Seed fragrance master with Delina and Baccarat Rouge 540
    csv_path.write_text(
        "\n".join([
            "fragrance_id,brand_name,perfume_name,source",
            "fr_001,Parfums de Marly,Delina,kaggle",
            "fr_002,Maison Francis Kurkdjian,Baccarat Rouge 540,kaggle",
        ]),
        encoding="utf-8",
    )
    ingest_seed_csv(csv_path, db_path)

    normalizer = SocialContentNormalizer()
    normalized = normalizer.normalize_reddit_item(
        raw_post, raw_payload_ref="data/raw/reddit/test/00001.json"
    )

    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()
    normalized_store.save_content_items([normalized])

    resolver = PerfumeResolver(db_path)
    resolved = resolver.resolve_content_item(normalized)

    signal_store = SignalStore(db_path)
    signal_store.init_schema()
    signal_store.save_resolved_signals([resolved])

    rows = signal_store.list_resolved_signals()
    assert len(rows) == 1

    entities_json = rows[0]["resolved_entities_json"]
    assert "Parfums de Marly Delina" in entities_json


def test_reddit_pipeline_resolves_multiple_perfumes(tmp_path: Path, raw_post: dict) -> None:
    """Both Delina and Baccarat Rouge 540 mentioned in post body should resolve."""
    db_path = str(tmp_path / "pti_reddit_multi.sqlite")
    csv_path = tmp_path / "seed.csv"

    csv_path.write_text(
        "\n".join([
            "fragrance_id,brand_name,perfume_name,source",
            "fr_001,Parfums de Marly,Delina,kaggle",
            "fr_002,Maison Francis Kurkdjian,Baccarat Rouge 540,kaggle",
        ]),
        encoding="utf-8",
    )
    ingest_seed_csv(csv_path, db_path)

    normalizer = SocialContentNormalizer()
    normalized = normalizer.normalize_reddit_item(raw_post, raw_payload_ref="ref")

    resolver = PerfumeResolver(db_path)
    resolved = resolver.resolve_content_item(normalized)

    entities = resolved["resolved_entities"]
    canonical_names = [e["canonical_name"] for e in entities]
    assert "Parfums de Marly Delina" in canonical_names
    assert "Maison Francis Kurkdjian Baccarat Rouge 540" in canonical_names


def test_reddit_raw_storage(tmp_path: Path, raw_post: dict) -> None:
    """Raw storage must be written before normalization."""
    raw_storage = FilesystemRawStorage(base_dir=str(tmp_path / "raw"))
    refs = raw_storage.save_raw_batch(
        source_name="reddit_watchlist_connector",
        run_id="reddit_fragrance_20260410T000000Z",
        items=[raw_post],
    )
    assert len(refs) == 1
    assert Path(refs[0]).exists()
    stored = json.loads(Path(refs[0]).read_text(encoding="utf-8"))
    assert stored["id"] == "abc123x"


def test_reddit_tolerates_empty_post_body(tmp_path: Path) -> None:
    """Posts with no selftext must not crash the pipeline."""
    db_path = str(tmp_path / "pti_reddit_empty.sqlite")

    title_only_post = {
        "id": "titleonly1",
        "title": "Best vanilla perfumes?",
        "subreddit": "fragrance",
        "score": 10,
        "num_comments": 5,
        "created_utc": 1712345678,
        "permalink": "/r/fragrance/comments/titleonly1/best_vanilla_perfumes/",
    }

    normalizer = SocialContentNormalizer()
    normalized = normalizer.normalize_reddit_item(title_only_post, raw_payload_ref="ref")

    assert normalized["text_content"] == "Best vanilla perfumes?"
    assert normalized["title"] == "Best vanilla perfumes?"

    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()
    normalized_store.save_content_items([normalized])

    resolver = PerfumeResolver(db_path)
    resolver.store.init_schema()
    resolved = resolver.resolve_content_item(normalized)

    signal_store = SignalStore(db_path)
    signal_store.init_schema()
    signal_store.save_resolved_signals([resolved])

    rows = signal_store.list_resolved_signals()
    assert len(rows) == 1
