"use client";

/**
 * Suggest a Source — MVP
 *
 * Low-friction logged-in flow: URL + terms only.
 * Protected by (terminal) layout — unauthenticated users are redirected to /login.
 * User email and ID are read from the Supabase session; not entered manually.
 */

import { useState, useEffect } from "react";
import { ExternalLink } from "lucide-react";
import { createClient } from "@/lib/auth/client";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type SubmitState = "idle" | "loading" | "success" | "duplicate" | "error";

// ---------------------------------------------------------------------------
// Platform badge — auto-detected from URL
// ---------------------------------------------------------------------------

function detectPlatformLabel(url: string): string | null {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (host.includes("youtube.com") || host.includes("youtu.be")) return "YouTube";
    if (host.includes("tiktok.com")) return "TikTok";
    if (host.includes("instagram.com")) return "Instagram";
    if (host.includes("reddit.com")) return "Reddit";
    return null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SuggestSourcePage() {
  const [url, setUrl] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [state, setState] = useState<SubmitState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);

  // Read session user on mount — Supabase browser client, safe in useEffect
  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => {
      if (data?.user) {
        setUserId(data.user.id ?? null);
        setUserEmail(data.user.email ?? null);
      }
    });
  }, []);

  const platformLabel = detectPlatformLabel(url);
  const isValidUrl =
    url.trim().startsWith("http://") || url.trim().startsWith("https://");
  const canSubmit = isValidUrl && termsAccepted && state !== "loading";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    setState("loading");
    setErrorMessage(null);

    try {
      const res = await fetch(`${API_BASE}/api/v1/source-submissions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          url: url.trim(),
          terms_accepted: true,
          submitted_by_user_id: userId,
          submitted_by_email: userEmail,
        }),
        cache: "no-store",
      });

      if (res.status === 409) {
        setState("duplicate");
        return;
      }

      if (!res.ok) {
        let detail = "Submission failed. Please try again.";
        try {
          const body = await res.json();
          if (body?.detail) detail = body.detail;
        } catch {
          // ignore parse error
        }
        setErrorMessage(detail);
        setState("error");
        return;
      }

      setState("success");
    } catch {
      setErrorMessage("Network error. Please check your connection and try again.");
      setState("error");
    }
  }

  function handleReset() {
    setUrl("");
    setTermsAccepted(false);
    setErrorMessage(null);
    setState("idle");
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Suggest a Source"
        subtitle="Submit a public fragrance creator, community, or blog for review."
      />

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-xl space-y-4 p-4">

          {/* ── Intro card ──────────────────────────────────────── */}
          <TerminalPanel>
            <div className="mb-1 flex items-center gap-2">
              <span className="h-px w-5 bg-amber-500/60" />
              <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-500/80">
                Community
              </span>
            </div>
            <h2 className="mt-2 text-base font-bold leading-snug text-zinc-100">
              Know a fragrance creator we should track?
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">
              Paste a public YouTube, TikTok, Instagram, Reddit, or fragrance
              blog link. We&apos;ll review it for possible inclusion in
              FragranceIndex.ai.
            </p>
          </TerminalPanel>

          {/* ── Success ─────────────────────────────────────────── */}
          {state === "success" && (
            <TerminalPanel>
              <p className="text-sm font-medium text-zinc-100">
                Submitted for review
              </p>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                Thank you — this source was submitted for review.
              </p>
              <button
                onClick={handleReset}
                className="mt-4 text-xs text-amber-500 hover:text-amber-400 transition-colors"
              >
                Suggest another source →
              </button>
            </TerminalPanel>
          )}

          {/* ── Duplicate ───────────────────────────────────────── */}
          {state === "duplicate" && (
            <TerminalPanel>
              <p className="text-sm font-medium text-zinc-100">
                Already in queue
              </p>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                This source has already been submitted and is in our review queue.
              </p>
              <button
                onClick={handleReset}
                className="mt-4 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                ← Try a different source
              </button>
            </TerminalPanel>
          )}

          {/* ── Form ────────────────────────────────────────────── */}
          {state !== "success" && state !== "duplicate" && (
            <TerminalPanel>
              <form onSubmit={handleSubmit} className="space-y-5" noValidate>

                {/* URL field */}
                <div>
                  <label
                    htmlFor="source-url"
                    className="mb-1.5 block text-xs font-medium text-zinc-400"
                  >
                    Source URL
                  </label>
                  <div className="relative">
                    <input
                      id="source-url"
                      type="url"
                      autoComplete="off"
                      value={url}
                      onChange={(e) => {
                        setUrl(e.target.value);
                        if (state === "error") setState("idle");
                      }}
                      placeholder="https://www.youtube.com/@channelname"
                      className={[
                        "w-full rounded border bg-zinc-900 px-4 py-2.5 text-sm text-zinc-100",
                        "placeholder:text-zinc-700 focus:outline-none focus:ring-1",
                        state === "error"
                          ? "border-red-800 focus:ring-red-700/40"
                          : "border-zinc-700 focus:border-amber-500 focus:ring-amber-500/30",
                        platformLabel ? "pr-24" : "",
                      ].join(" ")}
                    />
                    {platformLabel && (
                      <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-zinc-700 bg-zinc-800 px-1.5 py-px text-[10px] font-semibold text-zinc-400">
                        {platformLabel}
                      </span>
                    )}
                  </div>
                  {state === "error" && errorMessage && (
                    <p className="mt-1.5 text-xs text-red-400">{errorMessage}</p>
                  )}
                  <p className="mt-1.5 text-[11px] text-zinc-600">
                    YouTube, TikTok, Instagram, Reddit, or a fragrance blog.
                  </p>
                </div>

                {/* Terms checkbox */}
                <label className="flex cursor-pointer items-start gap-3">
                  <input
                    type="checkbox"
                    checked={termsAccepted}
                    onChange={(e) => setTermsAccepted(e.target.checked)}
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-amber-500"
                  />
                  <span className="text-xs leading-relaxed text-zinc-500">
                    I agree that FragranceIndex.ai may review and use publicly
                    available information from this source for fragrance trend
                    intelligence.
                  </span>
                </label>

                {/* Submitting-as */}
                {userEmail && (
                  <p className="text-[11px] text-zinc-700">
                    Submitting as{" "}
                    <span className="text-zinc-500">{userEmail}</span>
                  </p>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={!canSubmit}
                  className="w-full rounded bg-amber-500 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-amber-400 disabled:opacity-40 transition-colors"
                >
                  {state === "loading" ? "Submitting…" : "Submit source"}
                </button>

              </form>

              <p className="mt-5 border-t border-zinc-800/60 pt-4 text-[11px] leading-relaxed text-zinc-700">
                Submissions are reviewed manually. We do not guarantee
                inclusion. See our{" "}
                <a
                  href="/data-sources"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-zinc-600 hover:text-zinc-400 transition-colors"
                >
                  data sources policy
                  <ExternalLink size={9} className="mb-px" />
                </a>
                .
              </p>
            </TerminalPanel>
          )}

        </div>
      </div>
    </div>
  );
}
