from __future__ import annotations

"""
API endpoint integration tests — Market Terminal API v1.

Uses FastAPI TestClient (synchronous) to test all endpoints against
a real SQLite database seeded with known fixture data.
"""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from perfume_trend_sdk.storage.market.sqlite_store import MarketStore
from perfume_trend_sdk.workflows.run_daily_aggregation import run_aggregation
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore

TARGET_DATE = "2026-04-10"


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------

def _build_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "api_test.db")

    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()
    normalized_store.save_content_items([
        {
            "id": "yt_001",
            "schema_version": "1.0",
            "source_platform": "youtube",
            "source_account_id": None,
            "source_account_handle": "creator_a",
            "source_account_type": "creator",
            "source_url": "https://youtube.com/watch?v=yt001",
            "external_content_id": "yt_001",
            "published_at": f"{TARGET_DATE}T10:00:00+00:00",
            "collected_at": f"{TARGET_DATE}T12:00:00+00:00",
            "content_type": "video",
            "title": "Delina Review",
            "caption": None,
            "text_content": "Delina is stunning.",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {"source_type": "influencer", "influence_score": 80.0},
            "engagement": {"views": 80000, "likes": 4000, "comments": 120},
            "language": None,
            "region": "US",
            "raw_payload_ref": "data/raw/test/yt_001.json",
            "normalizer_version": "1.0",
            "query": "delina",
        },
        {
            "id": "tt_001",
            "schema_version": "1.0",
            "source_platform": "tiktok",
            "source_account_id": None,
            "source_account_handle": "creator_b",
            "source_account_type": "creator",
            "source_url": "https://tiktok.com/@test/001",
            "external_content_id": "tt_001",
            "published_at": f"{TARGET_DATE}T09:00:00+00:00",
            "collected_at": f"{TARGET_DATE}T11:00:00+00:00",
            "content_type": "short",
            "title": None,
            "caption": None,
            "text_content": "Obsessed with Delina!",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {"source_type": "user", "influence_score": 35.0},
            "engagement": {"views": 50000, "likes": 3000, "comments": 200},
            "language": None,
            "region": "US",
            "raw_payload_ref": "data/raw/test/tt_001.json",
            "normalizer_version": "1.0",
            "query": None,
        },
    ])

    signal_store = SignalStore(db_path)
    signal_store.init_schema()
    signal_store.save_resolved_signals([
        {
            "content_item_id": "yt_001",
            "resolver_version": "1.0",
            "resolved_entities": [{
                "entity_type": "perfume",
                "canonical_name": "Parfums de Marly Delina",
                "entity_id": "1",
                "matched_from": "delina",
                "confidence": 1.0,
                "match_type": "exact",
            }],
            "unresolved_mentions": [],
            "alias_candidates": [],
        },
        {
            "content_item_id": "tt_001",
            "resolver_version": "1.0",
            "resolved_entities": [{
                "entity_type": "perfume",
                "canonical_name": "Parfums de Marly Delina",
                "entity_id": "1",
                "matched_from": "delina",
                "confidence": 1.0,
                "match_type": "exact",
            }],
            "unresolved_mentions": [],
            "alias_candidates": [],
        },
    ])

    run_aggregation(db_path=db_path, target_date=TARGET_DATE)
    return db_path


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    db_path = _build_db(tmp_path_factory.mktemp("api"))
    os.environ["PTI_DB_PATH"] = db_path

    from perfume_trend_sdk.api.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------

def test_health_check(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# /api/v1/dashboard
# ---------------------------------------------------------------------------

def test_dashboard_returns_200(client: TestClient) -> None:
    r = client.get("/api/v1/dashboard")
    assert r.status_code == 200


def test_dashboard_has_required_keys(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard").json()
    assert "generated_at" in data
    assert "total_entities" in data
    assert "top_movers" in data
    assert "recent_signals" in data
    assert "breakouts" in data


def test_dashboard_top_movers_not_empty(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard").json()
    assert len(data["top_movers"]) >= 1


def test_dashboard_top_mover_has_required_fields(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard").json()
    row = data["top_movers"][0]
    assert "rank" in row
    assert "ticker" in row
    assert "canonical_name" in row
    assert "composite_market_score" in row
    assert "momentum" in row


def test_dashboard_top_mover_rank_starts_at_1(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard").json()
    assert data["top_movers"][0]["rank"] == 1


def test_dashboard_top_movers_sorted_by_score(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard").json()
    scores = [r["composite_market_score"] for r in data["top_movers"]]
    assert scores == sorted(scores, reverse=True)


def test_dashboard_recent_signals_present(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard").json()
    # new_entry signals should have been generated
    types = {s["signal_type"] for s in data["recent_signals"]}
    assert len(types) >= 1


def test_dashboard_top_n_query_param(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard?top_n=1").json()
    assert len(data["top_movers"]) <= 1


# ---------------------------------------------------------------------------
# /api/v1/screener
# ---------------------------------------------------------------------------

def test_screener_returns_200(client: TestClient) -> None:
    r = client.get("/api/v1/screener")
    assert r.status_code == 200


def test_screener_has_total_and_rows(client: TestClient) -> None:
    data = client.get("/api/v1/screener").json()
    assert "total" in data
    assert "rows" in data


def test_screener_min_score_filter(client: TestClient) -> None:
    data_all = client.get("/api/v1/screener").json()
    data_filtered = client.get("/api/v1/screener?min_score=9999").json()
    assert data_filtered["total"] == 0
    assert data_all["total"] >= data_filtered["total"]


def test_screener_order_asc(client: TestClient) -> None:
    data = client.get("/api/v1/screener?order=asc").json()
    scores = [r["composite_market_score"] for r in data["rows"] if r["composite_market_score"] is not None]
    if len(scores) >= 2:
        assert scores == sorted(scores)


# ---------------------------------------------------------------------------
# /api/v1/entities
# ---------------------------------------------------------------------------

def test_entities_list_returns_200(client: TestClient) -> None:
    r = client.get("/api/v1/entities")
    assert r.status_code == 200


def test_entities_list_not_empty(client: TestClient) -> None:
    data = client.get("/api/v1/entities").json()
    assert len(data) >= 1


def test_entities_list_row_has_required_fields(client: TestClient) -> None:
    data = client.get("/api/v1/entities").json()
    row = data[0]
    assert "entity_id" in row
    assert "ticker" in row
    assert "canonical_name" in row
    assert "entity_type" in row


def test_entity_detail_returns_200(client: TestClient) -> None:
    r = client.get("/api/v1/entities/Parfums de Marly Delina")
    assert r.status_code == 200


def test_entity_detail_has_required_sections(client: TestClient) -> None:
    data = client.get("/api/v1/entities/Parfums de Marly Delina").json()
    assert "entity" in data
    assert "latest" in data
    assert "history" in data
    assert "signals" in data


def test_entity_detail_history_is_chart_ready(client: TestClient) -> None:
    data = client.get("/api/v1/entities/Parfums de Marly Delina").json()
    if data["history"]:
        row = data["history"][0]
        assert "date" in row
        assert "composite_market_score" in row
        assert "momentum" in row


def test_entity_detail_latest_snapshot_present(client: TestClient) -> None:
    data = client.get("/api/v1/entities/Parfums de Marly Delina").json()
    assert data["latest"] is not None
    assert data["latest"]["composite_market_score"] is not None


def test_entity_detail_404_for_unknown(client: TestClient) -> None:
    r = client.get("/api/v1/entities/nonexistent_entity_xyz")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/v1/signals
# ---------------------------------------------------------------------------

def test_signals_returns_200(client: TestClient) -> None:
    r = client.get("/api/v1/signals")
    assert r.status_code == 200


def test_signals_returns_list(client: TestClient) -> None:
    data = client.get("/api/v1/signals").json()
    assert isinstance(data, list)


def test_signals_row_has_required_fields(client: TestClient) -> None:
    data = client.get("/api/v1/signals").json()
    if data:
        row = data[0]
        assert "entity_id" in row
        assert "signal_type" in row
        assert "detected_at" in row
        assert "strength" in row


def test_signals_filter_by_type(client: TestClient) -> None:
    all_data = client.get("/api/v1/signals").json()
    new_entry = client.get("/api/v1/signals?signal_type=new_entry").json()
    assert all(s["signal_type"] == "new_entry" for s in new_entry)


def test_signals_filter_by_unknown_type_returns_empty(client: TestClient) -> None:
    data = client.get("/api/v1/signals?signal_type=unknown_type").json()
    assert data == []
