from __future__ import annotations

"""
Pydantic v2 schemas for entity-level API responses.

Frontend contract:
- All metrics are precomputed; no aggregation expected on the client.
- history is chart-ready: sorted ASC, one row per day.
- signals are newest-first.
- recent_mentions is newest-first (up to 5 rows by default).
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class EntitySummary(BaseModel):
    """Entity row in a list or screener table."""

    entity_id: str
    entity_type: str
    ticker: str
    canonical_name: str
    brand_name: Optional[str] = None          # populated for perfumes
    # Latest snapshot fields — None when no snapshot exists yet
    date: Optional[str] = None
    mention_count: Optional[float] = None
    engagement_sum: Optional[float] = None
    composite_market_score: Optional[float] = None
    confidence_avg: Optional[float] = None
    momentum: Optional[float] = None
    acceleration: Optional[float] = None
    volatility: Optional[float] = None
    growth_rate: Optional[float] = None
    # Latest signal (if any) for screener/dashboard enrichment
    latest_signal_type: Optional[str] = None
    latest_signal_strength: Optional[float] = None
    # Top 3 notes for screener chips (populated only in screener response, empty otherwise)
    top_notes: List[str] = []


class SnapshotRow(BaseModel):
    """Single day in an entity's time series — chart-ready."""

    date: str
    mention_count: float
    unique_authors: int
    engagement_sum: float
    composite_market_score: float
    weighted_signal_score: Optional[float] = None  # Phase I2 — source-quality-weighted score
    confidence_avg: Optional[float] = None
    momentum: Optional[float] = None
    acceleration: Optional[float] = None
    volatility: Optional[float] = None
    growth_rate: Optional[float] = None
    search_index: Optional[float] = None
    retailer_score: Optional[float] = None


class SignalRow(BaseModel):
    """A detected market signal event."""

    entity_id: str           # canonical name string from EntityMarket.entity_id
    signal_type: str
    detected_at: str
    strength: float
    confidence: Optional[float] = None
    ticker: Optional[str] = None
    canonical_name: Optional[str] = None
    entity_type: Optional[str] = None
    brand_name: Optional[str] = None          # populated for perfumes
    metadata_json: Optional[Dict[str, Any]] = None


class RecentMentionRow(BaseModel):
    """Lightweight mention source row for entity detail context block."""

    source_platform: Optional[str] = None
    source_url: Optional[str] = None
    author_name: Optional[str] = None
    engagement: Optional[float] = None
    occurred_at: str
    # Phase I1 — source intelligence fields (nullable for backward compat)
    views: Optional[int] = None
    likes: Optional[int] = None
    comments_count: Optional[int] = None
    engagement_rate: Optional[float] = None


class EntityDetail(BaseModel):
    """Full entity page payload: metadata + chart series + signal history."""

    entity: Dict[str, Any]
    latest: Optional[Dict[str, Any]] = None
    history: List[SnapshotRow] = []
    signals: List[SignalRow] = []
    # Step 8C additions
    summary: Optional[Dict[str, Any]] = None           # structured flat summary block
    recent_mentions: List[RecentMentionRow] = []       # latest 5 mention sources


class MentionRow(BaseModel):
    """Single raw mention record for a drilldown view."""

    id: str                              # UUID as string
    entity_type: str
    source_platform: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    mention_count: float
    influence_score: Optional[float] = None
    sentiment: Optional[float] = None
    confidence: Optional[float] = None
    engagement: Optional[float] = None
    region: Optional[str] = None
    channel: Optional[str] = None
    occurred_at: str
