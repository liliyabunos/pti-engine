"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

/**
 * Auth-aware "Suggest a Source" CTA for the public landing page.
 *
 * - Logged in  → /submit-source (direct, no login redirect)
 * - Logged out → /login?next=/submit-source
 *
 * Session check uses the same lazy import pattern as PublicHeader to avoid
 * SSR crashes from browser-only Supabase client evaluation.
 */
export function SuggestSourceCta() {
  const [href, setHref] = useState<string>("/login?next=/submit-source");

  useEffect(() => {
    import("@/lib/auth/client")
      .then(({ createClient }) => createClient().auth.getSession())
      .then(({ data }) => {
        if (data.session) setHref("/submit-source");
      })
      .catch(() => {
        // Stay on default /login?next=/submit-source
      });
  }, []);

  return (
    <Link
      href={href}
      className="shrink-0 inline-flex items-center gap-2 rounded border border-amber-500/50 px-5 py-2.5 text-sm font-medium text-amber-400 hover:border-amber-400 hover:text-amber-300 transition-colors"
    >
      Suggest a Source
      <span aria-hidden className="text-zinc-600">→</span>
    </Link>
  );
}
