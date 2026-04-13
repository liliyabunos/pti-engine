from __future__ import annotations

"""
Unit tests for TikTokWatchlistClient.

All HTTP calls and time.sleep() are mocked — no network or real credentials needed.

Coverage:
  - _get_token(): success, missing creds, token caching, 401 fast-fail
  - _post(): retry on 429, retry on 5xx, fail-fast on 401, fail-fast on 4xx,
             Research API error envelope, exhausted retries
  - search_videos(): payload shape, pagination, field passthrough
  - _translate(): field mapping, empty/missing fields
"""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from perfume_trend_sdk.connectors.tiktok_watchlist.client import (
    TikTokAPIError,
    TikTokWatchlistClient,
    _RATE_LIMIT_WAIT,
    _RETRY_BACKOFF_BASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, body: Any = None, *, ok: bool | None = None) -> MagicMock:
    """Return a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = (status_code < 400) if ok is None else ok
    resp.json.return_value = body or {}
    resp.text = str(body or "")
    return resp


def _token_response(token: str = "tok_test", expires_in: int = 7200) -> MagicMock:
    return _make_response(200, {"access_token": token, "expires_in": expires_in})


def _search_response(
    videos: list[dict] | None = None,
    has_more: bool = False,
    cursor: int | None = None,
) -> MagicMock:
    return _make_response(200, {
        "data": {
            "videos": videos or [],
            "has_more": has_more,
            "cursor": cursor,
        },
        "error": {"code": "ok"},
    })


def _client(**kwargs) -> TikTokWatchlistClient:
    return TikTokWatchlistClient(
        client_key="key_test",
        client_secret="secret_test",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# _get_token — success path
# ---------------------------------------------------------------------------

class TestGetToken:
    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_returns_access_token(self, mock_post):
        mock_post.return_value = _token_response("my_token")
        client = _client()
        token = client._get_token()
        assert token == "my_token"

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_caches_token_on_second_call(self, mock_post):
        mock_post.return_value = _token_response("cached_token")
        client = _client()
        t1 = client._get_token()
        t2 = client._get_token()
        assert t1 == t2 == "cached_token"
        assert mock_post.call_count == 1  # only one HTTP call

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_refreshes_expired_token(self, mock_post):
        mock_post.return_value = _token_response("fresh_token")
        client = _client()

        # Set token to an already-expired state (expires_at=0 is far in the past).
        # Real time.time() (~1.7e9) is guaranteed > 0 - 30, so the cache check fails
        # and _get_token() must fetch a new token.
        client._access_token = "old_token"
        client._token_expires_at = 0.0

        token = client._get_token()
        assert token == "fresh_token"
        assert mock_post.call_count == 1

    def test_raises_when_credentials_missing(self):
        client = TikTokWatchlistClient(client_key="", client_secret="")
        with pytest.raises(TikTokAPIError, match="TIKTOK_CLIENT_KEY"):
            client._get_token()

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_raises_on_401(self, mock_post):
        mock_post.return_value = _make_response(401, "Unauthorized")
        client = _client()
        with pytest.raises(TikTokAPIError, match="401"):
            client._get_token()


# ---------------------------------------------------------------------------
# _post — retry and error handling
# ---------------------------------------------------------------------------

class TestPost:
    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_retries_on_429_then_succeeds(self, mock_post, mock_sleep):
        rate_limited = _make_response(429, ok=False)
        success = _make_response(200, {"data": {}, "error": {"code": "ok"}})
        mock_post.side_effect = [rate_limited, success]

        client = _client(max_retries=3)
        result = client._post("https://example.com", {}, "token")
        assert result == {"data": {}, "error": {"code": "ok"}}
        mock_sleep.assert_called_once_with(_RATE_LIMIT_WAIT)

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_retries_on_500_then_succeeds(self, mock_post, mock_sleep):
        server_err = _make_response(500, ok=False)
        success = _make_response(200, {"data": {}, "error": {"code": "ok"}})
        mock_post.side_effect = [server_err, success]

        client = _client(max_retries=3)
        result = client._post("https://example.com", {}, "token")
        assert result == {"data": {}, "error": {"code": "ok"}}
        mock_sleep.assert_called_once()

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_fail_fast_on_401(self, mock_post):
        mock_post.return_value = _make_response(401, ok=False)
        client = _client()
        with pytest.raises(TikTokAPIError, match="401"):
            client._post("https://example.com", {}, "token")

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_fail_fast_on_4xx_other_than_401(self, mock_post):
        mock_post.return_value = _make_response(400, "bad request", ok=False)
        client = _client()
        with pytest.raises(TikTokAPIError, match="400"):
            client._post("https://example.com", {}, "token")

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_raises_after_max_retries_exhausted(self, mock_post, mock_sleep):
        mock_post.return_value = _make_response(503, ok=False)
        client = _client(max_retries=3)
        with pytest.raises(TikTokAPIError, match="3 attempts"):
            client._post("https://example.com", {}, "token")
        assert mock_post.call_count == 3

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.time.sleep")
    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_raises_after_max_retries_on_network_error(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.ConnectionError("unreachable")
        client = _client(max_retries=3)
        with pytest.raises(TikTokAPIError, match="3 attempts"):
            client._post("https://example.com", {}, "token")
        assert mock_post.call_count == 3

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_401_invalidates_cached_token(self, mock_post):
        """
        Risk A — token expiry mid-session.

        When _post() receives a 401, it must clear self._access_token so that
        the next search_videos() call fetches a fresh token instead of reusing
        the stale one and looping on 401s forever.
        """
        mock_post.return_value = _make_response(401, "Token expired", ok=False)
        client = _client()
        client._access_token = "expired_token"
        client._token_expires_at = 9999999999.0  # looks valid for 300+ years

        with pytest.raises(TikTokAPIError, match="401"):
            client._post("https://example.com", {}, "expired_token")

        # Token must be cleared so next _get_token() triggers a real refresh
        assert client._access_token is None, (
            "401 from _post() must invalidate the cached token"
        )

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_raises_on_api_error_envelope(self, mock_post):
        body = {"data": {}, "error": {"code": "access_token_invalid", "message": "Token expired"}}
        mock_post.return_value = _make_response(200, body)
        client = _client()
        with pytest.raises(TikTokAPIError, match="access_token_invalid"):
            client._post("https://example.com", {}, "token")

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_ok_envelope_error_code_passes(self, mock_post):
        body = {"data": {"videos": []}, "error": {"code": "ok"}}
        mock_post.return_value = _make_response(200, body)
        client = _client()
        result = client._post("https://example.com", {}, "token")
        assert result == body


# ---------------------------------------------------------------------------
# search_videos
# ---------------------------------------------------------------------------

class TestSearchVideos:
    def _patched_client(self, mock_post, search_resp):
        """Pre-wire token + search response."""
        token_resp = _token_response()
        mock_post.side_effect = [token_resp, search_resp]
        return _client()

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_returns_empty_list_when_no_videos(self, mock_post):
        client = self._patched_client(mock_post, _search_response(videos=[]))
        videos, next_cursor = client.search_videos("Delina", "20260401", "20260410")
        assert videos == []
        assert next_cursor is None

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_returns_translated_videos(self, mock_post):
        raw_video = {
            "id": 123,
            "create_time": 1712345678,
            "username": "tester",
            "video_description": "Delina review",
            "view_count": 5000,
            "like_count": 200,
            "comment_count": 15,
            "share_count": 30,
            "hashtag_names": ["delina", "perfume"],
            "duration": 45,
        }
        client = self._patched_client(mock_post, _search_response(videos=[raw_video]))
        videos, next_cursor = client.search_videos("Delina", "20260401", "20260410")

        assert len(videos) == 1
        v = videos[0]
        assert v["id"] == "123"
        assert v["desc"] == "Delina review"
        assert v["stats"]["playCount"] == 5000
        assert v["stats"]["diggCount"] == 200
        assert v["stats"]["commentCount"] == 15
        assert v["stats"]["shareCount"] == 30
        assert v["author"]["uniqueId"] == "tester"
        assert next_cursor is None

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_returns_next_cursor_when_has_more(self, mock_post):
        raw_video = {"id": 1, "create_time": 0, "username": "u", "video_description": "", "view_count": 0,
                     "like_count": 0, "comment_count": 0, "share_count": 0, "hashtag_names": [], "duration": 0}
        resp = _search_response(videos=[raw_video], has_more=True, cursor=99)
        client = self._patched_client(mock_post, resp)
        _, next_cursor = client.search_videos("Delina", "20260401", "20260410")
        assert next_cursor == 99

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_next_cursor_is_none_when_no_more_pages(self, mock_post):
        resp = _search_response(videos=[], has_more=False, cursor=42)
        client = self._patched_client(mock_post, resp)
        _, next_cursor = client.search_videos("Delina", "20260401", "20260410")
        assert next_cursor is None

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_max_count_clamped_to_100(self, mock_post):
        client = self._patched_client(mock_post, _search_response())
        client.search_videos("Delina", "20260401", "20260410", max_count=999)
        # Second call is the search POST — inspect its JSON body
        search_call = mock_post.call_args_list[1]
        payload = search_call.kwargs.get("json") or search_call.args[1] if len(search_call.args) > 1 else search_call.kwargs["json"]
        assert payload["max_count"] == 100

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_passes_cursor_in_payload(self, mock_post):
        client = self._patched_client(mock_post, _search_response())
        client.search_videos("Delina", "20260401", "20260410", cursor=77)
        search_call = mock_post.call_args_list[1]
        payload = search_call.kwargs.get("json") or search_call.kwargs["json"]
        assert payload["cursor"] == 77

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_query_wrapped_in_and_clause(self, mock_post):
        client = self._patched_client(mock_post, _search_response())
        client.search_videos("Parfums de Marly", "20260401", "20260410")
        search_call = mock_post.call_args_list[1]
        payload = search_call.kwargs.get("json") or search_call.kwargs["json"]
        and_clauses = payload["query"]["and"]
        assert any(
            c["field_name"] == "keyword" and "Parfums de Marly" in c["field_values"]
            for c in and_clauses
        )

    # ------------------------------------------------------------------
    # Risk B — empty / zero cursor guard
    # ------------------------------------------------------------------

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_cursor_zero_in_response_returns_none(self, mock_post):
        """
        TikTok uses 0 as the initial request cursor.  Receiving cursor=0 back
        in a has_more=True response would cause the caller's
        'while next_cursor is not None' loop to page on cursor=0 forever.
        The fix: treat cursor=0 as no next page.
        """
        resp = _search_response(videos=[], has_more=True, cursor=0)
        client = self._patched_client(mock_post, resp)
        _, next_cursor = client.search_videos("Delina", "20260401", "20260410")
        assert next_cursor is None, (
            "cursor=0 with has_more=True must return next_cursor=None to prevent infinite loop"
        )

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_cursor_none_in_response_returns_none(self, mock_post):
        """has_more=True but cursor key missing → None, not KeyError."""
        body = _make_response(200, {
            "data": {"videos": [], "has_more": True},  # no "cursor" key
            "error": {"code": "ok"},
        })
        token_resp = _token_response()
        mock_post.side_effect = [token_resp, body]
        client = _client()
        _, next_cursor = client.search_videos("Delina", "20260401", "20260410")
        assert next_cursor is None

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_empty_videos_list_returns_empty_list_and_none(self, mock_post):
        """Zero-item response must return ([], None) cleanly — no exception."""
        resp = _search_response(videos=[], has_more=False)
        client = self._patched_client(mock_post, resp)
        videos, next_cursor = client.search_videos("Delina", "20260401", "20260410")
        assert videos == []
        assert next_cursor is None

    @patch("perfume_trend_sdk.connectors.tiktok_watchlist.client.requests.post")
    def test_missing_data_key_returns_empty(self, mock_post):
        """Response body without 'data' key must not raise — returns ([], None)."""
        body = _make_response(200, {"error": {"code": "ok"}})  # no "data" key
        mock_post.side_effect = [_token_response(), body]
        client = _client()
        videos, next_cursor = client.search_videos("Delina", "20260401", "20260410")
        assert videos == []
        assert next_cursor is None


# ---------------------------------------------------------------------------
# _translate — field mapping
# ---------------------------------------------------------------------------

class TestTranslate:
    def _raw(self, **overrides) -> dict:
        base = {
            "id": 999,
            "create_time": 1712345678,
            "username": "scentreviews",
            "video_description": "My fave perfume",
            "view_count": 50000,
            "like_count": 3000,
            "comment_count": 120,
            "share_count": 400,
            "hashtag_names": ["perfume", "niche"],
            "duration": 55,
        }
        base.update(overrides)
        return base

    def test_id_is_stringified(self):
        result = TikTokWatchlistClient._translate(self._raw(id=12345))
        assert result["id"] == "12345"

    def test_desc_maps_from_video_description(self):
        result = TikTokWatchlistClient._translate(self._raw(video_description="Delina review"))
        assert result["desc"] == "Delina review"

    def test_create_time_maps_to_createTime(self):
        result = TikTokWatchlistClient._translate(self._raw(create_time=1712345678))
        assert result["createTime"] == 1712345678

    def test_author_fields_from_username(self):
        result = TikTokWatchlistClient._translate(self._raw(username="scentreviews"))
        assert result["author"]["uniqueId"] == "scentreviews"
        assert result["author"]["id"] == "scentreviews"
        assert result["author"]["nickname"] == "scentreviews"

    def test_stats_mapped_correctly(self):
        result = TikTokWatchlistClient._translate(
            self._raw(view_count=50000, like_count=3000, comment_count=120, share_count=400)
        )
        assert result["stats"]["playCount"] == 50000
        assert result["stats"]["diggCount"] == 3000
        assert result["stats"]["commentCount"] == 120
        assert result["stats"]["shareCount"] == 400

    def test_hashtag_names_become_challenges(self):
        result = TikTokWatchlistClient._translate(self._raw(hashtag_names=["delina", "pdm"]))
        assert result["challenges"] == [{"title": "delina"}, {"title": "pdm"}]

    def test_duration_maps_to_video_duration(self):
        result = TikTokWatchlistClient._translate(self._raw(duration=55))
        assert result["video"]["duration"] == 55

    def test_missing_optional_fields_default_safely(self):
        result = TikTokWatchlistClient._translate({})
        assert result["id"] == ""
        assert result["desc"] == ""
        assert result["createTime"] == 0
        assert result["author"]["uniqueId"] == ""
        assert result["stats"]["playCount"] == 0
        assert result["challenges"] == []

    def test_none_hashtag_names_become_empty_challenges(self):
        result = TikTokWatchlistClient._translate(self._raw(hashtag_names=None))
        assert result["challenges"] == []

    def test_author_follower_count_is_zero(self):
        """Research API does not return follower count — must default to 0."""
        result = TikTokWatchlistClient._translate(self._raw())
        assert result["author"]["followerCount"] == 0

    def test_translate_output_passes_through_parser(self):
        """
        Translated output must be parseable by TikTokParser without raising.
        Confirms the schema bridge is complete.
        """
        from perfume_trend_sdk.connectors.tiktok_watchlist.parser import TikTokParser
        translated = TikTokWatchlistClient._translate(self._raw())
        parsed = TikTokParser().parse(translated)
        assert parsed["external_content_id"] == "999"
        assert parsed["caption"] == "My fave perfume"
        assert parsed["views"] == 50000
        assert parsed["hashtags"] == ["perfume", "niche"]


# ---------------------------------------------------------------------------
# fetch_user_posts — stub
# ---------------------------------------------------------------------------

class TestFetchUserPostsStub:
    def test_returns_empty_list(self):
        client = _client()
        result = client.fetch_user_posts("@scentreviews")
        assert result == []
