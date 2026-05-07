from __future__ import annotations

"""
SC1.1 — TikTok URL Extractor

Scans text from YouTube/Reddit content items for embedded TikTok video URLs
and produces derived canonical_content_item dicts ready for pg_store.

Design principles:
  - Only video URLs are extracted (/@handle/video/<id> pattern).
  - Channel/profile/other TikTok URLs are ignored — they belong in source_submissions.
  - Each derived item sets mention_weight_override=0.0 (enrichment-only, no mention count).
  - The parent content item MUST already be persisted before derived items are saved
    (correction 4 from SC1.1 spec).
  - Output is idempotent: same parent + same TikTok URL → same derived item id.

Usage:
    from perfume_trend_sdk.ingest.tiktok_url_extractor import extract_tiktok_video_urls

    derived_items = extract_tiktok_video_urls(
        parent_id="yt_abc123",
        text="Check this TikTok https://www.tiktok.com/@perfumeguy/video/123456789",
    )
    # → list of normalized item dicts with mention_weight_override=0.0
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from perfume_trend_sdk.normalizers.social_content.normalizer import SocialContentNormalizer

# Matches full TikTok video URLs: https://www.tiktok.com/@handle/video/123456789
# Handles optional trailing params / fragments.
_TIKTOK_VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._]+)/video/(\d{10,25})",
    re.IGNORECASE,
)

# Max length for the referencing_context snippet stored alongside derived items.
_CONTEXT_WINDOW = 200


@dataclass
class TikTokURLMatch:
    """A TikTok video URL found within a parent content item."""
    url: str
    handle: str
    video_id: str
    context_snippet: str   # surrounding text, max _CONTEXT_WINDOW chars


def _extract_snippet(text: str, match_start: int, match_end: int) -> str:
    """Return up to _CONTEXT_WINDOW chars of text centered on the URL match."""
    half = (_CONTEXT_WINDOW - (match_end - match_start)) // 2
    start = max(0, match_start - half)
    end = min(len(text), match_end + half)
    snippet = text[start:end].strip()
    # Collapse internal whitespace to a single space for compact storage.
    snippet = re.sub(r"\s+", " ", snippet)
    return snippet[:_CONTEXT_WINDOW]


def find_tiktok_video_urls(text: str) -> List[TikTokURLMatch]:
    """Return all unique TikTok video URL matches found in text.

    Deduplicates by video_id — the same TikTok video mentioned twice in one
    post yields a single derived item.
    """
    if not text:
        return []
    seen_ids: set[str] = set()
    matches: List[TikTokURLMatch] = []
    for m in _TIKTOK_VIDEO_URL_RE.finditer(text):
        handle = m.group(1)
        video_id = m.group(2)
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        snippet = _extract_snippet(text, m.start(), m.end())
        matches.append(TikTokURLMatch(
            url=m.group(0),
            handle=handle,
            video_id=video_id,
            context_snippet=snippet,
        ))
    return matches


def extract_tiktok_video_urls(
    *,
    parent_id: str,
    text: str,
    collected_at: Optional[str] = None,
) -> List[dict]:
    """Scan text from a parent content item and return derived TikTok item dicts.

    The parent content item MUST be persisted to canonical_content_items before
    calling this function so that referencing_source_id is a valid FK-like pointer.

    Args:
        parent_id:    id of the already-persisted parent canonical_content_item.
        text:         text_content or title from the parent item to scan.
        collected_at: ISO 8601 string; defaults to utcnow.

    Returns:
        List of normalized item dicts (may be empty). Each dict has:
          mention_weight_override=0.0 — aggregator skips mention count
          tiktok_layer=1
          referencing_source_id=parent_id
          referencing_context=snippet
    """
    url_matches = find_tiktok_video_urls(text)
    if not url_matches:
        return []

    normalizer = SocialContentNormalizer()
    derived: List[dict] = []

    for match in url_matches:
        item = normalizer.normalize_tiktok_derived_item(
            tiktok_url=match.url,
            referencing_source_id=parent_id,
            referencing_context=match.context_snippet,
            collected_at=collected_at,
        )
        if item is not None:
            derived.append(item)

    return derived
