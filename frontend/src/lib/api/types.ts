// ---------------------------------------------------------------------------
// PTI Market Terminal — API Response Types
// Mirrors backend Pydantic schemas exactly — do not compute from these on the
// client side. Format for display only via src/lib/formatters/index.ts.
// ---------------------------------------------------------------------------

export interface DashboardKPIs {
  tracked_brands: number;
  tracked_perfumes: number;
  active_movers: number;
  breakout_signals_today: number;
  acceleration_signals_today: number;
  total_signals_today: number;
  avg_market_score_today: number | null;
  avg_confidence_today: number | null;
  as_of_date: string | null;
}

export interface TopMoverRow {
  rank: number;
  entity_id: string;
  entity_type: string;
  ticker: string;
  canonical_name: string;
  name: string;
  brand_name: string | null;
  composite_market_score: number;
  /** Score after flood dampening — used for leaderboard sort order. */
  effective_rank_score: number;
  mention_count: number;
  /** Distinct authors/posts that mentioned this entity on the latest day. */
  unique_authors: number | null;
  /** True when unique_authors < 2 — score dampened to prevent single-post flood. */
  is_flood_dampened: boolean;
  growth_rate: number | null;
  confidence_avg: number | null;
  momentum: number | null;
  acceleration: number | null;
  volatility: number | null;
  latest_signal: string | null;
  latest_signal_strength: number | null;
  /** Concentration-variant canonical names collapsed into this row. */
  variant_names: string[];
}

export interface SignalRow {
  entity_id: string;
  signal_type: string;
  detected_at: string;
  strength: number;
  confidence: number | null;
  ticker: string | null;
  canonical_name: string | null;
  entity_type: string | null;
  brand_name: string | null;
  metadata_json: Record<string, unknown> | null;
}

export interface DashboardResponse {
  generated_at: string;
  total_entities: number;
  kpis: DashboardKPIs | null;
  top_movers: TopMoverRow[];
  recent_signals: SignalRow[];
  breakouts: TopMoverRow[];
}

export interface EntitySummary {
  entity_id: string;
  entity_type: string;
  ticker: string;
  canonical_name: string;
  brand_name: string | null;
  date: string | null;
  mention_count: number | null;
  engagement_sum: number | null;
  composite_market_score: number | null;
  confidence_avg: number | null;
  momentum: number | null;
  acceleration: number | null;
  volatility: number | null;
  growth_rate: number | null;
  latest_signal_type: string | null;
  latest_signal_strength: number | null;
}

export interface ScreenerResponse {
  total: number;
  limit: number;
  offset: number;
  rows: EntitySummary[];
}

export interface SnapshotRow {
  date: string;
  mention_count: number;
  unique_authors: number;
  engagement_sum: number;
  composite_market_score: number;
  confidence_avg: number | null;
  momentum: number | null;
  acceleration: number | null;
  volatility: number | null;
  growth_rate: number | null;
  search_index: number | null;
  retailer_score: number | null;
}

export interface RecentMentionRow {
  source_platform: string | null;
  source_url: string | null;
  author_name: string | null;
  engagement: number | null;
  occurred_at: string;
}

export interface EntitySummaryBlock {
  entity_id: string;
  entity_type: string;
  name: string;
  ticker: string;
  brand_name: string | null;
  last_score: number | null;
  mention_count: number | null;
  growth_rate: number | null;
  confidence_avg: number | null;
  momentum: number | null;
  acceleration: number | null;
  volatility: number | null;
  latest_date: string | null;
}

export interface EntityDetail {
  entity: Record<string, unknown>;
  latest: Record<string, unknown> | null;
  history: SnapshotRow[];
  signals: SignalRow[];
  summary: EntitySummaryBlock | null;
  recent_mentions: RecentMentionRow[];
}

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

export interface CatalogPerfumeRow {
  resolver_id: number;
  canonical_name: string;
  brand_name: string | null;
  /** Slug used in /entities/<entity_id> — present if tracked in market engine. */
  entity_id: string | null;
  /** True when mention_count > 0 on the latest data date. */
  has_activity_today: boolean;
}

export interface CatalogBrandRow {
  resolver_id: number;
  canonical_name: string;
  perfume_count: number;
  entity_id: string | null;
  has_activity_today: boolean;
}

export interface CatalogPerfumesResponse {
  total: number;
  limit: number;
  offset: number;
  rows: CatalogPerfumeRow[];
}

export interface CatalogBrandsResponse {
  total: number;
  limit: number;
  offset: number;
  rows: CatalogBrandRow[];
}

export interface CatalogCounts {
  /** Total in resolver KB (56k+). */
  known_perfumes: number;
  /** Total in resolver KB (1,600+). */
  known_brands: number;
  /** Entities with mention_count > 0 on the latest data date. */
  active_today: number;
  /** entity_market rows with entity_type='perfume'. */
  tracked_perfumes: number;
  /** entity_market rows with entity_type='brand'. */
  tracked_brands: number;
}

export interface CatalogParams {
  q?: string;
  limit?: number;
  offset?: number;
  sort_by?: string;
  active_only?: boolean;
}

export interface ScreenerParams {
  entity_type?: string;
  min_score?: number;
  min_confidence?: number;
  min_mentions?: number;
  signal_type?: string;
  has_signals?: boolean;
  sort_by?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Watchlists
// ---------------------------------------------------------------------------

export interface WatchlistSummary {
  id: string;
  name: string;
  description: string | null;
  item_count: number;
  created_at: string;
  updated_at: string;
}

export interface WatchlistItemRow {
  entity_id: string;
  entity_type: string;
  ticker: string;
  canonical_name: string;
  brand_name: string | null;
  composite_market_score: number | null;
  growth_rate: number | null;
  mention_count: number | null;
  confidence_avg: number | null;
  latest_signal: string | null;
  latest_date: string | null;
  added_at: string;
}

export interface WatchlistDetail {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  items: WatchlistItemRow[];
}

export interface WatchlistListResponse {
  watchlists: WatchlistSummary[];
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export const ALERT_CONDITION_TYPES = [
  "breakout_detected",
  "acceleration_detected",
  "any_new_signal",
  "score_above",
  "growth_above",
  "confidence_below",
] as const;

export type AlertConditionType = (typeof ALERT_CONDITION_TYPES)[number];

export interface AlertRow {
  id: string;
  name: string;
  entity_id: string;
  entity_type: string;
  canonical_name: string | null;
  ticker: string | null;
  condition_type: AlertConditionType;
  threshold_value: number | null;
  cooldown_hours: number;
  is_active: boolean;
  delivery_type: string;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertEventRow {
  id: string;
  alert_id: string;
  alert_name: string | null;
  entity_id: string;
  entity_type: string;
  canonical_name: string | null;
  triggered_at: string;
  status: "triggered" | "suppressed";
  reason_json: string | null;
  created_at: string;
}

export interface AlertListResponse {
  alerts: AlertRow[];
}

export interface AlertHistoryResponse {
  events: AlertEventRow[];
  total: number;
}
