from __future__ import annotations

"""
Integration tests for MarketVerifier.

Covers:
  - non-empty aggregated state after fixture load
  - signal invariant enforcement (clean pass)
  - reversal suppression detects violations
  - breakout suppression detects violations
  - pagination duplicate detection (clean pass with 8 entities)
  - idempotent verification result for repeated runs
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from perfume_trend_sdk.db.market.models import Base, EntityMarket
from perfume_trend_sdk.db.market.signal import Signal
from perfume_trend_sdk.storage.market.sqlite_store import MarketStore
from perfume_trend_sdk.storage.normalized.sqlite_store import NormalizedContentStore
from perfume_trend_sdk.storage.signals.sqlite_store import SignalStore
from perfume_trend_sdk.verification.market_verifier import MarketVerifier

TARGET_DATE = "2026-04-10"

# Eight real-world reference entities — gives two full pagination pages of 4
_ENTITIES = [
    "Parfums de Marly Delina",
    "MFK Baccarat Rouge 540",
    "Creed Aventus",
    "Dior Sauvage",
    "YSL Libre",
    "Tom Ford Black Orchid",
    "Xerjoff Erba Pura",
    "Byredo Gypsy Water",
]


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _content_item(item_id: str, platform: str, entity_name: str, views: int) -> Dict[str, Any]:
    return {
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
        "text_content": f"Talking about {entity_name} today.",
        "hashtags": [],
        "mentions_raw": [],
        "media_metadata": {"source_type": "influencer", "influence_score": 75.0},
        "engagement": {"views": views, "likes": views // 20, "comments": views // 100},
        "language": None,
        "region": "US",
        "raw_payload_ref": f"data/raw/test/{item_id}.json",
        "normalizer_version": "1.0",
        "query": entity_name.lower().split()[0],
    }


def _resolved_signal(content_item_id: str, entity_name: str) -> Dict[str, Any]:
    return {
        "content_item_id": content_item_id,
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
    }


def _build_multi_entity_db(db_path: str) -> str:
    """
    Populate db_path with 8 entities, each with 2 content items (youtube + tiktok).
    This gives mention_count = 1.2 + 1.3 = 2.5 per entity, well above suppression thresholds.
    """
    from perfume_trend_sdk.workflows.run_daily_aggregation import run_aggregation

    normalized_store = NormalizedContentStore(db_path)
    normalized_store.init_schema()

    signal_store = SignalStore(db_path)
    signal_store.init_schema()

    content_items: List[Dict[str, Any]] = []
    resolved_signals: List[Dict[str, Any]] = []

    for i, entity_name in enumerate(_ENTITIES):
        # Two items per entity so mention_count = 1.2 (yt) + 1.3 (tt) = 2.5
        yt_id = f"yt_{i:03d}"
        tt_id = f"tt_{i:03d}"
        base_views = (i + 1) * 10_000  # distinct scores so no sort ties

        content_items.append(_content_item(yt_id, "youtube", entity_name, base_views))
        content_items.append(_content_item(tt_id, "tiktok", entity_name, base_views // 2))

        resolved_signals.append(_resolved_signal(yt_id, entity_name))
        resolved_signals.append(_resolved_signal(tt_id, entity_name))

    normalized_store.save_content_items(content_items)
    signal_store.save_resolved_signals(resolved_signals)

    run_aggregation(db_path=db_path, target_date=TARGET_DATE)
    return db_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_path(tmp_path_factory) -> str:
    path = str(tmp_path_factory.mktemp("verifier") / "verifier_test.db")
    return _build_multi_entity_db(path)


@pytest.fixture(scope="module")
def orm_session(db_path: str):
    """SQLAlchemy session against the test DB for direct ORM queries."""
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    with Session_() as session:
        yield session


@pytest.fixture(scope="module")
def client(db_path: str):
    """FastAPI TestClient wired to the test DB."""
    os.environ["PTI_DB_PATH"] = db_path
    from perfume_trend_sdk.api.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture(scope="module")
def verifier(orm_session, client) -> MarketVerifier:
    # allow_demo=True: fixture data is intentionally synthetic (no real channel metadata)
    return MarketVerifier(db=orm_session, test_client=client, allow_demo=True)


@pytest.fixture(scope="module")
def clean_result(verifier):
    """Run verification once; reuse for multiple tests."""
    return verifier.verify(TARGET_DATE)


# ---------------------------------------------------------------------------
# 1. Non-empty aggregated state
# ---------------------------------------------------------------------------

class TestAggregatedState:
    def test_aggregated_rows_exist(self, clean_result):
        assert any(
            "aggregated_rows_exist" in c for c in clean_result.passed_checks
        ), "Expected aggregated_rows_exist to pass"

    def test_all_eight_entities_created(self, db_path):
        engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        Session_ = sessionmaker(bind=engine)
        with Session_() as s:
            count = s.query(EntityMarket).count()
        assert count == len(_ENTITIES), f"Expected {len(_ENTITIES)} entities, got {count}"

    def test_metrics_non_negative_passes(self, clean_result):
        assert any(
            "metrics_non_negative" in c for c in clean_result.passed_checks
        )


# ---------------------------------------------------------------------------
# 2. Signal invariant enforcement — clean data
# ---------------------------------------------------------------------------

class TestSignalInvariantsClean:
    def test_no_duplicate_signals_passes(self, clean_result):
        assert any(
            "no_duplicate_signals" in c for c in clean_result.passed_checks
        )

    def test_reversal_suppression_passes(self, clean_result):
        assert any(
            "reversal_suppression" in c for c in clean_result.passed_checks
        )

    def test_breakout_suppression_passes(self, clean_result):
        assert any(
            "breakout_suppression" in c for c in clean_result.passed_checks
        )

    def test_overall_result_passes(self, clean_result):
        assert clean_result.passed, (
            f"Expected clean fixture to pass all checks. "
            f"Failures: {clean_result.failed_checks}"
        )


# ---------------------------------------------------------------------------
# 3. Reversal suppression detects violation
# ---------------------------------------------------------------------------

def _build_violation_db(db_path: str, mention_count: float, signal_type: str) -> str:
    """
    Create a minimal DB with one entity whose snapshot has mention_count below
    suppression thresholds, then inject a violating signal of the given type.

    Uses MarketStore.upsert_entity/upsert_daily_snapshot so published_at date
    alignment is not a concern — we control the snapshot directly.
    """
    VIOLATION_DATE = TARGET_DATE
    entity_name = f"Violation {signal_type.title()} Perfume"

    store = MarketStore(db_path)
    store.init_schema()

    store.upsert_entity(
        entity_id=entity_name,
        entity_type="perfume",
        ticker="VIOL",
        canonical_name=entity_name,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    store.upsert_daily_snapshot({
        "entity_id": entity_name,
        "entity_type": "perfume",
        "date": VIOLATION_DATE,
        "mention_count": mention_count,     # deliberately below threshold
        "unique_authors": 1,
        "engagement_sum": 500.0,
        "composite_market_score": 22.0,
        "momentum": 0.5,
        "acceleration": -0.5,
        "volatility": 0.5,
        "growth_rate": -0.6,
    })

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Session_ = sessionmaker(bind=engine)

    with Session_() as s:
        em = s.query(EntityMarket).filter_by(entity_id=entity_name).first()
        assert em is not None, f"Entity '{entity_name}' not found after upsert"
        detected_dt = datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)
        s.add(Signal(
            entity_id=em.id,
            entity_type="perfume",
            signal_type=signal_type,
            strength=22.0,
            detected_at=detected_dt,
            created_at=datetime.now(timezone.utc),
        ))
        s.commit()

    return db_path


class TestReversalSuppressionViolation:
    def test_violation_is_detected(self, tmp_path):
        """
        A reversal signal fired when mention_count < reversal_min_mentions=2.0
        must be flagged as a failed check.

        We inject the violating signal directly (bypassing the detector) to
        simulate a misconfigured threshold or schema drift.
        """
        db_path = _build_violation_db(
            str(tmp_path / "rev_violation.db"),
            mention_count=1.2,       # youtube weight = 1.2 < 2.0
            signal_type="reversal",
        )

        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Session_ = sessionmaker(bind=engine)

        with Session_() as s:
            result = MarketVerifier(db=s).verify(TARGET_DATE)

        assert any("reversal_suppression" in f for f in result.failed_checks), (
            f"Expected reversal_suppression failure. "
            f"Failed: {result.failed_checks}  Passed: {result.passed_checks}"
        )
        assert not result.passed


# ---------------------------------------------------------------------------
# 4. Breakout suppression detects violation
# ---------------------------------------------------------------------------

class TestBreakoutSuppressionViolation:
    def test_violation_is_detected(self, tmp_path):
        """
        A breakout signal fired when mention_count < breakout_min_mentions=2.0
        must be flagged as a failed check.
        """
        db_path = _build_violation_db(
            str(tmp_path / "bk_violation.db"),
            mention_count=1.2,
            signal_type="breakout",
        )

        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Session_ = sessionmaker(bind=engine)

        with Session_() as s:
            result = MarketVerifier(db=s).verify(TARGET_DATE)

        assert any("breakout_suppression" in f for f in result.failed_checks), (
            f"Expected breakout_suppression failure. "
            f"Failed: {result.failed_checks}  Passed: {result.passed_checks}"
        )
        assert not result.passed


# ---------------------------------------------------------------------------
# 5. Pagination duplicate detection
# ---------------------------------------------------------------------------

class TestPaginationDuplicateDetection:
    def test_no_duplicates_across_pages(self, clean_result):
        """Eight entities across two pages of 5 must not overlap."""
        passed = [c for c in clean_result.passed_checks if "pagination_no_duplicates" in c]
        warned = [w for w in clean_result.warnings if "pagination_no_duplicates" in w]

        # Either a clean pass or a warning about insufficient data is acceptable;
        # a failure is not.
        failed = [f for f in clean_result.failed_checks if "pagination_no_duplicates" in f]
        assert not failed, f"Unexpected pagination duplicate: {failed}"
        assert passed or warned, "pagination_no_duplicates check did not run"

    def test_stable_ordering(self, clean_result):
        passed = [c for c in clean_result.passed_checks if "pagination_stable_ordering" in c]
        failed = [f for f in clean_result.failed_checks if "pagination_stable_ordering" in f]
        assert not failed, f"Non-deterministic ordering detected: {failed}"
        assert passed or any("pagination_stable_ordering" in w for w in clean_result.warnings)


# ---------------------------------------------------------------------------
# 6. Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_repeated_runs_produce_same_result(self, verifier):
        result_a = verifier.verify(TARGET_DATE)
        result_b = verifier.verify(TARGET_DATE)

        assert result_a.passed == result_b.passed
        assert sorted(result_a.passed_checks) == sorted(result_b.passed_checks)
        assert sorted(result_a.failed_checks) == sorted(result_b.failed_checks)
        assert sorted(result_a.warnings) == sorted(result_b.warnings)

    def test_result_has_required_dict_keys(self, clean_result):
        d = clean_result.to_dict()
        assert "date" in d
        assert "passed" in d
        assert "passed_checks" in d
        assert "failed_checks" in d
        assert "warnings" in d
        assert "metrics" in d
        assert "summary" in d
        assert isinstance(d["passed_checks"], list)
        assert isinstance(d["failed_checks"], list)
        assert isinstance(d["metrics"], dict)


# ---------------------------------------------------------------------------
# 7. Demo data purity check
# ---------------------------------------------------------------------------

class TestDemoDataCheck:
    """
    Tests for the demo_data_presence check.

    Uses the shared module-scoped fixture (all synthetic — no real channel metadata).
    Adds per-function isolation tests for allow_demo=True vs False modes.
    """

    def test_demo_stats_in_metrics(self, clean_result):
        """demo_stats must appear in result.metrics after verification."""
        assert "demo_stats" in clean_result.metrics, (
            f"Expected demo_stats in metrics. metrics={clean_result.metrics}"
        )

    def test_demo_stats_structure(self, clean_result):
        stats = clean_result.metrics["demo_stats"]
        for key in ("total_items", "real_items", "demo_items",
                    "demo_percentage", "real_percentage",
                    "real_channels_count", "demo_by_platform"):
            assert key in stats, f"Missing key '{key}' in demo_stats"

    def test_demo_stats_totals_consistent(self, clean_result):
        stats = clean_result.metrics["demo_stats"]
        assert stats["real_items"] + stats["demo_items"] == stats["total_items"]

    def test_demo_stats_percentages_sum_to_100(self, clean_result):
        stats = clean_result.metrics["demo_stats"]
        total_pct = round(stats["real_percentage"] + stats["demo_percentage"], 1)
        # Allow floating-point rounding: within 0.2 of 100
        assert abs(total_pct - 100.0) <= 0.2, f"Percentages don't sum to 100: {total_pct}"

    def test_allow_demo_false_fails_on_synthetic_data(self, db_path, orm_session):
        """With allow_demo=False, any synthetic data must FAIL verification."""
        # The shared fixture has entirely synthetic content → must fail
        result = MarketVerifier(db=orm_session, allow_demo=False).verify(TARGET_DATE)
        assert any("demo_data_presence" in f for f in result.failed_checks), (
            f"Expected demo_data_presence failure with allow_demo=False. "
            f"Failed: {result.failed_checks}"
        )
        assert not result.passed

    def test_allow_demo_true_warns_on_synthetic_data(self, db_path, orm_session):
        """With allow_demo=True, synthetic data must WARN not fail."""
        result = MarketVerifier(db=orm_session, allow_demo=True).verify(TARGET_DATE)
        assert not any("demo_data_presence" in f for f in result.failed_checks), (
            f"Expected no demo_data_presence failure with allow_demo=True. "
            f"Got: {result.failed_checks}"
        )
        assert any("demo_data_presence" in w for w in result.warnings), (
            f"Expected demo_data_presence warning. Warnings: {result.warnings}"
        )

    def test_real_only_db_passes_demo_check(self, tmp_path):
        """A DB with only real YouTube items (with channel metadata) must PASS."""
        db_path = str(tmp_path / "real_only.db")
        entity_name = "Real Channel Perfume"

        store = MarketStore(db_path)
        store.init_schema()

        # Insert entity and snapshot
        store.upsert_entity(
            entity_id=entity_name,
            entity_type="perfume",
            ticker="REAL",
            canonical_name=entity_name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        store.upsert_daily_snapshot({
            "entity_id": entity_name,
            "entity_type": "perfume",
            "date": TARGET_DATE,
            "mention_count": 2.4,
            "unique_authors": 2,
            "engagement_sum": 100_000.0,
            "composite_market_score": 55.0,
            "momentum": 1.2,
            "acceleration": 0.2,
            "volatility": 0.2,
            "growth_rate": 0.5,
        })

        # Seed one real YouTube item (with channel_id + channel_title)
        nc = NormalizedContentStore(db_path)
        nc.init_schema()
        nc.save_content_items([{
            "id": "yt_real_001",
            "schema_version": "1.0",
            "source_platform": "youtube",
            "source_account_id": "UCabc123",
            "source_account_handle": "FragranceGuru",
            "source_account_type": "creator",
            "source_url": "https://youtube.com/watch?v=real001",
            "external_content_id": "yt_real_001",
            "published_at": f"{TARGET_DATE}T10:00:00+00:00",
            "collected_at": f"{TARGET_DATE}T12:00:00+00:00",
            "content_type": "video",
            "title": "Real Perfume Review",
            "caption": None,
            "text_content": f"Reviewing {entity_name}.",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {
                "channel_id": "UCabc123",
                "channel_title": "FragranceGuru",
                "source_type": "influencer",
                "influence_score": 80.0,
            },
            "engagement": {"views": 50_000, "likes": 2_500, "comments": 120},
            "language": None,
            "region": "US",
            "raw_payload_ref": "data/raw/test/yt_real_001.json",
            "normalizer_version": "1.0",
            "query": "real perfume",
        }])

        engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        Session_ = sessionmaker(bind=engine)

        with Session_() as s:
            result = MarketVerifier(db=s, allow_demo=False).verify(TARGET_DATE)

        assert not any("demo_data_presence" in f for f in result.failed_checks), (
            f"Real-only DB should not fail demo check. Failures: {result.failed_checks}"
        )
        stats = result.metrics.get("demo_stats", {})
        assert stats.get("demo_percentage", 1) == 0.0, (
            f"Expected 0% demo. Got: {stats}"
        )

    def test_youtube_without_channel_metadata_is_real_not_synthetic(self, tmp_path):
        """
        Platform-based classification: a youtube item missing channel_id and
        channel_title must be classified as REAL, not synthetic.

        Regression guard: the old metadata-based classification would mark this
        item as synthetic because channel_id/channel_title were absent.
        """
        db_path = str(tmp_path / "yt_no_channel_meta.db")
        entity_name = "No Channel Meta Perfume"

        store = MarketStore(db_path)
        store.init_schema()

        store.upsert_entity(
            entity_id=entity_name,
            entity_type="perfume",
            ticker="NCM",
            canonical_name=entity_name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        store.upsert_daily_snapshot({
            "entity_id": entity_name,
            "entity_type": "perfume",
            "date": TARGET_DATE,
            "mention_count": 1.2,
            "unique_authors": 1,
            "engagement_sum": 20_000.0,
            "composite_market_score": 18.0,
            "momentum": 0.8,
            "acceleration": 0.1,
            "volatility": 0.3,
            "growth_rate": 0.2,
        })

        # YouTube item with NO channel_id or channel_title in media_metadata
        nc = NormalizedContentStore(db_path)
        nc.init_schema()
        nc.save_content_items([{
            "id": "yt_no_meta_001",
            "schema_version": "1.0",
            "source_platform": "youtube",          # platform = youtube → real
            "source_account_id": None,              # missing — quality gap only
            "source_account_handle": None,          # missing — quality gap only
            "source_account_type": "creator",
            "source_url": "https://youtube.com/watch?v=nometa001",
            "external_content_id": "yt_no_meta_001",
            "published_at": f"{TARGET_DATE}T10:00:00+00:00",
            "collected_at": f"{TARGET_DATE}T12:00:00+00:00",
            "content_type": "video",
            "title": f"{entity_name} Review",
            "caption": None,
            "text_content": f"Talking about {entity_name}.",
            "hashtags": [],
            "mentions_raw": [],
            "media_metadata": {},                   # empty — no channel_id, no channel_title
            "engagement": {"views": 20_000, "likes": 1_000, "comments": 50},
            "language": None,
            "region": "US",
            "raw_payload_ref": "data/raw/test/yt_no_meta_001.json",
            "normalizer_version": "1.0",
            "query": "perfume",
        }])

        engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        Session_ = sessionmaker(bind=engine)

        with Session_() as s:
            result = MarketVerifier(db=s, allow_demo=False).verify(TARGET_DATE)

        stats = result.metrics.get("demo_stats", {})

        # Must be classified as real (not synthetic) — platform-based rule
        assert stats.get("real_items") == 1, (
            f"YouTube item without channel metadata should be real. stats={stats}"
        )
        assert stats.get("demo_items") == 0, (
            f"YouTube item without channel metadata must NOT be synthetic. stats={stats}"
        )
        assert stats.get("demo_percentage") == 0.0, (
            f"Expected 0% synthetic. stats={stats}"
        )

        # Must not fail the demo check (no synthetic content)
        assert not any("demo_data_presence" in f for f in result.failed_checks), (
            f"YouTube-only DB with missing channel metadata must not fail demo check. "
            f"Failures: {result.failed_checks}"
        )

        # Must emit a quality sub-warning about missing channel metadata
        yt_meta_warnings = [
            w for w in result.warnings
            if "missing channel_id or channel_title" in w
        ]
        assert yt_meta_warnings, (
            f"Expected sub-warning about missing youtube channel metadata. "
            f"Warnings: {result.warnings}"
        )
