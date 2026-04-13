from __future__ import annotations

"""
Pydantic v2 schemas for dashboard and screener API responses.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from perfume_trend_sdk.api.schemas.entity import EntitySummary, SignalRow


class DashboardKPIs(BaseModel):
    """Headline KPI block for the dashboard summary bar."""

    tracked_brands: int
    tracked_perfumes: int
    active_movers: int
    breakout_signals_today: int
    acceleration_signals_today: int
    total_signals_today: int
    avg_market_score_today: Optional[float] = None
    avg_confidence_today: Optional[float] = None
    as_of_date: Optional[str] = None


class TopMoverRow(BaseModel):
    """Screener-ready row for the top movers leaderboard."""

    rank: int
    entity_id: str
    entity_type: str
    ticker: str
    canonical_name: str
    name: str                                  # alias for canonical_name — terminal display
    brand_name: Optional[str] = None           # populated for perfumes
    composite_market_score: float
    effective_rank_score: float                # composite_market_score × flood dampening
    mention_count: float
    unique_authors: Optional[int] = None       # distinct authors/posts contributing
    is_flood_dampened: bool = False            # True when unique_authors < 2
    growth_rate: Optional[float] = None
    confidence_avg: Optional[float] = None
    momentum: Optional[float] = None
    acceleration: Optional[float] = None
    volatility: Optional[float] = None
    latest_signal: Optional[str] = None        # signal_type of most-recent signal
    latest_signal_strength: Optional[float] = None
    variant_names: List[str] = []              # concentration variants collapsed into this row


class DashboardResponse(BaseModel):
    """Full dashboard payload."""

    generated_at: str
    total_entities: int
    kpis: Optional[DashboardKPIs] = None       # Step 8A headline KPIs
    top_movers: List[TopMoverRow]
    recent_signals: List[SignalRow]
    breakouts: List[TopMoverRow]


class ScreenerResponse(BaseModel):
    """Filterable, sortable entity table response."""

    total: int
    limit: int
    offset: int
    rows: List[EntitySummary]
