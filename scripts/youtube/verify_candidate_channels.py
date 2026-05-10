#!/usr/bin/env python3
"""
YT-CREATOR-EXPANSION-01 — Verify YouTube creator channel candidates.

Resolves each candidate to a canonical channel_id, checks recent activity,
deduplicates against the existing youtube_channels table, and outputs a
decision report.

Usage:
    python3 scripts/youtube/verify_candidate_channels.py [options]

Options:
    --api-key KEY       YouTube Data API v3 key (default: $YOUTUBE_API_KEY)
    --db-url URL        PostgreSQL URL for dedup check (default: $DATABASE_URL or
                        $DATABASE_PUBLIC_URL). Pass --no-db to skip.
    --no-db             Skip DB dedup check (dry-run mode)
    --output-dir DIR    Directory for reports (default: reports/)
    --batch BATCH       Intake batch label (default: YT-CREATOR-EXPANSION-01)

Outputs:
    reports/youtube_candidate_intake_YYYY-MM-DD.md
    reports/youtube_candidate_intake_YYYY-MM-DD.csv

Decisions:
    ADD                  Resolved, active (>=1 video/30d), not a duplicate
    SKIP_DUPLICATE       channel_id already in youtube_channels table
    SKIP_INACTIVE_30D    No videos in last 30 days
    NEEDS_OPERATOR_REVIEW  Search match confidence low; manual check required
    RESOLVE_FAILED       Could not resolve to a channel_id
"""

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote_plus

import requests

# ---------------------------------------------------------------------------
# Candidate list
# ---------------------------------------------------------------------------

CANDIDATES = [
    {"name": "Seldomly Often",                 "url": "https://www.youtube.com/results?search_query=seldomly+often+fragrance"},
    {"name": "The Scented",                    "url": "https://www.youtube.com/@TheScented"},
    {"name": "Clémence CC Fragrance",          "url": "https://www.youtube.com/@ClemenceCC"},
    {"name": "The Niche Fragrance Collector",  "url": "https://www.youtube.com/@TheNicheFragranceCollector"},
    {"name": "Des Paons Dansent Cent Heures",  "url": "https://www.youtube.com/results?search_query=des+paons+dansent+cent+heures"},
    {"name": "Scent Land (Chris)",             "url": "https://www.youtube.com/results?search_query=scent+land+chris+perfume"},
    {"name": "Fragmental",                     "url": "https://www.youtube.com/results?search_query=fragmental+perfume"},
    {"name": "Christopher Lee Fragrances",     "url": "https://www.youtube.com/@ChristopherLeeFragrances"},
    {"name": "Soki London",                    "url": "https://www.youtube.com/@SokiLondon"},
    {"name": "The Perfume Guy (Sebastian)",    "url": "https://www.youtube.com/results?search_query=perfume+guy+sebastian"},
    {"name": "Smelling Great Fragrance Reviews","url": "https://www.youtube.com/results?search_query=smelling+great+fragrance+sebastian"},
    {"name": "Eva Monroe",                     "url": "https://www.youtube.com/results?search_query=eva+monroe+fragrance"},
    {"name": "Paulina Schar",                  "url": "https://www.youtube.com/results?search_query=paulina+schar+fragrance"},
    {"name": "Delicious Delights",             "url": "https://www.youtube.com/@DeliciousDelights"},
    {"name": "Gabby Loves Perfume",            "url": "https://www.youtube.com/results?search_query=gabby+loves+perfume"},
    {"name": "MAGS FRAGS",                     "url": "https://www.youtube.com/@MAGSFRAGS"},
    {"name": "Fragrance Connoisseurs",         "url": "https://www.youtube.com/@FragranceConnoisseurs"},
    {"name": "The Honest Perfume Reviewer",    "url": "https://www.youtube.com/@TheHonestPerfumeReviewer"},
    {"name": "G Fragrance",                    "url": "https://www.youtube.com/@GFragrance"},
    {"name": "The Fragrance Channel (Ryan)",   "url": "https://www.youtube.com/@TheFragranceChannel"},
]

# ---------------------------------------------------------------------------
# YouTube API helper
# ---------------------------------------------------------------------------

YT_BASE = "https://www.googleapis.com/youtube/v3"


def _yt_get(endpoint: str, params: dict, api_key: str) -> dict:
    params["key"] = api_key
    r = requests.get(f"{YT_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def resolve_by_handle(handle: str, api_key: str) -> "Optional[dict]":
    """Return channel item dict from channels.list forHandle, or None."""
    handle = handle.lstrip("@")
    data = _yt_get("channels", {
        "forHandle": handle,
        "part": "snippet,statistics,contentDetails",
        "maxResults": 1,
    }, api_key)
    items = data.get("items", [])
    return items[0] if items else None


def resolve_by_search(query: str, candidate_name: str, api_key: str) -> tuple:
    """
    Search for a channel matching candidate_name.
    Returns (channel_item_or_None, confidence: "high"|"medium"|"low").
    """
    data = _yt_get("search", {
        "q": query,
        "type": "channel",
        "part": "snippet",
        "maxResults": 5,
    }, api_key)
    items = data.get("items", [])
    if not items:
        return None, "low"

    # Score each result against the candidate name
    best_item = None
    best_score = 0.0
    for item in items:
        title = item["snippet"]["channelTitle"]
        score = _name_similarity(candidate_name, title)
        if score > best_score:
            best_score = score
            best_item = item

    if best_score < 0.45:
        return None, "low"
    confidence = "high" if best_score >= 0.75 else "medium"

    # Fetch full channel details (statistics + contentDetails)
    channel_id = best_item["id"]["channelId"]
    detail = _yt_get("channels", {
        "id": channel_id,
        "part": "snippet,statistics,contentDetails",
    }, api_key)
    detail_items = detail.get("items", [])
    if not detail_items:
        return None, "low"
    return detail_items[0], confidence


def get_recent_video_count(uploads_playlist_id: str, api_key: str, days: int = 30) -> tuple[int, list[str]]:
    """
    Return (count_in_last_N_days, sample_titles) from the uploads playlist.
    Fetches up to 15 most recent items and checks publishedAt.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    data = _yt_get("playlistItems", {
        "playlistId": uploads_playlist_id,
        "part": "snippet",
        "maxResults": 15,
    }, api_key)
    items = data.get("items", [])
    count = 0
    titles = []
    for item in items:
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
# URL parsing
# ---------------------------------------------------------------------------

def parse_candidate_url(url: str) -> tuple:
    """
    Returns (url_type, value).
    url_type: "handle" | "search" | "channel_id" | "unknown"
    value: handle string (with @), search query, channel_id, or None
    """
    parsed = urlparse(url)
    path = parsed.path

    # Direct channel_id: /channel/UCxxx
    if path.startswith("/channel/UC"):
        cid = path.split("/channel/")[1].rstrip("/")
        return "channel_id", cid

    # @handle: /@handle or just /handle on youtube.com
    if path.startswith("/@"):
        return "handle", path[2:].split("/")[0]  # strip leading @ and trailing path

    # Search results page
    if path == "/results":
        qs = parse_qs(parsed.query)
        q = qs.get("search_query", [""])[0]
        return "search", unquote_plus(q) if q else None

    # /c/name or /user/name — legacy; treat as search
    if path.startswith("/c/") or path.startswith("/user/"):
        name = re.split(r"[/]", path.lstrip("/"), maxsplit=2)[1]
        return "search", name

    return "unknown", None


# ---------------------------------------------------------------------------
# Name similarity
# ---------------------------------------------------------------------------

_NOISE_WORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "at", "by", "for",
    "fragrance", "fragrances", "perfume", "perfumes", "review", "reviews",
    "scent", "scents", "channel", "official", "beauty", "makeup", "niche",
    "collector", "connoisseur", "connoisseurs", "international",
})


def _normalise(s: str) -> str:
    """Lowercase, strip accents, remove bracketed qualifiers, remove noise words."""
    s = re.sub(r"\([^)]*\)", "", s)           # remove (Sebastian), (Ryan), (Chris)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    tokens = [t for t in s.split() if t not in _NOISE_WORDS and len(t) >= 2]
    return " ".join(tokens)


def _name_similarity(candidate: str, title: str) -> float:
    """
    Returns 0.0–1.0 similarity score.
    Uses token overlap: what fraction of candidate tokens appear in title tokens.
    """
    cn = _normalise(candidate)
    tn = _normalise(title)
    if not cn:
        return 0.0
    c_tokens = set(cn.split())
    t_tokens = set(tn.split())
    if not c_tokens:
        return 0.0
    # Fraction of candidate tokens found in title
    overlap = len(c_tokens & t_tokens) / len(c_tokens)
    # Bonus: if candidate is a substring of title (handles short unique names)
    if cn in tn or tn in cn:
        overlap = max(overlap, 0.9)
    return overlap


# ---------------------------------------------------------------------------
# DB dedup check
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
# Tier assignment
# ---------------------------------------------------------------------------

def assign_tier(subscriber_count: "Optional[int]") -> str:
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
# Main verification loop
# ---------------------------------------------------------------------------

def verify_candidates(
    api_key: str,
    existing_ids: set[str],
    batch: str,
) -> list[dict]:
    results = []
    for c in CANDIDATES:
        name = c["name"]
        url = c["url"]
        print(f"  → {name}", flush=True)

        url_type, value = parse_candidate_url(url)
        channel_item = None
        confidence = "high"
        resolve_method = url_type

        try:
            if url_type == "handle":
                channel_item = resolve_by_handle(value, api_key)
                if channel_item is None:
                    confidence = "low"
            elif url_type == "channel_id":
                data = _yt_get("channels", {
                    "id": value,
                    "part": "snippet,statistics,contentDetails",
                }, api_key)
                items = data.get("items", [])
                channel_item = items[0] if items else None
            elif url_type == "search" and value:
                channel_item, confidence = resolve_by_search(value, name, api_key)
                resolve_method = "search"
            else:
                confidence = "low"
        except requests.HTTPError as exc:
            print(f"    [api_error] {exc}", file=sys.stderr)
            results.append(_make_result(name, url, resolve_method, None, confidence,
                                        "RESOLVE_FAILED", f"API error: {exc}", batch))
            continue

        if channel_item is None:
            results.append(_make_result(name, url, resolve_method, None, confidence,
                                        "RESOLVE_FAILED" if confidence == "high" else "NEEDS_OPERATOR_REVIEW",
                                        "Could not resolve to a channel_id", batch))
            continue

        # Extract metadata
        channel_id = channel_item["id"]
        snippet = channel_item.get("snippet", {})
        stats = channel_item.get("statistics", {})
        content = channel_item.get("contentDetails", {})

        title = snippet.get("title", "")
        handle = snippet.get("customUrl", "")  # @handle returned here by API
        subscriber_count = int(stats.get("subscriberCount", 0)) if stats.get("subscriberCount") else None
        video_count = int(stats.get("videoCount", 0)) if stats.get("videoCount") else None
        uploads_playlist_id = content.get("relatedPlaylists", {}).get("uploads", "")

        # Activity check
        recent_count = 0
        recent_titles: list[str] = []
        if uploads_playlist_id:
            try:
                recent_count, recent_titles = get_recent_video_count(uploads_playlist_id, api_key)
            except requests.HTTPError as exc:
                print(f"    [activity_error] {exc}", file=sys.stderr)

        # Dedup check
        if channel_id in existing_ids:
            decision = "SKIP_DUPLICATE"
            reason = f"channel_id {channel_id} already in youtube_channels"
        elif confidence == "low":
            decision = "NEEDS_OPERATOR_REVIEW"
            reason = "Low confidence search match — manual verification required"
        elif confidence == "medium":
            decision = "NEEDS_OPERATOR_REVIEW"
            reason = f"Medium confidence search match (title: '{title}') — operator should confirm identity"
        elif recent_count == 0:
            decision = "SKIP_INACTIVE_30D"
            reason = "No videos published in last 30 days"
        else:
            decision = "ADD"
            reason = f"{recent_count} video(s) in last 30 days"

        results.append(_make_result(
            name, url, resolve_method, channel_item, confidence, decision, reason, batch,
            channel_id=channel_id, title=title, handle=handle,
            subscriber_count=subscriber_count, video_count=video_count,
            uploads_playlist_id=uploads_playlist_id,
            recent_count=recent_count, recent_titles=recent_titles,
        ))

    return results


def _make_result(
    name: str,
    url: str,
    resolve_method: str,
    channel_item,
    confidence: str,
    decision: str,
    reason: str,
    batch: str,
    channel_id: str = "",
    title: str = "",
    handle: str = "",
    subscriber_count=None,
    video_count=None,
    uploads_playlist_id: str = "",
    recent_count: int = 0,
    recent_titles: "Optional[list]" = None,
) -> dict:
    return {
        "candidate_name": name,
        "input_url": url,
        "resolve_method": resolve_method,
        "channel_id": channel_id,
        "title": title,
        "handle": handle,
        "subscriber_count": subscriber_count,
        "video_count": video_count,
        "recent_video_count_30d": recent_count,
        "recent_video_titles_sample": "; ".join(recent_titles or []),
        "confidence": confidence,
        "decision": decision,
        "reason": reason,
        "intake_batch": batch,
        "quality_tier": assign_tier(subscriber_count),
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def write_reports(results: list[dict], output_dir: str, date_str: str) -> tuple[str, str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    md_path = f"{output_dir}/youtube_candidate_intake_{date_str}.md"
    csv_path = f"{output_dir}/youtube_candidate_intake_{date_str}.csv"

    # Decision counts
    by_decision: dict[str, list] = {}
    for r in results:
        by_decision.setdefault(r["decision"], []).append(r)

    # --- Markdown ---
    with open(md_path, "w") as f:
        f.write(f"# YT-CREATOR-EXPANSION-01 — YouTube Creator Channel Intake\n\n")
        f.write(f"**Date:** {date_str}  \n")
        f.write(f"**Candidates reviewed:** {len(results)}  \n")
        f.write(f"**ADD:** {len(by_decision.get('ADD', []))}  \n")
        f.write(f"**SKIP_DUPLICATE:** {len(by_decision.get('SKIP_DUPLICATE', []))}  \n")
        f.write(f"**SKIP_INACTIVE_30D:** {len(by_decision.get('SKIP_INACTIVE_30D', []))}  \n")
        f.write(f"**NEEDS_OPERATOR_REVIEW:** {len(by_decision.get('NEEDS_OPERATOR_REVIEW', []))}  \n")
        f.write(f"**RESOLVE_FAILED:** {len(by_decision.get('RESOLVE_FAILED', []))}  \n\n")
        f.write("---\n\n")

        f.write("## Decision Table\n\n")
        f.write("| Candidate | channel_id | Title | Subs | Videos/30d | Decision | Reason |\n")
        f.write("|-----------|-----------|-------|------|-----------|----------|--------|\n")
        for r in results:
            subs = f"{r['subscriber_count']:,}" if r["subscriber_count"] else "—"
            f.write(
                f"| {r['candidate_name']} "
                f"| {r['channel_id'] or '—'} "
                f"| {r['title'] or '—'} "
                f"| {subs} "
                f"| {r['recent_video_count_30d']} "
                f"| **{r['decision']}** "
                f"| {r['reason']} |\n"
            )

        f.write("\n---\n\n")

        for decision_label in ["ADD", "SKIP_DUPLICATE", "SKIP_INACTIVE_30D", "NEEDS_OPERATOR_REVIEW", "RESOLVE_FAILED"]:
            rows = by_decision.get(decision_label, [])
            if not rows:
                continue
            f.write(f"## {decision_label} ({len(rows)})\n\n")
            for r in rows:
                f.write(f"### {r['candidate_name']}\n")
                f.write(f"- **channel_id:** `{r['channel_id'] or 'unresolved'}`\n")
                f.write(f"- **title:** {r['title'] or '—'}\n")
                f.write(f"- **handle:** {r['handle'] or '—'}\n")
                f.write(f"- **subscribers:** {r['subscriber_count']:,}\n" if r["subscriber_count"] else "- **subscribers:** —\n")
                f.write(f"- **total videos:** {r['video_count'] or '—'}\n")
                f.write(f"- **videos last 30d:** {r['recent_video_count_30d']}\n")
                if r["recent_video_titles_sample"]:
                    f.write(f"- **recent titles sample:** {r['recent_video_titles_sample']}\n")
                f.write(f"- **resolve method:** {r['resolve_method']}\n")
                f.write(f"- **confidence:** {r['confidence']}\n")
                f.write(f"- **reason:** {r['reason']}\n")
                f.write(f"- **quality_tier (assigned):** {r['quality_tier']}\n")
                f.write("\n")

    # --- CSV ---
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

def main():
    parser = argparse.ArgumentParser(description="YT-CREATOR-EXPANSION-01 channel verification")
    parser.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY", ""))
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--no-db", action="store_true", help="Skip DB dedup check")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--batch", default="YT-CREATOR-EXPANSION-01")
    args = parser.parse_args()

    if not args.api_key:
        print("[error] YOUTUBE_API_KEY not set. Pass --api-key or export the env var.", file=sys.stderr)
        sys.exit(1)

    date_str = datetime.now().strftime("%Y-%m-%d")

    # Load existing channel IDs for dedup
    existing_ids: set[str] = set()
    if not args.no_db and args.db_url:
        print("[dedup] Loading existing youtube_channels from DB…")
        existing_ids = load_existing_channel_ids(args.db_url)
        print(f"[dedup] {len(existing_ids)} existing channel_ids loaded.")
    elif not args.no_db:
        print("[warn] No DB URL found. Dedup check skipped. Duplicates may appear in ADD list.", file=sys.stderr)

    # Run verification
    print(f"\n[verify] Checking {len(CANDIDATES)} candidates via YouTube API…\n")
    results = verify_candidates(args.api_key, existing_ids, args.batch)

    # Print summary
    from collections import Counter
    counts = Counter(r["decision"] for r in results)
    print(f"\n[summary]")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")

    # Write reports
    md_path, csv_path = write_reports(results, args.output_dir, date_str)
    print(f"\n[report] {md_path}")
    print(f"[report] {csv_path}")

    # Print ADD list
    add_rows = [r for r in results if r["decision"] == "ADD"]
    if add_rows:
        print(f"\n[ADD candidates] {len(add_rows)} channels ready to register:")
        for r in add_rows:
            print(f"  {r['channel_id']}  {r['title']}  ({r['subscriber_count']:,} subs, {r['recent_video_count_30d']} videos/30d)")
    else:
        print("\n[ADD candidates] None — all candidates need review or are duplicates/inactive.")

    # Dump ADD candidates as JSON for seed script
    add_json_path = f"{args.output_dir}/youtube_candidate_add_{date_str}.json"
    with open(add_json_path, "w") as f:
        json.dump(add_rows, f, indent=2)
    print(f"[report] {add_json_path}  (ADD candidates for seed script)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
