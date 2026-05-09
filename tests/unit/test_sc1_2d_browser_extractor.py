"""
SC1.2D — Unit tests for TikTok browser extractor helpers.

Tests operate on saved/mock HTML fixtures — no Playwright, no network,
no DB. All assertions are against pure extraction functions.
"""
from __future__ import annotations

import json
import pytest

from perfume_trend_sdk.ingest.tiktok_browser_extractor import (
    BrowserProfileResult,
    detect_captcha_or_block,
    detect_login_wall,
    extract_metadata_from_script_json,
    extract_video_urls_from_dom,
    extract_video_urls_from_script_json,
    parse_item_list_api_response,
    _find_item_list,
    _find_user_info,
)


# ---------------------------------------------------------------------------
# Fixtures: realistic HTML fragments
# ---------------------------------------------------------------------------

def _make_profile_html(handle: str, video_ids: list[str], user_info: dict = None) -> str:
    """Build a minimal TikTok-like profile HTML with DOM anchors."""
    links = "\n".join(
        f'<a href="https://www.tiktok.com/@{handle}/video/{vid}">Video</a>'
        for vid in video_ids
    )
    user_info_block = ""
    if user_info:
        script_data = {"__DEFAULT_SCOPE__": {"webapp.user-detail": {"userInfo": user_info}}}
        escaped = json.dumps(script_data).replace("</", "<\\/")
        user_info_block = (
            f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{escaped}</script>'
        )
    return f"""
    <html>
    <head><title>@{handle} | TikTok</title></head>
    <body>
    {links}
    {user_info_block}
    </body>
    </html>
    """


def _make_login_wall_html() -> str:
    return """
    <html>
    <body>
    <h1>Log in to TikTok</h1>
    <button>Log in with Google</button>
    </body>
    </html>
    """


def _make_captcha_html() -> str:
    return """
    <html>
    <body>
    <h2>Security Check</h2>
    <p>Please verify you are human.</p>
    </body>
    </html>
    """


def _make_block_html() -> str:
    return """
    <html>
    <body>
    <h1>Access Denied</h1>
    <p>Too many requests. Please try again later.</p>
    </body>
    </html>
    """


def _make_sigi_state_html(handle: str, video_ids: list[str]) -> str:
    """Build HTML with SIGI_STATE script tag containing itemList."""
    item_list = [{"id": vid} for vid in video_ids]
    data = {"ItemModule": {}, "UserPage": {"itemList": item_list}}
    escaped = json.dumps(data).replace("</", "<\\/")
    return f"""
    <html><body>
    <script id="SIGI_STATE">{escaped}</script>
    </body></html>
    """


def _make_universal_data_html_with_items(handle: str, video_ids: list[str]) -> str:
    """Build HTML with __UNIVERSAL_DATA_FOR_REHYDRATION__ containing itemList."""
    item_list = [{"id": vid} for vid in video_ids]
    data = {
        "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
                "userInfo": {
                    "user": {"uniqueId": handle, "nickname": "Test User", "signature": "My bio"},
                    "stats": {"followerCount": 12345},
                },
                "itemList": item_list,
            }
        }
    }
    escaped = json.dumps(data).replace("</", "<\\/")
    return f"""
    <html><body>
    <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{escaped}</script>
    </body></html>
    """


# ---------------------------------------------------------------------------
# Tests: detect_login_wall
# ---------------------------------------------------------------------------

class TestDetectLoginWall:
    def test_login_url_pattern(self):
        assert detect_login_wall("https://www.tiktok.com/login?redirect=...", "") is True

    def test_passport_url(self):
        assert detect_login_wall("https://accounts.tiktok.com/passport/login", "") is True

    def test_signup_url(self):
        assert detect_login_wall("https://www.tiktok.com/signup", "") is True

    def test_login_text_in_html(self):
        html = _make_login_wall_html()
        assert detect_login_wall("https://www.tiktok.com/@rawscents", html) is True

    def test_create_account_text(self):
        html = "<html><body><button>Create Account</button></body></html>"
        assert detect_login_wall("https://www.tiktok.com/@handle", html) is True

    def test_normal_profile_no_login(self):
        html = _make_profile_html("rawscents", ["1234567890123"])
        assert detect_login_wall("https://www.tiktok.com/@rawscents", html) is False

    def test_empty_url_and_html(self):
        assert detect_login_wall("", "") is False


# ---------------------------------------------------------------------------
# Tests: detect_captcha_or_block
# ---------------------------------------------------------------------------

class TestDetectCaptchaOrBlock:
    def test_captcha_html(self):
        assert detect_captcha_or_block(_make_captcha_html()) is True

    def test_block_html(self):
        assert detect_captcha_or_block(_make_block_html()) is True

    def test_access_denied(self):
        assert detect_captcha_or_block("<html>403 Forbidden</html>") is True

    def test_rate_limit(self):
        assert detect_captcha_or_block("<html>rate limit exceeded</html>") is True

    def test_are_you_human(self):
        assert detect_captcha_or_block("<html>Are you human?</html>") is True

    def test_normal_profile_no_captcha(self):
        html = _make_profile_html("rawscents", ["1234567890123"])
        assert detect_captcha_or_block(html) is False

    def test_too_many_requests(self):
        assert detect_captcha_or_block("<html>Too Many Requests</html>") is True


# ---------------------------------------------------------------------------
# Tests: extract_video_urls_from_dom
# ---------------------------------------------------------------------------

class TestExtractVideoUrlsFromDom:
    def test_single_video(self):
        html = _make_profile_html("rawscents", ["1234567890123456"])
        urls = extract_video_urls_from_dom(html, "rawscents")
        assert len(urls) == 1
        assert "rawscents" in urls[0]
        assert "1234567890123456" in urls[0]

    def test_multiple_videos(self):
        html = _make_profile_html(
            "rawscents",
            ["1111111111111111", "2222222222222222", "3333333333333333"],
        )
        urls = extract_video_urls_from_dom(html, "rawscents")
        assert len(urls) == 3

    def test_deduplication(self):
        # Same video linked twice
        vid = "9876543210987654"
        html = f"""
        <a href="https://www.tiktok.com/@rawscents/video/{vid}">v1</a>
        <a href="https://www.tiktok.com/@rawscents/video/{vid}">v2</a>
        """
        urls = extract_video_urls_from_dom(html, "rawscents")
        assert len(urls) == 1

    def test_handle_with_at_prefix(self):
        html = _make_profile_html("rawscents", ["1234567890123456"])
        urls = extract_video_urls_from_dom(html, "@rawscents")
        assert len(urls) == 1

    def test_no_videos_empty_html(self):
        assert extract_video_urls_from_dom("<html><body>nothing</body></html>", "rawscents") == []

    def test_other_creator_videos_excluded(self):
        # Links for a different creator should not be included
        html = '<a href="https://www.tiktok.com/@otherguy/video/1234567890123456">v</a>'
        urls = extract_video_urls_from_dom(html, "rawscents")
        assert urls == []

    def test_url_format_correct(self):
        html = _make_profile_html("rawscents", ["1234567890123456"])
        urls = extract_video_urls_from_dom(html, "rawscents")
        assert urls[0].startswith("https://www.tiktok.com/@rawscents/video/")

    def test_short_ids_ignored(self):
        # IDs must be 10-25 digits
        html = '<a href="https://www.tiktok.com/@rawscents/video/123">short</a>'
        urls = extract_video_urls_from_dom(html, "rawscents")
        assert urls == []


# ---------------------------------------------------------------------------
# Tests: extract_video_urls_from_script_json
# ---------------------------------------------------------------------------

class TestExtractVideoUrlsFromScriptJson:
    def test_sigi_state_item_list(self):
        html = _make_sigi_state_html("rawscents", ["1111111111111111", "2222222222222222"])
        urls = extract_video_urls_from_script_json(html, "rawscents")
        assert len(urls) == 2
        assert all("rawscents" in u for u in urls)

    def test_universal_data_item_list(self):
        html = _make_universal_data_html_with_items(
            "rawscents", ["9999999999999999"]
        )
        urls = extract_video_urls_from_script_json(html, "rawscents")
        assert len(urls) == 1
        assert "9999999999999999" in urls[0]

    def test_empty_item_list(self):
        # SSR itemList is usually empty — should return []
        data = {"__DEFAULT_SCOPE__": {"webapp.user-detail": {"itemList": []}}}
        escaped = json.dumps(data)
        html = f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{escaped}</script>'
        urls = extract_video_urls_from_script_json(html, "rawscents")
        assert urls == []

    def test_no_script_tag(self):
        assert extract_video_urls_from_script_json("<html><body></body></html>", "rawscents") == []

    def test_malformed_json_returns_empty(self):
        html = '<script id="SIGI_STATE">{invalid json!!}</script>'
        urls = extract_video_urls_from_script_json(html, "rawscents")
        assert urls == []


# ---------------------------------------------------------------------------
# Tests: extract_metadata_from_script_json
# ---------------------------------------------------------------------------

class TestExtractMetadataFromScriptJson:
    def test_extracts_display_name_and_followers(self):
        user_info = {
            "user": {"uniqueId": "rawscents", "nickname": "Raw Scents", "signature": "Fragrance lover"},
            "stats": {"followerCount": 5000},
        }
        html = _make_profile_html("rawscents", [], user_info)
        meta = extract_metadata_from_script_json(html)
        assert meta["display_name"] == "Raw Scents"
        assert meta["follower_count"] == 5000
        assert meta["bio"] == "Fragrance lover"

    def test_no_bio_returns_none(self):
        user_info = {
            "user": {"uniqueId": "rawscents", "nickname": "Raw Scents", "signature": ""},
            "stats": {"followerCount": 100},
        }
        html = _make_profile_html("rawscents", [], user_info)
        meta = extract_metadata_from_script_json(html)
        assert meta["bio"] is None

    def test_no_script_tag_returns_empty(self):
        meta = extract_metadata_from_script_json("<html><body>nothing</body></html>")
        assert meta == {}

    def test_missing_unique_id_skipped(self):
        # Without uniqueId the user dict is not recognised
        user_info = {
            "user": {"nickname": "Anon"},
            "stats": {"followerCount": 1},
        }
        html = _make_profile_html("rawscents", [], user_info)
        meta = extract_metadata_from_script_json(html)
        assert meta == {}


# ---------------------------------------------------------------------------
# Tests: parse_item_list_api_response
# ---------------------------------------------------------------------------

class TestParseItemListApiResponse:
    def test_parses_item_list(self):
        body = json.dumps({
            "statusCode": 0,
            "itemList": [
                {"id": "1111111111111111"},
                {"id": "2222222222222222"},
            ],
        })
        urls = parse_item_list_api_response(body, "rawscents")
        assert len(urls) == 2
        assert "1111111111111111" in urls[0]
        assert "rawscents" in urls[0]

    def test_empty_item_list(self):
        body = json.dumps({"statusCode": 0, "itemList": []})
        assert parse_item_list_api_response(body, "rawscents") == []

    def test_missing_item_list_key(self):
        body = json.dumps({"statusCode": 0})
        assert parse_item_list_api_response(body, "rawscents") == []

    def test_malformed_json(self):
        assert parse_item_list_api_response("{bad json", "rawscents") == []

    def test_handle_with_at(self):
        body = json.dumps({"itemList": [{"id": "3333333333333333"}]})
        urls = parse_item_list_api_response(body, "@rawscents")
        # TikTok URLs always have @ — confirm handle is present
        assert "rawscents" in urls[0]
        assert "3333333333333333" in urls[0]
        # @ is stripped from the lstrip("@") call before building URL
        assert urls[0] == "https://www.tiktok.com/@rawscents/video/3333333333333333"


# ---------------------------------------------------------------------------
# Tests: BrowserProfileResult.to_dict
# ---------------------------------------------------------------------------

class TestBrowserProfileResultToDict:
    def test_default_result(self):
        r = BrowserProfileResult(handle="rawscents", profile_url="https://www.tiktok.com/@rawscents")
        d = r.to_dict()
        assert d["rendered_success"] is False
        assert d["captcha_or_block_detected"] is False
        assert d["login_wall_detected"] is False
        assert d["video_urls_found"] == 0
        assert d["extraction_method"] == "none"
        assert d["metadata_found"] is False

    def test_sample_urls_capped_at_five(self):
        r = BrowserProfileResult(handle="h", profile_url="https://tiktok.com/@h")
        r.sample_video_urls = [f"url{i}" for i in range(20)]
        d = r.to_dict()
        assert len(d["sample_video_urls"]) == 5

    def test_no_db_write_fields(self):
        """Confirm to_dict never includes last_checked_at or status."""
        r = BrowserProfileResult(handle="h", profile_url="https://tiktok.com/@h")
        d = r.to_dict()
        assert "last_checked_at" not in d
        assert "status" not in d
        assert "entity_mentions" not in d


# ---------------------------------------------------------------------------
# Tests: _find_item_list helper
# ---------------------------------------------------------------------------

class TestFindItemList:
    def test_finds_direct_item_list(self):
        data = {"itemList": [{"id": "123"}]}
        assert _find_item_list(data) == [{"id": "123"}]

    def test_finds_nested_item_list(self):
        data = {"a": {"b": {"itemList": [{"id": "456"}]}}}
        assert _find_item_list(data) == [{"id": "456"}]

    def test_empty_item_list(self):
        data = {"itemList": []}
        assert _find_item_list(data) == []

    def test_no_item_list(self):
        data = {"other": "value"}
        assert _find_item_list(data) == []

    def test_depth_limit(self):
        # Deeply nested beyond limit — should not crash
        inner = {"itemList": [{"id": "x"}]}
        for _ in range(10):
            inner = {"a": inner}
        result = _find_item_list(inner)
        # May or may not find it depending on depth — important is no crash
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests: _find_user_info helper
# ---------------------------------------------------------------------------

class TestFindUserInfo:
    def test_finds_user_and_stats(self):
        data = {
            "userInfo": {
                "user": {"uniqueId": "rawscents", "nickname": "RS", "signature": "bio"},
                "stats": {"followerCount": 100},
            }
        }
        result = _find_user_info(data)
        assert result["display_name"] == "RS"
        assert result["follower_count"] == 100
        assert result["bio"] == "bio"

    def test_requires_unique_id(self):
        data = {
            "userInfo": {
                "user": {"nickname": "NoId"},
                "stats": {"followerCount": 1},
            }
        }
        assert _find_user_info(data) == {}

    def test_returns_empty_on_no_match(self):
        assert _find_user_info({"key": "value"}) == {}
