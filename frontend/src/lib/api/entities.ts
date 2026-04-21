import { apiFetch } from "./client";
import type { EntityDetail, EntitySummary, PerfumeEntityDetail, BrandEntityDetail } from "./types";

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

export function fetchPerfumeEntity(
  id: string,
  params?: { history_days?: number },
): Promise<PerfumeEntityDetail> {
  return apiFetch<PerfumeEntityDetail>(
    `/api/v1/entities/perfume/${encodeURIComponent(id)}`,
    params,
  );
}

export function fetchBrandEntity(
  id: string,
  params?: { history_days?: number },
): Promise<BrandEntityDetail> {
  return apiFetch<BrandEntityDetail>(
    `/api/v1/entities/brand/${encodeURIComponent(id)}`,
    params,
  );
}
