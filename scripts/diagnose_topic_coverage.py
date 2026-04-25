"""Diagnose entity_topic_links coverage gap (Phase I6)."""
import os
import re
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)
if not url:
    raise SystemExit("DATABASE_URL required")

engine = create_engine(url, pool_pre_ping=True)

with engine.connect() as conn:
    print("=== Basic counts ===")
    em_total = conn.execute(text("SELECT COUNT(*) FROM entity_mentions")).scalar()
    em_with_url = conn.execute(text("SELECT COUNT(*) FROM entity_mentions WHERE source_url IS NOT NULL")).scalar()
    cci_count = conn.execute(text("SELECT COUNT(*) FROM canonical_content_items")).scalar()
    ct_count = conn.execute(text("SELECT COUNT(*) FROM content_topics")).scalar()
    etl_count = conn.execute(text("SELECT COUNT(*) FROM entity_topic_links")).scalar()
    print(f"entity_mentions: {em_total} ({em_with_url} with source_url)")
    print(f"canonical_content_items: {cci_count}")
    print(f"content_topics: {ct_count}")
    print(f"entity_topic_links: {etl_count}")

    print("\n=== entity_mentions.source_url patterns ===")
    samples = conn.execute(text("SELECT DISTINCT source_url FROM entity_mentions LIMIT 8")).fetchall()
    for (url_val,) in samples:
        print(" ", url_val[:90])

    print("\n=== canonical_content_items fields ===")
    cci_rows = conn.execute(text(
        "SELECT id, source_platform, source_url, external_content_id FROM canonical_content_items LIMIT 5"
    )).fetchall()
    for r in cci_rows:
        print(f"  id={r[0]} platform={r[1]} source_url={str(r[2])[:60]} ext_id={r[3]}")

    print("\n=== Join analysis ===")
    # Match 1: em.source_url = cci.id (old YouTube short ID)
    m1 = conn.execute(text(
        "SELECT COUNT(DISTINCT em.id) FROM entity_mentions em "
        "JOIN canonical_content_items cci ON cci.id = em.source_url"
    )).scalar()
    print(f"Match em.source_url = cci.id: {m1}")

    # Match 2: em.source_url = cci.source_url (full URL)
    m2 = conn.execute(text(
        "SELECT COUNT(DISTINCT em.id) FROM entity_mentions em "
        "JOIN canonical_content_items cci ON cci.source_url = em.source_url"
    )).scalar()
    print(f"Match em.source_url = cci.source_url: {m2}")

    # Match 3: video ID extracted from em.source_url matches cci.id
    # YouTube URL pattern: ?v=VIDEOID or /embed/VIDEOID or youtu.be/VIDEOID
    m3 = conn.execute(text("""
        SELECT COUNT(DISTINCT em.id)
        FROM entity_mentions em
        JOIN canonical_content_items cci
          ON cci.id = SUBSTRING(em.source_url FROM 'v=([A-Za-z0-9_-]{11})')
        WHERE em.source_url LIKE '%youtube%' OR em.source_url LIKE '%youtu.be%'
    """)).scalar()
    print(f"Match YT video ID extracted from em.source_url = cci.id: {m3}")

    # Match 4: external_content_id = em.source_url (if source_url stores video ID)
    m4 = conn.execute(text(
        "SELECT COUNT(DISTINCT em.id) FROM entity_mentions em "
        "JOIN canonical_content_items cci ON cci.external_content_id = em.source_url"
    )).scalar()
    print(f"Match em.source_url = cci.external_content_id: {m4}")

    # Match 5: external_content_id extracted from YT URL
    m5 = conn.execute(text("""
        SELECT COUNT(DISTINCT em.id)
        FROM entity_mentions em
        JOIN canonical_content_items cci
          ON cci.external_content_id = SUBSTRING(em.source_url FROM 'v=([A-Za-z0-9_-]{11})')
        WHERE em.source_url LIKE '%youtube%'
    """)).scalar()
    print(f"Match YT video ID from em.source_url = cci.external_content_id: {m5}")

    # Match 6: Reddit - em.source_url contains post ID matching cci
    # Reddit URLs: /r/subreddit/comments/POST_ID/title/
    m6 = conn.execute(text("""
        SELECT COUNT(DISTINCT em.id)
        FROM entity_mentions em
        JOIN canonical_content_items cci
          ON cci.external_content_id = SUBSTRING(em.source_url FROM '/comments/([a-z0-9]+)/')
        WHERE em.source_url LIKE '%reddit%'
    """)).scalar()
    print(f"Match Reddit post ID from em.source_url = cci.external_content_id: {m6}")

    print("\n=== Platform breakdown of entity_mentions ===")
    plat_rows = conn.execute(text("""
        SELECT
            CASE
                WHEN source_url LIKE '%youtube%' OR source_url LIKE '%youtu.be%' THEN 'youtube'
                WHEN source_url LIKE '%reddit%' THEN 'reddit'
                ELSE 'other'
            END as plat,
            COUNT(*) as cnt
        FROM entity_mentions
        WHERE source_url IS NOT NULL
        GROUP BY 1
    """)).fetchall()
    for r in plat_rows:
        print(f"  {r[0]}: {r[1]}")

    print("\n=== Active entities (have timeseries) without topics ===")
    no_topics = conn.execute(text("""
        SELECT COUNT(DISTINCT em2.entity_id)
        FROM entity_market em2
        WHERE em2.entity_type = 'perfume'
        AND NOT EXISTS (
            SELECT 1 FROM entity_topic_links etl WHERE etl.entity_id = CAST(em2.id AS TEXT)
        )
    """)).scalar()
    with_topics = conn.execute(text("""
        SELECT COUNT(DISTINCT entity_id) FROM entity_topic_links
    """)).scalar()
    total_active = conn.execute(text(
        "SELECT COUNT(*) FROM entity_market WHERE entity_type = 'perfume'"
    )).scalar()
    print(f"Total perfume entities: {total_active}")
    print(f"With topics: {with_topics}")
    print(f"Without topics: {no_topics}")
    print(f"Coverage: {with_topics/total_active*100:.1f}%")
