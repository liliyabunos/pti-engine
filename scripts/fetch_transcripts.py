"""Minimal transcript fetcher — reads the transcript queue and writes to content_transcripts.

Usage:
    python3 scripts/fetch_transcripts.py [--limit N] [--channel-id ID] [--dry-run]

IMPORTANT — run locally, not on Railway.
    YouTube blocks caption requests from cloud/datacenter IPs (same constraint as Fragrantica).
    Run this script from your local machine against the production Postgres public proxy URL:

        DATABASE_URL="<production-public-url>" \\
          python3 scripts/fetch_transcripts.py --limit 5 --channel-id UCzKrJ5NSA9o7RHYRG12kHZw

    If the script exits with "RequestBlocked / IpBlocked", your current IP is blocked.
    Wait a few minutes and retry, or use a VPN exit node.

Reads:
    canonical_content_items WHERE transcript_status='needed'
                                AND transcript_priority='high'
                                AND source_platform='youtube'

Writes:
    content_transcripts (upsert on content_item_id)
    canonical_content_items.transcript_status → 'fetched' | 'unavailable' | 'failed'
    NOTE: RequestBlocked / IpBlocked does NOT change transcript_status (queue preserved).

Does NOT:
    - Call any LLM
    - Fetch comments
    - Modify text_content / title / description
    - Run aggregation
    - Touch any scheduled pipeline script

transcript_source value: 'youtube_captions'
    youtube_transcript_api fetches auto-generated or manual captions directly from
    YouTube's internal caption endpoint — no API key, no OAuth, no quota usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# YouTube transcript library
# ---------------------------------------------------------------------------

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        CouldNotRetrieveTranscript,
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
    )
    # AgeRestricted available in v1.x
    try:
        from youtube_transcript_api._errors import AgeRestricted
    except ImportError:
        AgeRestricted = Exception  # type: ignore[misc,assignment]
except ImportError as exc:
    sys.exit(
        "youtube-transcript-api is not installed.\n"
        "Run: pip install 'youtube-transcript-api>=0.6'\n"
        f"Original error: {exc}"
    )

# ---------------------------------------------------------------------------
# DB — psycopg2 for Postgres, sqlite3 fallback for local dev
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
PTI_DB_PATH = os.environ.get("PTI_DB_PATH", "outputs/market_dev.db").strip()

_YOUTUBE_VIDEO_ID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

TRANSCRIPT_SOURCE = "youtube_captions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_video_id(row: dict) -> Optional[str]:
    """Return the 11-char YouTube video ID from external_content_id or source_url."""
    eid = (row.get("external_content_id") or "").strip()
    if _BARE_ID_RE.match(eid):
        return eid
    url = (row.get("source_url") or "").strip()
    m = _YOUTUBE_VIDEO_ID_RE.search(url)
    if m:
        return m.group(1)
    return None


def _join_segments(segments: list[dict]) -> str:
    """Concatenate transcript segment text into a single string."""
    return " ".join(s.get("text", "").strip() for s in segments if s.get("text", "").strip())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(video_id: str, title: str, channel: str, status: str,
         length: Optional[int], source: Optional[str], language: Optional[str],
         error: Optional[str] = None, dry_run: bool = False) -> None:
    prefix = "[dry-run] " if dry_run else ""
    parts = {
        "video_id": video_id,
        "title": title[:60] if title else "",
        "channel": channel[:40] if channel else "",
        "transcript_status": status,
        "transcript_length": length,
        "transcript_source": source,
        "language": language,
    }
    if error:
        parts["error"] = error[:200]
    print(f"{prefix}[fetch_transcripts] " + json.dumps(parts, ensure_ascii=False))


# ---------------------------------------------------------------------------
# DB connection layer
# ---------------------------------------------------------------------------

def _get_conn():
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn, "pg"
    import sqlite3
    conn = sqlite3.connect(PTI_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn, "sqlite"


def _cursor(conn, dialect: str):
    """Return a dict-like cursor."""
    if dialect == "pg":
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()  # sqlite3 with row_factory=sqlite3.Row already dict-like


def _fetchall_dict(cur, dialect: str) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Queue selection
# ---------------------------------------------------------------------------

def _select_queue(conn, dialect: str, limit: int, channel_id: Optional[str]) -> list[dict]:
    if dialect == "pg":
        ph = "%s"
    else:
        ph = "?"

    sql = f"""
        SELECT
            cci.id,
            cci.external_content_id,
            cci.source_url,
            cci.title,
            cci.source_account_id,
            cci.source_account_handle,
            cci.published_at,
            cci.transcript_status,
            cci.transcript_priority
        FROM canonical_content_items cci
        WHERE cci.transcript_status = 'needed'
          AND cci.transcript_priority = 'high'
          AND cci.source_platform = 'youtube'
    """
    params: list = []
    if channel_id:
        sql += f"  AND cci.source_account_id = {ph}\n"
        params.append(channel_id)
    sql += f"ORDER BY cci.published_at DESC\nLIMIT {ph}"
    params.append(limit)

    cur = _cursor(conn, dialect)
    cur.execute(sql, params)
    rows = _fetchall_dict(cur, dialect)
    cur.close()
    return rows


# ---------------------------------------------------------------------------
# Transcript write
# ---------------------------------------------------------------------------

def _upsert_transcript(
    conn,
    dialect: str,
    content_item_id: str,
    transcript_text: Optional[str],
    language: Optional[str],
    word_count: Optional[int],
    processing_ms: Optional[int],
    error: Optional[str],
) -> None:
    if dialect == "pg":
        import psycopg2.extras  # noqa: F401
        sql = """
            INSERT INTO content_transcripts
                (content_item_id, transcript_source, transcript_text,
                 language, fetched_at, word_count, processing_ms, error)
            VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s)
            ON CONFLICT (content_item_id) DO UPDATE SET
                transcript_source = EXCLUDED.transcript_source,
                transcript_text   = EXCLUDED.transcript_text,
                language          = EXCLUDED.language,
                fetched_at        = EXCLUDED.fetched_at,
                word_count        = EXCLUDED.word_count,
                processing_ms     = EXCLUDED.processing_ms,
                error             = EXCLUDED.error
        """
        params = (content_item_id, TRANSCRIPT_SOURCE, transcript_text,
                  language, word_count, processing_ms, error)
    else:
        # SQLite: no gen_random_uuid(), use manual UUID
        import uuid
        sql = """
            INSERT OR REPLACE INTO content_transcripts
                (id, content_item_id, transcript_source, transcript_text,
                 language, fetched_at, word_count, processing_ms, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (str(uuid.uuid4()), content_item_id, TRANSCRIPT_SOURCE, transcript_text,
                  language, _now_iso(), word_count, processing_ms, error)

    cur = _cursor(conn, dialect)
    cur.execute(sql, params)
    cur.close()


def _update_status(conn, dialect: str, content_item_id: str, status: str) -> None:
    ph = "%s" if dialect == "pg" else "?"
    sql = f"""
        UPDATE canonical_content_items
        SET transcript_status = {ph}
        WHERE id = {ph}
    """
    cur = _cursor(conn, dialect)
    cur.execute(sql, (status, content_item_id))
    cur.close()


# ---------------------------------------------------------------------------
# Per-video fetch
# ---------------------------------------------------------------------------

def _fetch_one(row: dict, dry_run: bool, conn, dialect: str) -> str:
    """Fetch transcript for one queued video. Returns final transcript_status."""
    content_item_id: str = row["id"]
    title: str = (row.get("title") or "")
    channel: str = (row.get("source_account_handle") or row.get("source_account_id") or "")
    published_at: str = str(row.get("published_at") or "")

    video_id = _extract_video_id(row)
    if not video_id:
        _log(
            video_id=content_item_id,
            title=title,
            channel=channel,
            status="failed",
            length=None,
            source=None,
            language=None,
            error="could not extract video_id from row",
            dry_run=dry_run,
        )
        if not dry_run:
            _upsert_transcript(conn, dialect, content_item_id,
                               None, None, None, None,
                               "could not extract video_id")
            _update_status(conn, dialect, content_item_id, "failed")
            conn.commit()
        return "failed"

    if dry_run:
        _log(
            video_id=video_id,
            title=title,
            channel=channel,
            status="queued",
            length=None,
            source=TRANSCRIPT_SOURCE,
            language=None,
            dry_run=True,
        )
        return "queued"

    # --- real fetch ---
    # v1.x API: instance-based, api.list() / api.fetch()
    api = YouTubeTranscriptApi()
    t0 = time.perf_counter()
    try:
        transcript_list = api.list(video_id)
        # Prefer manually-created English transcript, fall back to auto-generated, then any
        lang: Optional[str] = None
        try:
            transcript = transcript_list.find_manually_created_transcript(["en"])
            lang = getattr(transcript, "language_code", "en")
        except Exception:
            try:
                transcript = transcript_list.find_generated_transcript(["en"])
                lang = getattr(transcript, "language_code", "en")
            except Exception:
                transcript = next(iter(transcript_list))
                lang = getattr(transcript, "language_code", None)

        segments = transcript.fetch()
        processing_ms = int((time.perf_counter() - t0) * 1000)

        # v1.x segments: each may be a FetchedTranscriptSnippet object or dict
        text = _join_segments([
            {"text": getattr(s, "text", s.get("text", "") if isinstance(s, dict) else "")}
            for s in segments
        ])
        word_count = len(text.split()) if text else 0

        _upsert_transcript(conn, dialect, content_item_id,
                           text, lang, word_count, processing_ms, None)
        _update_status(conn, dialect, content_item_id, "fetched")
        conn.commit()

        _log(
            video_id=video_id,
            title=title,
            channel=channel,
            status="fetched",
            length=len(text),
            source=TRANSCRIPT_SOURCE,
            language=lang,
        )
        return "fetched"

    except (RequestBlocked, IpBlocked) as exc:
        # IP-level block from YouTube — do NOT change transcript_status, abort entire run
        err_msg = f"[ABORT] {type(exc).__name__}: YouTube is blocking requests from this IP."
        print(f"[fetch_transcripts] CRITICAL {err_msg}", file=sys.stderr)
        print(
            "[fetch_transcripts] No status updated — queue preserved. "
            "Run from a different IP (local machine / VPN).",
            file=sys.stderr,
        )
        conn.close()
        sys.exit(2)

    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, AgeRestricted) as exc:
        processing_ms = int((time.perf_counter() - t0) * 1000)
        err_msg = type(exc).__name__

        _upsert_transcript(conn, dialect, content_item_id,
                           None, None, None, processing_ms, err_msg)
        _update_status(conn, dialect, content_item_id, "unavailable")
        conn.commit()

        _log(
            video_id=video_id,
            title=title,
            channel=channel,
            status="unavailable",
            length=None,
            source=TRANSCRIPT_SOURCE,
            language=None,
            error=err_msg,
        )
        return "unavailable"

    except CouldNotRetrieveTranscript as exc:
        processing_ms = int((time.perf_counter() - t0) * 1000)
        err_msg = str(exc)[:400]

        _upsert_transcript(conn, dialect, content_item_id,
                           None, None, None, processing_ms, err_msg)
        _update_status(conn, dialect, content_item_id, "unavailable")
        conn.commit()

        _log(
            video_id=video_id,
            title=title,
            channel=channel,
            status="unavailable",
            length=None,
            source=TRANSCRIPT_SOURCE,
            language=None,
            error=err_msg,
        )
        return "unavailable"

    except Exception as exc:  # noqa: BLE001
        processing_ms = int((time.perf_counter() - t0) * 1000)
        err_msg = f"{type(exc).__name__}: {exc}"[:400]

        _upsert_transcript(conn, dialect, content_item_id,
                           None, None, None, processing_ms, err_msg)
        _update_status(conn, dialect, content_item_id, "failed")
        conn.commit()

        _log(
            video_id=video_id,
            title=title,
            channel=channel,
            status="failed",
            length=None,
            source=TRANSCRIPT_SOURCE,
            language=None,
            error=err_msg,
        )
        return "failed"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch YouTube transcripts for queued videos.")
    ap.add_argument("--limit", type=int, default=5,
                    help="Maximum number of videos to process (default: 5)")
    ap.add_argument("--channel-id", default=None,
                    help="Restrict to a specific YouTube channel_id (UC...)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan without fetching or writing anything")
    args = ap.parse_args()

    conn, dialect = _get_conn()

    try:
        rows = _select_queue(conn, dialect, args.limit, args.channel_id)
    except Exception as exc:
        print(f"[fetch_transcripts] ERROR selecting queue: {exc}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    if not rows:
        print("[fetch_transcripts] Queue is empty — nothing to process.")
        conn.close()
        return

    mode = "dry-run" if args.dry_run else "fetch"
    channel_filter = f" channel_id={args.channel_id}" if args.channel_id else ""
    print(f"[fetch_transcripts] mode={mode} limit={args.limit}{channel_filter} queued={len(rows)}")

    counts: dict[str, int] = {"fetched": 0, "unavailable": 0, "failed": 0, "queued": 0}
    for row in rows:
        status = _fetch_one(row, dry_run=args.dry_run, conn=conn, dialect=dialect)
        counts[status] = counts.get(status, 0) + 1

    conn.close()

    summary = " | ".join(f"{k}={v}" for k, v in counts.items() if v > 0)
    print(f"[fetch_transcripts] Done. {summary}")


if __name__ == "__main__":
    main()
