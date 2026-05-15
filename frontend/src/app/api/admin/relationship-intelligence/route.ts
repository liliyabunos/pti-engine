/**
 * FTG-4 / RI1-E — Admin Relationship Intelligence base GET proxy (Next.js server route).
 *
 * FIX: The [...path] sibling only matches paths with at least one segment after the
 * base URL. GET /api/admin/relationship-intelligence?filter=all has ZERO extra
 * segments — so Next.js returns 404 from the catch-all. This base route.ts handles
 * the segment-free GET (list) call.
 *
 * POST/PATCH calls to /api/admin/relationship-intelligence/{id}/... continue to be
 * handled by the [...path]/route.ts sibling (they always carry at least one segment).
 *
 * Authorization model (identical to [...path]/route.ts):
 *   1. Reads the Supabase session from the httpOnly cookie.
 *   2. Checks user email against ADMIN_EMAILS env var (comma-separated).
 *   3. Also checks user ID against ADMIN_USER_IDS env var (comma-separated).
 *   4. Only after confirming admin identity, forwards to FastAPI with:
 *        X-Pti-Admin-User: <admin_email_or_id>
 *   5. Browser cannot forge X-Pti-Admin-User — only this server route sets it.
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
  const qs = searchParams.toString() ? `?${searchParams.toString()}` : "";

  try {
    const resp = await fetch(
      `${BACKEND}/api/v1/admin/relationship-intelligence${qs}`,
      {
        headers: {
          Accept: "application/json",
          "X-Pti-Admin-User": adminId,
        },
        cache: "no-store",
      },
    );
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    console.error("[admin/relationship-intelligence] GET backend error:", err);
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 503 });
  }
}
