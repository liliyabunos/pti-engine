"""SC1.2C — TikTok seeded creator monitoring worker unit tests.

Covers:
  - Kill switch: TIKTOK_PUBLIC_MONITORING_ENABLED=false exits safely
  - Active creator is processed (mocked HTTP)
  - pending/paused/rejected/error creators skipped in normal run
  - last_checked_at skip (within 24h) works
  - --force bypasses last_checked_at
  - Fetch failure logs error and continues; does not raise
  - Dry-run: fetch happens but DB writes skipped
  - Audit log written on successful profile check
  - No entity_mentions created by worker
  - Page parser: valid userInfo extracts follower_count correctly
  - Page parser: statusCode != 0 → not reachable
  - Page parser: missing UNIVERSAL_DATA → error captured
  - Page parser: empty itemList → video_list_requires_auth=True
  - Page parser: itemList with items → video_ids populated (future-proof)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from perfume_trend_sdk.ingest.tiktok_page_parser import (
    TikTokProfileResult,
    parse_profile_page,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE creator_platform_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                platform_handle TEXT NOT NULL,
                platform_url TEXT,
                display_name TEXT,
                creator_id TEXT,
                category TEXT,
                tier TEXT,
                status TEXT NOT NULL DEFAULT 'pending_review',
                seed_source TEXT,
                source_method TEXT NOT NULL DEFAULT 'manual_seed',
                confidence REAL,
                follower_count INTEGER,
                avg_views REAL,
                last_checked_at TEXT,
                last_new_content_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(platform, platform_handle)
            )
        """))
        conn.execute(text("""
            CREATE TABLE creator_watchlist_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                platform_handle TEXT NOT NULL,
                action TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT,
                source_method TEXT,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        # Explicit: no entity_mentions table — confirms worker never touches it
        conn.commit()
    sess = Session(engine)
    yield sess
    sess.close()


def _insert_creator(db, handle: str, status: str = "active",
                    last_checked_at: str = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    result = db.execute(text("""
        INSERT INTO creator_platform_accounts
            (platform, platform_handle, status, last_checked_at, created_at, updated_at, source_method)
        VALUES ('tiktok', :h, :s, :lc, :now, :now, 'manual_seed')
    """), {"h": handle, "s": status, "lc": last_checked_at, "now": now})
    db.commit()
    return db.execute(text("SELECT last_insert_rowid()")).scalar()


def _audit_entries(db, handle: str) -> list[dict]:
    rows = db.execute(
        text("SELECT * FROM creator_watchlist_audit_log WHERE platform_handle=:h ORDER BY id"),
        {"h": handle},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def _make_tiktok_html(handle: str, status_code: int = 0,
                      follower_count: int = 50000, video_count: int = 100,
                      item_list: list = None) -> str:
    """Build a minimal TikTok profile page HTML for testing."""
    user_detail = {
        "statusCode": status_code,
        "statusMsg": "",
        "needFix": False,
    }
    if status_code == 0:
        user_detail["userInfo"] = {
            "user": {
                "id": "1234567890",
                "uniqueId": handle,
                "nickname": f"{handle} display",
                "secUid": f"sec_{handle}",
                "verified": False,
            },
            "stats": {
                "followerCount": follower_count,
                "followingCount": 100,
                "videoCount": video_count,
                "heartCount": 1000000,
            },
            "statsV2": {},
            "itemList": item_list or [],
        }

    data = {
        "__DEFAULT_SCOPE__": {
            "webapp.user-detail": user_detail,
            "webapp.biz-context": {"navList": []},
        }
    }
    script_content = json.dumps(data)
    return f'<html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{script_content}</script></body></html>'


# ---------------------------------------------------------------------------
# TikTokPageParser tests
# ---------------------------------------------------------------------------

class TestTikTokPageParser:
    def test_valid_profile_is_reachable(self):
        html = _make_tiktok_html("rawscents", follower_count=8000, video_count=50)
        result = parse_profile_page("rawscents", html)
        assert result.reachable is True
        assert result.follower_count == 8000
        assert result.video_count == 50
        assert result.status_code == 0

    def test_empty_item_list_sets_requires_auth(self):
        html = _make_tiktok_html("rawscents")
        result = parse_profile_page("rawscents", html)
        assert result.video_list_requires_auth is True
        assert result.video_ids == []

    def test_item_list_with_videos_captured(self):
        """Future-proofing: if TikTok ever returns videos in SSR, we capture them."""
        items = [{"id": "7111111111111111111"}, {"id": "7222222222222222222"}]
        html = _make_tiktok_html("rawscents", item_list=items)
        result = parse_profile_page("rawscents", html)
        assert result.reachable is True
        assert result.video_list_requires_auth is False
        assert "7111111111111111111" in result.video_ids
        assert "7222222222222222222" in result.video_ids

    def test_user_not_found_status(self):
        html = _make_tiktok_html("nonexistent", status_code=10221)
        result = parse_profile_page("nonexistent", html)
        assert result.reachable is False
        assert result.status_code == 10221
        assert result.error is not None

    def test_unknown_status_code_not_reachable(self):
        html = _make_tiktok_html("creator", status_code=99999)
        result = parse_profile_page("creator", html)
        assert result.reachable is False

    def test_missing_script_tag_returns_error(self):
        result = parse_profile_page("creator", "<html><body>no data here</body></html>")
        assert result.reachable is False
        assert result.error is not None

    def test_empty_html_returns_error(self):
        result = parse_profile_page("creator", "")
        assert result.reachable is False
        assert "empty" in result.error

    def test_malformed_json_returns_error(self):
        html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{bad json}</script>'
        result = parse_profile_page("creator", html)
        assert result.reachable is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# Kill switch tests
# ---------------------------------------------------------------------------

class TestKillSwitch:
    def test_disabled_by_default_exits_safely(self):
        """TIKTOK_PUBLIC_MONITORING_ENABLED not set → disabled."""
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run
        env = {k: v for k, v in os.environ.items()
               if k != "TIKTOK_PUBLIC_MONITORING_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            result = run(limit=10, force=False, handle=None, dry_run=False, sleep_seconds=0)
        assert result.get("disabled") is True

    def test_explicitly_false_exits_safely(self):
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run
        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "false"}):
            result = run(limit=10, force=False, handle=None, dry_run=False, sleep_seconds=0)
        assert result.get("disabled") is True

    def test_true_proceeds(self, db):
        """With kill switch enabled, worker proceeds (mocked HTTP)."""
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run

        html = _make_tiktok_html("testcreator", follower_count=1000)

        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "true"}), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.get_database_url", return_value="sqlite:///:memory:"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._make_engine", return_value=db.get_bind()), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.Session", return_value=db), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._fetch_profile_page", return_value=(200, html)):
            result = run(limit=5, force=False, handle=None, dry_run=False, sleep_seconds=0)

        assert result.get("disabled") is None


# ---------------------------------------------------------------------------
# Creator filtering tests
# ---------------------------------------------------------------------------

class TestCreatorFiltering:
    def _run_with_db(self, db, handle=None, force=False, dry_run=False, html=None):
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run, _load_active_creators, _process_creator

        if html is None:
            html = _make_tiktok_html(handle or "testcreator", follower_count=5000)

        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "true"}), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.get_database_url", return_value="x"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._make_engine"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.Session") as MockSession, \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._fetch_profile_page", return_value=(200, html)), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.time.sleep"):

            ctx = MagicMock()
            ctx.__enter__ = lambda s: db
            ctx.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = ctx

            return run(limit=25, force=force, handle=handle, dry_run=dry_run, sleep_seconds=0)

    def test_active_creator_is_processed(self, db):
        _insert_creator(db, "active_c", status="active")
        result = self._run_with_db(db, html=_make_tiktok_html("active_c"))
        assert result["creators_checked"] >= 1

    def test_pending_creator_skipped_in_normal_run(self, db):
        _insert_creator(db, "pending_c", status="pending_review")
        result = self._run_with_db(db)
        # No active creators — none checked
        assert result["creators_checked"] == 0

    def test_paused_creator_skipped(self, db):
        _insert_creator(db, "paused_c", status="paused")
        result = self._run_with_db(db)
        assert result["creators_checked"] == 0

    def test_rejected_creator_skipped(self, db):
        _insert_creator(db, "rejected_c", status="rejected")
        result = self._run_with_db(db)
        assert result["creators_checked"] == 0

    def test_last_checked_within_24h_skipped(self, db):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _insert_creator(db, "recent_c", status="active", last_checked_at=recent)
        result = self._run_with_db(db)
        assert result["creators_skipped"] >= 1
        assert result["creators_checked"] == 0

    def test_force_bypasses_24h_skip(self, db):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _insert_creator(db, "recent_forced", status="active", last_checked_at=recent)
        result = self._run_with_db(db, force=True, handle="recent_forced",
                                   html=_make_tiktok_html("recent_forced"))
        assert result["creators_checked"] >= 1

    def test_old_last_checked_is_not_skipped(self, db):
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        _insert_creator(db, "old_c", status="active", last_checked_at=old)
        result = self._run_with_db(db, html=_make_tiktok_html("old_c"))
        assert result["creators_checked"] >= 1


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_fetch_failure_does_not_crash_run(self, db):
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run

        _insert_creator(db, "crashy_c", status="active")

        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "true"}), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.get_database_url", return_value="x"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._make_engine"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.Session") as MockSession, \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._fetch_profile_page",
                   side_effect=Exception("connection timeout")), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.time.sleep"):

            ctx = MagicMock()
            ctx.__enter__ = lambda s: db
            ctx.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = ctx

            # Must not raise
            result = run(limit=5, force=True, handle="crashy_c", dry_run=False, sleep_seconds=0)

        assert result["errors"] == 1
        assert result["creators_checked"] == 0

    def test_unreachable_profile_counted_as_error(self, db):
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run

        _insert_creator(db, "gone_c", status="active")
        html = _make_tiktok_html("gone_c", status_code=10221)

        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "true"}), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.get_database_url", return_value="x"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._make_engine"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.Session") as MockSession, \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._fetch_profile_page", return_value=(200, html)), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.time.sleep"):

            ctx = MagicMock()
            ctx.__enter__ = lambda s: db
            ctx.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = ctx

            result = run(limit=5, force=True, handle="gone_c", dry_run=False, sleep_seconds=0)

        assert result["errors"] == 1


# ---------------------------------------------------------------------------
# Dry-run test
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_does_not_write_to_db(self, db):
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run

        _insert_creator(db, "dryrun_c", status="active")
        html = _make_tiktok_html("dryrun_c", follower_count=12345)

        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "true"}), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.get_database_url", return_value="x"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._make_engine"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.Session") as MockSession, \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._fetch_profile_page", return_value=(200, html)), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.time.sleep"):

            ctx = MagicMock()
            ctx.__enter__ = lambda s: db
            ctx.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = ctx

            result = run(limit=5, force=True, handle="dryrun_c", dry_run=True, sleep_seconds=0)

        assert result["creators_checked"] == 1
        # DB follower_count was NOT updated (still None)
        row = db.execute(
            text("SELECT follower_count, last_checked_at FROM creator_platform_accounts WHERE platform_handle='dryrun_c'")
        ).fetchone()
        assert row[0] is None   # follower_count not written
        # Audit log not written in dry_run
        audit = _audit_entries(db, "dryrun_c")
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# Audit log test
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_audit_written_on_successful_check(self, db):
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run

        _insert_creator(db, "audit_c", status="active")
        html = _make_tiktok_html("audit_c", follower_count=99)

        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "true"}), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.get_database_url", return_value="x"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._make_engine"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.Session") as MockSession, \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._fetch_profile_page", return_value=(200, html)), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.time.sleep"):

            ctx = MagicMock()
            ctx.__enter__ = lambda s: db
            ctx.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = ctx

            run(limit=5, force=True, handle="audit_c", dry_run=False, sleep_seconds=0)

        audit = _audit_entries(db, "audit_c")
        assert len(audit) >= 1
        assert any(e["action"] == "monitor_profile_check" for e in audit)
        check_entry = next(e for e in audit if e["action"] == "monitor_profile_check")
        assert check_entry["source_method"] == "public_creator_monitoring"
        assert "followers=99" in (check_entry["note"] or "")


# ---------------------------------------------------------------------------
# No entity_mentions regression test
# ---------------------------------------------------------------------------

class TestNoEntityMentions:
    def test_worker_has_no_entity_mentions_table(self, db):
        """The SQLite fixture has no entity_mentions table.
        If the worker ever tries to write to it, the test will fail."""
        import os
        from perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators import run

        _insert_creator(db, "em_test_c", status="active")
        html = _make_tiktok_html("em_test_c")

        with patch.dict(os.environ, {"TIKTOK_PUBLIC_MONITORING_ENABLED": "true"}), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.get_database_url", return_value="x"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._make_engine"), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.Session") as MockSession, \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators._fetch_profile_page", return_value=(200, html)), \
             patch("perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators.time.sleep"):

            ctx = MagicMock()
            ctx.__enter__ = lambda s: db
            ctx.__exit__ = MagicMock(return_value=False)
            MockSession.return_value = ctx

            # This will raise if worker touches entity_mentions (table doesn't exist)
            result = run(limit=5, force=True, handle="em_test_c", dry_run=False, sleep_seconds=0)

        # Passed without exception → no entity_mentions touched
        assert result["creators_checked"] == 1

    def test_worker_does_not_import_entity_mentions(self):
        """Worker module must not reference entity_mentions in its SQL."""
        import inspect
        from perfume_trend_sdk.jobs import monitor_tiktok_seeded_creators as mod
        source = inspect.getsource(mod)
        assert "entity_mentions" not in source, (
            "monitor_tiktok_seeded_creators must NOT write to entity_mentions directly"
        )
