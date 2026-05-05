#!/usr/bin/env python3
"""
C1.4 — Compute creator_scores from creator_entity_relationships + youtube_channels.

Aggregates per (platform, creator_id):
  - total_content_items, content_with_entity_mentions
  - noise_rate (items without entity mentions / total items)
  - unique_entities_mentioned, unique_brands_mentioned, total_entity_mentions
  - total_views, avg_views, total_likes, total_comments, avg_engagement_rate
  - breakout_contributions, early_signal_count, early_signal_rate
  - influence_score (v1 composite: reach 25%, signal_quality 20%, entity_breadth 20%,
                     volume 15%, early_signal 10%, engagement 10%)

Usage:
    python3 scripts/compute_creator_scores.py --dry-run
    python3 scripts/compute_creator_scores.py --apply
    python3 scripts/compute_creator_scores.py --apply --limit 500
    python3 scripts/compute_creator_scores.py --verify

Notes:
  - Requires creator_entity_relationships to be populated first (run C1.3)
  - subscriber_count comes from youtube_channels (populated in C1.1)
  - engagement_json stored as TEXT — cast ::jsonb for queries
  - quality_tier comes from youtube_channels
  - Idempotent: UPSERT ON CONFLICT updates all fields
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
import psycopg2.extras

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

_UPSERT_BATCH = 200
_PLATFORM = "youtube"


def _get_conn():
    url = os.environ.get("DATABASE_URL", "")
    if not url or url.startswith("sqlite"):
        log.error("DATABASE_URL not set or points to SQLite — PostgreSQL required.")
        sys.exit(1)
    return psycopg2.connect(url)


# ---------------------------------------------------------------------------
# Step 1 — Aggregate from creator_entity_relationships + youtube_channels
# ---------------------------------------------------------------------------

_AGGREGATE_SQL = """
WITH cer_agg AS (
    -- Aggregate all per-entity stats up to per-creator level
    SELECT
        cer.platform,
        cer.creator_id,
        MAX(cer.creator_handle)                          AS creator_handle,
        COUNT(DISTINCT cer.entity_id)                    AS unique_entities_mentioned,
        COUNT(DISTINCT cer.brand_name)
            FILTER (WHERE cer.brand_name IS NOT NULL)    AS unique_brands_mentioned,
        SUM(cer.mention_count)                           AS total_entity_mentions,
        SUM(cer.total_views)                             AS total_views,
        AVG(cer.avg_views)                               AS avg_views,
        SUM(cer.total_likes)                             AS total_likes,
        SUM(cer.total_comments)                          AS total_comments,
        AVG(cer.avg_engagement_rate)
            FILTER (WHERE cer.avg_engagement_rate IS NOT NULL) AS avg_engagement_rate,
        SUM(CASE WHEN cer.mentions_before_first_breakout > 0 THEN 1 ELSE 0 END)
                                                         AS early_signal_count
    FROM creator_entity_relationships cer
    WHERE cer.platform = 'youtube'
    GROUP BY cer.platform, cer.creator_id
),
content_stats AS (
    -- Total content items per channel + content items that have entity mentions
    SELECT
        cci.source_account_id                            AS creator_id,
        COUNT(DISTINCT cci.id)                           AS total_content_items,
        COUNT(DISTINCT em.source_url)                    AS content_with_entity_mentions
    FROM canonical_content_items cci
    LEFT JOIN entity_mentions em
        ON (em.source_url = cci.source_url OR em.source_url = cci.id)
    WHERE cci.source_platform = 'youtube'
      AND cci.source_account_id IS NOT NULL
      AND cci.source_account_id ~ '^UC[a-zA-Z0-9_\\-]{{22}}$'
    GROUP BY cci.source_account_id
),
breakout_stats AS (
    -- Count how many entity breakout signals occurred where creator was active
    SELECT
        cer.creator_id,
        COUNT(DISTINCT cer.entity_id)                    AS breakout_contributions
    FROM creator_entity_relationships cer
    WHERE cer.platform = 'youtube'
      AND cer.mention_count > 0
      -- Entity must have had a breakout or acceleration signal
      AND EXISTS (
          SELECT 1 FROM signals s
          WHERE s.entity_id::text = cer.entity_id::text
            AND s.signal_type IN ('breakout', 'acceleration_spike')
      )
    GROUP BY cer.creator_id
)
SELECT
    ca.platform,
    ca.creator_id,
    ca.creator_handle,
    yc.quality_tier,
    yc.category,
    yc.subscriber_count,
    COALESCE(cs.total_content_items, 0)                  AS total_content_items,
    COALESCE(cs.content_with_entity_mentions, 0)         AS content_with_entity_mentions,
    CASE
        WHEN COALESCE(cs.total_content_items, 0) > 0
        THEN 1.0 - (COALESCE(cs.content_with_entity_mentions, 0)::float / cs.total_content_items)
        ELSE NULL
    END                                                  AS noise_rate,
    ca.unique_entities_mentioned,
    ca.unique_brands_mentioned,
    ca.total_entity_mentions,
    ca.total_views,
    ca.avg_views,
    ca.total_likes,
    ca.total_comments,
    ca.avg_engagement_rate,
    COALESCE(bs.breakout_contributions, 0)               AS breakout_contributions,
    ca.early_signal_count,
    CASE
        WHEN ca.unique_entities_mentioned > 0
        THEN ca.early_signal_count::float / ca.unique_entities_mentioned
        ELSE 0.0
    END                                                  AS early_signal_rate
FROM cer_agg ca
LEFT JOIN youtube_channels yc ON yc.channel_id = ca.creator_id
LEFT JOIN content_stats cs ON cs.creator_id = ca.creator_id
LEFT JOIN breakout_stats bs ON bs.creator_id = ca.creator_id
{limit_clause}
"""

_UPSERT_SQL = """
INSERT INTO creator_scores (
    platform, creator_id, creator_handle,
    quality_tier, category, subscriber_count,
    total_content_items, content_with_entity_mentions, noise_rate,
    unique_entities_mentioned, unique_brands_mentioned, total_entity_mentions,
    total_views, avg_views, total_likes, total_comments, avg_engagement_rate,
    breakout_contributions, early_signal_count, early_signal_rate,
    influence_score, score_components, computed_at
) VALUES (
    %(platform)s, %(creator_id)s, %(creator_handle)s,
    %(quality_tier)s, %(category)s, %(subscriber_count)s,
    %(total_content_items)s, %(content_with_entity_mentions)s, %(noise_rate)s,
    %(unique_entities_mentioned)s, %(unique_brands_mentioned)s, %(total_entity_mentions)s,
    %(total_views)s, %(avg_views)s, %(total_likes)s, %(total_comments)s, %(avg_engagement_rate)s,
    %(breakout_contributions)s, %(early_signal_count)s, %(early_signal_rate)s,
    %(influence_score)s, %(score_components)s, %(computed_at)s
)
ON CONFLICT (platform, creator_id)
DO UPDATE SET
    creator_handle              = EXCLUDED.creator_handle,
    quality_tier                = EXCLUDED.quality_tier,
    category                    = EXCLUDED.category,
    subscriber_count            = EXCLUDED.subscriber_count,
    total_content_items         = EXCLUDED.total_content_items,
    content_with_entity_mentions = EXCLUDED.content_with_entity_mentions,
    noise_rate                  = EXCLUDED.noise_rate,
    unique_entities_mentioned   = EXCLUDED.unique_entities_mentioned,
    unique_brands_mentioned     = EXCLUDED.unique_brands_mentioned,
    total_entity_mentions       = EXCLUDED.total_entity_mentions,
    total_views                 = EXCLUDED.total_views,
    avg_views                   = EXCLUDED.avg_views,
    total_likes                 = EXCLUDED.total_likes,
    total_comments              = EXCLUDED.total_comments,
    avg_engagement_rate         = EXCLUDED.avg_engagement_rate,
    breakout_contributions      = EXCLUDED.breakout_contributions,
    early_signal_count          = EXCLUDED.early_signal_count,
    early_signal_rate           = EXCLUDED.early_signal_rate,
    influence_score             = EXCLUDED.influence_score,
    score_components            = EXCLUDED.score_components,
    computed_at                 = EXCLUDED.computed_at
"""


def _compute_influence_score(row: dict) -> tuple[float, dict]:
    """
    v1 Influence Score — all components normalized 0.0–1.0.

    Weights:
      reach (25%)         — subscriber_count proxy
      signal_quality (20%) — 1 - noise_rate
      entity_breadth (20%) — unique_entities_mentioned / 50
      volume (15%)        — log10(total_entity_mentions+1) / log10(1000)
      early_signal (10%)  — early_signal_count / 20
      engagement (10%)    — avg_engagement_rate / 0.10

    Returns (influence_score, score_components dict)
    """
    subscriber_count = row.get("subscriber_count") or 0
    noise_rate = row.get("noise_rate") or 0.0
    unique_entities = row.get("unique_entities_mentioned") or 0
    total_mentions = row.get("total_entity_mentions") or 0
    early_signal_count = row.get("early_signal_count") or 0
    avg_engagement_rate = row.get("avg_engagement_rate") or 0.0

    # Reach proxy (25%)
    if subscriber_count and subscriber_count > 0:
        reach = min(math.log10(subscriber_count + 1) / math.log10(10_000_000), 1.0)
    else:
        reach = 0.0

    # Signal quality / low noise (20%)
    signal_quality = max(0.0, min(1.0 - noise_rate, 1.0))

    # Entity breadth (20%)
    entity_breadth = min(unique_entities / 50.0, 1.0)

    # Mention volume (15%)
    if total_mentions > 0:
        volume = min(math.log10(total_mentions + 1) / math.log10(1000), 1.0)
    else:
        volume = 0.0

    # Early signal contribution (10%)
    early_signal = min(early_signal_count / 20.0, 1.0)

    # Engagement quality (10%)
    engagement = min((avg_engagement_rate or 0.0) / 0.1, 1.0)

    influence_score = (
        0.25 * reach
        + 0.20 * signal_quality
        + 0.20 * entity_breadth
        + 0.15 * volume
        + 0.10 * early_signal
        + 0.10 * engagement
    )

    components = {
        "reach": round(reach, 4),
        "signal_quality": round(signal_quality, 4),
        "entity_breadth": round(entity_breadth, 4),
        "volume": round(volume, 4),
        "early_signal": round(early_signal, 4),
        "engagement": round(engagement, 4),
        "weights": {
            "reach": 0.25,
            "signal_quality": 0.20,
            "entity_breadth": 0.20,
            "volume": 0.15,
            "early_signal": 0.10,
            "engagement": 0.10,
        },
    }

    return round(influence_score, 6), components


def run(dry_run: bool, limit: int | None):
    import json

    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        limit_clause = f"LIMIT {limit}" if limit else ""
        sql = _AGGREGATE_SQL.format(limit_clause=limit_clause)

        log.info("Running creator score aggregation query...")
        cur.execute(sql)
        rows = cur.fetchall()
        log.info("  Aggregated %d creator rows", len(rows))

        if dry_run:
            log.info("[DRY-RUN] Would upsert %d rows to creator_scores", len(rows))
            log.info("Sample rows (first 5):")
            for r in rows[:5]:
                rd = dict(r)
                score, comps = _compute_influence_score(rd)
                log.info(
                    "  creator=%s handle=%s tier=%s subscribers=%s "
                    "entities=%d noise_rate=%.2f early_signal=%d influence=%.4f",
                    rd["creator_id"][:20],
                    rd["creator_handle"] or "?",
                    rd["quality_tier"] or "?",
                    rd["subscriber_count"],
                    rd["unique_entities_mentioned"] or 0,
                    rd["noise_rate"] or 0.0,
                    rd["early_signal_count"] or 0,
                    score,
                )
            return

        now = datetime.now(timezone.utc)
        batch = []
        total_upserted = 0

        for r in rows:
            rd = dict(r)
            influence_score, components = _compute_influence_score(rd)
            rd["influence_score"] = influence_score
            rd["score_components"] = json.dumps(components)
            rd["computed_at"] = now
            batch.append(rd)

            if len(batch) >= _UPSERT_BATCH:
                cur_plain = conn.cursor()
                psycopg2.extras.execute_batch(cur_plain, _UPSERT_SQL, batch, page_size=_UPSERT_BATCH)
                conn.commit()
                total_upserted += len(batch)
                log.info("  Upserted %d rows (total so far: %d)", len(batch), total_upserted)
                batch = []

        if batch:
            cur_plain = conn.cursor()
            psycopg2.extras.execute_batch(cur_plain, _UPSERT_SQL, batch, page_size=_UPSERT_BATCH)
            conn.commit()
            total_upserted += len(batch)

        log.info("[DONE] Upserted %d creator_scores rows", total_upserted)

    finally:
        conn.close()


def verify():
    conn = _get_conn()
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM creator_scores")
        total = cur.fetchone()[0]
        log.info("creator_scores total rows: %d", total)

        cur.execute("SELECT COUNT(DISTINCT creator_id) FROM creator_scores WHERE platform='youtube'")
        creators = cur.fetchone()[0]
        log.info("Unique YouTube creators scored: %d", creators)

        cur.execute("""
            SELECT COUNT(*) FROM creator_scores
            WHERE influence_score IS NOT NULL AND influence_score > 0
        """)
        scored = cur.fetchone()[0]
        log.info("Creators with influence_score > 0: %d", scored)

        cur.execute("""
            SELECT COUNT(*) FROM creator_scores
            WHERE early_signal_count > 0
        """)
        early = cur.fetchone()[0]
        log.info("Creators with early_signal_count > 0: %d", early)

        log.info("\nTop 10 creators by influence_score:")
        cur.execute("""
            SELECT creator_id, creator_handle, quality_tier, subscriber_count,
                   unique_entities_mentioned, early_signal_count,
                   ROUND(influence_score::numeric, 4) AS influence_score
            FROM creator_scores
            WHERE platform = 'youtube'
            ORDER BY influence_score DESC NULLS LAST
            LIMIT 10
        """)
        for r in cur.fetchall():
            log.info(
                "  %s (%s) tier=%s subs=%s entities=%d early=%d score=%.4f",
                r[0][:20], r[1] or "?", r[2] or "?", r[3],
                r[4] or 0, r[5] or 0, float(r[6] or 0),
            )

        log.info("\nTop 10 creators by early_signal_count:")
        cur.execute("""
            SELECT creator_id, creator_handle, quality_tier,
                   early_signal_count, early_signal_rate,
                   ROUND(influence_score::numeric, 4) AS influence_score
            FROM creator_scores
            WHERE platform = 'youtube' AND early_signal_count > 0
            ORDER BY early_signal_count DESC, early_signal_rate DESC
            LIMIT 10
        """)
        for r in cur.fetchall():
            log.info(
                "  %s (%s) tier=%s early=%d rate=%.2f score=%.4f",
                r[0][:20], r[1] or "?", r[2] or "?",
                r[3] or 0, float(r[4] or 0), float(r[5] or 0),
            )

        log.info("\nScore distribution:")
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE influence_score >= 0.7)  AS top_tier,
                COUNT(*) FILTER (WHERE influence_score >= 0.4 AND influence_score < 0.7) AS mid_tier,
                COUNT(*) FILTER (WHERE influence_score >= 0.1 AND influence_score < 0.4) AS low_tier,
                COUNT(*) FILTER (WHERE influence_score < 0.1 OR influence_score IS NULL)  AS minimal
            FROM creator_scores
            WHERE platform = 'youtube'
        """)
        r = cur.fetchone()
        log.info("  ≥0.7 (top):    %d", r[0] or 0)
        log.info("  0.4–0.7 (mid): %d", r[1] or 0)
        log.info("  0.1–0.4 (low): %d", r[2] or 0)
        log.info("  <0.1 (minimal):%d", r[3] or 0)

        log.info("\nSample score component breakdown (top 3 by influence_score):")
        cur.execute("""
            SELECT creator_handle, influence_score, score_components
            FROM creator_scores
            WHERE platform = 'youtube' AND score_components IS NOT NULL
            ORDER BY influence_score DESC NULLS LAST
            LIMIT 3
        """)
        for r in cur.fetchall():
            import json
            comps = r[2] if isinstance(r[2], dict) else (json.loads(r[2]) if r[2] else {})
            log.info(
                "  %s (score=%.4f): reach=%.3f sq=%.3f breadth=%.3f vol=%.3f early=%.3f eng=%.3f",
                r[0] or "?", float(r[1] or 0),
                comps.get("reach", 0),
                comps.get("signal_quality", 0),
                comps.get("entity_breadth", 0),
                comps.get("volume", 0),
                comps.get("early_signal", 0),
                comps.get("engagement", 0),
            )

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="C1.4 — compute creator_scores")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--limit", type=int, default=None, help="Limit rows processed")
    parser.add_argument("--verify", action="store_true", default=False)
    args = parser.parse_args()

    if args.verify:
        verify()
        return

    if not args.apply:
        args.dry_run = True

    run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
