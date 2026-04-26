"use client";

/**
 * Auth callback client — implicit flow + PKCE handler.
 *
 * Receives supabaseUrl and supabaseAnonKey from the Server Component parent
 * (AuthCallbackPage) so the client bundle never reads process.env directly.
 * This avoids the build-time static inlining problem where NEXT_PUBLIC_SUPABASE_ANON_KEY
 * is undefined during Nixpacks build.
 *
 * Handles two Supabase magic link response shapes:
 *
 *   1. Implicit flow → #access_token=...&refresh_token=... in URL hash
 *      Browser reads window.location.hash. Server code can never see the hash.
 *      Calls setSession() directly to store tokens in httpOnly cookies.
 *
 *   2. PKCE flow → ?code=... in URL query string
 *      exchangeCodeForSession() exchanges the code server-side.
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createBrowserClient } from "@supabase/ssr";

interface CallbackClientProps {
  supabaseUrl: string;
  supabaseAnonKey: string;
}

export default function CallbackClient({
  supabaseUrl,
  supabaseAnonKey,
}: CallbackClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState("Signing you in\u2026");

  useEffect(() => {
    const next = searchParams.get("next") || "/dashboard";

    // Safe diagnostics — booleans and lengths only, no token values logged
    console.log("[PTI CALLBACK] client init", {
      hasSupabaseUrl: !!supabaseUrl,
      hasAnonKey: !!supabaseAnonKey,
      anonKeyLength: supabaseAnonKey?.length ?? 0,
    });

    if (!supabaseUrl || !supabaseAnonKey) {
      console.error("[PTI CALLBACK] missing Supabase credentials — redirecting to login");
      router.replace("/login?error=auth_misconfigured");
      return;
    }

    // Create client from props — NOT from process.env
    const supabase = createBrowserClient(supabaseUrl, supabaseAnonKey, {
      auth: { flowType: "implicit" },
    });

    async function handleCallback() {
      const url = new URL(window.location.href);
      const code = url.searchParams.get("code");

      // ── PKCE flow: ?code= present ───────────────────────────────────────────
      if (code) {
        console.log("[PTI CALLBACK] pkce flow — exchanging code");
        const { data, error } = await supabase.auth.exchangeCodeForSession(code);
        if (error || !data.session) {
          console.error("[PTI CALLBACK] pkce exchange failed:", error?.message);
          router.replace("/login?error=auth_failed");
          return;
        }
        console.log("[PTI CALLBACK] pkce success — redirecting", { next });
        router.replace(next);
        return;
      }

      // ── Implicit flow: #access_token= in hash ──────────────────────────────
      // @supabase/ssr createBrowserClient hardcodes flowType:"pkce" internally and
      // does NOT process #access_token= hash tokens automatically.
      // We parse the hash manually and call setSession() so the cookie storage path fires.
      const hash = window.location.hash.slice(1);
      const hashParams = hash ? new URLSearchParams(hash) : null;
      const accessToken = hashParams?.get("access_token");
      const refreshToken = hashParams?.get("refresh_token");

      console.log("[PTI CALLBACK] implicit flow check", {
        hasHash: !!hash,
        hasAccessToken: !!accessToken,
        hasRefreshToken: !!refreshToken,
      });

      if (accessToken && refreshToken) {
        const { data, error } = await supabase.auth.setSession({
          access_token: accessToken,
          refresh_token: refreshToken,
        });
        const success = !error && !!data.session;
        console.log("[PTI CALLBACK] setSession result", {
          setSessionSuccess: success,
          error: error?.message ?? null,
        });
        if (!success) {
          router.replace("/login?error=auth_failed");
          return;
        }
        console.log("[PTI CALLBACK] implicit flow success — redirecting", { next });
        router.replace(next);
        return;
      }

      // ── Fallback: check for existing session in cookies ────────────────────
      console.log("[PTI CALLBACK] no hash tokens — checking existing session");
      const { data: { session } } = await supabase.auth.getSession();
      if (session) {
        console.log("[PTI CALLBACK] found existing session — redirecting", { next });
        router.replace(next);
        return;
      }

      console.error("[PTI CALLBACK] no session established", {
        hasHash: !!hash,
        hasAccessToken: !!accessToken,
        hasRefreshToken: !!refreshToken,
        hasCode: !!code,
      });
      router.replace("/login?error=auth_failed");
    }

    handleCallback().catch((err) => {
      console.error("[PTI CALLBACK] unexpected error:", err?.message ?? err);
      router.replace("/login?error=auth_failed");
    });
  }, [router, searchParams, supabaseUrl, supabaseAnonKey]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950">
      <p className="text-sm text-zinc-400">{status}</p>
    </div>
  );
}
