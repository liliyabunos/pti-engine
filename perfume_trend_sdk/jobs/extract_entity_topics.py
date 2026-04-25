"""Phase I5 — Extract Entity Topics job.

Reads canonical_content_items, extracts topics deterministically, then links
those topics to entities via entity_mentions.

Flow:
  canonical_content_items
    → extract_topics()           → content_topics (upsert)
    → entity_mentions (join)     → entity_topic_links (upsert)

Run:
  python3 -m perfume_trend_sdk.jobs.extract_entity_topics
  python3 -m perfume_trend_sdk.jobs.extract_entity_topics --dry-run
  python3 -m perfume_trend_sdk.jobs.extract_entity_topics --limit 100
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB setup
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
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract entity topics (Phase I5)")
    parser.add_argument("--dry-run", action="store_true", help="Preview — no DB writes")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N content items (0=all)")
    parser.add_argument("--force", action="store_true", help="Re-process content items that already have topics")
    parser.add_argument("--rebuild-links", action="store_true",
                        help="Clear entity_topic_links and rebuild from existing content_topics (faster than --force)")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from perfume_trend_sdk.analysis.topic_intelligence.extractor import extract_topics
    from perfume_trend_sdk.db.market.topic_intelligence import ContentTopic, EntityTopicLink

    db = _make_session()

    try:
        from sqlalchemy import text

        # ── 0. Rebuild-links fast path ─────────────────────────────────────
        if args.rebuild_links and not args.dry_run:
            deleted = db.execute(text("DELETE FROM entity_topic_links")).rowcount
            db.commit()
            logger.info("--rebuild-links: cleared %d entity_topic_links rows", deleted)
            # Skip topic extraction — go straight to re-linking from existing content_topics

        # ── 1. Load content items ───────────────────────────────────────────
        if args.rebuild_links and not args.dry_run:
            cci_rows = []  # No extraction needed — topics already exist
        elif args.force:
            cci_rows = db.execute(text(
                "SELECT id, source_platform, title, text_content, query, media_metadata_json "
                "FROM canonical_content_items " +
                (f"LIMIT {args.limit}" if args.limit else "")
            )).fetchall()
        else:
            # Only process items that don't yet have topics
            cci_rows = db.execute(text("""
                SELECT cci.id, cci.source_platform, cci.title, cci.text_content,
                       cci.query, cci.media_metadata_json
                FROM canonical_content_items cci
                WHERE NOT EXISTS (
                    SELECT 1 FROM content_topics ct WHERE ct.content_item_id = cci.id
                )
                """ + (f"LIMIT {args.limit}" if args.limit else "")
            )).fetchall()

        logger.info("Content items to process: %d", len(cci_rows))

        # ── 2. Load entity mention lookup: cci_id → list[(entity_id, entity_type, source_score)] ──
        #
        # Join entity_mentions → canonical_content_items so the map key is cci.id
        # (the same key used in content_topics.content_item_id).
        #
        # Three join strategies handle old and new source_url formats:
        #   A) cci.id = em.source_url         — old style: bare video ID stored in source_url
        #   B) cci.source_url = em.source_url — new style: full URL stored in source_url (YouTube + Reddit)
        #   C) em.source_url IS NULL          — skip rows with no URL
        try:
            mention_rows = db.execute(text("""
                SELECT DISTINCT ON (em.id) cci.id as cci_id,
                       em.entity_id, em.entity_type,
                       ms.source_score
                FROM entity_mentions em
                JOIN canonical_content_items cci
                  ON (cci.id = em.source_url OR cci.source_url = em.source_url)
                LEFT JOIN mention_sources ms ON ms.mention_id = em.id
                WHERE em.source_url IS NOT NULL
            """)).fetchall()
        except Exception:
            # SQLite fallback: no DISTINCT ON, simpler join
            try:
                mention_rows = db.execute(text("""
                    SELECT cci.id, em.entity_id, em.entity_type, NULL as source_score
                    FROM entity_mentions em
                    JOIN canonical_content_items cci
                      ON (cci.id = em.source_url OR cci.source_url = em.source_url)
                    WHERE em.source_url IS NOT NULL
                """)).fetchall()
            except Exception:
                # Last resort: bare source_url match (original behaviour)
                mention_rows = db.execute(text("""
                    SELECT source_url, entity_id, entity_type, NULL as source_score
                    FROM entity_mentions
                    WHERE source_url IS NOT NULL
                """)).fetchall()

        # Build lookup: cci_id → list of (entity_id_str, entity_type, source_score)
        mention_map: dict[str, list[tuple[str, str, Optional[float]]]] = {}
        for cci_id, entity_id, entity_type, source_score in mention_rows:
            entity_id_str = str(entity_id)
            mention_map.setdefault(str(cci_id), []).append(
                (entity_id_str, entity_type, source_score)
            )

        logger.info("Entity mention lookup built: %d unique content_item_ids", len(mention_map))

        # ── 3. Extract and persist ─────────────────────────────────────────
        topics_written = 0
        links_written = 0
        items_with_topics = 0
        items_with_links = 0

        BATCH = 200
        batch_count = 0

        for cci_id, platform, title, text_content, query, mm_json in cci_rows:
            topics = extract_topics(
                title=title,
                text_content=text_content,
                query=query,
                media_metadata_json=mm_json,
                source_platform=platform,
            )
            if not topics:
                continue

            items_with_topics += 1
            topic_ids: list[int] = []

            if not args.dry_run:
                for t in topics:
                    # Upsert content_topic
                    existing = db.execute(text("""
                        SELECT id FROM content_topics
                        WHERE content_item_id = :cid AND topic_type = :tt AND topic_text = :tx
                    """), {"cid": cci_id, "tt": t.topic_type, "tx": t.topic_text}).fetchone()

                    if existing:
                        topic_ids.append(existing[0])
                    else:
                        row = db.execute(text("""
                            INSERT INTO content_topics (content_item_id, source_platform, topic_type, topic_text, confidence)
                            VALUES (:cid, :plat, :tt, :tx, :conf)
                            RETURNING id
                        """), {
                            "cid": cci_id, "plat": platform,
                            "tt": t.topic_type, "tx": t.topic_text, "conf": t.confidence,
                        }).fetchone()
                        topic_ids.append(row[0])
                        topics_written += 1

                # Link topics to entities via entity_mentions
                entity_list = mention_map.get(cci_id, [])
                if entity_list:
                    items_with_links += 1
                    for entity_id_str, entity_type, source_score in entity_list:
                        for ct_id, t in zip(topic_ids, topics):
                            existing_link = db.execute(text("""
                                SELECT id FROM entity_topic_links
                                WHERE entity_id = :eid AND content_topic_id = :ctid
                            """), {"eid": entity_id_str, "ctid": ct_id}).fetchone()
                            if not existing_link:
                                db.execute(text("""
                                    INSERT INTO entity_topic_links
                                    (entity_id, entity_type, content_topic_id, topic_text, topic_type, source_score)
                                    VALUES (:eid, :etype, :ctid, :tx, :tt, :ss)
                                """), {
                                    "eid": entity_id_str, "etype": entity_type,
                                    "ctid": ct_id, "tx": t.topic_text, "tt": t.topic_type,
                                    "ss": source_score,
                                })
                                links_written += 1

                batch_count += 1
                if batch_count % BATCH == 0:
                    db.commit()
                    logger.info("  Committed batch %d (topics=%d, links=%d)...",
                                batch_count // BATCH, topics_written, links_written)
            else:
                # Dry run — just count
                entity_list = mention_map.get(cci_id, [])
                topics_written += len(topics)
                links_written += len(topics) * len(entity_list)
                if entity_list:
                    items_with_links += 1

        if not args.dry_run:
            db.commit()

        # ── 3b. Rebuild-links: link all existing content_topics to entities ──
        if args.rebuild_links and not args.dry_run:
            logger.info("Rebuild-links: linking all existing content_topics to entities...")
            # Load all content_topics
            all_ct = db.execute(text(
                "SELECT id, content_item_id, topic_text, topic_type FROM content_topics"
            )).fetchall()
            logger.info("  content_topics to link: %d", len(all_ct))
            rl_links = 0
            rl_batch = 0
            for ct_id, ct_cci_id, topic_text, topic_type in all_ct:
                entity_list = mention_map.get(str(ct_cci_id), [])
                for entity_id_str, entity_type, source_score in entity_list:
                    db.execute(text("""
                        INSERT INTO entity_topic_links
                        (entity_id, entity_type, content_topic_id, topic_text, topic_type, source_score)
                        VALUES (:eid, :etype, :ctid, :tx, :tt, :ss)
                        ON CONFLICT DO NOTHING
                    """), {
                        "eid": entity_id_str, "etype": entity_type,
                        "ctid": ct_id, "tx": topic_text, "tt": topic_type,
                        "ss": source_score,
                    })
                    rl_links += 1
                rl_batch += 1
                if rl_batch % 500 == 0:
                    db.commit()
                    logger.info("  rebuild-links progress: %d topics processed, %d links", rl_batch, rl_links)
            db.commit()
            links_written += rl_links
            logger.info("Rebuild-links complete: %d entity_topic_links written", rl_links)

        logger.info(
            "Done. items_with_topics=%d items_with_links=%d topics_written=%d links_written=%d%s",
            items_with_topics, items_with_links, topics_written, links_written,
            " [DRY RUN]" if args.dry_run else "",
        )

        # ── 4. Print distribution ──────────────────────────────────────────
        if not args.dry_run:
            print("\n=== content_topics distribution ===")
            for row in db.execute(text(
                "SELECT topic_type, COUNT(*) as n FROM content_topics GROUP BY topic_type ORDER BY n DESC"
            )).fetchall():
                print(f"  {row[0]:12} : {row[1]:,}")

            ct = db.execute(text("SELECT COUNT(*) FROM content_topics")).scalar()
            el = db.execute(text("SELECT COUNT(*) FROM entity_topic_links")).scalar()
            print(f"\nTotal content_topics:    {ct:,}")
            print(f"Total entity_topic_links: {el:,}")

            # Show sample entity topics
            print("\n=== Sample entity topics (top entities) ===")
            try:
                samples = db.execute(text("""
                    SELECT e.canonical_name, etl.topic_type, etl.topic_text, COUNT(*) as n
                    FROM entity_topic_links etl
                    JOIN entity_market e ON CAST(e.id AS TEXT) = etl.entity_id
                    GROUP BY e.canonical_name, etl.topic_type, etl.topic_text
                    ORDER BY n DESC
                    LIMIT 20
                """)).fetchall()
            except Exception:
                samples = []
            for name, ttype, ttext, n in samples:
                print(f"  {name[:35]:35} [{ttype:10}] {ttext} ({n}x)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
