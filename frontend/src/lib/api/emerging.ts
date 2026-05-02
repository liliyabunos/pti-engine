import { apiFetch } from "./client";
import type { EmergingCandidateRow, EmergingResponse } from "./types";

export type { EmergingCandidateRow, EmergingResponse };

export interface EmergingParams {
  limit?: number;
  min_mentions?: number;
  min_sources?: number;
  days?: number;
  entity_type?: "perfume" | "brand" | "note";
}

export function fetchEmerging(params?: EmergingParams): Promise<EmergingResponse> {
  return apiFetch<EmergingResponse>(
    "/api/v1/emerging",
    params as Record<string, string | number | boolean | undefined>,
  );
}
