import { apiFetch } from "./client";
import type { EntityDetail, EntitySummary } from "./types";

export function fetchEntities(): Promise<EntitySummary[]> {
  return apiFetch<EntitySummary[]>("/api/v1/entities");
}

export function fetchEntity(
  entityId: string,
  params?: { history_days?: number },
): Promise<EntityDetail> {
  return apiFetch<EntityDetail>(
    `/api/v1/entities/${encodeURIComponent(entityId)}`,
    params,
  );
}
