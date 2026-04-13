from __future__ import annotations

"""
Dashboard API contract tests — GET /api/v1/dashboard.

Validates:
  - HTTP 200 and required response keys
  - top_movers schema (required fields on each row)
  - top_movers sorted DESC by composite_market_score
  - rank starts at 1 and increments by 1
  - top_n query param limits the result
  - stable payload across two identical requests (ordering determinism)
  - offset-based pagination parity with screener (no page=N usage)
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

_ENTITIES = [
    ("Parfums de Marly Delina", 90_000),
    ("MFK Baccarat Rouge 540", 75_000),
    ("Creed Aventus", 60_000),
    ("Dior Sauvage", 50_000),
    ("YSL Libre", 40_000),
    ("Tom Ford Black Orchid", 30_000),
]

_REQUIRED_DASHBOARD_KEYS = {
    "generated_at", "total_entities", "top_movers", "recent_signals", "breakouts",
}
_REQUIRED_MOVER_KEYS = {
    "rank", "entity_id", "entity_type", "ticker", "canonical_name",
    "composite_market_score", "mention_count", "momentum",
}


# ---------------------------------------------------------------------------
# Shared DB + TestClient fixture
# ---------------------------------------------------------------------------

def _build_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "dashboard_test.db")

    nc = NormalizedContentStore(db_path)
    nc.init_schema()

    sc = SignalStore(db_path)
    sc.init_schema()

    content_items: List[Dict[str, Any]] = []
    resolved_signals: List[Dict[str, Any]] = []

    for i, (entity_name, views) in enumerate(_ENTITIES):
        yt_id = f"yt_d{i:03d}"
        tt_id = f"tt_d{i:03d}"

        for item_id, platform, v in [(yt_id, "youtube", views), (tt_id, "tiktok", views // 2)]:
            content_items.append({
                "id": item_id,
                "schema_version": "1.0",
                "source_platform": platform,
                "source_account_id": None,
                "source_account_handle": f"creator_{item_id}",
                "source_account_type": "creator",
                "source_url": f"https://{platform}.com/{item_id}",
                "external_content_id": item_id,
                "published_at": f"{TARGET_DATE}T10:00:00+00:00",
                "collected_at": f"{TARGET_DATE}T12:00:00+00:00",
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
            })
            resolved_signals.append({
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
            })

    nc.save_content_items(content_items)
    sc.save_resolved_signals(resolved_signals)
    run_aggregation(db_path=db_path, target_date=TARGET_DATE)
    return db_path


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    db_path = _build_db(tmp_path_factory.mktemp("dashboard"))
    os.environ["PTI_DB_PATH"] = db_path
    from perfume_trend_sdk.api.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# HTTP + top-level shape
# ---------------------------------------------------------------------------

class TestDashboardHTTP:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get("/api/v1/dashboard")
        assert r.status_code == 200

    def test_required_top_level_keys(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        missing = _REQUIRED_DASHBOARD_KEYS - set(data.keys())
        assert not missing, f"Missing dashboard keys: {missing}"

    def test_generated_at_is_string(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        assert isinstance(data["generated_at"], str)
        assert "T" in data["generated_at"], "generated_at should be ISO datetime"

    def test_total_entities_is_positive_int(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        assert isinstance(data["total_entities"], int)
        assert data["total_entities"] >= 1


# ---------------------------------------------------------------------------
# top_movers schema
# ---------------------------------------------------------------------------

class TestTopMoversSchema:
    def test_top_movers_not_empty(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        assert len(data["top_movers"]) >= 1

    def test_top_mover_row_has_required_fields(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        row = data["top_movers"][0]
        missing = _REQUIRED_MOVER_KEYS - set(row.keys())
        assert not missing, f"top_movers[0] missing fields: {missing}"

    def test_composite_market_score_is_numeric(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        for row in data["top_movers"]:
            assert isinstance(row["composite_market_score"], (int, float))
            assert row["composite_market_score"] >= 0

    def test_mention_count_is_non_negative(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        for row in data["top_movers"]:
            assert (row["mention_count"] or 0) >= 0


# ---------------------------------------------------------------------------
# Ordering invariants
# ---------------------------------------------------------------------------

class TestTopMoversOrdering:
    def test_sorted_descending_by_score(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        scores = [r["composite_market_score"] for r in data["top_movers"]]
        assert scores == sorted(scores, reverse=True), (
            f"top_movers not sorted DESC: {scores}"
        )

    def test_rank_starts_at_1(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        assert data["top_movers"][0]["rank"] == 1

    def test_rank_increments_by_1(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard").json()
        ranks = [r["rank"] for r in data["top_movers"]]
        expected = list(range(1, len(ranks) + 1))
        assert ranks == expected, f"Ranks not sequential: {ranks}"

    def test_ordering_stable_across_requests(self, client: TestClient) -> None:
        """Two identical requests must return the same top_movers order."""
        ids_a = [r["entity_id"] for r in client.get("/api/v1/dashboard").json()["top_movers"]]
        ids_b = [r["entity_id"] for r in client.get("/api/v1/dashboard").json()["top_movers"]]
        assert ids_a == ids_b, "Dashboard top_movers order is non-deterministic"


# ---------------------------------------------------------------------------
# Query parameter behaviour
# ---------------------------------------------------------------------------

class TestDashboardQueryParams:
    def test_top_n_limits_results(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard?top_n=2").json()
        assert len(data["top_movers"]) <= 2

    def test_top_n_1_returns_single_row(self, client: TestClient) -> None:
        data = client.get("/api/v1/dashboard?top_n=1").json()
        assert len(data["top_movers"]) == 1

    def test_signal_days_param_accepted(self, client: TestClient) -> None:
        r = client.get("/api/v1/dashboard?signal_days=30")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Screener offset pagination — no page numbers
# ---------------------------------------------------------------------------

class TestScreenerOffsetPagination:
    """Offset-based pagination: no page=N, use limit + offset only."""

    def test_offset_pagination_no_duplicates(self, client: TestClient) -> None:
        r1 = client.get("/api/v1/screener?limit=3&offset=0")
        r2 = client.get("/api/v1/screener?limit=3&offset=3")
        assert r1.status_code == 200
        assert r2.status_code == 200

        ids1 = {row["entity_id"] for row in r1.json()["rows"]}
        ids2 = {row["entity_id"] for row in r2.json()["rows"]}
        overlap = ids1 & ids2
        assert not overlap, f"Duplicate entity_ids across pages: {overlap}"

    def test_offset_pagination_total_consistent(self, client: TestClient) -> None:
        r = client.get("/api/v1/screener?limit=100&offset=0")
        total = r.json()["total"]
        all_rows = r.json()["rows"]

        # Fetch same data in two halves
        half = max(1, total // 2)
        r_a = client.get(f"/api/v1/screener?limit={half}&offset=0")
        r_b = client.get(f"/api/v1/screener?limit={half}&offset={half}")

        combined = r_a.json()["rows"] + r_b.json()["rows"]
        combined_ids = {row["entity_id"] for row in combined}
        all_ids = {row["entity_id"] for row in all_rows}

        # The union of both pages must be a subset of the full result
        assert combined_ids <= all_ids

    def test_screener_response_has_pagination_fields(self, client: TestClient) -> None:
        data = client.get("/api/v1/screener").json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "rows" in data
        assert isinstance(data["rows"], list)

    def test_screener_offset_beyond_total_returns_empty_rows(self, client: TestClient) -> None:
        total = client.get("/api/v1/screener").json()["total"]
        data = client.get(f"/api/v1/screener?offset={total + 100}").json()
        assert data["rows"] == []
        assert data["total"] == total  # total count is unaffected by offset
