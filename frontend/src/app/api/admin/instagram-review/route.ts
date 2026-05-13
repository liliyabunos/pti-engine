/**
 * IG1-R — Admin Instagram Review API proxy (Next.js server route).
 *
 * Authorization model (identical to other admin proxies):
 *   1. Reads the Supabase session from the httpOnly cookie.
 *   2. Checks user email/ID against ADMIN_EMAILS / ADMIN_USER_IDS env vars.
 *   3. Only after confirming admin identity, forwards to FastAPI with
 *        X-Pti-Admin-User: <admin_email_or_id>
 *   4. Browser cannot forge X-Pti-Admin-User — this server route is the only path.
 *
 * Security rules:
 *   - INSTAGRAM_ACCESS_TOKEN is never returned to the browser.
 *   - Only the FastAPI sanitized response (IGStatusResponse / IGDemoResponse) is forwarded.
 *   - This is a read-only demo endpoint — no DB writes.
 *
 * Supported:
 *   GET /api/admin/instagram-review?action=status
 *       → proxies to GET /api/v1/admin/instagram-review/status
 *   GET /api/admin/instagram-review?action=demo&hashtag=perfume
 *       → proxies to GET /api/v1/admin/instagram-review/demo?hashtag=perfume
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

export async function GET(request: NextRequest): Promise<NextResponse> {
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
          "X-Pti-Admin-User": adminId,
        },
      }
    );
    const body = await resp.json().catch(() => ({}));
    return NextResponse.json(body, { status: resp.status });
  } catch (err) {
    console.error("[instagram-review proxy] backend unreachable", err);
    return NextResponse.json(
      { detail: "Backend unreachable" },
      { status: 502 }
    );
  }
}
