import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";

/**
 * Supabase auth callback — handles the magic link redirect.
 *
 * Flow:
 *   1. Supabase redirects to /auth/callback?code=<PKCE_code>&next=<path>
 *   2. We exchange the code for a session (sets httpOnly cookies)
 *   3. We verify the authenticated email is approved in app_users
 *   4a. Approved  → update last_login_at + redirect to intended destination
 *   4b. Not approved / revoked → sign out + redirect to /login?error=not_approved
 *
 * This is the ONLY place a Supabase session is established. All other
 * auth checks are read-only (session verify via middleware or server client).
 *
 * Security: double-checking approval here means a user who was revoked
 * after receiving a magic link can never actually gain access — the
 * revocation is enforced at session creation time.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);

  // Derive the public-facing origin from Railway's reverse-proxy headers.
  // request.url contains the internal address (localhost:PORT) — never use its origin.
  // x-forwarded-proto and x-forwarded-host carry the real external URL.
  const proto =
    request.headers.get("x-forwarded-proto")?.split(",")[0].trim() ?? "https";
  const host =
    request.headers.get("x-forwarded-host") ??
    request.headers.get("host") ??
    "";
  const origin = host
    ? `${proto}://${host}`
    : process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "";

  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/dashboard";

  // No code → malformed link
  if (!code) {
    return NextResponse.redirect(`${origin}/login?error=invalid_link`);
  }

  // Build a mutable response so we can write session cookies into it
  const response = NextResponse.redirect(`${origin}${next}`);

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            response.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  // Exchange PKCE code for a session
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);

  if (error || !data.user?.email) {
    console.error("[PTI] Auth callback error:", error?.message ?? "no user");
    return NextResponse.redirect(`${origin}/login?error=auth_failed`);
  }

  const email = data.user.email.toLowerCase();

  // Verify the user is approved in our app_users table
  let approved = false;
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/auth/users/${encodeURIComponent(email)}`,
      { cache: "no-store" }
    );
    if (res.ok) {
      const appUser = await res.json();
      approved = appUser?.access_status === "approved";
    }
  } catch (err) {
    console.error("[PTI] app_users check failed:", err);
    // Fail closed: if we can't verify, deny access
    approved = false;
  }

  if (!approved) {
    // Sign the session out immediately — don't leave a valid Supabase session
    // for a user who isn't in our approved list
    await supabase.auth.signOut();
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("error", "not_approved");
    return NextResponse.redirect(loginUrl.toString());
  }

  // Update last_login_at in app_users (fire and forget — don't block redirect)
  fetch(`${API_BASE}/api/v1/auth/users/${encodeURIComponent(email)}/login`, {
    method: "POST",
    cache: "no-store",
  }).catch((err) => {
    // Non-critical — log but don't fail the login
    console.warn("[PTI] Failed to update last_login_at:", err);
  });

  // Redirect to intended destination with the session cookies set
  return response;
}
