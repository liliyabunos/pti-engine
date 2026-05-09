/**
 * C2.1 — Admin reject creator claim (Next.js server route).
 *
 * POST /api/admin/creator-claims/[id]/reject
 * Body: { rejection_reason: string }
 *
 * Server-side only. Reads Supabase session, checks admin allowlist,
 * then forwards to FastAPI POST /api/v1/admin/creator-claims/{id}/reject
 * with X-Pti-Admin-User header.
 */

import { NextRequest, NextResponse } from "next/server";

import { createClient } from "@/lib/auth/server";

const BACKEND =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function getAdminIdentifier(): Promise<string | null> {
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return null;

    const adminEmails = (process.env.ADMIN_EMAILS ?? "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);

    const adminUserIds = (process.env.ADMIN_USER_IDS ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const email = user.email?.toLowerCase() ?? "";
    const userId = user.id;

    if (
      (email && adminEmails.includes(email)) ||
      adminUserIds.includes(userId)
    ) {
      return email || userId;
    }
    return null;
  } catch {
    return null;
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));

  if (!user) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const adminId = await getAdminIdentifier();
  if (!adminId) {
    return NextResponse.json({ detail: "Forbidden" }, { status: 403 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  try {
    const resp = await fetch(
      `${BACKEND}/api/v1/admin/creator-claims/${encodeURIComponent(id)}/reject`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Pti-Admin-User": adminId,
        },
        body: JSON.stringify(body),
        cache: "no-store",
      }
    );
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    console.error("[admin/creator-claims/reject] POST backend error:", err);
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 }
    );
  }
}
