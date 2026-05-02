import { apiFetch } from "./client";
import type {
  EmergingCandidateRow,
  EmergingResponse,
  EmergingSignalRow,
  EmergingV2Response,
} from "./types";

export type { EmergingCandidateRow, EmergingResponse, EmergingSignalRow, EmergingV2Response };

// v1 params (kept for reference — v1 endpoint still available)
export interface EmergingParams {
  limit?: number;
  min_mentions?: number;
  min_sources?: number;
  days?: number;
  entity_type?: "perfume" | "brand" | "note";
}

// v2 params — channel-aware, title-first
export interface EmergingV2Params {
  limit?: number;
  days?: number;
  min_channels?: number;
  min_channel_score?: number;
  candidate_type?: "perfume" | "brand" | "clone_reference" | "flanker" | "unknown";
}

export function fetchEmerging(params?: EmergingV2Params): Promise<EmergingV2Response> {
  return apiFetch<EmergingV2Response>(
    "/api/v1/emerging/v2",
    params as Record<string, string | number | boolean | undefined>,
  );
}
