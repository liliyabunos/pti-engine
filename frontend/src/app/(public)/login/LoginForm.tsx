"use client";

import { useState, useTransition, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { createOtpClient } from "@/lib/auth/otp-client";

type LoginState = "idle" | "success" | "error";

// Detects WhatsApp, Instagram, Facebook, and other in-app browsers
// that restrict fetch/cookie behavior or may have unexpected window.location.origin
function detectInAppBrowser(): string | null {
  if (typeof navigator === "undefined") return null;
  const ua = navigator.userAgent;
  if (/WhatsApp/.test(ua)) return "WhatsApp";
  if (/FBAN|FBAV|FB_IAB/.test(ua)) return "Facebook";
  if (/Instagram/.test(ua)) return "Instagram";
  if (/Line\//.test(ua)) return "Line";
  if (/Snapchat/.test(ua)) return "Snapchat";
  return null;
}

// Always use the env var for redirect — never rely on window.location.origin.
// In-app browsers (WhatsApp WebView) may return unexpected or null origins,
// causing emailRedirectTo to fail Supabase's allowlist check.
const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ||
  "https://pti-frontend-production.up.railway.app";

export default function LoginForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [state, setState] = useState<LoginState>("idle");
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [inAppBrowser, setInAppBrowser] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const next = searchParams.get("next") || "/dashboard";

  useEffect(() => {
    setInAppBrowser(detectInAppBrowser());
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const normalized = email.trim().toLowerCase();
    if (!normalized) return;

    startTransition(async () => {
      setState("idle");
      setErrorDetail(null);

      const emailRedirectTo = `${SITE_URL}/auth/callback?next=${encodeURIComponent(next)}`;

      console.log("[PTI LOGIN] attempting signInWithOtp", {
        email: normalized,
        emailRedirectTo,
        origin: typeof window !== "undefined" ? window.location.origin : "ssr",
        userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "ssr",
      });

      const supabase = createOtpClient();
      const { error } = await supabase.auth.signInWithOtp({
        email: normalized,
        options: { emailRedirectTo },
      });

      if (error) {
        console.error("[PTI LOGIN] signInWithOtp failed", {
          message: error.message,
          status: error.status,
          name: error.name,
        });
        setErrorDetail(error.message);
        setState("error");
        return;
      }

      console.log("[PTI LOGIN] signInWithOtp success — email dispatched");
      setState("success");
    });
  }

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">

        {/* ── In-app browser warning ── */}
        {inAppBrowser && (
          <div className="mb-6 rounded border border-amber-700/50 bg-amber-950/40 px-4 py-3">
            <p className="text-xs leading-relaxed text-amber-300">
              You&apos;re opening PTI inside {inAppBrowser}. For sign-in to work
              correctly, please open this page in{" "}
              <strong>Safari</strong> or your default browser first.
            </p>
          </div>
        )}

        {/* Header block */}
        <div className="mb-10">
          <div className="mb-3 flex items-center gap-2">
            <span className="h-px w-6 bg-amber-500/60" />
            <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-500/80">
              Soft launch
            </span>
          </div>
          <h1 className="mb-1 text-xl font-bold tracking-tight text-zinc-100">
            PTI Market Terminal
          </h1>
          <p className="text-sm text-zinc-500">
            Enter your email to receive a secure sign-in link.
          </p>
        </div>

        {/* ── Success state ── */}
        {state === "success" && (
          <div className="rounded border border-zinc-700 bg-zinc-900 p-5">
            <p className="mb-1 text-sm font-medium text-zinc-100">
              Check your email
            </p>
            <p className="text-xs leading-relaxed text-zinc-500">
              A secure sign-in link has been sent to{" "}
              <span className="text-zinc-300">{email.trim().toLowerCase()}</span>.
              Click the link in the email to open the terminal. The link expires
              in 1 hour.
            </p>
          </div>
        )}

        {/* ── Form (idle / error) ── */}
        {state !== "success" && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="mb-1.5 block text-xs font-medium text-zinc-400"
              >
                Email address
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className={[
                  "w-full rounded border bg-zinc-900 px-4 py-2.5 text-sm text-zinc-100",
                  "placeholder:text-zinc-700",
                  "focus:outline-none focus:ring-1",
                  state === "error"
                    ? "border-red-800 focus:ring-red-700/40"
                    : "border-zinc-700 focus:border-amber-500 focus:ring-amber-500/30",
                ].join(" ")}
              />

              {/* ── Error ── */}
              {state === "error" && (
                <p className="mt-2 text-xs text-red-400">
                  {errorDetail ?? "Unable to send sign-in link. Please try again."}
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={isPending || !email.trim()}
              className="w-full rounded bg-amber-500 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-amber-400 disabled:opacity-50 transition-colors"
            >
              {isPending ? "Sending…" : "Send magic link →"}
            </button>
          </form>
        )}

        {/* ── Footer note ── */}
        <p className="mt-8 text-center text-xs text-zinc-700">
          Problems signing in?{" "}
          <a
            href="mailto:access@pti.market"
            className="text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Contact support
          </a>
        </p>
      </div>
    </div>
  );
}
