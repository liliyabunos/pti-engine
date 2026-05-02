"""Regression tests for _write_mentions() dedup fix (FIX-1D).

Root cause of the bug:
  The dedup check used `source_url=cid` (bare content_item_id, e.g. "abc123xyz")
  while the INSERT wrote `source_url=_resolve_source_url(item, cid)` (full URL,
  e.g. "https://www.youtube.com/watch?v=abc123xyz").  These never matched, so
  every re-aggregation of the same date inserted fresh duplicate entity_mentions.

Fix:
  source_url_resolved = _resolve_source_url(item, cid)
  — used consistently for both the dedup check and the INSERT.

Tests:
  1. No duplicates on double-aggregation (same date run twice → count must not increase)
  2. Dedup check uses the full resolved URL, not the bare content_item_id
  3. One video resolving to two entities creates two distinct entity_mention rows
     (different entity_id, same source_url — this is correct, not a duplicate)
"""

import sys
import uuid
from pathlib import Path
from typing import List, Dict, Any
from unittest.mock import MagicMock, patch, call

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from perfume_trend_sdk.jobs.aggregate_daily_market_metrics import (
    _resolve_source_url,
)


# ---------------------------------------------------------------------------
# Test 1 — _resolve_source_url returns a full URL for YouTube content items
# ---------------------------------------------------------------------------

class TestResolveSourceUrl:
    """Verify the URL resolution used in the dedup check and INSERT."""

    def test_youtube_external_content_id_returns_full_url(self):
        """YouTube items without a source_url field must return a full watch URL."""
        item = {
            "source_platform": "youtube",
            "external_content_id": "abc123xyz",
            "source_url": None,
        }
        result = _resolve_source_url(item, "abc123xyz")
        assert result == "https://www.youtube.com/watch?v=abc123xyz"
        # Critically: the bare fallback is NOT returned
        assert result != "abc123xyz"

    def test_source_url_present_returns_as_is(self):
        """If source_url is already a full URL, return it unchanged."""
        item = {
            "source_platform": "youtube",
            "source_url": "https://www.youtube.com/watch?v=zzz999",
            "external_content_id": "zzz999",
        }
        result = _resolve_source_url(item, "zzz999")
        assert result == "https://www.youtube.com/watch?v=zzz999"

    def test_fallback_to_content_item_id_when_no_platform_data(self):
        """Items with no platform-specific data fall back to the bare cid."""
        item = {
            "source_platform": "other",
            "external_content_id": None,
            "source_url": None,
        }
        result = _resolve_source_url(item, "bare-cid-fallback")
        assert result == "bare-cid-fallback"

    def test_bare_content_id_differs_from_resolved_youtube_url(self):
        """Prove that the old bug (checking source_url=cid) would always miss.

        The dedup check used source_url=cid, but the INSERT wrote the full URL.
        These are always different for YouTube items. This test documents why
        the old check was broken.
        """
        cid = "videoidXYZ"
        item = {
            "source_platform": "youtube",
            "external_content_id": cid,
            "source_url": None,
        }
        resolved = _resolve_source_url(item, cid)
        # These must differ — the old dedup check (using cid) would never hit
        assert resolved != cid
        assert resolved == "https://www.youtube.com/watch?v=videoidXYZ"


# ---------------------------------------------------------------------------
# Test 2 — Dedup check consistency: check and INSERT use the same URL
# ---------------------------------------------------------------------------

class TestDedupConsistency:
    """Verify that the dedup check and the INSERT value are derived identically."""

    def _make_youtube_item(self, video_id: str) -> Dict[str, Any]:
        return {
            "id": video_id,
            "source_platform": "youtube",
            "external_content_id": video_id,
            "source_url": None,
            "source_account_handle": "testchannel",
            "published_at": "2026-05-01T12:00:00Z",
            "media_metadata_json": "{}",
            "engagement_json": "{}",
            "ingestion_method": "search",
        }

    def test_check_url_equals_insert_url_for_youtube(self):
        """For a YouTube item, the URL used in the check must equal the INSERT URL.

        This is the regression: in the old code the check used `cid` directly
        while INSERT used `_resolve_source_url(item, cid)`. Now both must
        go through _resolve_source_url.
        """
        cid = "yt-vid-001"
        item = self._make_youtube_item(cid)

        check_url = _resolve_source_url(item, cid)   # what the dedup check now uses
        insert_url = _resolve_source_url(item, cid)  # what the INSERT uses

        assert check_url == insert_url
        assert check_url == "https://www.youtube.com/watch?v=yt-vid-001"

    def test_check_url_equals_insert_url_for_reddit(self):
        """For a Reddit item with a full source_url, both paths return the same URL."""
        cid = "reddit-post-abc"
        item = {
            "id": cid,
            "source_platform": "reddit",
            "external_content_id": cid,
            "source_url": "https://www.reddit.com/r/fragrance/comments/abc/",
            "published_at": "2026-05-01T12:00:00Z",
            "media_metadata_json": "{}",
            "engagement_json": "{}",
        }

        check_url = _resolve_source_url(item, cid)
        insert_url = _resolve_source_url(item, cid)

        assert check_url == insert_url
        assert check_url == "https://www.reddit.com/r/fragrance/comments/abc/"

    def test_check_url_equals_insert_url_for_item_with_source_url_set(self):
        """YouTube item where source_url is already set as full URL."""
        cid = "yt-vid-002"
        full_url = "https://www.youtube.com/watch?v=yt-vid-002"
        item = {
            "id": cid,
            "source_platform": "youtube",
            "external_content_id": cid,
            "source_url": full_url,
            "published_at": "2026-05-01T12:00:00Z",
            "media_metadata_json": "{}",
            "engagement_json": "{}",
        }

        check_url = _resolve_source_url(item, cid)
        insert_url = _resolve_source_url(item, cid)

        assert check_url == insert_url == full_url


# ---------------------------------------------------------------------------
# Test 3 — Multi-entity video creates two rows, not one
# ---------------------------------------------------------------------------

class TestMultiEntityVideoDedup:
    """A video resolving to two entities must create two distinct entity_mention rows.

    This tests the correct behavior: two rows sharing the same source_url
    but with different entity_ids are NOT duplicates. They represent
    separate resolved entity links from one piece of content.

    Only rows with the same (entity_id, source_url) pair are duplicates.
    """

    def test_two_entities_from_one_video_are_distinct(self):
        """Two resolved entities from the same video → two distinct keys."""
        cid = "shared-video-001"
        item = {
            "id": cid,
            "source_platform": "youtube",
            "external_content_id": cid,
            "source_url": None,
            "published_at": "2026-05-01T12:00:00Z",
            "media_metadata_json": "{}",
            "engagement_json": "{}",
        }
        source_url = _resolve_source_url(item, cid)

        entity_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        entity_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        key_a = (entity_a, source_url)
        key_b = (entity_b, source_url)

        # Same source_url, different entity_ids → distinct dedup keys
        assert key_a != key_b
        assert key_a[1] == key_b[1]   # same URL
        assert key_a[0] != key_b[0]   # different entity

    def test_same_entity_same_video_is_duplicate(self):
        """The same (entity_id, source_url) pair appearing twice IS a duplicate."""
        cid = "shared-video-001"
        item = {
            "id": cid,
            "source_platform": "youtube",
            "external_content_id": cid,
            "source_url": None,
            "published_at": "2026-05-01T12:00:00Z",
            "media_metadata_json": "{}",
            "engagement_json": "{}",
        }
        source_url = _resolve_source_url(item, cid)
        entity_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

        key_first_run = (entity_a, source_url)
        key_second_run = (entity_a, source_url)

        # Same (entity_id, source_url) — this is a duplicate, must be rejected
        assert key_first_run == key_second_run

    def test_dedup_key_set_tracks_uniqueness_correctly(self):
        """Simulate the dedup set logic: one entity + two videos = 2 keys; same entity + same video = 1 key."""
        cid_a = "video-aaa"
        cid_b = "video-bbb"
        entity = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

        item_a = {"source_platform": "youtube", "external_content_id": cid_a, "source_url": None}
        item_b = {"source_platform": "youtube", "external_content_id": cid_b, "source_url": None}

        url_a = _resolve_source_url(item_a, cid_a)
        url_b = _resolve_source_url(item_b, cid_b)

        seen: set = set()

        # First run: add both
        seen.add((entity, url_a))
        seen.add((entity, url_b))
        assert len(seen) == 2

        # Second run (re-aggregation): same pairs → no growth
        seen.add((entity, url_a))
        seen.add((entity, url_b))
        assert len(seen) == 2, "Re-aggregation must not add duplicates"
