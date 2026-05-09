/**
 * C2.1 — Admin Creator Claims API client.
 *
 * All requests go through /api/admin/creator-claims (Next.js server routes),
 * NOT directly to the FastAPI backend. The server routes verify admin identity
 * server-side before forwarding with X-Pti-Admin-User header.
 */

export interface AdminClaimEntry {
  claim_id: string;
  user_id: string;
  platform: string;
  creator_id: string;
  creator_display_name: string | null;
  creator_profile_url: string | null;
  claim_method: "bio_code" | "screenshot" | "manual_review";
  claim_status: "pending" | "verified" | "rejected" | "revoked";
  evidence_url: string | null;
  reviewer_notes: string | null;
  claimed_at: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  rejection_reason: string | null;
}

export interface AdminClaimListResponse {
  claims: AdminClaimEntry[];
  total: number;
}

export type ClaimStatusFilter = "pending" | "verified" | "rejected" | "all";

export async function adminListClaims(
  status: ClaimStatusFilter = "pending"
): Promise<AdminClaimListResponse> {
  const resp = await fetch(
    `/api/admin/creator-claims?status=${encodeURIComponent(status)}`,
    { cache: "no-store" }
  );

  if (resp.status === 401) {
    throw Object.assign(new Error("Unauthorized"), { status: 401 });
  }
  if (resp.status === 403) {
    throw Object.assign(new Error("Forbidden"), { status: 403 });
  }
  if (!resp.ok) {
    throw new Error("Failed to load claims");
  }
  return resp.json();
}

export async function adminApproveClaim(claimId: string): Promise<void> {
  const resp = await fetch(
    `/api/admin/creator-claims/${encodeURIComponent(claimId)}/approve`,
    { method: "POST", cache: "no-store" }
  );
  if (!resp.ok) {
    let detail = "Approve failed";
    try {
      const body = await resp.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore
    }
    throw Object.assign(new Error(detail), { status: resp.status });
  }
}

export async function adminRejectClaim(
  claimId: string,
  rejectionReason: string
): Promise<void> {
  const resp = await fetch(
    `/api/admin/creator-claims/${encodeURIComponent(claimId)}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rejection_reason: rejectionReason }),
      cache: "no-store",
    }
  );
  if (!resp.ok) {
    let detail = "Reject failed";
    try {
      const body = await resp.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore
    }
    throw Object.assign(new Error(detail), { status: resp.status });
  }
}
