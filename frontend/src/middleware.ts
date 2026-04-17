import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";

/**
 * Route gating middleware — session gate only (soft launch).
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
 * Protected routes — require a valid Supabase session (httpOnly cookie).
 * No app_users approval check at this stage — access gating via payment layer later.
 */

const PUBLIC_PATHS = new Set(["/", "/login", "/glossary", "/privacy", "/terms"]);

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

  // ── Protected path — verify session ──
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
 * For protected pages: verify Supabase session only.
 */
async function guardProtectedRoute(request: NextRequest, pathname: string) {
  const response = NextResponse.next();
  const supabase = buildSupabaseClient(request, response);

  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    return redirectToLogin(request, pathname);
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

function redirectToLogin(request: NextRequest, pathname: string) {
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
