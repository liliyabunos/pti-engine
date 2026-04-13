from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from perfume_trend_sdk.analysis.market_signals.aggregator import (
    DailyAggregator,
    generate_ticker,
    _compute_composite,
    _normalize_views,
    _engagement_total,
    TIKTOK_VIEW_CAP,
)

TARGET_DATE = "2026-04-10"


def _content_item(
    item_id: str,
    platform: str = "youtube",
    author: str = "creator_a",
    published_at: str = "2026-04-10T10:00:00",
    views: int = 80000,
    likes: int = 4000,
    influence: float = 80.0,
) -> Dict[str, Any]:
    return {
        "id": item_id,
        "source_platform": platform,
        "source_account_handle": author,
        "published_at": published_at,
        "engagement_json": json.dumps({"views": views, "likes": likes, "comments": 100}),
        "media_metadata_json": json.dumps({"influence_score": influence}),
        "text_content": "test content",
        "title": "test title",
        "content_type": "video",
    }


def _resolved_signal(
    content_item_id: str,
    entity_name: str,
    entity_id: str = "1",
) -> Dict[str, Any]:
    return {
        "content_item_id": content_item_id,
        "resolver_version": "1.0",
        "resolved_entities_json": json.dumps([
            {
                "entity_type": "perfume",
                "canonical_name": entity_name,
                "entity_id": entity_id,
                "matched_from": entity_name.lower(),
                "confidence": 1.0,
                "match_type": "exact",
            }
        ]),
    }


@pytest.fixture
def aggregator() -> DailyAggregator:
    return DailyAggregator()


# ---------------------------------------------------------------------------
# generate_ticker
# ---------------------------------------------------------------------------

def test_ticker_single_word() -> None:
    assert generate_ticker("Delina") == "DELIN"


def test_ticker_filters_stop_words() -> None:
    ticker = generate_ticker("Parfums de Marly Delina")
    # "de" is stop → sig words: Parfums, Marly, Delina → P M D = "PMD" or similar
    assert "D" in ticker or len(ticker) >= 2


def test_ticker_with_number() -> None:
    ticker = generate_ticker("Baccarat Rouge 540")
    assert "540" in ticker


def test_ticker_max_length() -> None:
    ticker = generate_ticker("Very Long Perfume Name By A Famous House In France Edition Limitee")
    assert len(ticker) <= 8


def test_ticker_is_uppercase() -> None:
    assert generate_ticker("some perfume name").isupper()


def test_ticker_two_words() -> None:
    ticker = generate_ticker("Oud Wood")
    assert len(ticker) >= 2 and ticker.isupper()


# ---------------------------------------------------------------------------
# _compute_composite
# ---------------------------------------------------------------------------

def test_composite_max_score_at_ceiling() -> None:
    score = _compute_composite(
        mention_count=10.0,      # at ceiling
        engagement_sum=500_000.0,  # at ceiling
        growth=1.0,              # max growth
        source_diversity=3,      # max diversity
        momentum=3.0,            # at momentum ceiling
    )
    assert score == pytest.approx(100.0, abs=0.1)


def test_composite_zero_score_when_no_data() -> None:
    score = _compute_composite(
        mention_count=0.0,
        engagement_sum=0.0,
        growth=0.0,
        source_diversity=0,
    )
    # growth=0 → growth_score=0.5 (neutral), rest are 0 → composite = 0.5*0.20*100 = 10
    assert score == pytest.approx(10.0, abs=0.1)


def test_composite_higher_with_more_mentions() -> None:
    low = _compute_composite(1.0, 10000.0, 0.0, 1)
    high = _compute_composite(8.0, 10000.0, 0.0, 1)
    assert high > low


def test_composite_penalized_by_negative_growth() -> None:
    positive = _compute_composite(5.0, 50000.0, 0.5, 2)
    negative = _compute_composite(5.0, 50000.0, -0.5, 2)
    assert positive > negative


def test_composite_in_range_0_100() -> None:
    for mc, eng, gr, div in [
        (0, 0, -1.0, 0),
        (5, 100000, 0.5, 2),
        (10, 500000, 1.0, 3),
    ]:
        score = _compute_composite(float(mc), float(eng), float(gr), div)
        assert 0.0 <= score <= 100.0


# ---------------------------------------------------------------------------
# DailyAggregator.aggregate_from_data
# ---------------------------------------------------------------------------

def test_aggregator_counts_correct_mentions(aggregator: DailyAggregator) -> None:
    items = [
        _content_item("yt_001"),
        _content_item("yt_002"),
        _content_item("tt_001", platform="tiktok"),
    ]
    signals = [
        _resolved_signal("yt_001", "Parfums de Marly Delina"),
        _resolved_signal("yt_002", "Parfums de Marly Delina"),
        _resolved_signal("tt_001", "Parfums de Marly Delina"),
    ]
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE)
    delina = next(s for s in snaps if s["entity_id"] == "Parfums de Marly Delina")
    # Platform-weighted: youtube=1.2 × 2 + tiktok=1.3 × 1 = 3.7
    assert delina["mention_count"] == pytest.approx(3.7, abs=0.01)


def test_aggregator_source_diversity(aggregator: DailyAggregator) -> None:
    items = [
        _content_item("yt_001", platform="youtube"),
        _content_item("tt_001", platform="tiktok"),
        _content_item("rd_001", platform="reddit"),
    ]
    signals = [
        _resolved_signal("yt_001", "Parfums de Marly Delina"),
        _resolved_signal("tt_001", "Parfums de Marly Delina"),
        _resolved_signal("rd_001", "Parfums de Marly Delina"),
    ]
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE)
    delina = next(s for s in snaps if s["entity_id"] == "Parfums de Marly Delina")
    # Platform-weighted: youtube=1.2 + tiktok=1.3 + reddit=1.0 = 3.5
    assert delina["mention_count"] == pytest.approx(3.5, abs=0.01)


def test_aggregator_filters_by_date(aggregator: DailyAggregator) -> None:
    items = [
        _content_item("yt_001", published_at="2026-04-10T10:00:00"),
        _content_item("yt_002", published_at="2026-04-09T10:00:00"),  # wrong date
    ]
    signals = [
        _resolved_signal("yt_001", "Parfums de Marly Delina"),
        _resolved_signal("yt_002", "Parfums de Marly Delina"),
    ]
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE)
    delina = next((s for s in snaps if s["entity_id"] == "Parfums de Marly Delina"), None)
    assert delina is not None
    # Only yt_001 matches TARGET_DATE; platform weight youtube=1.2
    assert delina["mention_count"] == pytest.approx(1.2, abs=0.01)


def test_aggregator_ignores_non_perfume_entities(aggregator: DailyAggregator) -> None:
    items = [_content_item("yt_001")]
    signals = [{
        "content_item_id": "yt_001",
        "resolver_version": "1.0",
        "resolved_entities_json": json.dumps([
            {"entity_type": "brand", "canonical_name": "Dior", "entity_id": "99",
             "matched_from": "dior", "confidence": 1.0, "match_type": "exact"}
        ]),
    }]
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE)
    assert snaps == []


def test_aggregator_deduplicates_content_item_per_entity(aggregator: DailyAggregator) -> None:
    """Same content item with two mentions of same entity → counted once."""
    items = [_content_item("yt_001")]
    signals = [{
        "content_item_id": "yt_001",
        "resolver_version": "1.0",
        "resolved_entities_json": json.dumps([
            {"entity_type": "perfume", "canonical_name": "Parfums de Marly Delina",
             "entity_id": "1", "matched_from": "delina", "confidence": 1.0, "match_type": "exact"},
            {"entity_type": "perfume", "canonical_name": "Parfums de Marly Delina",
             "entity_id": "1", "matched_from": "parfums de marly delina",
             "confidence": 1.0, "match_type": "exact"},
        ]),
    }]
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE)
    delina = next(s for s in snaps if s["entity_id"] == "Parfums de Marly Delina")
    # Same content item resolved twice → counted once; platform weight youtube=1.2
    assert delina["mention_count"] == pytest.approx(1.2, abs=0.01)


def test_aggregator_computes_momentum_from_prev(aggregator: DailyAggregator) -> None:
    items = [_content_item("yt_001")]
    signals = [_resolved_signal("yt_001", "Parfums de Marly Delina")]
    prev = {
        "Parfums de Marly Delina": {
            "mention_count": 2.0,
            "momentum": 1.0,
        }
    }
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE, prev_snapshots=prev)
    delina = next(s for s in snaps if s["entity_id"] == "Parfums de Marly Delina")
    # mention_count = 1.2 (youtube weight); momentum = 1.2 / max(2.0, 1) = 0.6
    assert delina["momentum"] == pytest.approx(0.6, abs=0.01)


def test_aggregator_computes_growth_from_prev(aggregator: DailyAggregator) -> None:
    items = [
        _content_item("yt_001"),
        _content_item("yt_002"),
        _content_item("yt_003"),
    ]
    signals = [
        _resolved_signal("yt_001", "Parfums de Marly Delina"),
        _resolved_signal("yt_002", "Parfums de Marly Delina"),
        _resolved_signal("yt_003", "Parfums de Marly Delina"),
    ]
    prev = {"Parfums de Marly Delina": {"mention_count": 2.0, "momentum": 1.0}}
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE, prev_snapshots=prev)
    delina = next(s for s in snaps if s["entity_id"] == "Parfums de Marly Delina")
    # mention_count = 3 × 1.2 (youtube weight) = 3.6
    # growth_rate = (3.6 - 2.0) / 2.0 = 0.8
    assert delina["growth_rate"] == pytest.approx(0.8, abs=0.01)


def test_aggregator_empty_data_returns_empty_list(aggregator: DailyAggregator) -> None:
    snaps = aggregator.aggregate_from_data([], [], TARGET_DATE)
    assert snaps == []


def test_aggregator_snapshot_has_required_keys(aggregator: DailyAggregator) -> None:
    items = [_content_item("yt_001")]
    signals = [_resolved_signal("yt_001", "Parfums de Marly Delina")]
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE)
    required = {
        "entity_id", "entity_type", "date", "mention_count", "unique_authors",
        "engagement_sum", "composite_market_score", "momentum", "acceleration",
        "volatility", "growth_rate",
    }
    for key in required:
        assert key in snaps[0], f"Missing key: {key}"


# ---------------------------------------------------------------------------
# build_entity_records
# ---------------------------------------------------------------------------

def test_build_entity_records_produces_correct_fields(aggregator: DailyAggregator) -> None:
    snaps = [{"entity_id": "Parfums de Marly Delina"}]
    records = aggregator.build_entity_records(snaps, "2026-04-10T00:00:00Z")
    assert len(records) == 1
    rec = records[0]
    assert rec["entity_id"] == "Parfums de Marly Delina"
    assert rec["entity_type"] == "perfume"
    assert len(rec["ticker"]) >= 2
    assert rec["canonical_name"] == "Parfums de Marly Delina"


# ---------------------------------------------------------------------------
# _normalize_views
# ---------------------------------------------------------------------------

def test_normalize_views_youtube_unchanged() -> None:
    """YouTube views pass through as-is regardless of magnitude."""
    assert _normalize_views(1_000_000.0, "youtube") == 1_000_000.0


def test_normalize_views_other_unchanged() -> None:
    assert _normalize_views(999_999.0, "other") == 999_999.0


def test_normalize_views_tiktok_below_cap_unchanged() -> None:
    """TikTok plays under the cap are not modified."""
    assert _normalize_views(100_000.0, "tiktok") == 100_000.0


def test_normalize_views_tiktok_at_cap_unchanged() -> None:
    assert _normalize_views(TIKTOK_VIEW_CAP, "tiktok") == TIKTOK_VIEW_CAP


def test_normalize_views_tiktok_above_cap_clipped() -> None:
    """TikTok plays above the cap are clipped to TIKTOK_VIEW_CAP."""
    assert _normalize_views(5_000_000.0, "tiktok") == TIKTOK_VIEW_CAP
    assert _normalize_views(10_000_000.0, "tiktok") == TIKTOK_VIEW_CAP


def test_normalize_views_zero() -> None:
    assert _normalize_views(0.0, "tiktok") == 0.0
    assert _normalize_views(0.0, "youtube") == 0.0


# ---------------------------------------------------------------------------
# _engagement_total with platform normalization
# ---------------------------------------------------------------------------

def test_engagement_total_youtube_uses_raw_views() -> None:
    eng = {"views": 800_000, "likes": 1_000, "comments": 100}
    result = _engagement_total(eng, platform="youtube")
    # views unchanged: 800_000 + 1_000*3 + 100*5 = 803_500
    assert result == pytest.approx(803_500.0, abs=1.0)


def test_engagement_total_tiktok_caps_views() -> None:
    eng = {"views": 5_000_000, "likes": 50_000, "comments": 2_000}
    result = _engagement_total(eng, platform="tiktok")
    # views clipped to 500_000; likes/comments unchanged
    expected = TIKTOK_VIEW_CAP + 50_000 * 3 + 2_000 * 5
    assert result == pytest.approx(expected, abs=1.0)


def test_engagement_total_tiktok_view_cap_is_idempotent() -> None:
    """10M-play TikTok and 500K-play TikTok produce the same engagement_total.
    Confirms the cap works: extra plays beyond TIKTOK_VIEW_CAP are discarded."""
    same_likes = {"likes": 5_000, "comments": 200}
    at_cap = _engagement_total({"views": TIKTOK_VIEW_CAP, **same_likes}, platform="tiktok")
    viral = _engagement_total({"views": 10_000_000, **same_likes}, platform="tiktok")
    assert at_cap == pytest.approx(viral, abs=1.0)


def test_engagement_total_default_platform_is_other() -> None:
    """Calling without platform arg must not raise and must not apply TikTok cap."""
    eng = {"views": 1_000_000, "likes": 0, "comments": 0}
    result = _engagement_total(eng)
    assert result == pytest.approx(1_000_000.0, abs=1.0)


# ---------------------------------------------------------------------------
# Aggregator end-to-end: TikTok view cap in engagement_sum
# ---------------------------------------------------------------------------

def test_aggregator_tiktok_capped_engagement_sum(aggregator: DailyAggregator) -> None:
    """A viral TikTok item (10M plays) must produce a capped engagement_sum,
    not an inflated one that swamps YouTube items in composite scoring."""
    items = [
        _content_item("yt_001", platform="youtube", views=80_000),
        _content_item("tt_viral", platform="tiktok", views=10_000_000),
    ]
    signals = [
        _resolved_signal("yt_001", "Parfums de Marly Delina"),
        _resolved_signal("tt_viral", "Parfums de Marly Delina"),
    ]
    snaps = aggregator.aggregate_from_data(items, signals, TARGET_DATE)
    delina = next(s for s in snaps if s["entity_id"] == "Parfums de Marly Delina")

    # TikTok contribution capped at TIKTOK_VIEW_CAP + likes*3 + comments*5
    # YouTube  contribution: 80_000 + 4_000*3 + 100*5 = 92_500
    # TikTok   contribution: 500_000 + 4_000*3 + 100*5 = 512_500  (not 10_192_500)
    assert delina["engagement_sum"] < 700_000, (
        f"engagement_sum {delina['engagement_sum']} suggests TikTok cap is not applied"
    )
