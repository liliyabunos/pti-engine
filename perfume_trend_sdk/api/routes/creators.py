from __future__ import annotations

"""
Creator Intelligence routes — Phase C1 Product/API.

GET /api/v1/creators                — leaderboard ranked by influence_score
GET /api/v1/creators/{creator_id}   — creator profile with entity portfolio
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from perfume_trend_sdk.api.dependencies import get_db_session
from perfume_trend_sdk.api.schemas.creators import (
    CreatorLeaderboardResponse,
    CreatorProfileResponse,
    CreatorRow,
    EntityRelationshipRow,
    RecentContentRow,
)

router = APIRouter()
_log = logging.getLogger(__name__)

_SORT_ALLOWLIST = frozenset({
    "influence_score",
    "early_signal_count",
    "avg_views",
    "total_entity_mentions",
    "unique_entities_mentioned",
    "noise_rate",
})


def _fmt_date(val) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ---------------------------------------------------------------------------
# GET /api/v1/creators
# ---------------------------------------------------------------------------

@router.get("", response_model=CreatorLeaderboardResponse, summary="Creator leaderboard")
def list_creators(
    sort_by: str = Query("influence_score", description="Sort field"),
    order: Literal["asc", "desc"] = Query("desc"),
    quality_tier: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    platform: str = Query("youtube"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> CreatorLeaderboardResponse:
    # Validate sort_by against allowlist — fall back to influence_score on unknown value
    if sort_by not in _SORT_ALLOWLIST:
        sort_by = "influence_score"
    order_sql = "ASC" if order == "asc" else "DESC"

    where_clauses = ["cs.platform = :platform"]
    params: dict = {"platform": platform, "limit": limit, "offset": offset}

    if quality_tier:
        where_clauses.append("cs.quality_tier = :quality_tier")
        params["quality_tier"] = quality_tier
    if category:
        where_clauses.append("cs.category = :category")
        params["category"] = category

    where_sql = " AND ".join(where_clauses)

    # Total count (for pagination)
    try:
        count_row = db.execute(
            text(f"SELECT COUNT(*) FROM creator_scores cs WHERE {where_sql}"),
            params,
        ).fetchone()
        total = int(count_row[0]) if count_row else 0
    except Exception as exc:
        _log.warning("[C1] creator_scores unavailable: %s", exc)
        return CreatorLeaderboardResponse(total=0, limit=limit, offset=offset, creators=[])

    rows = db.execute(text(f"""
        SELECT
            cs.platform,
            cs.creator_id,
            cs.creator_handle,
            cs.quality_tier,
            cs.category,
            cs.subscriber_count,
            cs.total_content_items,
            cs.content_with_entity_mentions,
            cs.noise_rate,
            cs.unique_entities_mentioned,
            cs.unique_brands_mentioned,
            cs.total_entity_mentions,
            cs.total_views,
            cs.avg_views,
            cs.total_likes,
            cs.total_comments,
            cs.avg_engagement_rate,
            cs.breakout_contributions,
            cs.early_signal_count,
            cs.early_signal_rate,
            cs.influence_score,
            cs.score_components,
            cs.computed_at
        FROM creator_scores cs
        WHERE {where_sql}
        ORDER BY cs.{sort_by} {order_sql} NULLS LAST
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    creators = []
    for r in rows:
        sc = r[21]
        if isinstance(sc, str):
            import json
            sc = json.loads(sc)
        creators.append(CreatorRow(
            platform=r[0],
            creator_id=r[1],
            creator_handle=r[2],
            quality_tier=r[3],
            category=r[4],
            subscriber_count=r[5],
            total_content_items=int(r[6] or 0),
            content_with_entity_mentions=int(r[7] or 0),
            noise_rate=float(r[8]) if r[8] is not None else None,
            unique_entities_mentioned=int(r[9] or 0),
            unique_brands_mentioned=int(r[10] or 0),
            total_entity_mentions=int(r[11] or 0),
            total_views=int(r[12] or 0),
            avg_views=float(r[13]) if r[13] is not None else None,
            total_likes=int(r[14] or 0),
            total_comments=int(r[15] or 0),
            avg_engagement_rate=float(r[16]) if r[16] is not None else None,
            breakout_contributions=int(r[17] or 0),
            early_signal_count=int(r[18] or 0),
            early_signal_rate=float(r[19]) if r[19] is not None else None,
            influence_score=float(r[20]) if r[20] is not None else None,
            score_components=sc,
            computed_at=_fmt_date(r[22]),
        ))

    return CreatorLeaderboardResponse(total=total, limit=limit, offset=offset, creators=creators)


# ---------------------------------------------------------------------------
# GET /api/v1/creators/{creator_id}
# ---------------------------------------------------------------------------

@router.get("/{creator_id}", response_model=CreatorProfileResponse, summary="Creator profile")
def get_creator(
    creator_id: str,
    platform: str = Query("youtube"),
    top_entities_limit: int = Query(20, ge=1, le=100),
    recent_content_limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db_session),
) -> CreatorProfileResponse:
    # Scores row
    try:
        score_row = db.execute(text("""
            SELECT
                cs.platform,
                cs.creator_id,
                cs.creator_handle,
                cs.quality_tier,
                cs.category,
                cs.subscriber_count,
                cs.total_content_items,
                cs.content_with_entity_mentions,
                cs.noise_rate,
                cs.unique_entities_mentioned,
                cs.unique_brands_mentioned,
                cs.total_entity_mentions,
                cs.total_views,
                cs.avg_views,
                cs.total_likes,
                cs.total_comments,
                cs.avg_engagement_rate,
                cs.breakout_contributions,
                cs.early_signal_count,
                cs.early_signal_rate,
                cs.influence_score,
                cs.score_components,
                cs.computed_at
            FROM creator_scores cs
            WHERE cs.platform = :platform AND cs.creator_id = :creator_id
        """), {"platform": platform, "creator_id": creator_id}).fetchone()
    except Exception as exc:
        _log.warning("[C1] creator_scores unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Creator Intelligence data not available in this environment")

    if score_row is None:
        raise HTTPException(status_code=404, detail=f"Creator not found: {creator_id}")

    sc = score_row[21]
    if isinstance(sc, str):
        import json
        sc = json.loads(sc)

    # Channel metadata from youtube_channels (YouTube-specific)
    ch_row = None
    if platform == "youtube":
        ch_row = db.execute(text("""
            SELECT title, quality_tier, category, status,
                   subscriber_count, view_count, video_count
            FROM youtube_channels
            WHERE channel_id = :cid
        """), {"cid": creator_id}).fetchone()

    # Top entities
    entity_rows = db.execute(text("""
        SELECT
            CAST(cer.entity_id AS TEXT),
            cer.entity_type,
            cer.canonical_name,
            cer.brand_name,
            cer.mention_count,
            cer.unique_content_count,
            cer.first_mention_date,
            cer.last_mention_date,
            cer.total_views,
            cer.avg_views,
            cer.total_likes,
            cer.total_comments,
            cer.avg_engagement_rate,
            cer.mentions_before_first_breakout,
            cer.days_before_first_breakout
        FROM creator_entity_relationships cer
        WHERE cer.platform = :platform AND cer.creator_id = :creator_id
        ORDER BY cer.mention_count DESC, cer.total_views DESC
        LIMIT :lim
    """), {"platform": platform, "creator_id": creator_id, "lim": top_entities_limit}).fetchall()

    top_entities = [
        EntityRelationshipRow(
            entity_id=r[0],
            entity_type=r[1],
            canonical_name=r[2],
            brand_name=r[3],
            mention_count=int(r[4] or 0),
            unique_content_count=int(r[5] or 0),
            first_mention_date=_fmt_date(r[6]),
            last_mention_date=_fmt_date(r[7]),
            total_views=int(r[8] or 0),
            avg_views=float(r[9]) if r[9] is not None else None,
            total_likes=int(r[10] or 0),
            total_comments=int(r[11] or 0),
            avg_engagement_rate=float(r[12]) if r[12] is not None else None,
            mentions_before_first_breakout=int(r[13] or 0),
            days_before_first_breakout=int(r[14]) if r[14] is not None else None,
        )
        for r in entity_rows
    ]

    # Recent content from canonical_content_items
    recent_content: list[RecentContentRow] = []
    try:
        content_rows = db.execute(text("""
            SELECT
                cci.title,
                cci.source_url,
                cci.published_at,
                (cci.engagement_json::jsonb->>'views')::bigint   AS views,
                (cci.engagement_json::jsonb->>'likes')::bigint   AS likes,
                (cci.engagement_json::jsonb->>'comments')::bigint AS comments,
                cci.ingestion_method
            FROM canonical_content_items cci
            WHERE cci.source_account_id = :cid
              AND cci.source_platform = :platform
            ORDER BY cci.published_at DESC
            LIMIT :lim
        """), {"cid": creator_id, "platform": platform, "lim": recent_content_limit}).fetchall()

        recent_content = [
            RecentContentRow(
                title=r[0],
                source_url=r[1],
                published_at=str(r[2]) if r[2] else None,
                views=int(r[3]) if r[3] is not None else None,
                likes=int(r[4]) if r[4] is not None else None,
                comments=int(r[5]) if r[5] is not None else None,
                ingestion_method=r[6],
            )
            for r in content_rows
        ]
    except Exception as exc:
        _log.warning("[C1] recent_content query failed for %s: %s", creator_id, exc)

    # Construct external platform URL from creator_id
    external_url: Optional[str] = None
    if platform == "youtube" and creator_id:
        external_url = f"https://www.youtube.com/channel/{creator_id}"

    return CreatorProfileResponse(
        platform=score_row[0],
        creator_id=score_row[1],
        creator_handle=score_row[2],
        # Channel metadata (YouTube only)
        title=ch_row[0] if ch_row else None,
        quality_tier=ch_row[1] if ch_row else score_row[3],
        category=ch_row[2] if ch_row else score_row[4],
        status=ch_row[3] if ch_row else None,
        subscriber_count=ch_row[4] if ch_row else score_row[5],
        channel_view_count=int(ch_row[5]) if ch_row and ch_row[5] is not None else None,
        channel_video_count=int(ch_row[6]) if ch_row and ch_row[6] is not None else None,
        external_url=external_url,
        # Scores
        influence_score=float(score_row[20]) if score_row[20] is not None else None,
        score_components=sc,
        early_signal_count=int(score_row[18] or 0),
        early_signal_rate=float(score_row[19]) if score_row[19] is not None else None,
        unique_entities_mentioned=int(score_row[9] or 0),
        total_entity_mentions=int(score_row[11] or 0),
        avg_engagement_rate=float(score_row[16]) if score_row[16] is not None else None,
        total_views=int(score_row[12] or 0),
        breakout_contributions=int(score_row[17] or 0),
        noise_rate=float(score_row[8]) if score_row[8] is not None else None,
        computed_at=_fmt_date(score_row[22]),
        top_entities=top_entities,
        recent_content=recent_content,
    )
