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

      // ── PKCE flow: ?code= present ────────────────────────────────────────
      if (code) {
        console.log("[PTI CALLBACK] pkce flow — exchanging code");
        const { data, error } = await supabase.auth.exchangeCodeForSession(code);
        if (error || !data.session) {
          console.error("[PTI CALLBACK] pkce exchange failed:", error?.message);
          router.replace("/login?error=auth_failed");
          return;
        }
        finalize();
        return;
      }

      // ── Implicit flow: #access_token= in hash ────────────────────────────
      // @supabase/ssr createBrowserClient hardcodes flowType:"pkce" and does NOT
      // process #access_token= hash tokens automatically. We must parse the hash
      // manually and call setSession() directly so the PKCE-wired cookie storage
      // receives the tokens.
      const hash = window.location.hash.slice(1);
      const hashParams = hash ? new URLSearchParams(hash) : null;
      const accessToken = hashParams?.get("access_token");
      const refreshToken = hashParams?.get("refresh_token");

      if (accessToken && refreshToken) {
        console.log("[PTI CALLBACK] implicit flow — calling setSession from hash");
        const { data, error } = await supabase.auth.setSession({
          access_token: accessToken,
          refresh_token: refreshToken,
        });
        if (error || !data.session) {
          console.error("[PTI CALLBACK] setSession from hash failed:", error?.message);
          router.replace("/login?error=auth_failed");
          return;
        }
        finalize();
        return;
      }

      // No hash tokens — check cookies (already-established session edge case)
      console.log("[PTI CALLBACK] no hash tokens — checking existing session");
      const { data: { session } } = await supabase.auth.getSession();
      if (session) {
        console.log("[PTI CALLBACK] found existing session in cookies");
        finalize();
        return;
      }

      // Nothing worked — log details and fail
      console.error(
        "[PTI CALLBACK] no session established. hash present:", !!hash,
        "access_token present:", !!accessToken,
        "code present:", !!code
      );
      router.replace("/login?error=auth_failed");
    }

    handleCallback().catch((err) => {
      console.error("[PTI CALLBACK] unexpected error:", err);
      router.replace("/login?error=auth_failed");
    });
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950">
      <p className="text-sm text-zinc-400">{status}</p>
    </div>
  );
}
