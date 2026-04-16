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
 * After a session is established:
 *   - verified the email is approved in app_users (backend check)
 *   - approved  → redirect to /dashboard
 *   - not approved / API error → sign out + redirect to /login?error=not_approved
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/auth/client";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";

async function verifyApproval(email: string): Promise<boolean> {
  if (!API_BASE) return false;
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/auth/users/${encodeURIComponent(email.toLowerCase())}`,
      { cache: "no-store" }
    );
    if (!res.ok) return false;
    const user = await res.json();
    return user?.access_status === "approved";
  } catch {
    return false;
  }
}

function recordLogin(email: string): void {
  if (!API_BASE) return;
  fetch(
    `${API_BASE}/api/v1/auth/users/${encodeURIComponent(email.toLowerCase())}/login`,
    { method: "POST", cache: "no-store" }
  ).catch(() => {});
}

export default function AuthCallbackPage() {
  const router = useRouter();
  const [status, setStatus] = useState("Signing you in\u2026");

  useEffect(() => {
    const supabase = createClient();

    async function finalize(email: string) {
      const approved = await verifyApproval(email);
      if (!approved) {
        setStatus("Access not approved. Redirecting\u2026");
        await supabase.auth.signOut();
        router.replace("/login?error=not_approved");
        return;
      }
      recordLogin(email);
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
        if (error || !data.session?.user?.email) {
          console.error("[PTI] exchangeCodeForSession failed:", error?.message);
          router.replace("/login?error=auth_failed");
          return;
        }
        await finalize(data.session.user.email);
        return;
      }

      // ── Implicit flow: #access_token= in hash ────────────────────────────
      // @supabase/ssr createBrowserClient has detectSessionInUrl: true by default.
      // getSession() automatically parses and stores the hash tokens.
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (session?.user?.email) {
        await finalize(session.user.email);
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
      } = supabase.auth.onAuthStateChange(async (_event, session) => {
        if (session?.user?.email) {
          clearTimeout(timeout);
          sub.unsubscribe();
          await finalize(session.user.email);
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
