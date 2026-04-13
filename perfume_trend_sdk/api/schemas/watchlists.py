from __future__ import annotations

"""Pydantic schemas for the watchlists API."""

from typing import Optional

from pydantic import BaseModel, Field


class WatchlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class WatchlistItemAdd(BaseModel):
    entity_id: str = Field(..., min_length=1, max_length=255)
    entity_type: str = Field(..., pattern="^(perfume|brand|note)$")


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

class WatchlistItemRow(BaseModel):
    """Enriched watchlist item row — includes current market data."""
    entity_id: str
    entity_type: str
    ticker: str
    canonical_name: str
    brand_name: Optional[str]
    composite_market_score: Optional[float]
    growth_rate: Optional[float]
    mention_count: Optional[float]
    confidence_avg: Optional[float]
    latest_signal: Optional[str]
    latest_date: Optional[str]
    added_at: str


class WatchlistSummary(BaseModel):
    """Lightweight watchlist row used in the sidebar list."""
    id: str
    name: str
    description: Optional[str]
    item_count: int
    created_at: str
    updated_at: str


class WatchlistDetail(BaseModel):
    """Full watchlist with enriched item rows."""
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    items: list[WatchlistItemRow]


class WatchlistListResponse(BaseModel):
    watchlists: list[WatchlistSummary]
