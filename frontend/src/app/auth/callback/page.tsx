"use client";

/**
 * Auth callback page — client-side session finalizer.
 *
 * Handles TWO Supabase magic link response shapes:
 *
 *   1. Implicit flow  → URL hash:  #access_token=...&refresh_token=...
 *      Used by admin-generated links (generate_magic_link.py).
 *      Server Route Handlers NEVER see the hash — only the browser can read it.
 *
 *   2. PKCE flow      → URL query: ?code=...
 *      Used by browser-initiated signInWithOtp (normal login form).
 *      exchangeCodeForSession() exchanges the code for a session.
 *
 * After a session is established → redirect to /dashboard.
 * No approval gate at this stage — access control via payment/subscription later.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/auth/client";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [status, setStatus] = useState("Signing you in\u2026");

  useEffect(() => {
    const supabase = createClient();

    function finalize() {
      router.replace("/dashboard");
    }

    async function handleCallback() {
      const url = new URL(window.location.href);
      const code = url.searchParams.get("code");
      const next = url.searchParams.get("next") ?? "/dashboard";
      void next; // reserved for future use

      // ── PKCE flow: ?code= present ────────────────────────────────────────
      if (code) {
        const { data, error } = await supabase.auth.exchangeCodeForSession(code);
        if (error || !data.session) {
          console.error("[PTI] exchangeCodeForSession failed:", error?.message);
          router.replace("/login?error=auth_failed");
          return;
        }
        finalize();
        return;
      }

      // ── Implicit flow: #access_token= in hash ────────────────────────────
      // @supabase/ssr createBrowserClient has detectSessionInUrl: true by default.
      // getSession() automatically parses and stores the hash tokens.
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (session) {
        finalize();
        return;
      }

      // Session not ready yet — wait for onAuthStateChange (hash parsing async)
      const timeout = setTimeout(() => {
        sub.unsubscribe();
        console.error("[PTI] Auth callback timeout — no session established");
        router.replace("/login?error=auth_failed");
      }, 8_000);

      const {
        data: { subscription: sub },
      } = supabase.auth.onAuthStateChange((_event, session) => {
        if (session) {
          clearTimeout(timeout);
          sub.unsubscribe();
          finalize();
        }
      });
    }

    handleCallback().catch((err) => {
      console.error("[PTI] Auth callback unexpected error:", err);
      router.replace("/login?error=auth_failed");
    });
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950">
      <p className="text-sm text-zinc-400">{status}</p>
    </div>
  );
}
