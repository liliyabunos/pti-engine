"""Unit tests for P3 — pipeline_health_check.py

Covers:
  - OK case: all metrics healthy
  - total entity_mentions below CRITICAL threshold
  - total entity_mentions below WARNING threshold
  - reddit entity_mentions = 0 (morning → WARNING, evening → CRITICAL)
  - reddit canonical_content_items = 0 (WARNING)
  - youtube items low (WARNING)
  - total items critical (evening only)
  - signals low (evening only)
  - log output contains PIPELINE_HEALTH_* marker
  - exit code always 0
  - _persist_result: upsert SQL executed correctly
  - _persist_result: non-fatal on DB error
  - _resolve_pipeline_service: env var resolution order
"""

from __future__ import annotations

import json
import logging
import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest

from perfume_trend_sdk.jobs.pipeline_health_check import (
    _evaluate,
    _persist_result,
    _resolve_pipeline_service,
    run_health_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metrics(
    total_mentions=200,
    reddit_mentions=40,
    reddit_items=25,
    youtube_items=120,
    total_items=150,
    signals_today=80,
) -> dict:
    return {
        "total_mentions": total_mentions,
        "reddit_mentions": reddit_mentions,
        "reddit_items": reddit_items,
        "youtube_items": youtube_items,
        "total_items": total_items,
        "signals_today": signals_today,
        "date": "2026-05-07",
    }


# ---------------------------------------------------------------------------
# _evaluate unit tests
# ---------------------------------------------------------------------------

class TestEvaluateOK:
    def test_healthy_morning(self):
        level, issues = _evaluate(_metrics(), "morning")
        assert level == "OK"
        assert issues == []

    def test_healthy_evening(self):
        level, issues = _evaluate(_metrics(), "evening")
        assert level == "OK"
        assert issues == []


class TestEntityMentionsThresholds:
    def test_below_critical_50(self):
        level, issues = _evaluate(_metrics(total_mentions=30), "evening")
        assert level == "CRITICAL"
        assert any("entity_mentions=30" in i and "CRITICAL" in i for i in issues)

    def test_exactly_critical_threshold(self):
        """At the threshold itself — below means < 50, so 50 is OK."""
        level, issues = _evaluate(_metrics(total_mentions=50), "evening")
        # 50 is NOT below 50, so no CRITICAL for mentions
        crit_mention = [i for i in issues if "entity_mentions=50" in i and "CRITICAL" in i]
        assert crit_mention == []

    def test_below_warning_70(self):
        level, issues = _evaluate(_metrics(total_mentions=70), "morning")
        assert level == "WARNING"
        assert any("entity_mentions=70" in i and "WARNING" in i for i in issues)

    def test_above_warning_100_no_issue(self):
        level, issues = _evaluate(_metrics(total_mentions=150), "morning")
        assert level == "OK"
        assert issues == []


class TestRedditMentions:
    def test_reddit_zero_morning_warning(self):
        level, issues = _evaluate(_metrics(reddit_mentions=0), "morning")
        assert level == "WARNING"
        assert any("reddit entity_mentions=0" in i and "WARNING" in i for i in issues)

    def test_reddit_zero_evening_critical(self):
        level, issues = _evaluate(_metrics(reddit_mentions=0), "evening")
        assert level == "CRITICAL"
        assert any("reddit entity_mentions=0" in i and "CRITICAL" in i for i in issues)

    def test_reddit_nonzero_no_issue(self):
        level, issues = _evaluate(_metrics(reddit_mentions=50), "evening")
        reddit_issues = [i for i in issues if "reddit entity_mentions" in i]
        assert reddit_issues == []


class TestContentItemsThresholds:
    def test_reddit_items_zero_warning(self):
        level, issues = _evaluate(_metrics(reddit_items=0), "morning")
        assert level == "WARNING"
        assert any("reddit canonical_content_items=0" in i for i in issues)

    def test_youtube_items_low_warning(self):
        level, issues = _evaluate(_metrics(youtube_items=30), "morning")
        assert level == "WARNING"
        assert any("youtube canonical_content_items=30" in i for i in issues)

    def test_total_items_critical_evening(self):
        level, issues = _evaluate(_metrics(total_items=50, reddit_items=0, youtube_items=30), "evening")
        assert level == "CRITICAL"
        assert any("total canonical_content_items=50" in i and "CRITICAL" in i for i in issues)

    def test_total_items_critical_morning_no_trigger(self):
        """Total items CRITICAL threshold only fires for evening."""
        level, issues = _evaluate(_metrics(total_items=50, reddit_items=10, youtube_items=30), "morning")
        total_crit = [i for i in issues if "total canonical_content_items" in i and "CRITICAL" in i]
        assert total_crit == []


class TestSignalsThreshold:
    def test_signals_low_evening_warning(self):
        level, issues = _evaluate(_metrics(signals_today=5), "evening")
        assert any("signals today=5" in i and "WARNING" in i for i in issues)

    def test_signals_low_morning_no_trigger(self):
        """Signal threshold only fires for evening."""
        level, issues = _evaluate(_metrics(signals_today=5), "morning")
        signal_issues = [i for i in issues if "signals today" in i]
        assert signal_issues == []

    def test_signals_above_threshold_no_issue(self):
        level, issues = _evaluate(_metrics(signals_today=50), "evening")
        signal_issues = [i for i in issues if "signals today" in i]
        assert signal_issues == []


# ---------------------------------------------------------------------------
# _resolve_pipeline_service
# ---------------------------------------------------------------------------

class TestResolvePipelineService:
    def test_pipeline_service_env_takes_precedence(self):
        with patch.dict(os.environ, {"PIPELINE_SERVICE": "pipeline-daily", "RAILWAY_SERVICE_NAME": "other"}):
            assert _resolve_pipeline_service() == "pipeline-daily"

    def test_railway_service_name_fallback(self):
        env = {"RAILWAY_SERVICE_NAME": "pipeline-evening"}
        with patch.dict(os.environ, env, clear=False):
            env_no_ps = {k: v for k, v in os.environ.items() if k != "PIPELINE_SERVICE"}
            with patch.dict(os.environ, env_no_ps, clear=True):
                # only RAILWAY_SERVICE_NAME set
                with patch.dict(os.environ, {"RAILWAY_SERVICE_NAME": "pipeline-evening"}):
                    result = _resolve_pipeline_service()
                    assert result == "pipeline-evening"

    def test_no_env_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _resolve_pipeline_service() is None


# ---------------------------------------------------------------------------
# _persist_result unit tests
# ---------------------------------------------------------------------------

class TestPersistResult:
    def _make_engine(self):
        """Return a MagicMock engine whose context manager yields a mock conn."""
        engine = MagicMock()
        conn = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        return engine, conn

    def test_executes_trim_then_upsert(self):
        engine, conn = self._make_engine()
        m = _metrics()

        _persist_result(engine, "2026-05-11", "morning", "OK", m, [], "pipeline-daily")

        assert conn.execute.call_count == 2
        # First call: trim
        first_sql = str(conn.execute.call_args_list[0][0][0])
        assert "DELETE FROM pipeline_health_log" in first_sql
        assert "90 days" in first_sql
        # Second call: upsert
        second_sql = str(conn.execute.call_args_list[1][0][0])
        assert "INSERT INTO pipeline_health_log" in second_sql
        assert "ON CONFLICT" in second_sql

    def test_upsert_params_mapped_correctly(self):
        engine, conn = self._make_engine()
        m = _metrics(
            total_mentions=150,
            reddit_mentions=30,
            youtube_items=100,
            reddit_items=20,
            total_items=120,
            signals_today=50,
        )
        issues = ["WARNING some issue"]

        _persist_result(engine, "2026-05-11", "evening", "WARNING", m, issues, "pipeline-evening")

        upsert_params = conn.execute.call_args_list[1][0][1]
        assert upsert_params["run_date"] == "2026-05-11"
        assert upsert_params["run_label"] == "evening"
        assert upsert_params["overall_level"] == "WARNING"
        assert upsert_params["entity_mentions"] == 150
        assert upsert_params["reddit_mentions"] == 30
        assert upsert_params["youtube_items"] == 100
        assert upsert_params["reddit_items"] == 20
        assert upsert_params["total_items"] == 120
        assert upsert_params["signals_count"] == 50
        assert json.loads(upsert_params["issues"]) == issues
        assert upsert_params["pipeline_service"] == "pipeline-evening"

    def test_null_pipeline_service_allowed(self):
        engine, conn = self._make_engine()
        _persist_result(engine, "2026-05-11", "manual", "OK", _metrics(), [], None)
        upsert_params = conn.execute.call_args_list[1][0][1]
        assert upsert_params["pipeline_service"] is None

    def test_db_error_is_nonfatal(self, caplog):
        engine = MagicMock()
        engine.begin.side_effect = Exception("connection refused")

        with caplog.at_level(logging.WARNING, logger="perfume_trend_sdk.jobs.pipeline_health_check"):
            # Must not raise
            _persist_result(engine, "2026-05-11", "morning", "OK", _metrics(), [])

        assert any("pipeline_health_persist_failed" in r.message for r in caplog.records)

    def test_upsert_issues_empty_list(self):
        engine, conn = self._make_engine()
        _persist_result(engine, "2026-05-11", "morning", "OK", _metrics(), [])
        upsert_params = conn.execute.call_args_list[1][0][1]
        assert json.loads(upsert_params["issues"]) == []


# ---------------------------------------------------------------------------
# run_health_check integration (mocked DB)
# ---------------------------------------------------------------------------

class TestRunHealthCheckLogging:
    def _fake_metrics(self):
        return {
            "total_mentions": 200,
            "reddit_mentions": 0,
            "reddit_items": 0,
            "youtube_items": 120,
            "total_items": 120,
            "signals_today": 80,
        }

    def test_ok_logs_pipeline_health_ok(self, caplog):
        good = {
            "total_mentions": 200,
            "reddit_mentions": 40,
            "reddit_items": 25,
            "youtube_items": 120,
            "total_items": 145,
            "signals_today": 80,
        }
        with patch("perfume_trend_sdk.jobs.pipeline_health_check._fetch_metrics", return_value=good), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._persist_result"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._make_engine"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check.get_database_url", return_value="sqlite://"):
            with caplog.at_level(logging.INFO, logger="perfume_trend_sdk.jobs.pipeline_health_check"):
                level = run_health_check("2026-05-07", "evening")
        assert level == "OK"
        assert any("PIPELINE_HEALTH_OK" in r.message for r in caplog.records)

    def test_reddit_zero_evening_logs_critical(self, caplog):
        with patch("perfume_trend_sdk.jobs.pipeline_health_check._fetch_metrics", return_value=self._fake_metrics()), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._persist_result"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._make_engine"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check.get_database_url", return_value="sqlite://"):
            with caplog.at_level(logging.INFO, logger="perfume_trend_sdk.jobs.pipeline_health_check"):
                level = run_health_check("2026-05-07", "evening")
        assert level == "CRITICAL"
        assert any("PIPELINE_HEALTH_CRITICAL" in r.message for r in caplog.records)

    def test_warning_logs_pipeline_health_warning(self, caplog):
        metrics = {
            "total_mentions": 70,   # < 100, >= 50 → WARNING
            "reddit_mentions": 5,
            "reddit_items": 5,
            "youtube_items": 80,
            "total_items": 85,
            "signals_today": 40,
        }
        with patch("perfume_trend_sdk.jobs.pipeline_health_check._fetch_metrics", return_value=metrics), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._persist_result"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._make_engine"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check.get_database_url", return_value="sqlite://"):
            with caplog.at_level(logging.INFO, logger="perfume_trend_sdk.jobs.pipeline_health_check"):
                level = run_health_check("2026-05-07", "morning")
        assert level == "WARNING"
        assert any("PIPELINE_HEALTH_WARNING" in r.message for r in caplog.records)

    def test_db_error_returns_critical(self, caplog):
        with patch("perfume_trend_sdk.jobs.pipeline_health_check._fetch_metrics", side_effect=Exception("conn refused")), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._persist_result"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._make_engine"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check.get_database_url", return_value="sqlite://"):
            with caplog.at_level(logging.ERROR, logger="perfume_trend_sdk.jobs.pipeline_health_check"):
                level = run_health_check("2026-05-07", "evening")
        assert level == "CRITICAL"

    def test_exit_code_zero(self):
        """main() must exit 0 regardless of health level."""
        good = {
            "total_mentions": 10,  # CRITICAL level
            "reddit_mentions": 0,
            "reddit_items": 0,
            "youtube_items": 10,
            "total_items": 10,
            "signals_today": 0,
        }
        with patch("perfume_trend_sdk.jobs.pipeline_health_check._fetch_metrics", return_value=good), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._persist_result"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._make_engine"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check.get_database_url", return_value="sqlite://"), \
             patch("sys.argv", ["pipeline_health_check", "--date", "2026-05-07", "--run-label", "evening"]):
            with pytest.raises(SystemExit) as exc_info:
                from perfume_trend_sdk.jobs.pipeline_health_check import main
                main()
        assert exc_info.value.code == 0

    def test_persist_called_with_correct_args(self):
        """Verify _persist_result is called after a successful health check."""
        good = {
            "total_mentions": 200,
            "reddit_mentions": 40,
            "reddit_items": 25,
            "youtube_items": 120,
            "total_items": 145,
            "signals_today": 80,
        }
        mock_persist = MagicMock()
        with patch("perfume_trend_sdk.jobs.pipeline_health_check._fetch_metrics", return_value=good), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._persist_result", mock_persist), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._resolve_pipeline_service", return_value="pipeline-daily"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check._make_engine"), \
             patch("perfume_trend_sdk.jobs.pipeline_health_check.get_database_url", return_value="sqlite://"):
            level = run_health_check("2026-05-11", "morning")

        assert level == "OK"
        mock_persist.assert_called_once()
        call_kwargs = mock_persist.call_args
        assert call_kwargs[0][1] == "2026-05-11"   # date
        assert call_kwargs[0][2] == "morning"       # run_label
        assert call_kwargs[0][3] == "OK"            # level
        assert call_kwargs[0][6] == "pipeline-daily"  # pipeline_service
