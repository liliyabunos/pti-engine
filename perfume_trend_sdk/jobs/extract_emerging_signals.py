"""Phase E3-A — Extract Emerging Signals (channel-aware, title-first).

Reads channel_poll canonical_content_items, extracts unresolved candidates
from video titles only (not descriptions), and upserts into emerging_signals.

Each run is a full recompute over the lookback window — idempotent.

Flow:
  canonical_content_items (ingestion_method='channel_poll', last N days)
    JOIN youtube_channels (quality_tier, title)
    → resolve title only
    → collect unresolved candidates per (phrase, channel)
    → aggregate stats per phrase
    → check is_in_resolver, is_in_entity_market
    → upsert emerging_signals

Run:
  python3 -m perfume_trend_sdk.jobs.extract_emerging_signals
  python3 -m perfume_trend_sdk.jobs.extract_emerging_signals --dry-run
  python3 -m perfume_trend_sdk.jobs.extract_emerging_signals --days 14 --limit 500
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel quality tier weights
# ---------------------------------------------------------------------------

_TIER_WEIGHTS: Dict[str, float] = {
    "tier_1": 3.0,
    "tier_2": 2.0,
    "tier_3": 1.0,
    "tier_4": 0.5,
    "unrated": 0.5,
    "blocked": 0.0,
}

# ---------------------------------------------------------------------------
# Boilerplate stripping — phrases that appear in channel descriptions / cta
# applied before candidate extraction when content is a title (but descriptions
# may leak in; this ensures even if text_content is set to title it's clean).
# ---------------------------------------------------------------------------

_TITLE_STOP_WORDS: frozenset[str] = frozenset({
    # Generic review vocabulary
    "review", "reviews", "reviewing",
    "first impression", "impressions",
    "unboxing", "haul", "collection",
    "ranking", "ranked", "tier list",
    "top", "best", "worst",
    "vs", "versus", "comparison", "compared",
    "cheap", "expensive", "affordable",
    # Platform meta
    "subscribe", "like", "comment",
    "youtube", "instagram", "tiktok",
    # Generic perfume meta
    "fragrance", "fragrances", "cologne", "colognes",
    "perfume", "perfumes", "scent", "scents",
    "edp", "edt", "parfum",
    "spray", "mist",
})

# Candidate type classification patterns (applied to normalized_text)
_CLONE_MARKERS: frozenset[str] = frozenset({
    "dupe", "clone", "inspired by", "smells like",
    "alternative", "alternative to", "better than",
})

_FLANKER_SUFFIXES: frozenset[str] = frozenset({
    "intense", "noir", "extreme", "sport", "bleu",
    "rose", "berry", "wood", "woods", "absolute",
    "elixir", "parfum", "gold",
})

# Minimum token length for a phrase to be stored as emerging signal
_MIN_PHRASE_TOKENS = 2

# Phrases that are generic fragrance vocabulary — never store
_PHRASE_BLOCKLIST: frozenset[str] = frozenset({
    "eau de", "de parfum", "de toilette", "eau de parfum",
    "eau de toilette", "de cologne", "eau fraiche",
    "new fragrance", "new perfume", "new cologne",
    "my collection", "your collection",
    "top notes", "base notes", "middle notes", "heart notes",
})


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _make_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if not url:
        db_path = os.environ.get("PTI_DB_PATH", "outputs/market_dev.db")
        url = f"sqlite:///{db_path}"

    engine = create_engine(url, pool_pre_ping=True)
    return sessionmaker(bind=engine)()


# ---------------------------------------------------------------------------
# Candidate type classification
# ---------------------------------------------------------------------------

def _classify_candidate(normalized_text: str) -> str:
    """Deterministic candidate type classification. Fast, no AI."""
    for marker in _CLONE_MARKERS:
        if marker in normalized_text:
            return "clone_reference"

    tokens = normalized_text.split()

    # Single token that looks like a brand (capitalised in original — we
    # can't tell after normalisation, so keep as unknown for now)
    if len(tokens) == 1:
        return "unknown"

    # Last token is a flanker suffix → likely a flanker variant
    if tokens[-1] in _FLANKER_SUFFIXES:
        return "flanker"

    # Two+ tokens, no special marker → treat as perfume candidate
    if len(tokens) >= 2:
        return "perfume"

    return "unknown"


# ---------------------------------------------------------------------------
# Title phrase extractor
# ---------------------------------------------------------------------------

def _is_valid_phrase(phrase: str, tokens: List[str]) -> bool:
    """Return True if the phrase is worth storing as an emerging signal candidate."""
    if len(tokens) < _MIN_PHRASE_TOKENS:
        return False
    if phrase in _PHRASE_BLOCKLIST:
        return False
    # First token must not be a generic stop word
    if tokens[0] in _TITLE_STOP_WORDS:
        return False
    # All-digit phrases (prices, years)
    if all(t.isdigit() for t in tokens):
        return False
    # Very short tokens (e.g. "a b") with no substance
    if all(len(t) <= 1 for t in tokens):
        return False
    return True


def _title_case(text: str) -> str:
    return " ".join(w.capitalize() for w in text.split())


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def _load_channel_items(db, days: int, limit: int) -> List[Dict]:
    """
    Load channel_poll canonical_content_items from the last N days,
    joined with youtube_channels for tier attribution.
    Returns list of dicts: {cid, title, channel_id, channel_title, channel_tier, published_at}
    """
    from sqlalchemy import text

    # Graceful fallback when youtube_channels table doesn't exist (SQLite dev)
    try:
        result = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'youtube_channels'
            )
        """))
        if not result.scalar():
            logger.warning("youtube_channels table not found — returning empty")
            return []
    except Exception:
        # SQLite — check differently
        try:
            db.execute(text("SELECT 1 FROM youtube_channels LIMIT 1"))
        except Exception:
            logger.warning("youtube_channels table not found — returning empty")
            return []

    sql = """
        SELECT
            cci.id              AS cid,
            cci.title           AS title,
            cci.source_account_id AS channel_id,
            cci.published_at    AS published_at,
            yc.title            AS channel_title,
            yc.quality_tier     AS channel_tier
        FROM canonical_content_items cci
        LEFT JOIN youtube_channels yc
            ON yc.channel_id = cci.source_account_id
        WHERE cci.source_platform = 'youtube'
          AND cci.ingestion_method = 'channel_poll'
          AND cci.title IS NOT NULL
          AND cci.title != ''
          AND cci.published_at >= NOW() - CAST(:days || ' days' AS INTERVAL)
        ORDER BY cci.published_at DESC
    """
    if limit:
        sql += " LIMIT :limit"

    params = {"days": days}
    if limit:
        params["limit"] = limit

    rows = db.execute(text(sql), params).fetchall()

    result_list = []
    for row in rows:
        cid, title, channel_id, published_at, channel_title, channel_tier = row
        result_list.append({
            "cid": cid,
            "title": title or "",
            "channel_id": channel_id or "",
            "channel_title": channel_title or channel_id or "unknown",
            "channel_tier": channel_tier or "unrated",
            "published_at": published_at,
        })
    return result_list


def _check_resolver_membership(db, normalized_texts: Set[str]) -> Set[str]:
    """Return set of normalized_texts present in resolver_aliases."""
    if not normalized_texts:
        return set()
    try:
        from sqlalchemy import text
        result = db.execute(
            text("""
                SELECT DISTINCT normalized_alias_text
                FROM resolver_aliases
                WHERE normalized_alias_text = ANY(:texts)
            """),
            {"texts": list(normalized_texts)},
        )
        return {row[0] for row in result}
    except Exception:
        return set()


def _check_entity_market_membership(db, normalized_texts: Set[str]) -> Set[str]:
    """Return set of normalized_texts whose LOWER(canonical_name) matches in entity_market."""
    if not normalized_texts:
        return set()
    try:
        from sqlalchemy import text
        result = db.execute(
            text("""
                SELECT DISTINCT LOWER(canonical_name)
                FROM entity_market
                WHERE LOWER(canonical_name) = ANY(:texts)
            """),
            {"texts": list(normalized_texts)},
        )
        return {row[0] for row in result}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Main extraction logic
# ---------------------------------------------------------------------------

def extract_emerging_signals(
    db,
    resolver,
    days: int = 7,
    limit: int = 0,
    dry_run: bool = False,
) -> Dict:
    """
    Full extraction run. Returns a summary dict.
    Idempotent — safe to re-run multiple times over the same window.
    """
    from sqlalchemy import text

    logger.info("[extract_emerging] loading channel_poll items (last %d days)", days)
    items = _load_channel_items(db, days, limit)
    logger.info("[extract_emerging] loaded %d channel_poll items", len(items))

    if not items:
        return {
            "items_processed": 0,
            "candidates_found": 0,
            "upserted": 0,
            "skipped_known": 0,
            "dry_run": dry_run,
        }

    # -----------------------------------------------------------------------
    # Per-phrase aggregation
    # phrase_data[normalized_text] = {
    #   "channels": {channel_id: {"tier": ..., "title": ...}},
    #   "total_mentions": int,
    #   "first_seen": datetime,
    #   "last_seen": datetime,
    # }
    # -----------------------------------------------------------------------
    phrase_data: Dict[str, Dict] = defaultdict(lambda: {
        "channels": {},
        "total_mentions": 0,
        "first_seen": None,
        "last_seen": None,
    })

    items_processed = 0

    for item in items:
        title = item["title"]
        channel_id = item["channel_id"]
        channel_title = item["channel_title"]
        channel_tier = item["channel_tier"]
        published_at = item["published_at"]

        if not title or not channel_id:
            continue

        # Resolve title-only: get unresolved candidates
        resolution = resolver.resolve_content_item(
            {"id": item["cid"], "text_content": title},
            emit_candidates=True,
        )

        candidates: List[str] = resolution.get("unresolved_mentions", [])

        for phrase in candidates:
            tokens = phrase.split()
            if not _is_valid_phrase(phrase, tokens):
                continue

            pd = phrase_data[phrase]

            # Track channel attribution (unique per channel per phrase)
            if channel_id not in pd["channels"]:
                pd["channels"][channel_id] = {
                    "tier": channel_tier,
                    "title": channel_title,
                }

            pd["total_mentions"] += 1

            # Track first/last seen from published_at
            if published_at is not None:
                if isinstance(published_at, str):
                    try:
                        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    except ValueError:
                        published_at = None

                if published_at is not None:
                    if not isinstance(published_at, datetime):
                        # already a datetime
                        pass
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)

                    if pd["first_seen"] is None or published_at < pd["first_seen"]:
                        pd["first_seen"] = published_at
                    if pd["last_seen"] is None or published_at > pd["last_seen"]:
                        pd["last_seen"] = published_at

        items_processed += 1

    logger.info(
        "[extract_emerging] processed %d items → %d unique phrases",
        items_processed, len(phrase_data),
    )

    # -----------------------------------------------------------------------
    # Compute per-phrase aggregate stats
    # -----------------------------------------------------------------------

    now_utc = datetime.now(timezone.utc)

    # Build final candidate records
    records = []
    all_phrases = set(phrase_data.keys())

    # Batch-check resolver and entity_market membership
    in_resolver = _check_resolver_membership(db, all_phrases)
    in_entity_market = _check_entity_market_membership(db, all_phrases)

    for phrase, pd in phrase_data.items():
        channels = pd["channels"]
        if not channels:
            continue

        total_mentions = pd["total_mentions"]
        distinct_channels_count = len(channels)

        # Weighted score: sum of per-channel weights (each channel counted once)
        weighted_score = sum(
            _TIER_WEIGHTS.get(ch["tier"], 0.5) for ch in channels.values()
        )

        # Top channel: highest-weight channel
        top_channel_id = max(
            channels.keys(),
            key=lambda cid: _TIER_WEIGHTS.get(channels[cid]["tier"], 0.5),
        )
        top_channel = channels[top_channel_id]

        first_seen = pd["first_seen"] or now_utc
        last_seen = pd["last_seen"] or now_utc

        days_active = max(1, (last_seen - first_seen).days + 1)

        days_since_last = max(0, (now_utc - last_seen).total_seconds() / 86400.0)
        emerging_score = round(weighted_score * math.exp(-0.1 * days_since_last), 4)

        candidate_type = _classify_candidate(phrase)
        display_name = _title_case(phrase)

        is_resolver = phrase in in_resolver
        is_market = phrase in in_entity_market

        records.append({
            "normalized_text": phrase,
            "display_name": display_name,
            "candidate_type": candidate_type,
            "total_mentions": total_mentions,
            "distinct_channels_count": distinct_channels_count,
            "weighted_channel_score": round(weighted_score, 4),
            "top_channel_id": top_channel_id,
            "top_channel_title": top_channel.get("title", ""),
            "top_channel_tier": top_channel.get("tier", "unrated"),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "days_active": days_active,
            "is_in_resolver": is_resolver,
            "is_in_entity_market": is_market,
            "emerging_score": emerging_score,
        })

    # Sort by emerging_score desc for logging
    records.sort(key=lambda r: r["emerging_score"], reverse=True)

    candidates_found = len(records)
    logger.info("[extract_emerging] %d scoreable candidates", candidates_found)

    if dry_run:
        _log_top_candidates(records[:30], in_resolver, in_entity_market)
        return {
            "items_processed": items_processed,
            "candidates_found": candidates_found,
            "upserted": 0,
            "skipped_known": sum(1 for r in records if r["is_in_resolver"] or r["is_in_entity_market"]),
            "dry_run": True,
        }

    # -----------------------------------------------------------------------
    # Upsert into emerging_signals
    # -----------------------------------------------------------------------

    # Check table exists
    try:
        db.execute(text("SELECT 1 FROM emerging_signals LIMIT 1"))
    except Exception:
        logger.error(
            "[extract_emerging] emerging_signals table not found. "
            "Run: alembic upgrade head (migration 027)"
        )
        return {
            "items_processed": items_processed,
            "candidates_found": candidates_found,
            "upserted": 0,
            "skipped_known": 0,
            "dry_run": False,
            "error": "table_not_found",
        }

    upserted = 0
    for rec in records:
        try:
            db.execute(
                text("""
                    INSERT INTO emerging_signals (
                        normalized_text, display_name, candidate_type,
                        total_mentions, distinct_channels_count, weighted_channel_score,
                        top_channel_id, top_channel_title, top_channel_tier,
                        first_seen, last_seen, days_active,
                        is_in_resolver, is_in_entity_market,
                        review_status, emerging_score,
                        created_at, updated_at
                    ) VALUES (
                        :normalized_text, :display_name, :candidate_type,
                        :total_mentions, :distinct_channels_count, :weighted_channel_score,
                        :top_channel_id, :top_channel_title, :top_channel_tier,
                        :first_seen, :last_seen, :days_active,
                        :is_in_resolver, :is_in_entity_market,
                        'pending', :emerging_score,
                        NOW(), NOW()
                    )
                    ON CONFLICT (normalized_text) DO UPDATE SET
                        display_name             = EXCLUDED.display_name,
                        candidate_type           = EXCLUDED.candidate_type,
                        total_mentions           = EXCLUDED.total_mentions,
                        distinct_channels_count  = EXCLUDED.distinct_channels_count,
                        weighted_channel_score   = EXCLUDED.weighted_channel_score,
                        top_channel_id           = EXCLUDED.top_channel_id,
                        top_channel_title        = EXCLUDED.top_channel_title,
                        top_channel_tier         = EXCLUDED.top_channel_tier,
                        first_seen               = LEAST(emerging_signals.first_seen, EXCLUDED.first_seen),
                        last_seen                = GREATEST(emerging_signals.last_seen, EXCLUDED.last_seen),
                        days_active              = EXCLUDED.days_active,
                        is_in_resolver           = EXCLUDED.is_in_resolver,
                        is_in_entity_market      = EXCLUDED.is_in_entity_market,
                        emerging_score           = EXCLUDED.emerging_score,
                        updated_at               = NOW()
                """),
                rec,
            )
            upserted += 1
        except Exception as exc:
            logger.warning("[extract_emerging] upsert failed for %r: %s", rec["normalized_text"], exc)

    db.commit()
    logger.info("[extract_emerging] upserted %d emerging_signals rows", upserted)

    skipped_known = sum(
        1 for r in records if r["is_in_resolver"] or r["is_in_entity_market"]
    )
    _log_top_candidates(records[:30], in_resolver, in_entity_market)

    return {
        "items_processed": items_processed,
        "candidates_found": candidates_found,
        "upserted": upserted,
        "skipped_known": skipped_known,
        "dry_run": False,
    }


def _log_top_candidates(
    records: List[Dict],
    in_resolver: Set[str],
    in_entity_market: Set[str],
) -> None:
    logger.info("=" * 70)
    logger.info("TOP EMERGING SIGNAL CANDIDATES (by emerging_score)")
    logger.info("%-40s %6s %4s %6s %5s %-10s", "phrase", "score", "ch", "tier", "known", "type")
    logger.info("-" * 70)
    for rec in records:
        phrase = rec["normalized_text"][:39]
        known = ""
        if rec["is_in_resolver"]:
            known = "RESOLVER"
        elif rec["is_in_entity_market"]:
            known = "MARKET"
        logger.info(
            "%-40s %6.3f %4d %6.2f %5s %-10s",
            phrase,
            rec["emerging_score"],
            rec["distinct_channels_count"],
            rec["weighted_channel_score"],
            known or "-",
            rec["candidate_type"],
        )
    logger.info("=" * 70)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Emerging Signals (Phase E3-A) — channel-aware, title-first"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print candidates without writing to DB",
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Lookback window in days (default: 7)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max content items to process (0=all)",
    )
    parser.add_argument(
        "--resolver-db", type=str, default=None,
        help="Path to SQLite resolver DB (local dev only; production uses DATABASE_URL)",
    )
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import make_resolver

    db = _make_session()

    resolver = make_resolver(db_path=args.resolver_db)

    summary = extract_emerging_signals(
        db=db,
        resolver=resolver,
        days=args.days,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    print("\n[extract_emerging] Summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
