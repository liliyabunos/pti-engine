from __future__ import annotations

from pathlib import Path

import pytest

from perfume_trend_sdk.storage.market.sqlite_store import MarketStore


@pytest.fixture
def store(tmp_path: Path) -> MarketStore:
    s = MarketStore(str(tmp_path / "market.db"))
    s.init_schema()
    return s


def _entity(entity_id: str = "Parfums de Marly Delina") -> dict:
    return {
        "entity_id": entity_id,
        "entity_type": "perfume",
        "ticker": "DLNA",
        "canonical_name": entity_id,
        "created_at": "2026-04-10T00:00:00Z",
    }


def _snapshot(entity_id: str = "Parfums de Marly Delina", date: str = "2026-04-10") -> dict:
    return {
        "entity_id": entity_id,
        "entity_type": "perfume",
        "date": date,
        "mention_count": 4.0,
        "unique_authors": 3,
        "engagement_sum": 120000.0,
        "sentiment_avg": None,
        "confidence_avg": None,
        "search_index": None,
        "retailer_score": None,
        "growth_rate": 0.333,
        "composite_market_score": 45.0,
        "momentum": 1.2,
        "acceleration": 0.3,
        "volatility": 0.3,
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_init_schema_creates_tables(tmp_path: Path) -> None:
    db = str(tmp_path / "test.db")
    import sqlite3
    MarketStore(db).init_schema()
    conn = sqlite3.connect(db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "entity_market" in tables
    assert "entity_timeseries_daily" in tables
    assert "signals" in tables
    conn.close()


def test_init_schema_idempotent(store: MarketStore) -> None:
    store.init_schema()
    store.init_schema()  # Should not raise


# ---------------------------------------------------------------------------
# entity_market
# ---------------------------------------------------------------------------

def test_upsert_and_get_entity(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    ent = store.get_entity("Parfums de Marly Delina")
    assert ent is not None
    assert ent["ticker"] == "DLNA"
    assert ent["entity_type"] == "perfume"


def test_get_entity_returns_none_for_missing(store: MarketStore) -> None:
    assert store.get_entity("nonexistent") is None


def test_upsert_entity_is_idempotent(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.upsert_entity(**_entity())
    entities = store.list_entities()
    assert len(entities) == 1


def test_list_entities_returns_all(store: MarketStore) -> None:
    store.upsert_entity(**_entity("Entity A"))
    store.upsert_entity(**_entity("Entity B"))
    assert len(store.list_entities()) == 2


# ---------------------------------------------------------------------------
# entity_timeseries_daily
# ---------------------------------------------------------------------------

def test_upsert_and_get_latest_snapshot(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.upsert_daily_snapshot(_snapshot())
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    assert snap is not None
    assert snap["composite_market_score"] == 45.0
    assert str(snap["date"]) == "2026-04-10"


def test_get_latest_snapshot_returns_most_recent(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.upsert_daily_snapshot(_snapshot(date="2026-04-08"))
    store.upsert_daily_snapshot(_snapshot(date="2026-04-10"))
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    assert str(snap["date"]) == "2026-04-10"


def test_get_latest_snapshot_returns_none_when_empty(store: MarketStore) -> None:
    assert store.get_latest_snapshot("nonexistent") is None


def test_get_prev_snapshot(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.upsert_daily_snapshot(_snapshot(date="2026-04-08"))
    store.upsert_daily_snapshot(_snapshot(date="2026-04-10"))
    prev = store.get_prev_snapshot("Parfums de Marly Delina", before_date="2026-04-10")
    assert prev is not None
    assert str(prev["date"]) == "2026-04-08"


def test_get_prev_snapshot_returns_none_at_first_entry(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.upsert_daily_snapshot(_snapshot(date="2026-04-10"))
    prev = store.get_prev_snapshot("Parfums de Marly Delina", before_date="2026-04-10")
    assert prev is None


def test_get_entity_history_returns_ordered_asc(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.upsert_daily_snapshot(_snapshot(date="2026-04-08"))
    store.upsert_daily_snapshot(_snapshot(date="2026-04-09"))
    store.upsert_daily_snapshot(_snapshot(date="2026-04-10"))
    history = store.get_entity_history("Parfums de Marly Delina", days=30)
    dates = [str(r["date"]) for r in history]
    assert dates == sorted(dates)


def test_upsert_snapshot_is_idempotent(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.upsert_daily_snapshot(_snapshot())
    updated = {**_snapshot(), "composite_market_score": 99.0}
    store.upsert_daily_snapshot(updated)
    snap = store.get_latest_snapshot("Parfums de Marly Delina")
    assert snap["composite_market_score"] == 99.0


def test_list_latest_snapshots_returns_entities(store: MarketStore) -> None:
    store.upsert_entity(**_entity("Parfums de Marly Delina"))
    store.upsert_entity(**_entity("Maison Francis Kurkdjian Baccarat Rouge 540"))
    store.upsert_daily_snapshot(_snapshot("Parfums de Marly Delina"))
    store.upsert_daily_snapshot(_snapshot("Maison Francis Kurkdjian Baccarat Rouge 540"))
    rows = store.list_latest_snapshots()
    names = {r["entity_id"] for r in rows}
    assert "Parfums de Marly Delina" in names
    assert "Maison Francis Kurkdjian Baccarat Rouge 540" in names


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------

def test_save_and_retrieve_signals(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    signals = [
        {
            "entity_id": "Parfums de Marly Delina",  # resolved to UUID internally
            "signal_type": "breakout",
            "detected_at": "2026-04-10",
            "score": 45.0,
            "details": {"growth_pct": 80.0},
        }
    ]
    store.save_signals(signals)
    result = store.list_recent_signals(days=7)
    assert len(result) == 1
    assert result[0]["signal_type"] == "breakout"


def test_save_signals_idempotent(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    sig = {
        "entity_id": "Parfums de Marly Delina",
        "signal_type": "breakout",
        "detected_at": "2026-04-10",
        "score": 45.0,
        "details": {},
    }
    store.save_signals([sig])
    store.save_signals([sig])
    assert len(store.list_recent_signals(days=7)) == 1


def test_get_entity_signals(store: MarketStore) -> None:
    store.upsert_entity(**_entity())
    store.save_signals([
        {
            "entity_id": "Parfums de Marly Delina",
            "signal_type": "new_entry",
            "detected_at": "2026-04-09",
            "score": 10.0,
            "details": {},
        },
        {
            "entity_id": "Parfums de Marly Delina",
            "signal_type": "breakout",
            "detected_at": "2026-04-10",
            "score": 45.0,
            "details": {},
        },
    ])
    sigs = store.get_entity_signals("Parfums de Marly Delina")
    assert len(sigs) == 2


def test_list_recent_signals_empty_when_no_data(store: MarketStore) -> None:
    assert store.list_recent_signals(days=7) == []
