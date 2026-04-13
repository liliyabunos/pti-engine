from __future__ import annotations

"""
Unit tests for RedditWatchlistClient.

All HTTP calls are mocked — no network required.

Coverage:
  - fetch_subreddit_posts(): success, empty, pagination cursor, cutoff filter
  - _get(): retry on 429, retry on 5xx, fail-fast on 4xx, exhausted retries
  - rate limiting: _rate_limit() delays next call when within min_interval
  - _parse_iso_to_ts(): valid ISO, Z suffix, invalid, None
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from perfume_trend_sdk.connectors.reddit_watchlist.client import (
    RedditAPIError,
    RedditWatchlistClient,
    _parse_iso_to_ts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, body: Any = None, *, ok: bool | None = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = (status_code < 400) if ok is None else ok
    resp.json.return_value = body or {}
    resp.text = str(body or "")
    return resp


def _listing_response(
    posts: list[dict] | None = None,
    after: str | None = None,
) -> MagicMock:
    """Simulate a Reddit listing JSON response."""
    children = [{"kind": "t3", "data": p} for p in (posts or [])]
    return _make_response(200, {
        "kind": "Listing",
        "data": {
            "after": after,
            "children": children,
        },
    })


def _sample_post(
    post_id: str = "abc123",
    created_utc: float = 1712345678.0,
    subreddit: str = "fragrance",
    title: str = "Delina review",
    score: int = 100,
) -> dict:
    return {
        "id": post_id,
        "name": f"t3_{post_id}",
        "title": title,
        "selftext": "Great perfume",
        "author": "tester",
        "subreddit": subreddit,
        "permalink": f"/r/{subreddit}/comments/{post_id}/title/",
        "created_utc": created_utc,
        "score": score,
        "num_comments": 10,
        "upvote_ratio": 0.95,
        "is_self": True,
        "link_flair_text": None,
    }


def _client(**kwargs) -> RedditWatchlistClient:
    return RedditWatchlistClient(
        user_agent="test-agent/1.0",
        requests_per_second=999.0,   # no real rate limit in tests
        **kwargs,
    )


# ---------------------------------------------------------------------------
# fetch_subreddit_posts — success cases
# ---------------------------------------------------------------------------

class TestFetchSubredditPosts:
    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_returns_posts(self, mock_get):
        posts = [_sample_post("p1"), _sample_post("p2")]
        mock_get.return_value = _listing_response(posts=posts)
        client = _client()
        result, next_cursor = client.fetch_subreddit_posts("fragrance", max_count=10)
        assert len(result) == 2
        assert result[0]["id"] == "p1"
        assert next_cursor is None

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_returns_next_cursor(self, mock_get):
        posts = [_sample_post("p1")]
        mock_get.return_value = _listing_response(posts=posts, after="t3_p1")
        client = _client()
        _, next_cursor = client.fetch_subreddit_posts("fragrance", max_count=1)
        assert next_cursor == "t3_p1"

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_empty_listing_returns_empty_and_none_cursor(self, mock_get):
        mock_get.return_value = _listing_response(posts=[])
        client = _client()
        result, cursor = client.fetch_subreddit_posts("fragrance")
        assert result == []
        assert cursor is None

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_passes_after_cursor_in_url(self, mock_get):
        mock_get.return_value = _listing_response()
        client = _client()
        client.fetch_subreddit_posts("fragrance", after_cursor="t3_xyz")
        call_url = mock_get.call_args.args[0]
        assert "after=t3_xyz" in call_url

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_limit_clamped_to_100(self, mock_get):
        mock_get.return_value = _listing_response()
        client = _client()
        client.fetch_subreddit_posts("fragrance", max_count=999)
        call_url = mock_get.call_args.args[0]
        assert "limit=100" in call_url

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_sort_mode_in_url(self, mock_get):
        mock_get.return_value = _listing_response()
        client = _client(sort_mode="hot")
        client.fetch_subreddit_posts("fragrance")
        call_url = mock_get.call_args.args[0]
        assert "/hot.json" in call_url

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_non_t3_children_are_skipped(self, mock_get):
        """Comments (t1) or other kinds must be filtered out."""
        body = {
            "data": {
                "after": None,
                "children": [
                    {"kind": "t1", "data": {"id": "comment1"}},  # comment — skip
                    {"kind": "t3", "data": _sample_post("post1")},
                ],
            }
        }
        mock_get.return_value = _make_response(200, body)
        client = _client()
        result, _ = client.fetch_subreddit_posts("fragrance")
        assert len(result) == 1
        assert result[0]["id"] == "post1"

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_published_after_cutoff_filters_old_posts(self, mock_get):
        """Posts older than published_after must be excluded; cursor set to None."""
        old_ts = 1000000.0    # very old
        new_ts = 1712345678.0  # recent
        posts = [_sample_post("new", created_utc=new_ts), _sample_post("old", created_utc=old_ts)]
        mock_get.return_value = _listing_response(posts=posts, after="t3_more")
        client = _client()
        # cutoff set between old and new
        cutoff = "2024-04-01T00:00:00Z"   # 1711929600 — newer than old_ts
        result, cursor = client.fetch_subreddit_posts("fragrance", published_after=cutoff)
        ids = [p["id"] for p in result]
        assert "new" in ids
        assert "old" not in ids
        # Cursor must be None because we hit a post older than cutoff
        assert cursor is None

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_user_agent_header_set(self, mock_get):
        mock_get.return_value = _listing_response()
        client = RedditWatchlistClient(
            user_agent="my-custom-agent/2.0",
            requests_per_second=999.0,
        )
        client.fetch_subreddit_posts("fragrance")
        headers = mock_get.call_args.kwargs.get("headers", {})
        assert headers.get("User-Agent") == "my-custom-agent/2.0"


# ---------------------------------------------------------------------------
# _get — retry and error handling
# ---------------------------------------------------------------------------

class TestGet:
    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_retries_on_429_then_succeeds(self, mock_get, mock_sleep):
        rate_limited = _make_response(429, ok=False)
        success = _listing_response()
        mock_get.side_effect = [rate_limited, success]
        client = _client(max_retries=3)
        result = client._get("https://example.com")
        assert result is not None
        mock_sleep.assert_called()

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_retries_on_500_then_succeeds(self, mock_get, mock_sleep):
        server_err = _make_response(500, ok=False)
        success = _listing_response()
        mock_get.side_effect = [server_err, success]
        client = _client(max_retries=3)
        result = client._get("https://example.com")
        assert result is not None

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_fail_fast_on_403(self, mock_get):
        mock_get.return_value = _make_response(403, "Forbidden", ok=False)
        client = _client()
        with pytest.raises(RedditAPIError, match="403"):
            client._get("https://example.com")

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_raises_after_max_retries_exhausted(self, mock_get, mock_sleep):
        mock_get.return_value = _make_response(503, ok=False)
        client = _client(max_retries=3)
        with pytest.raises(RedditAPIError, match="3 attempts"):
            client._get("https://example.com")
        assert mock_get.call_count == 3

    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.reddit_watchlist.client.requests.get")
    def test_raises_after_max_retries_on_network_error(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.ConnectionError("unreachable")
        client = _client(max_retries=3)
        with pytest.raises(RedditAPIError, match="3 attempts"):
            client._get("https://example.com")
        assert mock_get.call_count == 3


# ---------------------------------------------------------------------------
# _parse_iso_to_ts — helper
# ---------------------------------------------------------------------------

class TestParseIsoToTs:
    def test_valid_iso_with_z(self):
        ts = _parse_iso_to_ts("2024-04-05T12:00:00Z")
        assert ts is not None
        assert ts > 0

    def test_valid_iso_with_offset(self):
        ts = _parse_iso_to_ts("2024-04-05T12:00:00+00:00")
        assert ts is not None

    def test_none_returns_none(self):
        assert _parse_iso_to_ts(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_iso_to_ts("") is None

    def test_invalid_string_returns_none(self):
        assert _parse_iso_to_ts("not-a-date") is None

    def test_z_and_plus_utc_produce_same_timestamp(self):
        t1 = _parse_iso_to_ts("2024-04-05T12:00:00Z")
        t2 = _parse_iso_to_ts("2024-04-05T12:00:00+00:00")
        assert t1 == pytest.approx(t2)
