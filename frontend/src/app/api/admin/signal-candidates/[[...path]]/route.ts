/**
 * SIG-ID1 — Admin Signal Candidates API proxy (Next.js server route).
 *
 * Authorization model (identical to other admin routes):
 *   1. Reads the Supabase session from the httpOnly cookie.
 *   2. Checks user email against ADMIN_EMAILS env var (comma-separated).
 *   3. Also checks user ID against ADMIN_USER_IDS env var (comma-separated).
 *   4. Only after confirming admin identity, forwards to FastAPI with:
 *        X-Pti-Admin-User: <admin_email_or_id>
 *   5. Browser cannot forge X-Pti-Admin-User — only this server route sets it.
 *
 * Supported methods: GET, POST
 * Routes handled (proxied to FastAPI /api/v1/admin/signal-candidates/*):
 *   GET  /api/admin/signal-candidates           — list candidates (base route.ts)
 *   POST /api/admin/signal-candidates/{id}/dismiss — dismiss candidate
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

async function handler(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> },
): Promise<NextResponse> {
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

  const { path } = await context.params;
  const { searchParams } = request.nextUrl;
  const qs = searchParams.toString() ? `?${searchParams.toString()}` : "";
  const backendPath = path ? path.join("/") : "";

  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Pti-Admin-User": adminId,
  };

  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers["Content-Type"] = contentType;
  }

  const body =
    request.method !== "GET" && request.method !== "HEAD"
      ? await request.text()
      : undefined;

  const backendUrl = backendPath
    ? `${BACKEND}/api/v1/admin/signal-candidates/${backendPath}${qs}`
    : `${BACKEND}/api/v1/admin/signal-candidates${qs}`;

  try {
    const resp = await fetch(backendUrl, {
      method: request.method,
      headers,
      body: body || undefined,
      cache: "no-store",
    });
    const data = await resp.json();
    return NextResponse.json(data, { status: resp.status });
  } catch (err) {
    console.error("[admin/signal-candidates] backend error:", err);
    return NextResponse.json({ detail: "Backend unavailable" }, { status: 503 });
  }
}

export const GET = handler;
export const POST = handler;
