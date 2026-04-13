import { apiFetch } from "./client";
import type { ScreenerParams, ScreenerResponse } from "./types";

export function fetchScreener(
  params?: ScreenerParams,
): Promise<ScreenerResponse> {
  return apiFetch<ScreenerResponse>("/api/v1/screener", params as Record<string, string | number | boolean | undefined>);
}
