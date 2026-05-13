/**
 * IG1-R — Meta App Review public demo proxy (Next.js server route).
 *
 * This route is intentionally accessible WITHOUT Supabase authentication.
 * It exists solely to allow Meta App Review reviewers to test the
 * Instagram Public Content demo at /meta-review/instagram.
 *
 * Security model:
 *   - No Supabase session required — the reviewer has no FragranceIndex account.
 *   - Injects X-Pti-Admin-User: meta-app-review (fixed string, not a secret).
 *     The backend requires this header to be present; the reviewer cannot
 *     call the backend directly because NEXT_PUBLIC_API_BASE_URL points to
 *     a Railway internal URL not exposed publicly.
 *   - Only two safe read-only actions are forwarded: status + demo.
 *   - Demo hashtags are validated against an allowlist on the backend.
 *   - INSTAGRAM_ACCESS_TOKEN is never returned to the browser.
 *   - No DB writes. No admin capabilities beyond the two demo endpoints.
 *
 * Supported:
 *   GET /api/review/instagram-review?action=status
 *       → proxies to GET /api/v1/admin/instagram-review/status
 *   GET /api/review/instagram-review?action=demo&hashtag=perfume
 *       → proxies to GET /api/v1/admin/instagram-review/demo?hashtag=perfume
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams } = request.nextUrl;
  const action = searchParams.get("action") ?? "status";
  const hashtag = searchParams.get("hashtag") ?? "perfume";

  let backendPath: string;
  let backendQs = "";

  if (action === "demo") {
    backendPath = "demo";
    backendQs = `?hashtag=${encodeURIComponent(hashtag)}`;
  } else {
    backendPath = "status";
  }

  try {
    const resp = await fetch(
      `${BACKEND}/api/v1/admin/instagram-review/${backendPath}${backendQs}`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          "X-Pti-Admin-User": "meta-app-review",
        },
      }
    );
    const body = await resp.json().catch(() => ({}));
    return NextResponse.json(body, { status: resp.status });
  } catch (err) {
    console.error("[review/instagram-review proxy] backend unreachable", err);
    return NextResponse.json(
      { detail: "Backend unreachable" },
      { status: 502 }
    );
  }
}
