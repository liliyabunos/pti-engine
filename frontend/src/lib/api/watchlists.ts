import { apiFetch, apiMutate } from "./client";
import type {
  WatchlistDetail,
  WatchlistListResponse,
  WatchlistSummary,
} from "./types";

export function fetchWatchlists(): Promise<WatchlistListResponse> {
  return apiFetch<WatchlistListResponse>("/api/v1/watchlists");
}

export function fetchWatchlist(id: string): Promise<WatchlistDetail> {
  return apiFetch<WatchlistDetail>(`/api/v1/watchlists/${id}`);
}

export function createWatchlist(
  name: string,
  description?: string,
): Promise<WatchlistSummary> {
  return apiMutate<WatchlistSummary>("/api/v1/watchlists", {
    method: "POST",
    body: { name, description },
  });
}

export function addWatchlistItem(
  watchlistId: string,
  entity_id: string,
  entity_type: string,
): Promise<WatchlistDetail> {
  return apiMutate<WatchlistDetail>(
    `/api/v1/watchlists/${watchlistId}/items`,
    { method: "POST", body: { entity_id, entity_type } },
  );
}

export function removeWatchlistItem(
  watchlistId: string,
  entityId: string,
): Promise<void> {
  return apiMutate<void>(
    `/api/v1/watchlists/${watchlistId}/items/${encodeURIComponent(entityId)}`,
    { method: "DELETE" },
  );
}
