#!/usr/bin/env python3
"""
Source Intake: Verify YouTube creator candidates from a CSV file.

Unlike verify_candidate_channels.py (which uses a hardcoded list + URL resolution),
this script reads from a CSV where channel_id is already known. It batch-fetches
current metadata from the YouTube API, checks recent activity, deduplicates against
youtube_channels, and persists results to source_intake_batches for operator review.

Usage:
    python3 scripts/youtube/verify_from_csv.py \\
        --csv data_inputs/fragrance_channels_reviewed_2026-05-10.csv \\
        --filter-status approved_creator_candidate \\
        --batch YT-CREATOR-EXPANSION-02-AGENT-APPROVED-136 \\
        --description "Agent-provided cleaned YouTube creator candidates" \\
        --persist

Options:
    --csv FILE             Path to CSV file (required)
    --filter-status STR    Only process rows with this review_status value
                           (default: approved_creator_candidate)
    --batch LABEL          Batch label for source_intake_batches
    --description TEXT     Human-readable batch description
    --api-key KEY          YouTube Data API v3 key (default: $YOUTUBE_API_KEY)
    --db-url URL           PostgreSQL URL (default: $DATABASE_PUBLIC_URL or $DATABASE_URL)
    --no-db                Skip DB dedup check
    --persist              Write results to source_intake_batches DB
    --output-dir DIR       Directory for report files (default: reports/)
    --activity-days N      Days of recent activity to check (default: 30)

CSV columns used:
    channel_id (required)     UC... YouTube channel ID
    title                     Channel display name from agent
    url                       Channel URL (informational)
    subscriber_count_estimate Estimated subscriber count (used as fallback)
    review_status             Filter column (e.g. approved_creator_candidate)
    description               Channel description (stored as notes)

Decisions:
    VERIFIED_ADD_READY       Active channel, not a duplicate, high confidence
    SKIP_DUPLICATE           channel_id already in youtube_channels table
    SKIP_INACTIVE            No videos in last N days
    NEEDS_OPERATOR_REVIEW    API returned no data, or channel private/deleted
    ERROR                    Unexpected exception during processing
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

YT_BASE = "https://www.googleapis.com/youtube/v3"

# ---------------------------------------------------------------------------
# YouTube API helpers
# ---------------------------------------------------------------------------

def _yt_get(endpoint: str, params: dict, api_key: str) -> dict:
    params = dict(params, key=api_key)
    r = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def batch_fetch_channel_metadata(channel_ids: list[str], api_key: str) -> dict[str, dict]:
    """
    Fetch snippet + statistics + contentDetails for up to 50 channel_ids per call.
    Returns dict keyed by channel_id.
    """
    result: dict[str, dict] = {}
    batch_size = 50
    for i in range(0, len(channel_ids), batch_size):
        batch = channel_ids[i : i + batch_size]
        data = _yt_get("channels", {
            "id": ",".join(batch),
            "part": "snippet,statistics,contentDetails",
        }, api_key)
        for item in data.get("items", []):
            result[item["id"]] = item
    return result


def get_recent_video_count(uploads_playlist_id: str, api_key: str, days: int) -> tuple[int, list[str]]:
    """Return (count_last_N_days, sample_titles)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        data = _yt_get("playlistItems", {
            "playlistId": uploads_playlist_id,
            "part": "snippet",
            "maxResults": 15,
        }, api_key)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return 0, []  # playlist not found (private/deleted)
        raise

    count = 0
    titles: list[str] = []
    for item in data.get("items", []):
        published = item["snippet"].get("publishedAt", "")
        if not published:
            continue
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if pub_dt >= cutoff:
            count += 1
            title = item["snippet"].get("title", "")
            if title and title != "Deleted video":
                titles.append(title)
    return count, titles[:3]


# ---------------------------------------------------------------------------
# Tier assignment (same as verify_candidate_channels.py)
# ---------------------------------------------------------------------------

def assign_tier(subscriber_count: Optional[int]) -> str:
    if subscriber_count is None:
        return "tier_4"
    if subscriber_count >= 500_000:
        return "tier_1"
    if subscriber_count >= 50_000:
        return "tier_2"
    if subscriber_count >= 10_000:
        return "tier_3"
    return "tier_4"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def load_existing_channel_ids(db_url: str) -> set[str]:
    """Return set of channel_ids already in youtube_channels."""
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT channel_id FROM youtube_channels")
        rows = cur.fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception as exc:
        print(f"[warn] DB dedup check failed: {exc}", file=sys.stderr)
        return set()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_from_csv(
    csv_path: str,
    filter_status: str,
    api_key: str,
    existing_ids: set[str],
    batch_label: str,
    activity_days: int,
) -> list[dict]:
    """
    Read CSV, filter by review_status, fetch YouTube metadata, check activity,
    dedup, and return a list of result dicts.
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    candidates = [r for r in all_rows if r.get("review_status", "").strip() == filter_status]
    print(f"[csv] {len(all_rows)} total rows, {len(candidates)} with review_status={filter_status!r}")

    if not candidates:
        return []

    channel_ids = [r["channel_id"].strip() for r in candidates]

    # --- Batch-fetch current metadata from YouTube API ---
    print(f"[api] Fetching metadata for {len(channel_ids)} channel_ids in batches of 50…")
    metadata: dict[str, dict] = {}
    try:
        metadata = batch_fetch_channel_metadata(channel_ids, api_key)
    except requests.HTTPError as exc:
        print(f"[api_error] batch_fetch_channel_metadata: {exc}", file=sys.stderr)
    print(f"[api] Received metadata for {len(metadata)} / {len(channel_ids)} channels")

    # --- Process each candidate ---
    results = []
    for idx, row in enumerate(candidates, 1):
        cid = row["channel_id"].strip()
        csv_title = row.get("title", "").strip()
        csv_url = row.get("url", "").strip()
        csv_subs_est = row.get("subscriber_count_estimate", "").strip()
        csv_description = row.get("description", "").strip()

        print(f"  [{idx}/{len(candidates)}] {csv_title or cid}", flush=True)

        item = metadata.get(cid)

        # If API returned no data for this channel
        if item is None:
            results.append({
                "candidate_name": csv_title or cid,
                "input_url": csv_url,
                "channel_id": cid,
                "title": csv_title,
                "handle": "",
                "subscriber_count": int(csv_subs_est) if csv_subs_est.isdigit() else None,
                "video_count": None,
                "recent_video_count_30d": 0,
                "recent_video_titles_sample": "",
                "resolve_method": "channel_id_direct",
                "confidence": "low",
                "decision": "NEEDS_OPERATOR_REVIEW",
                "reason": "YouTube API returned no data for channel_id (private, deleted, or rate-limited)",
                "intake_batch": batch_label,
                "quality_tier": assign_tier(int(csv_subs_est) if csv_subs_est.isdigit() else None),
                "notes": csv_description,
            })
            continue

        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})

        title = snippet.get("title", csv_title)
        handle = snippet.get("customUrl", "")
        subscriber_count = int(stats["subscriberCount"]) if stats.get("subscriberCount") else None
        video_count = int(stats["videoCount"]) if stats.get("videoCount") else None
        uploads_playlist_id = content.get("relatedPlaylists", {}).get("uploads", "")

        # Activity check
        recent_count = 0
        recent_titles: list[str] = []
        if uploads_playlist_id:
            try:
                recent_count, recent_titles = get_recent_video_count(
                    uploads_playlist_id, api_key, activity_days
                )
            except requests.HTTPError as exc:
                print(f"    [activity_warn] {exc}", file=sys.stderr)

        # Decision
        if cid in existing_ids:
            decision = "SKIP_DUPLICATE"
            reason = f"channel_id {cid} already in youtube_channels"
        elif recent_count == 0:
            decision = "SKIP_INACTIVE"
            reason = f"No videos published in last {activity_days} days"
        else:
            decision = "VERIFIED_ADD_READY"
            reason = f"{recent_count} video(s) in last {activity_days} days (channel_id pre-validated)"

        tier = assign_tier(subscriber_count)

        results.append({
            "candidate_name": csv_title or title,
            "input_url": csv_url,
            "channel_id": cid,
            "title": title,
            "handle": handle,
            "subscriber_count": subscriber_count,
            "video_count": video_count,
            "recent_video_count_30d": recent_count,
            "recent_video_titles_sample": "; ".join(recent_titles),
            "resolve_method": "channel_id_direct",
            "confidence": "high",
            "decision": decision,
            "reason": reason,
            "intake_batch": batch_label,
            "quality_tier": tier,
            "notes": csv_description,
        })

    return results


# ---------------------------------------------------------------------------
# DB persist
# ---------------------------------------------------------------------------

def _persist_to_db(
    results: list[dict],
    batch_label: str,
    batch_description: str,
    db_url: str,
) -> str:
    """Insert batch + candidates + initial audit log entries. Returns batch_id."""
    import psycopg2

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    _STATUS_MAP = {
        "VERIFIED_ADD_READY": "VERIFIED_ADD_READY",
        "SKIP_DUPLICATE": "SKIP_DUPLICATE",
        "SKIP_INACTIVE": "SKIP_INACTIVE",
        "NEEDS_OPERATOR_REVIEW": "NEEDS_OPERATOR_REVIEW",
        "ERROR": "NEEDS_OPERATOR_REVIEW",
    }

    # Check for existing batch with same label first
    cur.execute("SELECT id FROM source_intake_batches WHERE batch_label = %s", (batch_label,))
    existing_batch = cur.fetchone()
    if existing_batch:
        conn.close()
        raise ValueError(
            f"Batch label {batch_label!r} already exists in source_intake_batches "
            f"(id={existing_batch[0]}). Choose a different batch label or "
            "delete the existing batch first."
        )

    batch_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO source_intake_batches
            (id, batch_label, platform, status, description, candidate_count, applied_count, created_at, created_by)
        VALUES (%s, %s, %s, 'open', %s, %s, 0, NOW(), %s)
    """, (batch_id, batch_label, "youtube", batch_description, len(results),
          "cli:verify_from_csv"))

    for r in results:
        status = _STATUS_MAP.get(r["decision"], "NEEDS_OPERATOR_REVIEW")
        cid = str(uuid.uuid4())
        sample = r.get("recent_video_titles_sample", "")
        titles_json = json.dumps(sample.split("; ")) if sample else None

        cur.execute("""
            INSERT INTO source_intake_candidates
                (id, batch_id, platform, candidate_name, input_url,
                 resolved_platform_id, resolved_title, subscriber_count,
                 total_content_count, recent_content_count, recent_titles_sample,
                 resolve_method, confidence, status, decision_reason, quality_tier, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            cid, batch_id, "youtube",
            r["candidate_name"], r.get("input_url") or r.get("channel_id"),
            r.get("channel_id") or None,
            r.get("title") or None,
            r.get("subscriber_count"),
            r.get("video_count"),
            r.get("recent_video_count_30d", 0),
            titles_json,
            r.get("resolve_method", "channel_id_direct"),
            r.get("confidence", "high"),
            status,
            r.get("reason"),
            r.get("quality_tier"),
        ))

        cur.execute("""
            INSERT INTO source_intake_audit_log
                (id, candidate_id, actor, action, old_status, new_status, notes, created_at)
            VALUES (%s, %s, %s, %s, NULL, %s, %s, NOW())
        """, (
            str(uuid.uuid4()), cid,
            "cli:verify_from_csv", "initial_classification",
            status, r.get("reason"),
        ))

    conn.commit()
    conn.close()
    return batch_id


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def write_reports(results: list[dict], output_dir: str, batch_label: str) -> tuple[str, str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = batch_label.lower().replace(" ", "_").replace("/", "_")
    md_path = f"{output_dir}/source_intake_{slug}_{date_str}.md"
    csv_path = f"{output_dir}/source_intake_{slug}_{date_str}.csv"

    by_decision: dict[str, list] = {}
    for r in results:
        by_decision.setdefault(r["decision"], []).append(r)

    with open(md_path, "w") as f:
        f.write(f"# Source Intake: {batch_label}\n\n")
        f.write(f"**Date:** {date_str}  \n")
        f.write(f"**Candidates processed:** {len(results)}  \n")
        for label in ["VERIFIED_ADD_READY", "SKIP_DUPLICATE", "SKIP_INACTIVE",
                      "NEEDS_OPERATOR_REVIEW", "ERROR"]:
            f.write(f"**{label}:** {len(by_decision.get(label, []))}  \n")
        f.write("\n---\n\n")

        for label in ["VERIFIED_ADD_READY", "SKIP_DUPLICATE", "SKIP_INACTIVE",
                      "NEEDS_OPERATOR_REVIEW", "ERROR"]:
            rows = by_decision.get(label, [])
            if not rows:
                continue
            f.write(f"## {label} ({len(rows)})\n\n")
            f.write("| channel_id | Title | Subs | Videos/30d | Reason |\n")
            f.write("|-----------|-------|------|-----------|--------|\n")
            for r in rows:
                subs = f"{r['subscriber_count']:,}" if r["subscriber_count"] else "—"
                f.write(
                    f"| `{r['channel_id']}` | {r['title'] or r['candidate_name']} "
                    f"| {subs} | {r['recent_video_count_30d']} | {r['reason']} |\n"
                )
            f.write("\n")

    csv_fields = [
        "candidate_name", "channel_id", "title", "handle",
        "subscriber_count", "video_count", "recent_video_count_30d",
        "recent_video_titles_sample", "resolve_method", "confidence",
        "decision", "reason", "quality_tier", "intake_batch",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    return md_path, csv_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Source Intake: verify YouTube creators from a CSV with pre-known channel_ids"
    )
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--filter-status", default="approved_creator_candidate",
                        help="Only process rows with this review_status (default: approved_creator_candidate)")
    parser.add_argument("--batch", required=True, help="Batch label for source_intake_batches")
    parser.add_argument("--description", default="",
                        help="Human-readable batch description")
    parser.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY", ""))
    parser.add_argument("--db-url",
                        default=os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--no-db", action="store_true", help="Skip DB dedup check")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--activity-days", type=int, default=30,
                        help="Days to check for recent activity (default: 30)")
    parser.add_argument("--persist", action="store_true",
                        help="Write results to source_intake_batches DB for admin review")
    args = parser.parse_args()

    if not args.api_key:
        print("[error] YOUTUBE_API_KEY not set", file=sys.stderr)
        return 1

    if not os.path.isfile(args.csv):
        print(f"[error] CSV not found: {args.csv}", file=sys.stderr)
        return 1

    # Load existing channel IDs for dedup
    existing_ids: set[str] = set()
    if not args.no_db and args.db_url:
        print("[dedup] Loading existing youtube_channels from DB…")
        existing_ids = load_existing_channel_ids(args.db_url)
        print(f"[dedup] {len(existing_ids)} existing channel_ids loaded.")
    else:
        print("[warn] DB dedup check skipped.", file=sys.stderr)

    print(f"\n[verify] Processing {args.csv} (filter_status={args.filter_status!r})\n")
    results = verify_from_csv(
        csv_path=args.csv,
        filter_status=args.filter_status,
        api_key=args.api_key,
        existing_ids=existing_ids,
        batch_label=args.batch,
        activity_days=args.activity_days,
    )

    if not results:
        print("[warn] No candidates matched the filter. Nothing to do.")
        return 0

    # Summary
    from collections import Counter
    counts = Counter(r["decision"] for r in results)
    print(f"\n[summary] {len(results)} candidates processed:")
    for k in ["VERIFIED_ADD_READY", "SKIP_DUPLICATE", "SKIP_INACTIVE",
              "NEEDS_OPERATOR_REVIEW", "ERROR"]:
        if counts.get(k):
            print(f"  {k}: {counts[k]}")

    # Reports
    md_path, csv_path = write_reports(results, args.output_dir, args.batch)
    print(f"\n[report] {md_path}")
    print(f"[report] {csv_path}")

    # Persist
    if args.persist:
        if not args.db_url:
            print("[persist] --persist requires --db-url or DATABASE_URL/DATABASE_PUBLIC_URL", file=sys.stderr)
            return 1
        try:
            batch_id = _persist_to_db(results, args.batch, args.description, args.db_url)
            print(f"\n[persist] Batch written to source_intake_batches")
            print(f"[persist]   batch_id = {batch_id}")
            print(f"[persist]   label    = {args.batch}")
            print(f"[persist]   Admin review: /admin/source-intake/{batch_id}")
        except Exception as exc:
            print(f"[persist_error] {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
