/**
 * C2.1 — Admin Creator Claims API proxy (Next.js server route).
 *
 * Authorization model (server-side only):
 *   1. Reads the Supabase session from the httpOnly cookie.
 *   2. Checks user email against ADMIN_EMAILS env var (comma-separated).
 *   3. Also checks user ID against ADMIN_USER_IDS env var (comma-separated).
 *   4. Only after confirming admin identity, forwards to FastAPI with:
 *        X-Pti-Admin-User: <admin_email_or_id>
 *   5. Browser cannot forge X-Pti-Admin-User — only this server route sets it.
 *
 * ADMIN_EMAILS / ADMIN_USER_IDS are temporary environment allowlists (C2.1).
 * Future hardening option: app_admins table or Supabase custom claims.
 *
 * GET /api/admin/creator-claims?status=pending — list claims (proxied to FastAPI)
 */

import { NextRequest, NextResponse } from "next/server";

import { createClient } from "@/lib/auth/server";

const BACKEND =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Returns admin identifier string if user is admin, null otherwise. */
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
      // Prefer email as the human-readable reviewed_by identifier
      return email || userId;
    }

    return null;
  } catch {
    return null;
  }
}

export async function GET(request: NextRequest) {
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

  const { searchParams } = request.nextUrl;
  const params = new URLSearchParams();
  for (const [k, v] of searchParams.entries()) {
    params.set(k, v);
  }
  const qs = params.toString() ? `?${params.toString()}` : "";

  try {
    const resp = await fetch(
      `${BACKEND}/api/v1/admin/creator-claims${qs}`,
      {
        headers: {
          Accept: "application/json",
          "X-Pti-Admin-User": adminId,
        },
        cache: "no-store",
      }
    );
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    console.error("[admin/creator-claims] GET backend error:", err);
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 }
    );
  }
}
