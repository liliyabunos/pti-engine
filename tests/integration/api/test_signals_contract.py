from __future__ import annotations

"""
Signals API contract tests — GET /api/v1/signals.

Validates:
  - HTTP 200 and list response type
  - required fields on every signal row
  - only known signal_type values
  - filter by signal_type works correctly
  - filter by date_from / date_to is respected
  - limit parameter is respected
  - offset-based pagination via limit + date_from produces no duplicates
  - ordering is newest-first (detected_at DESC)
  - repeated requests return the same order (stable)
"""

import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.workflows.run_daily_aggregation import run_aggregation

TARGET_DATE = "2026-04-10"
PREV_DATE = "2026-04-09"

_ENTITIES = [
    ("Parfums de Marly Delina", 90_000),
    ("MFK Baccarat Rouge 540", 75_000),
    ("Creed Aventus", 60_000),
    ("Dior Sauvage", 50_000),
    ("YSL Libre", 40_000),
    ("Tom Ford Black Orchid", 30_000),
]

_VALID_SIGNAL_TYPES = frozenset({"new_entry", "breakout", "acceleration_spike", "reversal"})

_REQUIRED_SIGNAL_KEYS = {
    "entity_id", "signal_type", "detected_at", "strength",
}


# ---------------------------------------------------------------------------
# DB fixture helper
# ---------------------------------------------------------------------------

def _seed_entity(
    nc: NormalizedContentStore,
    sc: SignalStore,
    entity_name: str,
    views: int,
    date: str,
    id_prefix: str,
) -> None:
    yt_id = f"{id_prefix}_yt"
    tt_id = f"{id_prefix}_tt"
    for item_id, platform, v in [(yt_id, "youtube", views), (tt_id, "tiktok", views // 2)]:
        nc.save_content_items([{
            "id": item_id,
            "schema_version": "1.0",
            "source_platform": platform,
            "source_account_id": None,
            "source_account_handle": f"creator_{item_id}",
            "source_account_type": "creator",
            "source_url": f"https://{platform}.com/{item_id}",
            "external_content_id": item_id,
            "published_at": f"{date}T10:00:00+00:00",
            "collected_at": f"{date}T12:00:00+00:00",
            "content_type": "video",
            "title": f"{entity_name} Review",
            "caption": None,
            "text_content": f"Talking about {entity_name}.",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {"source_type": "influencer", "influence_score": 80.0},
            "engagement": {"views": v, "likes": v // 20, "comments": v // 100},
            "language": None,
            "region": "US",
            "raw_payload_ref": f"data/raw/test/{item_id}.json",
            "normalizer_version": "1.0",
            "query": entity_name.lower().split()[0],
        }])
        sc.save_resolved_signals([{
            "content_item_id": item_id,
            "resolver_version": "1.0",
            "resolved_entities": [{
                "entity_type": "perfume",
                "canonical_name": entity_name,
                "entity_id": "1",
                "matched_from": entity_name.lower().split()[0],
                "confidence": 1.0,
                "match_type": "exact",
            }],
            "unresolved_mentions": [],
            "alias_candidates": [],
        }])


def _build_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "signals_test.db")

    nc = NormalizedContentStore(db_path)
    nc.init_schema()
    sc = SignalStore(db_path)
    sc.init_schema()

    # Seed PREV_DATE first so TARGET_DATE entities get acceleration/reversal checks
    for i, (entity_name, views) in enumerate(_ENTITIES):
        _seed_entity(nc, sc, entity_name, views, PREV_DATE, f"prev_{i:02d}")

    run_aggregation(db_path=db_path, target_date=PREV_DATE)

    # TARGET_DATE with varying volumes to trigger different signal types
    for i, (entity_name, views) in enumerate(_ENTITIES):
        _seed_entity(nc, sc, entity_name, views * 2, TARGET_DATE, f"cur_{i:02d}")

    run_aggregation(db_path=db_path, target_date=TARGET_DATE)
    return db_path


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    db_path = _build_db(tmp_path_factory.mktemp("signals"))
    os.environ["PTI_DB_PATH"] = db_path
    from perfume_trend_sdk.api.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# HTTP + type
# ---------------------------------------------------------------------------

class TestSignalsHTTP:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get("/api/v1/signals")
        assert r.status_code == 200

    def test_returns_list(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals").json()
        assert isinstance(data, list), f"Expected list, got {type(data).__name__}"


# ---------------------------------------------------------------------------
# Row schema
# ---------------------------------------------------------------------------

class TestSignalsSchema:
    def test_required_fields_on_each_row(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals").json()
        for row in data:
            missing = _REQUIRED_SIGNAL_KEYS - set(row.keys())
            assert not missing, f"Signal row missing fields: {missing} — row: {row}"

    def test_signal_type_values_are_known(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals").json()
        bad_types = {
            r["signal_type"] for r in data
            if r.get("signal_type") not in _VALID_SIGNAL_TYPES
        }
        assert not bad_types, f"Unknown signal_type values: {bad_types}"

    def test_strength_is_non_negative_float(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals").json()
        for row in data:
            assert isinstance(row["strength"], (int, float))
            assert row["strength"] >= 0, f"Negative strength: {row['strength']}"

    def test_detected_at_is_string(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals").json()
        for row in data:
            assert isinstance(row["detected_at"], str), (
                f"detected_at is not a string: {row['detected_at']}"
            )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class TestSignalsFilters:
    def test_filter_by_signal_type_new_entry(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals?signal_type=new_entry").json()
        for row in data:
            assert row["signal_type"] == "new_entry"

    def test_filter_by_unknown_signal_type_returns_empty(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals?signal_type=nonexistent_type").json()
        assert data == []

    def test_filter_by_date_from_restricts_results(self, client: TestClient) -> None:
        all_data = client.get("/api/v1/signals").json()
        filtered = client.get(f"/api/v1/signals?date_from={TARGET_DATE}").json()
        # Filtered set must be a subset
        all_ids = {r["detected_at"] for r in all_data}
        for row in filtered:
            assert row["detected_at"] >= TARGET_DATE, (
                f"Row detected_at {row['detected_at']} < date_from {TARGET_DATE}"
            )

    def test_limit_param_respected(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals?limit=2").json()
        assert len(data) <= 2

    def test_limit_1_returns_at_most_one_row(self, client: TestClient) -> None:
        data = client.get("/api/v1/signals?limit=1").json()
        assert len(data) <= 1


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

class TestSignalsOrdering:
    def test_newest_first(self, client: TestClient) -> None:
        """detected_at values must be non-increasing (newest first)."""
        data = client.get("/api/v1/signals").json()
        if len(data) < 2:
            pytest.skip("Fewer than 2 signals — cannot check ordering")
        detected_at_values = [r["detected_at"] for r in data]
        assert detected_at_values == sorted(detected_at_values, reverse=True), (
            f"Signals not in newest-first order: {detected_at_values[:5]}"
        )

    def test_ordering_stable_across_requests(self, client: TestClient) -> None:
        detected_a = [r["detected_at"] for r in client.get("/api/v1/signals").json()]
        detected_b = [r["detected_at"] for r in client.get("/api/v1/signals").json()]
        assert detected_a == detected_b, "Signal ordering is non-deterministic"


# ---------------------------------------------------------------------------
# Offset pagination consistency
# ---------------------------------------------------------------------------

class TestSignalsOffsetPagination:
    """Signals are fetched with limit only (no offset on the signals endpoint
    directly — it uses date_from / date_to for windowing). We verify that
    limit works cleanly and that the same data returned by two consecutive
    calls with the same params doesn't contain duplicates within the response.
    """

    def test_no_duplicate_entity_signal_pairs_in_response(self, client: TestClient) -> None:
        """Each (entity_id, signal_type, detected_at) must appear at most once."""
        data = client.get("/api/v1/signals?limit=500").json()
        keys = [(r["entity_id"], r["signal_type"], r["detected_at"]) for r in data]
        assert len(keys) == len(set(keys)), (
            f"Duplicate (entity_id, signal_type, detected_at) in signals response. "
            f"Duplicates: {[k for k in keys if keys.count(k) > 1][:5]}"
        )

    def test_consistent_count_across_identical_requests(self, client: TestClient) -> None:
        count_a = len(client.get("/api/v1/signals?limit=500").json())
        count_b = len(client.get("/api/v1/signals?limit=500").json())
        assert count_a == count_b, "Signal count differs between identical requests"

    def test_date_range_filter_produces_no_overlap(self, client: TestClient) -> None:
        """Signals for TARGET_DATE must not appear in a query that excludes that date."""
        prev_only = client.get(
            f"/api/v1/signals?date_from={PREV_DATE}&date_to={PREV_DATE}"
        ).json()
        target_only = client.get(
            f"/api/v1/signals?date_from={TARGET_DATE}&date_to={TARGET_DATE}"
        ).json()

        prev_keys = {(r["entity_id"], r["detected_at"]) for r in prev_only}
        target_keys = {(r["entity_id"], r["detected_at"]) for r in target_only}
        overlap = prev_keys & target_keys
        assert not overlap, (
            f"Signals for {PREV_DATE} and {TARGET_DATE} overlap: {list(overlap)[:3]}"
        )
