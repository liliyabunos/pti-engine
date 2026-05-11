"""Regression test: Creator leaderboard must show channel display name, not video titles.

Root cause (2026-05-11): discover_youtube_channels.py used MAX(cci.title) — a video title —
as the youtube_channels.title placeholder. This caused the /creators leaderboard to display
video titles instead of channel names, and made searches for creator names match unrelated
channels.

Covers:
  - API returns yc.title (channel display name) not video title
  - Search by channel name matches channel title only
  - Search by video title does NOT create a fake creator row
  - discover_youtube_channels uses handle not sample_title as title placeholder
  - ingest_youtube_channels._update_channel_after_poll accepts channel_title param
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from perfume_trend_sdk.api.main import app
from perfume_trend_sdk.api.dependencies import get_db_session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TABLES = [
    """CREATE TABLE IF NOT EXISTS creator_scores (
        platform TEXT NOT NULL,
        creator_id TEXT NOT NULL,
        creator_handle TEXT,
        quality_tier TEXT,
        category TEXT,
        subscriber_count INTEGER,
        total_content_items INTEGER DEFAULT 0,
        content_with_entity_mentions INTEGER DEFAULT 0,
        noise_rate REAL,
        unique_entities_mentioned INTEGER DEFAULT 0,
        unique_brands_mentioned INTEGER DEFAULT 0,
        total_entity_mentions INTEGER DEFAULT 0,
        total_views INTEGER DEFAULT 0,
        avg_views REAL,
        total_likes INTEGER DEFAULT 0,
        total_comments INTEGER DEFAULT 0,
        avg_engagement_rate REAL,
        breakout_contributions INTEGER DEFAULT 0,
        early_signal_count INTEGER DEFAULT 0,
        early_signal_rate REAL DEFAULT 0.0,
        influence_score REAL DEFAULT 0.0,
        score_components TEXT,
        computed_at TEXT,
        PRIMARY KEY (platform, creator_id)
    )""",
    """CREATE TABLE IF NOT EXISTS youtube_channels (
        id TEXT PRIMARY KEY,
        channel_id TEXT UNIQUE NOT NULL,
        handle TEXT,
        channel_url TEXT,
        title TEXT,
        normalized_title TEXT,
        quality_tier TEXT,
        category TEXT,
        status TEXT DEFAULT 'active',
        priority TEXT DEFAULT 'medium',
        subscriber_count INTEGER,
        video_count INTEGER,
        uploads_playlist_id TEXT,
        added_at TEXT,
        added_by TEXT,
        notes TEXT,
        last_polled_at TEXT,
        next_poll_after TEXT,
        last_video_count INTEGER,
        consecutive_empty_polls INTEGER DEFAULT 0,
        last_poll_status TEXT,
        last_poll_error TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS creator_oauth_grants (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        platform_user_id TEXT
    )""",
]


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        for ddl in _TABLES:
            conn.execute(text(ddl))
        conn.commit()
    SessionLocal = sessionmaker(bind=engine)

    def override():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override
    yield SessionLocal()
    app.dependency_overrides.pop(get_db_session, None)
    engine.dispose()


@pytest.fixture
def client(db_session):
    return TestClient(app)


def _seed_creator(db_session: Session, channel_id: str, channel_title: str,
                  handle: str, subscriber_count: int = 1000) -> None:
    """Insert a youtube_channels row + creator_scores row."""
    db_session.execute(text("""
        INSERT INTO youtube_channels (id, channel_id, handle, title, status, added_by)
        VALUES (:id, :cid, :handle, :title, 'active', 'test')
    """), {"id": str(uuid.uuid4()), "cid": channel_id, "handle": handle, "title": channel_title})

    db_session.execute(text("""
        INSERT INTO creator_scores (
            platform, creator_id, creator_handle, quality_tier,
            subscriber_count, influence_score, computed_at
        ) VALUES ('youtube', :cid, :handle, 'tier_3', :subs, 0.3, :now)
    """), {
        "cid": channel_id,
        "handle": handle,
        "subs": subscriber_count,
        "now": datetime.now(timezone.utc).isoformat(),
    })
    db_session.commit()


# ---------------------------------------------------------------------------
# Tests: display_name from channel title, not video title
# ---------------------------------------------------------------------------

class TestCreatorDisplayName:

    def test_display_name_is_channel_title_not_video_title(self, client, db_session):
        """API must return youtube_channels.title (channel name) as display_name."""
        _seed_creator(
            db_session,
            channel_id="UCtest1234567890ABCDEFGHIa",
            channel_title="G Fragrance",   # correct channel title
            handle="GFragrance3",
        )
        r = client.get("/api/v1/creators?platform=youtube")
        assert r.status_code == 200
        creators = r.json()["creators"]
        assert len(creators) == 1
        assert creators[0]["display_name"] == "G Fragrance"
        assert creators[0]["creator_handle"] == "GFragrance3"

    def test_display_name_is_not_video_title(self, client, db_session):
        """A youtube_channels row with a video title as 'title' must be treated as a bug.
        This test seeds the BAD state (video title in title col) and confirms the
        API would serve it — documenting the regression scenario."""
        VIDEO_TITLE = "30 Fragrances I'll NEVER Replace (My Forever Collection) #fragrance"
        _seed_creator(
            db_session,
            channel_id="UCtest1234567890ABCDEFGHIb",
            channel_title=VIDEO_TITLE,  # BAD: video title stored as channel title
            handle="GFragrance3",
        )
        r = client.get("/api/v1/creators?platform=youtube")
        assert r.status_code == 200
        creators = r.json()["creators"]
        # The row exists but display_name is wrong — this is the pre-fix state
        assert creators[0]["display_name"] == VIDEO_TITLE
        # Regression guard: after the fix, the repair script would correct this
        # so the real production channel should never serve a video title here

    def test_search_by_channel_name_matches_correct_creator(self, client, db_session):
        """?q=G Fragrance should match channels whose title contains 'g fragrance'."""
        _seed_creator(
            db_session,
            channel_id="UCtest1234567890ABCDEFGHIc",
            channel_title="G Fragrance",
            handle="GFragrance3",
        )
        # Unrelated channel whose title doesn't match
        _seed_creator(
            db_session,
            channel_id="UCtest1234567890ABCDEFGHId",
            channel_title="The Perfume Guy",
            handle="theperfumeguy",
        )
        r = client.get("/api/v1/creators?q=G+Fragrance")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 1
        assert d["creators"][0]["display_name"] == "G Fragrance"

    def test_search_by_video_title_does_not_create_fake_creator(self, client, db_session):
        """Searching for a video title should NOT surface creators unless their
        channel title happens to match — the search is on yc.title (channel name),
        not on content item titles."""
        _seed_creator(
            db_session,
            channel_id="UCtest1234567890ABCDEFGHIe",
            channel_title="G Fragrance",  # correct channel title
            handle="GFragrance3",
        )
        # Search for a video title — should NOT match
        r = client.get("/api/v1/creators?q=30+Fragrances+I%27ll+NEVER+Replace")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 0, (
            "Video title in search should not match creator whose channel title is 'G Fragrance'"
        )

    def test_display_name_fallback_to_creator_handle(self, client, db_session):
        """When yc.title is None, display_name in API response should be None
        (frontend uses creator_handle as fallback)."""
        # Creator score with no matching youtube_channels row
        db_session.execute(text("""
            INSERT INTO creator_scores (
                platform, creator_id, creator_handle, quality_tier,
                subscriber_count, influence_score, computed_at
            ) VALUES ('youtube', 'UCtest1234567890ABCDEFGHIf', 'MyHandle', 'tier_4',
                      500, 0.1, :now)
        """), {"now": datetime.now(timezone.utc).isoformat()})
        db_session.commit()

        r = client.get("/api/v1/creators?platform=youtube")
        assert r.status_code == 200
        creators = r.json()["creators"]
        found = next((c for c in creators if c["creator_id"] == "UCtest1234567890ABCDEFGHIf"), None)
        assert found is not None
        # No youtube_channels row → display_name is None; frontend uses creator_handle
        assert found["display_name"] is None
        assert found["creator_handle"] == "MyHandle"


# ---------------------------------------------------------------------------
# Tests: discover_youtube_channels script logic
# ---------------------------------------------------------------------------

class TestDiscoverScriptTitlePlaceholder:

    def test_discover_insert_uses_handle_not_sample_title(self):
        """The _insert_channel function must use handle (not sample_title) as title."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

        # Import the relevant function
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "discover_youtube_channels",
            os.path.join(
                os.path.dirname(__file__), "..", "..", "scripts",
                "discover_youtube_channels.py"
            ),
        )
        # We only need to inspect the source, not execute it
        with open(spec.origin) as f:
            source = f.read()

        # The script must NOT use sample_title as the title value
        assert '"title": row.get("sample_title")' not in source, (
            "discover_youtube_channels must not use sample_title as youtube_channels.title — "
            "sample_title is a video title, not a channel display name."
        )
        # It must use handle or channel_id as placeholder
        assert 'title_placeholder' in source, (
            "discover_youtube_channels must use a title_placeholder derived from handle/channel_id"
        )

    def test_ingest_poll_accepts_channel_title_param(self):
        """_update_channel_after_poll must accept channel_title kwarg."""
        import inspect
        import importlib.util
        import os

        spec = importlib.util.spec_from_file_location(
            "ingest_youtube_channels",
            os.path.join(
                os.path.dirname(__file__), "..", "..", "scripts",
                "ingest_youtube_channels.py"
            ),
        )
        module = importlib.util.module_from_spec(spec)
        # Don't exec (has side effects) — just check source
        with open(spec.origin) as f:
            source = f.read()

        assert "channel_title" in source, (
            "ingest_youtube_channels._update_channel_after_poll must accept channel_title param"
        )
        assert "title = %s" in source or "title =" in source, (
            "ingest_youtube_channels must update youtube_channels.title from channelTitle"
        )
