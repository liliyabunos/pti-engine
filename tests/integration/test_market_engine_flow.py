from __future__ import annotations

import json
from pathlib import Path

import pytest

from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.storage.market.sqlite_store import MarketStore
from perfume_trend_sdk.workflows.run_daily_aggregation import run_aggregation


TARGET_DATE = "2026-04-10"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_pipeline(db_path: str, date: str = TARGET_DATE) -> None:
    """Seed the existing pipeline tables with test data."""
    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()

    items = [
        {
            "id": "yt_001",
            "schema_version": "1.0",
            "source_platform": "youtube",
            "source_account_id": None,
            "source_account_handle": "perfume_channel",
            "source_account_type": "creator",
            "source_url": "https://youtube.com/watch?v=yt001",
            "external_content_id": "yt_001",
            "published_at": f"{date}T10:00:00+00:00",
            "collected_at": f"{date}T12:00:00+00:00",
            "content_type": "video",
            "title": "Delina Review",
            "caption": None,
            "text_content": "Delina by Parfums de Marly is stunning.",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {"source_type": "influencer", "influence_score": 80.0},
            "engagement": {"views": 80000, "likes": 4000, "comments": 120},
            "language": None,
            "region": "US",
            "raw_payload_ref": "data/raw/test/yt_001.json",
            "normalizer_version": "1.0",
            "query": "delina perfume",
        },
        {
            "id": "tt_001",
            "schema_version": "1.0",
            "source_platform": "tiktok",
            "source_account_id": None,
            "source_account_handle": "perfume_lover_usa",
            "source_account_type": "creator",
            "source_url": "https://tiktok.com/@test/video/001",
            "external_content_id": "tt_001",
            "published_at": f"{date}T09:00:00+00:00",
            "collected_at": f"{date}T11:00:00+00:00",
            "content_type": "short",
            "title": None,
            "caption": None,
            "text_content": "Obsessed with Delina!",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {"source_type": "user", "influence_score": 35.0},
            "engagement": {"views": 124300, "likes": 8900, "comments": 342},
            "language": None,
            "region": "US",
            "raw_payload_ref": "data/raw/test/tt_001.json",
            "normalizer_version": "1.0",
            "query": None,
        },
        {
            "id": "rd_001",
            "schema_version": "1.0",
            "source_platform": "reddit",
            "source_account_id": None,
            "source_account_handle": "fragrance_nerd",
            "source_account_type": "creator",
            "source_url": "https://reddit.com/r/fragrance/comments/abc123/",
            "external_content_id": "rd_001",
            "published_at": f"{date}T14:00:00+00:00",
            "collected_at": f"{date}T15:00:00+00:00",
            "content_type": "post",
            "title": "Delina worth the hype?",
            "caption": None,
            "text_content": "Delina worth the hype? BR540 is more synthetic.",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {"source_type": "community", "influence_score": 265.5},
            "engagement": {"views": None, "likes": 342, "comments": 87},
            "language": None,
            "region": "US",
            "raw_payload_ref": "data/raw/test/rd_001.json",
            "normalizer_version": "1.0",
            "query": None,
        },
    ]
    normalized_store.save_content_items(items)

    signal_store = SignalStore(db_path)
    signal_store.init_schema()
    signal_store.save_resolved_signals([
        {
            "content_item_id": "yt_001",
            "resolver_version": "1.0",
            "resolved_entities": [
                {
                    "entity_type": "perfume",
                    "canonical_name": "Parfums de Marly Delina",
                    "entity_id": "1",
                    "matched_from": "delina",
                    "confidence": 1.0,
                    "match_type": "exact",
                }
            ],
            "unresolved_mentions": [],
            "alias_candidates": [],
        },
        {
            "content_item_id": "tt_001",
            "resolver_version": "1.0",
            "resolved_entities": [
                {
                    "entity_type": "perfume",
                    "canonical_name": "Parfums de Marly Delina",
                    "entity_id": "1",
                    "matched_from": "delina",
                    "confidence": 1.0,
                    "match_type": "exact",
                }
            ],
            "unresolved_mentions": [],
            "alias_candidates": [],
        },
        {
            "content_item_id": "rd_001",
            "resolver_version": "1.0",
            "resolved_entities": [
                {
                    "entity_type": "perfume",
                    "canonical_name": "Parfums de Marly Delina",
                    "entity_id": "1",
                    "matched_from": "delina",
                    "confidence": 1.0,
                    "match_type": "exact",
                },
                {
                    "entity_type": "perfume",
                    "canonical_name": "Maison Francis Kurkdjian Baccarat Rouge 540",
                    "entity_id": "2",
                    "matched_from": "br540",
                    "confidence": 0.9,
                    "match_type": "fuzzy",
                },
            ],
            "unresolved_mentions": [],
            "alias_candidates": [],
        },
    ])


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_run_aggregation_produces_snapshots(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)

    result = run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    assert result["entities_processed"] >= 1
    assert result["target_date"] == TARGET_DATE


def test_run_aggregation_writes_entity_market_records(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    entities = store.list_entities()
    names = {e["entity_id"] for e in entities}
    assert "Parfums de Marly Delina" in names


def test_run_aggregation_computes_correct_mention_count(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    assert snap is not None
    # Platform-weighted: youtube=1.2 + tiktok=1.3 + reddit=1.0 = 3.5
    assert round(snap["mention_count"], 1) == 3.5  # yt_001 + tt_001 + rd_001


def test_run_aggregation_source_diversity_is_3(tmp_path: Path) -> None:
    # source_diversity removed from new schema; verify 3 mentions still aggregated
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    # Platform-weighted: youtube=1.2 + tiktok=1.3 + reddit=1.0 = 3.5
    assert round(snap["mention_count"], 1) == 3.5


def test_run_aggregation_composite_score_in_valid_range(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    assert 0.0 <= snap["composite_market_score"] <= 100.0


def test_run_aggregation_detects_new_entry_signal(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    signals = store.list_recent_signals(days=7)
    signal_types = {s["signal_type"] for s in signals}
    assert "new_entry" in signal_types


def test_run_aggregation_ticker_assigned(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    ent = store.get_entity("Parfums de Marly Delina")
    assert ent is not None
    assert len(ent["ticker"]) >= 2


def test_run_aggregation_idempotent(tmp_path: Path) -> None:
    """Running aggregation twice for same date should not duplicate data."""
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    entities = store.list_entities()
    # No duplicate entity_id entries
    ids = [e["entity_id"] for e in entities]
    assert len(ids) == len(set(ids))


def test_run_aggregation_momentum_computed_on_second_run(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    # Day 1: seed 1 mention for Delina
    _seed_pipeline(db_path, date="2026-04-09")
    run_aggregation(db_path=db_path, target_date="2026-04-09")

    # Day 2: seed 3 mentions for Delina
    _seed_pipeline(db_path, date=TARGET_DATE)  # adds more items
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    # Day 1 had 3 mentions, Day 2 also has 3 → momentum = 3/3 = 1.0
    assert snap["momentum"] == pytest.approx(1.0, abs=0.1)


def test_run_aggregation_empty_db_does_not_crash(tmp_path: Path) -> None:
    db_path = str(tmp_path / "empty.db")
    result = run_aggregation(db_path=db_path, target_date=TARGET_DATE)
    assert result["entities_processed"] == 0
    assert result["signals_detected"] == 0


def test_run_aggregation_all_required_snapshot_fields(tmp_path: Path) -> None:
    db_path = str(tmp_path / "pti.db")
    _seed_pipeline(db_path)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)

    store = MarketStore(db_path)
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    required = {
        "entity_id", "date", "mention_count", "unique_authors",
        "engagement_sum", "composite_market_score",
        "momentum", "acceleration", "volatility", "growth_rate",
    }
    for key in required:
        assert key in snap, f"Missing key: {key}"
