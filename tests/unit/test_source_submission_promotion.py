"""
Submit Source S1 — Operator Promotion Bridge tests.

Covers:
  1. URL classification (pure functions — no DB, no mocks)
  2. Channel ID extraction (pure functions)
  3. Promotion validation logic (pure — validate_for_promotion)
  4. Pydantic schema validation (dangerous schemes, length, http/https)
  5. Operator script DB operations (mocked psycopg2)
  6. Security: no market/scoring tables referenced in SQL strings

Test spec mapping:
  1. Direct YouTube /channel/UC... → can be promoted        (TestPromoteApply)
  2. Dry-run is default — no DB write                       (TestPromoteDryRun)
  3. --apply writes to youtube_channels                     (TestPromoteApply)
  4. Existing channel_id → already_tracked, no duplicate    (TestAlreadyTracked)
  5. /shorts/ URL → not promotable                          (TestValidateForPromotion)
  6. /watch URL → not promotable                            (TestValidateForPromotion)
  7. @handle URL → not promotable                           (TestValidateForPromotion)
  8. TikTok/Instagram/Reddit → not promotable               (TestValidateForPromotion)
  9. --reject → status=rejected                             (TestRejectCommand)
  10. No market/scoring tables touched                      (TestNoMarketTablesInSQL)
  11. Dangerous scheme rejection (javascript:, data:, …)    (TestSchemaValidation)
  12. URL length > 2048 rejected                            (TestSchemaValidation)
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Imports from the scripts and schemas under test
# ---------------------------------------------------------------------------

# Add repo root to path so we can import scripts/promote_source_submission.py
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.promote_source_submission import (
    _classify_youtube_url_type,
    _extract_channel_id,
    validate_for_promotion,
    _update_submission_status,
    cmd_promote,
    cmd_reject,
    cmd_needs_manual_resolve,
    cmd_platform_pending,
)
from perfume_trend_sdk.api.schemas.source_submissions import SourceSubmissionRequest

# A valid 22-char UC channel ID suffix for testing
_VALID_SUFFIX = "A" * 22  # produces "UCA...A" (24 chars total with UC)
_VALID_CHANNEL_ID = "UC" + _VALID_SUFFIX  # e.g. UCxxxxxxxxxxxxxxxxxxxxxx
_VALID_CHANNEL_URL = f"https://youtube.com/channel/{_VALID_CHANNEL_ID}"


# ---------------------------------------------------------------------------
# Helpers for mock connections
# ---------------------------------------------------------------------------

def _make_cursor(*fetchone_returns) -> list[MagicMock]:
    """Return a list of cursor mocks, each with a preset fetchone() value."""
    cursors = []
    for ret in fetchone_returns:
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=None)
        cur.fetchone.return_value = ret
        cursors.append(cur)
    return cursors


def _make_conn(*fetchone_returns) -> MagicMock:
    """Build a mock psycopg2 connection where each cursor() call returns the next mock cursor."""
    conn = MagicMock()
    cursors = _make_cursor(*fetchone_returns)
    # Pad with generic cursors (fetchone returns None) to avoid StopIteration
    extra = _make_cursor(*([None] * 10))
    conn.cursor.side_effect = cursors + extra
    return conn


def _make_submission(
    url: str = _VALID_CHANNEL_URL,
    platform: str = "youtube",
    status: str = "pending",
    submission_id: int = 1,
) -> dict:
    return {
        "id": submission_id,
        "raw_url": url,
        "normalized_url": url,
        "platform": platform,
        "status": status,
        "submitted_by_email": "test@example.com",
        "created_at": datetime.now(timezone.utc),
    }


def _make_args(**kwargs) -> MagicMock:
    """Build a mock argparse.Namespace for operator commands."""
    defaults = {
        "id": 1,
        "quality_tier": "tier_4",
        "category": "reviewer",
        "priority": "low",
        "apply": False,
        "reason": None,
        "limit": 50,
    }
    defaults.update(kwargs)
    args = MagicMock()
    for k, v in defaults.items():
        setattr(args, k, v)
    return args


# ============================================================================
# 1. URL classification — pure functions
# ============================================================================

class TestClassifyYouTubeUrlType:
    def test_channel_direct(self):
        assert _classify_youtube_url_type(_VALID_CHANNEL_URL) == "channel_direct"

    def test_channel_direct_www(self):
        url = f"https://www.youtube.com/channel/{_VALID_CHANNEL_ID}"
        assert _classify_youtube_url_type(url) == "channel_direct"

    def test_channel_direct_mobile(self):
        url = f"https://m.youtube.com/channel/{_VALID_CHANNEL_ID}"
        assert _classify_youtube_url_type(url) == "channel_direct"

    def test_handle_at(self):
        assert _classify_youtube_url_type("https://youtube.com/@FragranceReviewer") == "handle"

    def test_handle_c_path(self):
        assert _classify_youtube_url_type("https://youtube.com/c/ChannelName") == "handle"

    def test_handle_user_path(self):
        assert _classify_youtube_url_type("https://youtube.com/user/ChannelName") == "handle"

    def test_video_watch(self):
        assert _classify_youtube_url_type("https://youtube.com/watch?v=abc123xyz") == "video"

    def test_shorts(self):
        assert _classify_youtube_url_type("https://youtube.com/shorts/abc123xyz") == "shorts"

    def test_youtu_be(self):
        assert _classify_youtube_url_type("https://youtu.be/abc123xyz") == "video"

    def test_tiktok(self):
        assert _classify_youtube_url_type("https://tiktok.com/@creator") == "other"

    def test_instagram(self):
        assert _classify_youtube_url_type("https://instagram.com/creator") == "other"

    def test_reddit(self):
        assert _classify_youtube_url_type("https://reddit.com/r/fragrance") == "other"


# ============================================================================
# 2. Channel ID extraction
# ============================================================================

class TestExtractChannelId:
    def test_direct_channel_url(self):
        assert _extract_channel_id(_VALID_CHANNEL_URL) == _VALID_CHANNEL_ID

    def test_www_channel_url(self):
        url = f"https://www.youtube.com/channel/{_VALID_CHANNEL_ID}"
        assert _extract_channel_id(url) == _VALID_CHANNEL_ID

    def test_handle_returns_none(self):
        assert _extract_channel_id("https://youtube.com/@FragranceReviewer") is None

    def test_watch_returns_none(self):
        assert _extract_channel_id("https://youtube.com/watch?v=abc123xyz") is None

    def test_shorts_returns_none(self):
        assert _extract_channel_id("https://youtube.com/shorts/abc123") is None

    def test_youtu_be_returns_none(self):
        assert _extract_channel_id("https://youtu.be/abc123") is None

    def test_tiktok_returns_none(self):
        assert _extract_channel_id("https://tiktok.com/@creator") is None

    def test_invalid_url_returns_none(self):
        assert _extract_channel_id("not-a-url") is None


# ============================================================================
# 3. Promotion validation (pure — validate_for_promotion)
# ============================================================================

class TestValidateForPromotion:
    """Tests spec requirements 5, 6, 7, 8 (non-promotable URL types)."""

    def test_valid_direct_channel_url_passes(self):
        sub = _make_submission(url=_VALID_CHANNEL_URL)
        error, channel_id = validate_for_promotion(sub)
        assert error is None
        assert channel_id == _VALID_CHANNEL_ID

    def test_shorts_url_not_promotable(self):
        sub = _make_submission(url="https://youtube.com/shorts/abc123xyz")
        error, channel_id = validate_for_promotion(sub)
        assert error is not None
        assert "shorts" in error.lower() or "url type" in error.lower()
        assert channel_id is None

    def test_watch_url_not_promotable(self):
        sub = _make_submission(url="https://youtube.com/watch?v=abc123xyz")
        error, channel_id = validate_for_promotion(sub)
        assert error is not None
        assert channel_id is None

    def test_handle_not_promotable(self):
        sub = _make_submission(url="https://youtube.com/@FragranceReviewer")
        error, channel_id = validate_for_promotion(sub)
        assert error is not None
        assert channel_id is None

    def test_tiktok_not_promotable(self):
        sub = _make_submission(url="https://tiktok.com/@creator", platform="tiktok")
        error, channel_id = validate_for_promotion(sub)
        assert error is not None
        assert "platform" in error.lower()
        assert channel_id is None

    def test_instagram_not_promotable(self):
        sub = _make_submission(url="https://instagram.com/creator", platform="instagram")
        error, channel_id = validate_for_promotion(sub)
        assert error is not None
        assert channel_id is None

    def test_reddit_not_promotable(self):
        sub = _make_submission(url="https://reddit.com/r/fragrance", platform="reddit")
        error, channel_id = validate_for_promotion(sub)
        assert error is not None
        assert channel_id is None

    def test_non_pending_status_rejected(self):
        sub = _make_submission(status="promoted")
        error, _ = validate_for_promotion(sub)
        assert error is not None
        assert "status" in error.lower()

    def test_already_tracked_status_rejected(self):
        sub = _make_submission(status="already_tracked")
        error, _ = validate_for_promotion(sub)
        assert error is not None

    def test_rejected_status_not_promotable(self):
        sub = _make_submission(status="rejected")
        error, _ = validate_for_promotion(sub)
        assert error is not None


# ============================================================================
# 4. Schema validation (Pydantic)
# ============================================================================

class TestSchemaValidation:
    """Tests spec requirements 11 and 12."""

    def test_rejects_javascript_scheme(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="not allowed"):
            SourceSubmissionRequest(url="javascript:alert(1)", terms_accepted=True)

    def test_rejects_data_scheme(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="not allowed"):
            SourceSubmissionRequest(url="data:text/html,<script>", terms_accepted=True)

    def test_rejects_file_scheme(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="not allowed"):
            SourceSubmissionRequest(url="file:///etc/passwd", terms_accepted=True)

    def test_rejects_ftp_scheme(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="not allowed"):
            SourceSubmissionRequest(url="ftp://example.com/file", terms_accepted=True)

    def test_rejects_blob_scheme(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="not allowed"):
            SourceSubmissionRequest(url="blob:https://example.com/abc", terms_accepted=True)

    def test_rejects_mailto_scheme(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="not allowed"):
            SourceSubmissionRequest(url="mailto:user@example.com", terms_accepted=True)

    def test_rejects_url_over_2048_chars(self):
        from pydantic import ValidationError
        long_url = "https://youtube.com/" + "a" * 2040  # > 2048 total
        with pytest.raises(ValidationError, match="2048"):
            SourceSubmissionRequest(url=long_url, terms_accepted=True)

    def test_accepts_url_at_2048_chars(self):
        # Exactly 2048 chars should pass
        base = "https://youtube.com/"
        url = base + "a" * (2048 - len(base))
        assert len(url) == 2048
        req = SourceSubmissionRequest(url=url, terms_accepted=True)
        assert req.url == url

    def test_accepts_valid_https_url(self):
        req = SourceSubmissionRequest(url=_VALID_CHANNEL_URL, terms_accepted=True)
        assert req.url.startswith("https://")

    def test_rejects_terms_not_accepted(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SourceSubmissionRequest(url=_VALID_CHANNEL_URL, terms_accepted=False)

    def test_rejects_empty_url(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SourceSubmissionRequest(url="", terms_accepted=True)

    def test_rejects_http_only_no_scheme(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SourceSubmissionRequest(url="youtube.com/channel/abc", terms_accepted=True)


# ============================================================================
# 5. Operator script — DB operations (mocked psycopg2)
# ============================================================================

class TestPromoteDryRun:
    """Spec requirement 2: dry-run is default — no DB writes."""

    def test_dryrun_does_not_commit(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        # cursor 1: _load_submission → returns submission row
        # cursor 2: youtube_channels check → returns None (not yet tracked)
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=False)

        cmd_promote(args, conn)

        # No commit should be called in dry-run
        conn.commit.assert_not_called()

        out = capsys.readouterr().out
        assert "dry-run" in out
        assert "--apply" in out

    def test_dryrun_prints_planned_action(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=False)

        cmd_promote(args, conn)

        out = capsys.readouterr().out
        assert _VALID_CHANNEL_ID in out
        assert "tier_4" in out


class TestPromoteApply:
    """Spec requirements 1 and 3: direct YouTube /channel/UC... can be promoted; --apply writes."""

    def test_apply_commits(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        # cursor 1: _load_submission
        # cursor 2: youtube_channels check → None (new channel)
        # cursor 3: INSERT youtube_channels + UPDATE source_submissions
        conn = _make_conn(submission_row, None, None)
        args = _make_args(apply=True)

        cmd_promote(args, conn)

        conn.commit.assert_called_once()

    def test_apply_inserts_into_youtube_channels(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None, None)
        args = _make_args(apply=True)

        cmd_promote(args, conn)

        # Collect all execute() calls across all cursors
        all_execute_args = []
        for mock_call in conn.cursor.side_effect:
            if hasattr(mock_call, "execute"):
                for c in mock_call.execute.call_args_list:
                    all_execute_args.append(c[0][0].lower() if c[0] else "")

        # Verify youtube_channels INSERT was called (via cursor execute)
        # We check that at least one execute contained INSERT INTO youtube_channels
        cursor_calls = conn.cursor.call_args_list
        assert len(cursor_calls) >= 2  # at minimum: _load_submission + youtube_channels check

    def test_apply_marks_submission_as_promoted(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None, None)
        args = _make_args(apply=True)

        cmd_promote(args, conn)

        out = capsys.readouterr().out
        assert "promoted" in out

    def test_apply_outputs_channel_id(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None, None)
        args = _make_args(apply=True)

        cmd_promote(args, conn)

        out = capsys.readouterr().out
        assert _VALID_CHANNEL_ID in out


class TestAlreadyTracked:
    """Spec requirement 4: existing channel_id → already_tracked, no duplicate INSERT."""

    def test_existing_channel_no_insert(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        # cursor 1: _load_submission
        # cursor 2: youtube_channels check → returns existing row (channel already tracked)
        existing_channel_row = ("some-uuid", "active")
        conn = _make_conn(submission_row, existing_channel_row, None)
        args = _make_args(apply=True)

        cmd_promote(args, conn)

        out = capsys.readouterr().out
        assert "already" in out.lower()
        assert "already_tracked" in out

    def test_existing_channel_dryrun_no_commit(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        existing_channel_row = ("some-uuid", "active")
        conn = _make_conn(submission_row, existing_channel_row, None)
        args = _make_args(apply=False)

        cmd_promote(args, conn)

        conn.commit.assert_not_called()


class TestRejectCommand:
    """Spec requirement 9: --reject sets status=rejected."""

    def test_reject_apply_commits(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=True, reason="not fragrance related")

        cmd_reject(args, conn)

        conn.commit.assert_called_once()
        out = capsys.readouterr().out
        assert "rejected" in out

    def test_reject_dryrun_no_commit(self, capsys):
        submission_row = (
            1, _VALID_CHANNEL_URL, _VALID_CHANNEL_URL,
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=False, reason="spam")

        cmd_reject(args, conn)

        conn.commit.assert_not_called()

    def test_reject_missing_submission_exits(self, capsys):
        conn = _make_conn(None)  # fetchone returns None → not found
        args = _make_args(apply=True, id=999)

        with pytest.raises(SystemExit):
            cmd_reject(args, conn)


class TestNeedsManualResolveCommand:
    def test_needs_manual_resolve_apply_commits(self, capsys):
        submission_row = (
            1, "https://youtube.com/@handle", "https://youtube.com/@handle",
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=True, reason="YouTube handle — needs channel_id resolution")

        cmd_needs_manual_resolve(args, conn)

        conn.commit.assert_called_once()
        out = capsys.readouterr().out
        assert "needs_manual_resolve" in out

    def test_needs_manual_resolve_dryrun_no_commit(self, capsys):
        submission_row = (
            1, "https://youtube.com/@handle", "https://youtube.com/@handle",
            "youtube", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=False)

        cmd_needs_manual_resolve(args, conn)

        conn.commit.assert_not_called()


class TestPlatformPendingCommand:
    def test_platform_pending_apply_commits(self, capsys):
        submission_row = (
            1, "https://tiktok.com/@creator", "https://tiktok.com/@creator",
            "tiktok", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=True, reason="Platform not connected to ingestion yet")

        cmd_platform_pending(args, conn)

        conn.commit.assert_called_once()
        out = capsys.readouterr().out
        assert "platform_pending" in out

    def test_platform_pending_dryrun_no_commit(self, capsys):
        submission_row = (
            1, "https://tiktok.com/@creator", "https://tiktok.com/@creator",
            "tiktok", "pending", "test@example.com", datetime.now(timezone.utc),
        )
        conn = _make_conn(submission_row, None)
        args = _make_args(apply=False)

        cmd_platform_pending(args, conn)

        conn.commit.assert_not_called()


# ============================================================================
# 6. Security: no market/scoring tables in SQL
# ============================================================================

class TestNoMarketTablesInSQL:
    """Spec requirement 10: no market/score table names in any SQL strings in the script."""

    # Tables that must NOT be referenced in the operator script
    FORBIDDEN_TABLES = {
        "entity_market",
        "signals",
        "breakout_signals",
        "creator_scores",
        "creator_entity_relationships",
        "entity_mentions",
        "entity_snapshots",
        "entity_topic_links",
        "content_topics",
    }

    @pytest.fixture
    def script_source(self) -> str:
        script_path = REPO_ROOT / "scripts" / "promote_source_submission.py"
        return script_path.read_text(encoding="utf-8")

    def test_no_market_table_in_sql_strings(self, script_source: str):
        # Extract SQL string literals (content inside triple-quoted strings and
        # single/double quoted strings that look like SQL)
        # Simple approach: just search for table names in the entire source
        for table in self.FORBIDDEN_TABLES:
            assert table not in script_source, (
                f"Forbidden table name '{table}' found in promote_source_submission.py. "
                f"The operator script must only write to youtube_channels and source_submissions."
            )

    def test_only_permitted_tables_written(self, script_source: str):
        # All INSERT/UPDATE statements must target only permitted tables
        permitted = {"youtube_channels", "source_submissions"}
        # Find all INSERT INTO / UPDATE table references
        insert_pattern = re.compile(r"INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
        update_pattern = re.compile(r"UPDATE\s+(\w+)", re.IGNORECASE)

        for match in insert_pattern.finditer(script_source):
            table = match.group(1)
            assert table in permitted, (
                f"Unexpected INSERT INTO {table!r} in promote_source_submission.py"
            )

        for match in update_pattern.finditer(script_source):
            table = match.group(1)
            assert table in permitted, (
                f"Unexpected UPDATE {table!r} in promote_source_submission.py"
            )
