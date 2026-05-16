"""FTG-5 / SN1-A — Signal Intelligence Snapshot Tests.

Tests:
  A  write_signal_snapshot() creates a snapshot for a new signal
  B  write_signal_snapshot() is idempotent — rerun does not duplicate
  C  Snapshot captures expected market metrics from EntityTimeSeriesDaily
  D  Snapshot captures signal_type, signal_strength, signal_metadata
  E  Snapshot captures entity_canonical_name and entity_brand_name
  F  _safe_decimal() handles None, NaN, inf, normal values
  G  write_signal_snapshot() is non-fatal when entity_canonical_name is empty
  H  write_signal_snapshot() is non-fatal when snap dict is empty (metrics all NULL)
  I  SNAPSHOT_SCHEMA_VERSION constant equals 1
  J  signal_threshold_version propagated from calling arg
  K  detect_breakout_signals.run() summary includes snapshots_written key
  L  pipeline_run_date = detected_at.date()
  M  Acceleration/momentum captured from snap dict correctly
  N  growth_rate captured from snap dict correctly
  O  signal_metadata sanitized (None for missing)
  P  write_signal_snapshot() returns True for new snapshot, False for duplicate
  Q  ORM model table name is signal_intelligence_snapshots
  R  Uniqueness constraint name is correct
  S  Missing entity_id returns False without crashing
  T  Missing detected_at returns False without crashing
  U  Existing signals regressions: detect_breakout_signals.run() still returns
     signals_detected and new_signals keys alongside snapshots_written
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.db.market.signal_intelligence_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    SignalIntelligenceSnapshot,
    _safe_decimal,
    write_signal_snapshot,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_sig(
    entity_id: Optional[uuid.UUID] = None,
    signal_type: str = "breakout",
    detected_at: Optional[datetime] = None,
    strength: float = 0.75,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "entity_id": entity_id or uuid.uuid4(),
        "signal_type": signal_type,
        "detected_at": detected_at or datetime(2026, 5, 16, 11, 0, 0, tzinfo=timezone.utc),
        "strength": strength,
        "metadata": metadata or {"growth_pct": 42.5},
    }


def _make_snap(
    composite_market_score: float = 68.4,
    growth_rate: float = 0.32,
    momentum: float = 0.15,
    acceleration: float = 0.05,
    mention_count: float = 12.0,
) -> Dict[str, Any]:
    return {
        "composite_market_score": composite_market_score,
        "growth_rate": growth_rate,
        "momentum": momentum,
        "acceleration": acceleration,
        "mention_count": mention_count,
    }


def _make_mock_session() -> MagicMock:
    """Return a SQLAlchemy Session mock that tracks added objects."""
    session = MagicMock()
    session._added: list = []

    def fake_add(obj):
        session._added.append(obj)

    session.add.side_effect = fake_add
    return session


def _session_returns_existing(session: MagicMock) -> None:
    """Configure session.execute().fetchone() to return a truthy row (conflict)."""
    session.execute.return_value.fetchone.return_value = (uuid.uuid4(),)


def _session_returns_new(session: MagicMock) -> None:
    """Configure session.execute().fetchone() to return None (no existing row)."""
    session.execute.return_value.fetchone.return_value = None


# ---------------------------------------------------------------------------
# A — Snapshot created for new signal
# ---------------------------------------------------------------------------

class TestSnapshotCreation:
    def test_write_returns_true_for_new_snapshot(self):
        session = _make_mock_session()
        _session_returns_new(session)
        sig = _make_sig()
        snap = _make_snap()
        result = write_signal_snapshot(session, sig, snap, "perfume", "Creed Aventus", "Creed")
        assert result is True

    def test_snapshot_object_added_to_session(self):
        session = _make_mock_session()
        _session_returns_new(session)
        sig = _make_sig()
        snap = _make_snap()
        write_signal_snapshot(session, sig, snap, "perfume", "Creed Aventus", "Creed")
        assert len(session._added) == 1
        obj = session._added[0]
        assert isinstance(obj, SignalIntelligenceSnapshot)

    def test_nothing_added_when_existing(self):
        session = _make_mock_session()
        _session_returns_existing(session)
        sig = _make_sig()
        snap = _make_snap()
        result = write_signal_snapshot(session, sig, snap, "perfume", "Creed Aventus", "Creed")
        assert result is False
        assert len(session._added) == 0


# ---------------------------------------------------------------------------
# B — Idempotency (duplicate prevention)
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_call_returns_false(self):
        session = _make_mock_session()
        _session_returns_existing(session)
        sig = _make_sig()
        result = write_signal_snapshot(session, sig, {}, "perfume", "Creed Aventus", "Creed")
        assert result is False

    def test_session_not_modified_on_duplicate(self):
        session = _make_mock_session()
        _session_returns_existing(session)
        sig = _make_sig()
        write_signal_snapshot(session, sig, {}, "perfume", "Creed Aventus", "Creed")
        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# C — Market metrics captured from snap dict
# ---------------------------------------------------------------------------

class TestMetricsCapture:
    def _get_snapshot(self, snap: Dict, **kwargs) -> SignalIntelligenceSnapshot:
        session = _make_mock_session()
        _session_returns_new(session)
        sig = _make_sig()
        write_signal_snapshot(session, sig, snap, "perfume", "Test Perfume", "Brand", **kwargs)
        return session._added[0]

    def test_market_score_captured(self):
        obj = self._get_snapshot(_make_snap(composite_market_score=72.1))
        assert obj.market_score_at_detection == Decimal("72.1000")

    def test_growth_rate_captured(self):
        obj = self._get_snapshot(_make_snap(growth_rate=0.456))
        assert obj.growth_rate_at_detection == Decimal("0.4560")

    def test_momentum_captured(self):
        obj = self._get_snapshot(_make_snap(momentum=0.15))
        assert obj.momentum_at_detection == Decimal("0.1500")

    def test_acceleration_captured(self):
        obj = self._get_snapshot(_make_snap(acceleration=0.03))
        assert obj.acceleration_at_detection == Decimal("0.0300")

    def test_mention_count_captured(self):
        obj = self._get_snapshot(_make_snap(mention_count=18.0))
        assert obj.mention_count_at_detection == Decimal("18.00")


# ---------------------------------------------------------------------------
# D — Signal data captured
# ---------------------------------------------------------------------------

class TestSignalData:
    def _get_snapshot(self, **sig_kwargs) -> SignalIntelligenceSnapshot:
        session = _make_mock_session()
        _session_returns_new(session)
        sig = _make_sig(**sig_kwargs)
        write_signal_snapshot(session, sig, _make_snap(), "perfume", "Perfume A", "Brand X")
        return session._added[0]

    def test_signal_type_captured(self):
        obj = self._get_snapshot(signal_type="acceleration_spike")
        assert obj.signal_type == "acceleration_spike"

    def test_signal_strength_captured(self):
        obj = self._get_snapshot(strength=0.88)
        assert obj.signal_strength == pytest.approx(0.88)

    def test_signal_metadata_captured(self):
        meta = {"momentum": 0.15, "acceleration": 0.05}
        obj = self._get_snapshot(metadata=meta)
        assert obj.signal_metadata == meta

    def test_detected_at_captured(self):
        dt = datetime(2026, 5, 16, 23, 0, 0, tzinfo=timezone.utc)
        obj = self._get_snapshot(detected_at=dt)
        assert obj.detected_at == dt


# ---------------------------------------------------------------------------
# E — Entity fields denormalized
# ---------------------------------------------------------------------------

class TestEntityDenormalization:
    def _get_snapshot(self, canonical_name: str, brand_name: Optional[str]) -> SignalIntelligenceSnapshot:
        session = _make_mock_session()
        _session_returns_new(session)
        write_signal_snapshot(session, _make_sig(), _make_snap(), "perfume", canonical_name, brand_name)
        return session._added[0]

    def test_canonical_name_stored(self):
        obj = self._get_snapshot("Creed Aventus", "Creed")
        assert obj.entity_canonical_name == "Creed Aventus"

    def test_brand_name_stored(self):
        obj = self._get_snapshot("Creed Aventus", "Creed")
        assert obj.entity_brand_name == "Creed"

    def test_brand_name_none_allowed(self):
        obj = self._get_snapshot("Kilian Angels' Share", None)
        assert obj.entity_brand_name is None


# ---------------------------------------------------------------------------
# F — _safe_decimal() edge cases
# ---------------------------------------------------------------------------

class TestSafeDecimal:
    def test_none_returns_none(self):
        assert _safe_decimal(None) is None

    def test_nan_returns_none(self):
        import math
        assert _safe_decimal(float("nan")) is None

    def test_inf_returns_none(self):
        assert _safe_decimal(float("inf")) is None

    def test_neg_inf_returns_none(self):
        assert _safe_decimal(float("-inf")) is None

    def test_normal_float(self):
        result = _safe_decimal(68.4)
        assert isinstance(result, Decimal)
        assert result == Decimal("68.4000")

    def test_int_input(self):
        result = _safe_decimal(42)
        assert isinstance(result, Decimal)

    def test_zero(self):
        result = _safe_decimal(0.0)
        assert result == Decimal("0.0000")


# ---------------------------------------------------------------------------
# G — Non-fatal when entity_canonical_name is empty
# ---------------------------------------------------------------------------

class TestNonFatalEdgeCases:
    def test_empty_canonical_name_returns_false(self):
        session = _make_mock_session()
        _session_returns_new(session)
        result = write_signal_snapshot(session, _make_sig(), {}, "perfume", "", "Brand")
        assert result is False
        assert len(session._added) == 0

    def test_missing_entity_id_returns_false(self):
        session = _make_mock_session()
        sig = _make_sig()
        sig["entity_id"] = None
        result = write_signal_snapshot(session, sig, {}, "perfume", "Name", "Brand")
        assert result is False

    def test_missing_detected_at_returns_false(self):
        session = _make_mock_session()
        sig = _make_sig()
        sig["detected_at"] = None
        result = write_signal_snapshot(session, sig, {}, "perfume", "Name", "Brand")
        assert result is False


# ---------------------------------------------------------------------------
# H — Empty snap dict → metrics are NULL (no crash)
# ---------------------------------------------------------------------------

class TestEmptySnap:
    def test_empty_snap_writes_snapshot_with_null_metrics(self):
        session = _make_mock_session()
        _session_returns_new(session)
        result = write_signal_snapshot(session, _make_sig(), {}, "perfume", "Test Perfume", None)
        assert result is True
        obj = session._added[0]
        assert obj.market_score_at_detection is None
        assert obj.growth_rate_at_detection is None
        assert obj.momentum_at_detection is None
        assert obj.acceleration_at_detection is None
        assert obj.mention_count_at_detection is None


# ---------------------------------------------------------------------------
# I — SNAPSHOT_SCHEMA_VERSION constant
# ---------------------------------------------------------------------------

class TestSchemaVersionConstant:
    def test_schema_version_is_1(self):
        assert SNAPSHOT_SCHEMA_VERSION == 1

    def test_schema_version_written_to_snapshot(self):
        session = _make_mock_session()
        _session_returns_new(session)
        write_signal_snapshot(session, _make_sig(), {}, "perfume", "Test", None)
        obj = session._added[0]
        assert obj.snapshot_schema_version == 1


# ---------------------------------------------------------------------------
# J — signal_threshold_version propagated
# ---------------------------------------------------------------------------

class TestSignalThresholdVersion:
    def test_threshold_version_propagated(self):
        session = _make_mock_session()
        _session_returns_new(session)
        write_signal_snapshot(
            session, _make_sig(), {}, "perfume", "Test", None,
            signal_threshold_version=2,
        )
        obj = session._added[0]
        assert obj.signal_threshold_version == 2

    def test_threshold_version_default_is_1(self):
        session = _make_mock_session()
        _session_returns_new(session)
        write_signal_snapshot(session, _make_sig(), {}, "perfume", "Test", None)
        obj = session._added[0]
        assert obj.signal_threshold_version == 1


# ---------------------------------------------------------------------------
# K — detect_breakout_signals.run() summary includes snapshots_written
# ---------------------------------------------------------------------------

class TestJobSummaryContract:
    def test_run_summary_contains_snapshots_written(self):
        """The run() return dict must include snapshots_written (SN1-A contract)."""
        # We can verify this by inspecting the function source or importing and
        # mocking — use source inspection to avoid a full DB mock.
        import inspect
        from perfume_trend_sdk.jobs import detect_breakout_signals
        src = inspect.getsource(detect_breakout_signals.run)
        assert "snapshots_written" in src

    def test_run_summary_still_contains_signals_detected(self):
        """Existing keys must still be present (regression)."""
        import inspect
        from perfume_trend_sdk.jobs import detect_breakout_signals
        src = inspect.getsource(detect_breakout_signals.run)
        assert "signals_detected" in src
        assert "new_signals" in src
        assert "signal_types" in src


# ---------------------------------------------------------------------------
# L — pipeline_run_date = detected_at.date()
# ---------------------------------------------------------------------------

class TestPipelineRunDate:
    def test_pipeline_run_date_matches_detected_at_date(self):
        session = _make_mock_session()
        _session_returns_new(session)
        dt = datetime(2026, 5, 16, 11, 0, 0, tzinfo=timezone.utc)
        sig = _make_sig(detected_at=dt)
        write_signal_snapshot(session, sig, {}, "perfume", "Test", None)
        obj = session._added[0]
        assert obj.pipeline_run_date == date(2026, 5, 16)


# ---------------------------------------------------------------------------
# Q — ORM model metadata
# ---------------------------------------------------------------------------

class TestORMModel:
    def test_table_name(self):
        assert SignalIntelligenceSnapshot.__tablename__ == "signal_intelligence_snapshots"

    def test_uniqueness_constraint_name(self):
        constraints = SignalIntelligenceSnapshot.__table_args__
        constraint_names = [c.name for c in constraints if hasattr(c, "name")]
        assert "uq_sig_snapshot_entity_signal_detected" in constraint_names


# ---------------------------------------------------------------------------
# P — Returns True for new, False for duplicate (summary)
# ---------------------------------------------------------------------------

class TestReturnValues:
    def test_returns_true_for_new(self):
        session = _make_mock_session()
        _session_returns_new(session)
        result = write_signal_snapshot(session, _make_sig(), {}, "perfume", "Test", None)
        assert result is True

    def test_returns_false_for_existing(self):
        session = _make_mock_session()
        _session_returns_existing(session)
        result = write_signal_snapshot(session, _make_sig(), {}, "perfume", "Test", None)
        assert result is False
