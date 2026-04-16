"use client";

import { useState, useTransition } from "react";
import { useSearchParams } from "next/navigation";
import { createClient } from "@/lib/auth/client";
import { isApprovedUser } from "@/lib/auth/guards";

type LoginState = "idle" | "success" | "not_approved" | "error";

export default function LoginForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [state, setState] = useState<LoginState>("idle");
  const [isPending, startTransition] = useTransition();

  // Where to land after successful auth (magic link callback will honour this)
  const next = searchParams.get("next") || "/dashboard";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const normalized = email.trim().toLowerCase();
    if (!normalized) return;

    startTransition(async () => {
      setState("idle");

      // Step 1 — pre-check: is this email in app_users with status = approved?
      const approved = await isApprovedUser(normalized);
      if (!approved) {
        setState("not_approved");
        return;
      }

      // Step 2 — send Supabase magic link
      const supabase = createClient();
      const { error } = await supabase.auth.signInWithOtp({
        email: normalized,
        options: {
          // The callback route will redirect the user to their intended destination
          emailRedirectTo: `${process.env.NEXT_PUBLIC_SITE_URL}/auth/callback?next=${encodeURIComponent(next)}`,
        },
      });

      if (error) {
        console.error("[PTI] Magic link error:", error.message);
        setState("error");
        return;
      }

      setState("success");
    });
  }

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        {/* Header block */}
        <div className="mb-10">
          <div className="mb-3 flex items-center gap-2">
            <span className="h-px w-6 bg-amber-500/60" />
            <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-500/80">
              Invite only
            </span>
          </div>
          <h1 className="mb-1 text-xl font-bold tracking-tight text-zinc-100">
            PTI Market Terminal
          </h1>
          <p className="text-sm text-zinc-500">
            PTI is currently in invite-only soft launch. Enter your email to
            receive a secure sign-in link.
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

        {/* ── Form (idle / error / not_approved) ── */}
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
                  state === "not_approved" || state === "error"
                    ? "border-red-800 focus:ring-red-700/40"
                    : "border-zinc-700 focus:border-amber-500 focus:ring-amber-500/30",
                ].join(" ")}
              />

              {/* ── Not approved ── */}
              {state === "not_approved" && (
                <p className="mt-2 text-xs leading-relaxed text-red-400">
                  This email is not approved for access yet. If you believe this
                  is a mistake, contact{" "}
                  <a
                    href="mailto:access@pti.market"
                    className="underline underline-offset-2"
                  >
                    access@pti.market
                  </a>
                  .
                </p>
              )}

              {/* ── Error ── */}
              {state === "error" && (
                <p className="mt-2 text-xs text-red-400">
                  Unable to send sign-in link. Please try again.
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={isPending || !email.trim()}
              className="w-full rounded bg-amber-500 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-amber-400 disabled:opacity-50 transition-colors"
            >
              {isPending ? "Checking…" : "Send magic link →"}
            </button>
          </form>
        )}

        {/* ── Footer note ── */}
        <p className="mt-8 text-center text-xs text-zinc-700">
          Don&apos;t have access?{" "}
          <a
            href="mailto:access@pti.market"
            className="text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Request an invite
          </a>
        </p>
      </div>
    </div>
  );
}
