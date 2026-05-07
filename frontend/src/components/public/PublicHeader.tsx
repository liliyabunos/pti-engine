"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

/**
 * Auth-aware public header.
 *
 * Session check is done client-side only via lazy dynamic import of the
 * Supabase browser client — never evaluated during SSR, preventing the
 * "This page couldn't load" crash pattern seen on /submit-source.
 *
 * States:
 *   checking (null) — brief initial state; CTA shows "Sign in" until resolved
 *   loggedIn (true)  — shows "Open Terminal" → /dashboard
 *   loggedOut (false) — shows "Sign in" → /login
 */
export function PublicHeader() {
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  useEffect(() => {
    import("@/lib/auth/client")
      .then(({ createClient }) => createClient().auth.getSession())
      .then(({ data }) => {
        setIsLoggedIn(!!data.session);
      })
      .catch(() => {
        // Session read failed — treat as logged out; header still functional
        setIsLoggedIn(false);
      });
  }, []);

  return (
    <header className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        {/* Wordmark */}
        <Link href="/" className="flex items-center gap-2.5 text-zinc-100 hover:text-amber-400 transition-colors">
          <span className="font-mono text-xs font-bold tracking-widest text-amber-400 uppercase">
            FTI
          </span>
          <span className="text-sm font-semibold tracking-tight">
            Market Terminal
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-6 text-xs text-zinc-500">
          <Link href="/glossary" className="hover:text-zinc-300 transition-colors">
            Glossary
          </Link>
          <Link href="/privacy" className="hover:text-zinc-300 transition-colors">
            Privacy
          </Link>
          <Link href="/terms" className="hover:text-zinc-300 transition-colors">
            Terms
          </Link>

          {isLoggedIn ? (
            <Link
              href="/dashboard"
              className="rounded border border-amber-500/60 px-3 py-1.5 text-amber-400 hover:border-amber-400 hover:text-amber-300 transition-colors"
            >
              Open Terminal
            </Link>
          ) : (
            <Link
              href="/login"
              className="rounded border border-zinc-700 px-3 py-1.5 text-zinc-300 hover:border-amber-500 hover:text-amber-400 transition-colors"
            >
              Sign in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
