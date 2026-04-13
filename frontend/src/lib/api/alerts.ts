import { apiFetch, apiMutate } from "./client";
import type {
  AlertHistoryResponse,
  AlertListResponse,
  AlertRow,
} from "./types";

export function fetchAlerts(): Promise<AlertListResponse> {
  return apiFetch<AlertListResponse>("/api/v1/alerts");
}

export function fetchAlertHistory(params?: {
  limit?: number;
  offset?: number;
  alert_id?: string;
}): Promise<AlertHistoryResponse> {
  return apiFetch<AlertHistoryResponse>("/api/v1/alerts/history", params);
}

export interface CreateAlertBody {
  name: string;
  entity_id: string;
  entity_type: string;
  condition_type: string;
  threshold_value?: number;
  cooldown_hours?: number;
}

export function createAlert(body: CreateAlertBody): Promise<AlertRow> {
  return apiMutate<AlertRow>("/api/v1/alerts", { method: "POST", body });
}

export function patchAlert(
  id: string,
  body: { is_active?: boolean; name?: string; cooldown_hours?: number },
): Promise<AlertRow> {
  return apiMutate<AlertRow>(`/api/v1/alerts/${id}`, {
    method: "PATCH",
    body,
  });
}
