from __future__ import annotations

"""
Pydantic schemas for Creator Intelligence API (Phase C1 Product/API).
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

class CreatorRow(BaseModel):
    platform: str
    creator_id: str
    creator_handle: Optional[str] = None
    quality_tier: Optional[str] = None
    category: Optional[str] = None
    subscriber_count: Optional[int] = None
    total_content_items: int = 0
    content_with_entity_mentions: int = 0
    noise_rate: Optional[float] = None
    unique_entities_mentioned: int = 0
    unique_brands_mentioned: int = 0
    total_entity_mentions: int = 0
    total_views: int = 0
    avg_views: Optional[float] = None
    total_likes: int = 0
    total_comments: int = 0
    avg_engagement_rate: Optional[float] = None
    breakout_contributions: int = 0
    early_signal_count: int = 0
    early_signal_rate: Optional[float] = None
    influence_score: Optional[float] = None
    score_components: Optional[Dict[str, Any]] = None
    computed_at: Optional[str] = None


class CreatorLeaderboardResponse(BaseModel):
    total: int
    limit: int
    offset: int
    creators: List[CreatorRow]


# ---------------------------------------------------------------------------
# Creator profile
# ---------------------------------------------------------------------------

class EntityRelationshipRow(BaseModel):
    entity_id: str
    entity_type: Optional[str] = None
    canonical_name: Optional[str] = None
    brand_name: Optional[str] = None
    mention_count: int = 0
    unique_content_count: int = 0
    first_mention_date: Optional[str] = None
    last_mention_date: Optional[str] = None
    total_views: int = 0
    avg_views: Optional[float] = None
    total_likes: int = 0
    total_comments: int = 0
    avg_engagement_rate: Optional[float] = None
    mentions_before_first_breakout: int = 0
    days_before_first_breakout: Optional[int] = None


class RecentContentRow(BaseModel):
    title: Optional[str] = None
    source_url: Optional[str] = None
    published_at: Optional[str] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    ingestion_method: Optional[str] = None


class CreatorProfileResponse(BaseModel):
    platform: str
    creator_id: str
    creator_handle: Optional[str] = None
    # Channel metadata from youtube_channels
    title: Optional[str] = None
    quality_tier: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    subscriber_count: Optional[int] = None
    channel_view_count: Optional[int] = None
    channel_video_count: Optional[int] = None
    # External platform link (constructed from creator_id for YouTube)
    external_url: Optional[str] = None
    # Scores from creator_scores
    influence_score: Optional[float] = None
    score_components: Optional[Dict[str, Any]] = None
    early_signal_count: int = 0
    early_signal_rate: Optional[float] = None
    unique_entities_mentioned: int = 0
    total_entity_mentions: int = 0
    avg_engagement_rate: Optional[float] = None
    total_views: int = 0
    breakout_contributions: int = 0
    noise_rate: Optional[float] = None
    computed_at: Optional[str] = None
    # Entity portfolio
    top_entities: List[EntityRelationshipRow] = []
    # Recent content
    recent_content: List[RecentContentRow] = []


# ---------------------------------------------------------------------------
# Entity page: top creators for a perfume or brand
# ---------------------------------------------------------------------------

class TopCreatorRow(BaseModel):
    platform: str
    creator_id: str
    creator_handle: Optional[str] = None
    quality_tier: Optional[str] = None
    category: Optional[str] = None
    mention_count: int = 0
    unique_content_count: int = 0
    first_mention_date: Optional[str] = None
    last_mention_date: Optional[str] = None
    total_views: int = 0
    avg_views: Optional[float] = None
    total_likes: int = 0
    total_comments: int = 0
    avg_engagement_rate: Optional[float] = None
    mentions_before_first_breakout: int = 0
    days_before_first_breakout: Optional[int] = None
    influence_score: Optional[float] = None
    early_signal_count: int = 0


class EntityCreatorsResponse(BaseModel):
    entity_id: str
    entity_type: str
    top_creators: List[TopCreatorRow]
