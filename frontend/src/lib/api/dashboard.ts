import { apiFetch } from "./client";
import type { DashboardResponse } from "./types";

export function fetchDashboard(params?: {
  top_n?: number;
  signal_days?: number;
}): Promise<DashboardResponse> {
  return apiFetch<DashboardResponse>("/api/v1/dashboard", params);
}
