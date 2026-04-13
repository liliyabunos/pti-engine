import { apiFetch } from "./client";
import type { SignalRow } from "./types";

interface SignalsResponse {
  total: number;
  rows: SignalRow[];
}

export function fetchSignals(params?: {
  days?: number;
  entity_type?: string;
  signal_type?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}): Promise<SignalsResponse> {
  return apiFetch<SignalsResponse>("/api/v1/signals", params);
}
