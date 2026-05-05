import { apiFetch } from "./client";
import type { DashboardResponse } from "./types";

export function fetchDashboard(params?: {
  top_n?: number;
  signal_days?: number;
  range_preset?: string;
  start_date?: string;
  end_date?: string;
}): Promise<DashboardResponse> {
  return apiFetch<DashboardResponse>("/api/v1/dashboard", params);
}
