/**
 * C2 — Creator Claim API proxy (Next.js server route).
 *
 * This route runs server-side only. It:
 *   1. Reads the Supabase session from the httpOnly cookie (server-side).
 *   2. Extracts the verified user ID.
 *   3. Forwards the request to the FastAPI backend with X-Pti-Verified-User-Id header.
 *
 * Browser clients NEVER send X-Pti-Verified-User-Id directly — only this
 * server route does, after verifying the Supabase session.
 *
 * GET  /api/creator-claims  — list current user's claims (proxied to FastAPI /me)
 * POST /api/creator-claims  — submit a new claim
 */

import { NextRequest, NextResponse } from "next/server";

import { createClient } from "@/lib/auth/server";

const BACKEND =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function getVerifiedUserId(): Promise<string | null> {
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    return user?.id ?? null;
  } catch {
    return null;
  }
}

export async function POST(request: NextRequest) {
  const userId = await getVerifiedUserId();
  if (!userId) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  try {
    const resp = await fetch(`${BACKEND}/api/v1/creator-claims`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Pti-Verified-User-Id": userId,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    console.error("[creator-claims] POST backend error:", err);
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 }
    );
  }
}

export async function GET(request: NextRequest) {
  const userId = await getVerifiedUserId();
  if (!userId) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  // Forward query params (platform, creator_id) to backend
  const { searchParams } = request.nextUrl;
  const params = new URLSearchParams();
  for (const [k, v] of searchParams.entries()) {
    params.set(k, v);
  }
  const qs = params.toString() ? `?${params.toString()}` : "";

  try {
    const resp = await fetch(`${BACKEND}/api/v1/creator-claims/me${qs}`, {
      headers: {
        Accept: "application/json",
        "X-Pti-Verified-User-Id": userId,
      },
      cache: "no-store",
    });

    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    console.error("[creator-claims] GET backend error:", err);
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 }
    );
  }
}
