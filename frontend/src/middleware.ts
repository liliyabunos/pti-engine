import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";

/**
 * Route gating middleware — Phase 3 (Supabase session + app_users approval).
 *
 * Public routes (no auth required):
 *   /          — landing page
 *   /login     — magic link login
 *   /glossary  — signal glossary
 *   /privacy   — privacy policy
 *   /terms     — terms of use
 *   /auth/*    — Supabase callback
 *   /_next/*   — Next.js internals
 *   /api/*     — backend proxy / health
 *
 * Protected routes — require:
 *   1. A valid Supabase session (httpOnly cookie)
 *   2. email approved in app_users (checked via PTI API)
 *
 * Two-layer security:
 *   Layer 1 — this middleware: early redirect before the page renders
 *   Layer 2 — (terminal)/layout.tsx: server-side re-check before rendering content
 *
 * Performance note:
 *   The app_users approval check is a fetch to the PTI API on every protected
 *   request. This is acceptable for soft-launch traffic volumes.
 *   For higher scale, add a short-lived server-side cache or embed approval
 *   status in the Supabase JWT custom claims.
 */

const PUBLIC_PATHS = new Set(["/", "/login", "/glossary", "/privacy", "/terms"]);
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Pass through Next.js internals, Supabase callback, and API routes
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/auth") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/healthz") ||
    pathname.startsWith("/health")
  ) {
    return NextResponse.next();
  }

  // Public pages are always accessible
  if (PUBLIC_PATHS.has(pathname)) {
    return refreshSessionAndContinue(request);
  }

  // ── Protected path — verify session + approval ──
  return guardProtectedRoute(request, pathname);
}

/**
 * For public pages: refresh the Supabase session (renew token if near expiry)
 * without blocking the response.
 */
async function refreshSessionAndContinue(request: NextRequest) {
  const response = NextResponse.next();
  buildSupabaseClient(request, response); // wires cookie refresh as a side effect
  return response;
}

/**
 * For protected pages: verify Supabase session AND approval status.
 */
async function guardProtectedRoute(request: NextRequest, pathname: string) {
  const response = NextResponse.next();
  const supabase = buildSupabaseClient(request, response);

  // Check Supabase session
  const { data: { user } } = await supabase.auth.getUser();

  if (!user?.email) {
    return redirectToLogin(request, pathname);
  }

  // Check approval in app_users
  const approved = await checkApproval(user.email);
  if (!approved) {
    // Valid Supabase session but not approved — sign out and redirect
    await supabase.auth.signOut();
    return redirectToLogin(request, pathname, "not_approved");
  }

  return response;
}

function buildSupabaseClient(request: NextRequest, response: NextResponse) {
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            request.cookies.set(name, value);
            response.cookies.set(name, value, options);
          });
        },
      },
    }
  );
}

async function checkApproval(email: string): Promise<boolean> {
  if (!API_BASE) return false;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3_000);

  try {
    const res = await fetch(
      `${API_BASE}/api/v1/auth/users/${encodeURIComponent(email.toLowerCase())}`,
      { cache: "no-store", signal: controller.signal }
    );
    if (!res.ok) return false;
    const user = await res.json();
    return user?.access_status === "approved";
  } catch {
    // Fail closed: timeout, network failure, or API unreachable → deny access
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function redirectToLogin(
  request: NextRequest,
  pathname: string,
  error?: string
) {
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.searchParams.set("next", pathname);
  if (error) loginUrl.searchParams.set("error", error);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
