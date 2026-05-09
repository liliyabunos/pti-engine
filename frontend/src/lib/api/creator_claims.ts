/**
 * C2 — Creator Claim API client.
 *
 * All requests go to /api/creator-claims (Next.js server route),
 * NOT directly to the FastAPI backend. The server route reads the
 * Supabase session and injects the verified user_id header.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ClaimResponse {
  claim_id: string;
  platform: string;
  creator_id: string;
  claim_status: "pending" | "verified" | "rejected" | "revoked";
  claim_method: "bio_code" | "screenshot" | "manual_review";
  evidence_url: string | null;
  /** Plaintext verification code — only present on initial submission of bio_code claims. */
  verification_code: string | null;
  verification_code_expires_at: string | null;
  message: string;
  claimed_at: string | null;
  verified_at: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
}

export interface ClaimSummary {
  claim_id: string;
  platform: string;
  creator_id: string;
  claim_status: "pending" | "verified" | "rejected" | "revoked";
  claim_method: "bio_code" | "screenshot" | "manual_review";
  evidence_url: string | null;
  claimed_at: string | null;
  verified_at: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
}

export interface ClaimListResponse {
  claims: ClaimSummary[];
}

export interface CreateClaimParams {
  platform: string;
  creator_id: string;
  claim_method: "bio_code" | "screenshot" | "manual_review";
  evidence_url: string;
  note?: string;
}

// ---------------------------------------------------------------------------
// API functions — call /api/creator-claims (Next.js server route)
// ---------------------------------------------------------------------------

export async function submitClaim(
  params: CreateClaimParams
): Promise<ClaimResponse> {
  const resp = await fetch("/api/creator-claims", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    cache: "no-store",
  });

  if (!resp.ok) {
    let detail = "Submission failed. Please try again.";
    try {
      const body = await resp.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore
    }
    const err = new Error(detail);
    (err as Error & { status: number }).status = resp.status;
    throw err;
  }

  return resp.json();
}

export async function fetchMyClaims(
  platform?: string,
  creatorId?: string
): Promise<ClaimListResponse> {
  const params = new URLSearchParams();
  if (platform) params.set("platform", platform);
  if (creatorId) params.set("creator_id", creatorId);
  const qs = params.toString() ? `?${params.toString()}` : "";

  const resp = await fetch(`/api/creator-claims${qs}`, {
    cache: "no-store",
  });

  if (!resp.ok) {
    return { claims: [] };
  }
  return resp.json();
}
