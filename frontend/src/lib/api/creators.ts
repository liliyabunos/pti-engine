import { apiFetch } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreatorRow {
  platform: string;
  creator_id: string;
  creator_handle: string | null;
  quality_tier: string | null;
  category: string | null;
  subscriber_count: number | null;
  total_content_items: number;
  content_with_entity_mentions: number;
  noise_rate: number | null;
  unique_entities_mentioned: number;
  unique_brands_mentioned: number;
  total_entity_mentions: number;
  total_views: number;
  avg_views: number | null;
  total_likes: number;
  total_comments: number;
  avg_engagement_rate: number | null;
  breakout_contributions: number;
  early_signal_count: number;
  early_signal_rate: number | null;
  influence_score: number | null;
  score_components: Record<string, number> | null;
  computed_at: string | null;
}

export interface CreatorLeaderboardResponse {
  total: number;
  limit: number;
  offset: number;
  creators: CreatorRow[];
}

// ---------------------------------------------------------------------------
// Entity top creators
// ---------------------------------------------------------------------------

export interface TopCreatorRow {
  platform: string;
  creator_id: string;
  creator_handle: string | null;
  quality_tier: string | null;
  category: string | null;
  mention_count: number;
  unique_content_count: number;
  first_mention_date: string | null;
  last_mention_date: string | null;
  total_views: number;
  avg_views: number | null;
  total_likes: number;
  total_comments: number;
  avg_engagement_rate: number | null;
  mentions_before_first_breakout: number;
  days_before_first_breakout: number | null;
  influence_score: number | null;
  early_signal_count: number;
}

export interface EntityCreatorsResponse {
  entity_id: string;
  entity_type: string;
  top_creators: TopCreatorRow[];
}

// ---------------------------------------------------------------------------
// Creator profile
// ---------------------------------------------------------------------------

export interface EntityRelationshipRow {
  entity_id: string;
  entity_type: string | null;
  canonical_name: string | null;
  brand_name: string | null;
  mention_count: number;
  unique_content_count: number;
  first_mention_date: string | null;
  last_mention_date: string | null;
  total_views: number;
  avg_views: number | null;
  total_likes: number;
  total_comments: number;
  avg_engagement_rate: number | null;
  mentions_before_first_breakout: number;
  days_before_first_breakout: number | null;
}

export interface RecentContentRow {
  title: string | null;
  source_url: string | null;
  published_at: string | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  ingestion_method: string | null;
}

export interface CreatorProfileResponse {
  platform: string;
  creator_id: string;
  creator_handle: string | null;
  title: string | null;
  quality_tier: string | null;
  category: string | null;
  status: string | null;
  subscriber_count: number | null;
  channel_view_count: number | null;
  channel_video_count: number | null;
  influence_score: number | null;
  score_components: Record<string, number> | null;
  early_signal_count: number;
  early_signal_rate: number | null;
  unique_entities_mentioned: number;
  total_entity_mentions: number;
  avg_engagement_rate: number | null;
  total_views: number;
  breakout_contributions: number;
  noise_rate: number | null;
  computed_at: string | null;
  top_entities: EntityRelationshipRow[];
  recent_content: RecentContentRow[];
}

export async function fetchCreatorProfile(
  creatorId: string,
  platform = "youtube",
): Promise<CreatorProfileResponse> {
  return apiFetch<CreatorProfileResponse>(
    `/api/v1/creators/${encodeURIComponent(creatorId)}`,
    { platform },
  );
}

export async function fetchEntityCreators(
  entityType: string,
  entityId: string,
  limit = 10,
): Promise<EntityCreatorsResponse> {
  return apiFetch<EntityCreatorsResponse>(
    `/api/v1/entities/${entityType}/${encodeURIComponent(entityId)}/creators`,
    { limit },
  );
}

export interface FetchCreatorsParams {
  sort_by?: string;
  order?: "asc" | "desc";
  quality_tier?: string;
  category?: string;
  platform?: string;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------

export async function fetchCreators(
  params: FetchCreatorsParams = {},
): Promise<CreatorLeaderboardResponse> {
  return apiFetch<CreatorLeaderboardResponse>("/api/v1/creators", {
    sort_by: params.sort_by ?? "influence_score",
    order: params.order ?? "desc",
    quality_tier: params.quality_tier,
    category: params.category,
    platform: params.platform ?? "youtube",
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  });
}
