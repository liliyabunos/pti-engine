/**
 * SOURCE-INTAKE-V1A — TypeScript types and fetch helpers for the admin source intake API.
 *
 * All requests go through Next.js server routes (/api/admin/source-intake/*)
 * which inject X-Pti-Admin-User from the verified Supabase session.
 * Never call the FastAPI backend directly from the browser.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CandidateStatus =
  | "PENDING_VERIFICATION"
  | "VERIFIED_ADD_READY"
  | "SKIP_DUPLICATE"
  | "SKIP_INACTIVE"
  | "NEEDS_OPERATOR_REVIEW"
  | "OPERATOR_APPROVED"
  | "OPERATOR_REJECTED"
  | "DEFERRED"
  | "BLOCKED_BY_API_PERMISSION"
  | "APPLIED"
  | "APPLY_FAILED"
  | "PRODUCTION_VERIFIED";

export interface BatchSummary {
  id: string;
  batch_label: string;
  platform: string;
  description: string | null;
  status: string;
  candidate_count: number;
  applied_count: number;
  created_at: string | null;
  created_by: string;
  applied_at: string | null;
  applied_by: string | null;
  verified_at: string | null;
  count_verified_add_ready: number;
  count_needs_review: number;
  count_applied: number;
  count_operator_approved: number;
}

export interface BatchListResponse {
  batches: BatchSummary[];
  total: number;
}

export interface CandidateRow {
  id: string;
  batch_id: string;
  platform: string;
  candidate_name: string;
  input_url: string;
  resolved_platform_id: string | null;
  resolved_title: string | null;
  subscriber_count: number | null;
  total_content_count: number | null;
  recent_content_count: number | null;
  recent_titles_sample: string | null;
  resolve_method: string | null;
  confidence: string | null;
  status: CandidateStatus;
  decision_reason: string | null;
  operator_override_url: string | null;
  operator_notes: string | null;
  quality_tier: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  applied_at: string | null;
  apply_error: string | null;
  created_at: string | null;
  // Role Routing v1
  source_role: string | null;
  creator_score_eligible: boolean | null;
}

export interface CandidateListResponse {
  candidates: CandidateRow[];
  total: number;
  batch_id: string;
}

export interface ApplyResult {
  batch_id: string;
  applied: number;
  skipped: number;
  failed: number;
  details: Array<{
    candidate_id: string;
    name?: string;
    channel_id?: string;
    result: string;
    reason?: string;
    error?: string;
  }>;
}

export interface ProductionVerifyResult {
  batch_id: string;
  verified: number;
  pending_ingestion: number;
  details: Array<{
    candidate_id: string;
    channel_id?: string;
    name?: string;
    content_items?: number;
    result: string;
  }>;
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

export const STATUS_LABELS: Record<CandidateStatus, string> = {
  PENDING_VERIFICATION: "Pending",
  VERIFIED_ADD_READY: "Add Ready",
  SKIP_DUPLICATE: "Duplicate",
  SKIP_INACTIVE: "Inactive",
  NEEDS_OPERATOR_REVIEW: "Needs Review",
  OPERATOR_APPROVED: "Approved",
  OPERATOR_REJECTED: "Rejected",
  DEFERRED: "Deferred",
  BLOCKED_BY_API_PERMISSION: "Blocked",
  APPLIED: "Applied",
  APPLY_FAILED: "Apply Failed",
  PRODUCTION_VERIFIED: "Verified",
};

export const STATUS_COLORS: Record<CandidateStatus, string> = {
  PENDING_VERIFICATION: "text-zinc-400",
  VERIFIED_ADD_READY: "text-green-400",
  SKIP_DUPLICATE: "text-zinc-500",
  SKIP_INACTIVE: "text-zinc-500",
  NEEDS_OPERATOR_REVIEW: "text-amber-400",
  OPERATOR_APPROVED: "text-green-300",
  OPERATOR_REJECTED: "text-red-400",
  DEFERRED: "text-zinc-400",
  BLOCKED_BY_API_PERMISSION: "text-orange-400",
  APPLIED: "text-blue-400",
  APPLY_FAILED: "text-red-500",
  PRODUCTION_VERIFIED: "text-emerald-400",
};

export const TERMINAL_STATUSES = new Set<CandidateStatus>([
  "SKIP_DUPLICATE",
  "SKIP_INACTIVE",
  "OPERATOR_REJECTED",
  "PRODUCTION_VERIFIED",
]);

export const APPLY_ELIGIBLE = new Set<CandidateStatus>([
  "VERIFIED_ADD_READY",
  "OPERATOR_APPROVED",
]);

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const API_BASE = "/api/admin/source-intake";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(body.detail ?? `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export async function fetchBatches(params?: {
  platform?: string;
  status?: string;
  limit?: number;
}): Promise<BatchListResponse> {
  const qs = new URLSearchParams();
  if (params?.platform) qs.set("platform", params.platform);
  if (params?.status) qs.set("status", params.status);
  if (params?.limit) qs.set("limit", String(params.limit));
  return apiFetch<BatchListResponse>(`/batches${qs.toString() ? `?${qs}` : ""}`);
}

export async function fetchBatchCandidates(
  batchId: string,
  status?: string,
): Promise<CandidateListResponse> {
  const qs = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<CandidateListResponse>(`/batches/${batchId}${qs}`);
}

export async function approveCandidate(candidateId: string): Promise<void> {
  await apiFetch(`/candidates/${candidateId}/approve`, { method: "POST" });
}

export async function rejectCandidate(
  candidateId: string,
  reason: string,
): Promise<void> {
  await apiFetch(`/candidates/${candidateId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function deferCandidate(candidateId: string): Promise<void> {
  await apiFetch(`/candidates/${candidateId}/defer`, { method: "POST" });
}

export async function markDuplicate(candidateId: string): Promise<void> {
  await apiFetch(`/candidates/${candidateId}/mark-duplicate`, { method: "POST" });
}

export async function updateCandidateOverride(
  candidateId: string,
  overrideUrl: string,
  notes?: string,
): Promise<void> {
  await apiFetch(`/candidates/${candidateId}`, {
    method: "PATCH",
    body: JSON.stringify({
      operator_override_url: overrideUrl,
      operator_notes: notes ?? undefined,
    }),
  });
}

export async function updateCandidateRole(
  candidateId: string,
  sourceRole: string,
  creatorScoreEligible?: boolean,
): Promise<void> {
  await apiFetch(`/candidates/${candidateId}`, {
    method: "PATCH",
    body: JSON.stringify({
      source_role: sourceRole,
      ...(creatorScoreEligible !== undefined ? { creator_score_eligible: creatorScoreEligible } : {}),
    }),
  });
}

export async function rerunCandidate(candidateId: string): Promise<CandidateRow> {
  return apiFetch<CandidateRow>(`/candidates/${candidateId}/rerun`, { method: "POST" });
}

export async function applyBatch(batchId: string): Promise<ApplyResult> {
  return apiFetch<ApplyResult>(`/batches/${batchId}/apply`, { method: "POST" });
}

export async function productionVerifyBatch(
  batchId: string,
): Promise<ProductionVerifyResult> {
  return apiFetch<ProductionVerifyResult>(`/batches/${batchId}/production-verify`, {
    method: "POST",
  });
}
