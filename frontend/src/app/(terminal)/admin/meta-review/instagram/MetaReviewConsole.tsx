"use client";

/**
 * IG1-R — Meta App Review Demo Console (client component).
 *
 * This component provides the reviewer/screencast demo flow for the
 * Meta App Review submission for Instagram Public Content Access.
 *
 * Security: credentials are never returned to the browser. The component
 * calls /api/admin/instagram-review (Next.js server proxy) which injects
 * X-Pti-Admin-User and forwards to the FastAPI backend. The FastAPI route
 * reads INSTAGRAM_ACCESS_TOKEN from env server-side only.
 */

import { useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IGStatus {
  configured: boolean;
  ig_business_account_id?: string;
  username?: string;
  error?: string;
}

interface IGMediaItem {
  id: string;
  media_type?: string;
  timestamp?: string;
  permalink?: string;
  caption_preview?: string;
  like_count?: number;
}

interface IGDemoResult {
  hashtag: string;
  hashtag_id: string;
  items: IGMediaItem[];
  total_returned: number;
  note: string;
}

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function StatusCard({ status }: { status: IGStatus | null; }) {
  if (!status) return null;

  if (!status.configured) {
    return (
      <div className="rounded border border-amber-700/40 bg-amber-950/20 p-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-400 mb-1">
          Credentials Not Configured
        </p>
        <p className="text-xs text-zinc-400">{status.error}</p>
        <p className="mt-2 text-[11px] text-zinc-600">
          Set <code className="text-amber-400">INSTAGRAM_ACCESS_TOKEN</code> and{" "}
          <code className="text-amber-400">INSTAGRAM_BUSINESS_ACCOUNT_ID</code>{" "}
          in Railway env, then retry.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded border border-emerald-700/40 bg-emerald-950/20 p-4">
      <p className="text-xs font-semibold uppercase tracking-widest text-emerald-400 mb-2">
        Instagram Business Account Connected
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {status.username && (
          <>
            <dt className="text-zinc-500">Username</dt>
            <dd className="text-zinc-200 font-mono">@{status.username}</dd>
          </>
        )}
        <dt className="text-zinc-500">IG Business Account ID</dt>
        <dd className="text-zinc-200 font-mono">{status.ig_business_account_id}</dd>
      </dl>
    </div>
  );
}

function MediaCard({ item }: { item: IGMediaItem }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/60 p-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
          {item.media_type ?? "POST"}
        </span>
        <span className="text-[10px] text-zinc-600">
          {item.timestamp ? new Date(item.timestamp).toLocaleDateString() : ""}
        </span>
      </div>
      {item.caption_preview && (
        <p className="text-xs text-zinc-300 mb-2 leading-relaxed">
          {item.caption_preview}
          {item.caption_preview.length >= 200 && (
            <span className="text-zinc-600"> …</span>
          )}
        </p>
      )}
      <div className="flex items-center justify-between">
        {item.permalink && (
          <a
            href={item.permalink}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] text-amber-400/70 hover:text-amber-400 transition-colors"
          >
            View on Instagram ↗
          </a>
        )}
        {item.like_count !== undefined && item.like_count !== null && (
          <span className="text-[11px] text-zinc-500">
            {item.like_count.toLocaleString()} likes
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main console
// ---------------------------------------------------------------------------

const DEMO_HASHTAGS = [
  "perfume",
  "fragrance",
  "nicheperfume",
  "fragrancecommunity",
  "perfumereview",
  "scentsoftheday",
] as const;

type DemoHashtag = typeof DEMO_HASHTAGS[number];

export function MetaReviewConsole() {
  const [status, setStatus] = useState<IGStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [selectedHashtag, setSelectedHashtag] = useState<DemoHashtag>("perfume");
  const [demoResult, setDemoResult] = useState<IGDemoResult | null>(null);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);

  async function checkStatus() {
    setLoadingStatus(true);
    setStatus(null);
    try {
      const resp = await fetch("/api/admin/instagram-review?action=status");
      const data = await resp.json();
      setStatus(data);
    } catch {
      setStatus({ configured: false, error: "Could not reach backend." });
    } finally {
      setLoadingStatus(false);
    }
  }

  async function runDemo() {
    setLoadingDemo(true);
    setDemoResult(null);
    setDemoError(null);
    try {
      const resp = await fetch(
        `/api/admin/instagram-review?action=demo&hashtag=${encodeURIComponent(selectedHashtag)}`
      );
      const data = await resp.json();
      if (!resp.ok) {
        setDemoError(data.detail ?? `Error ${resp.status}`);
      } else {
        setDemoResult(data);
      }
    } catch {
      setDemoError("Network error. Check backend connection.");
    } finally {
      setLoadingDemo(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10 space-y-8">
      {/* Header */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-amber-400 mb-1">
          Admin · Meta App Review
        </p>
        <h1 className="text-xl font-bold text-zinc-100">
          Instagram Public Content — App Review Demo
        </h1>
        <p className="mt-2 text-sm text-zinc-400 leading-relaxed max-w-xl">
          This screen demonstrates how FragranceIndex.ai uses Instagram Public Content Access.
          It is intended for Meta App Review screencast recording and operator verification.
        </p>
      </div>

      {/* Reviewer explanation */}
      <section className="rounded border border-zinc-800 bg-zinc-900/50 p-5 space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
          How FragranceIndex.ai Uses This Permission
        </h2>
        <ul className="text-xs text-zinc-400 space-y-1.5 leading-relaxed list-none">
          <li>
            <span className="text-zinc-300 font-medium">Purpose:</span>{" "}
            FragranceIndex.ai is a fragrance market intelligence platform. We analyze
            aggregated trend signals from public social media content to help brands,
            marketers, and researchers understand which fragrances are gaining momentum.
          </li>
          <li>
            <span className="text-zinc-300 font-medium">What we retrieve:</span>{" "}
            Public Instagram posts associated with fragrance-related hashtags (e.g.,{" "}
            <code className="text-amber-400">#perfume</code>,{" "}
            <code className="text-amber-400">#fragrance</code>). We retrieve post
            caption text, timestamp, permalink, media type, and publicly visible
            engagement signals.
          </li>
          <li>
            <span className="text-zinc-300 font-medium">What we do not do:</span>{" "}
            We do not collect private data, build public profiles of individual users,
            resell raw content datasets, or expose raw post text on public pages.
            All data is processed internally into aggregated trend intelligence.
          </li>
          <li>
            <span className="text-zinc-300 font-medium">Output:</span>{" "}
            Fragrance trend scores, momentum indicators, and market signals — surfaced
            in the authenticated terminal for industry professionals.
          </li>
        </ul>
      </section>

      {/* Step 1: Connection status */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
            Step 1 · Instagram Business Account Connection
          </h2>
          <button
            onClick={checkStatus}
            disabled={loadingStatus}
            className="rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-500 hover:text-zinc-100 transition-colors disabled:opacity-50"
          >
            {loadingStatus ? "Checking…" : "Check Connection"}
          </button>
        </div>
        <StatusCard status={status} />
        {!status && (
          <p className="text-[11px] text-zinc-600">
            Click "Check Connection" to verify that the Instagram Business Account
            credentials are configured and reachable.
          </p>
        )}
      </section>

      {/* Step 2: Hashtag demo */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
          Step 2 · Live Hashtag Search Demo
        </h2>
        <p className="text-[11px] text-zinc-500">
          Select a fragrance hashtag and run a live query against the Instagram
          Graph API. This demonstrates the exact API usage under review:
          hashtag search → recent media retrieval → field extraction.
        </p>

        <div className="flex items-center gap-3">
          <select
            value={selectedHashtag}
            onChange={(e) => setSelectedHashtag(e.target.value as DemoHashtag)}
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-200 focus:border-amber-500 focus:outline-none"
          >
            {DEMO_HASHTAGS.map((tag) => (
              <option key={tag} value={tag}>
                #{tag}
              </option>
            ))}
          </select>
          <button
            onClick={runDemo}
            disabled={loadingDemo || status?.configured === false}
            className="rounded border border-amber-500/60 px-4 py-1.5 text-xs text-amber-400 hover:border-amber-400 hover:text-amber-300 transition-colors disabled:opacity-40"
          >
            {loadingDemo ? "Querying Instagram…" : "Run Hashtag Demo"}
          </button>
        </div>

        {demoError && (
          <div className="rounded border border-rose-800/40 bg-rose-950/20 p-3">
            <p className="text-xs text-rose-400">{demoError}</p>
          </div>
        )}
      </section>

      {/* Demo results */}
      {demoResult && (
        <section className="space-y-4">
          <div className="rounded border border-zinc-800 bg-zinc-900/30 p-3">
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs font-semibold text-zinc-300">
                #{demoResult.hashtag}
              </p>
              <span className="text-[10px] text-zinc-600 font-mono">
                ID: {demoResult.hashtag_id}
              </span>
            </div>
            <p className="text-[11px] text-zinc-500">
              {demoResult.total_returned} public posts returned from Instagram recent_media endpoint
            </p>
          </div>

          <div className="space-y-2">
            {demoResult.items.map((item) => (
              <MediaCard key={item.id} item={item} />
            ))}
          </div>

          <div className="rounded border border-zinc-800/60 bg-zinc-950 p-3">
            <p className="text-[11px] text-zinc-500 italic">{demoResult.note}</p>
          </div>
        </section>
      )}

      {/* API summary for reviewer */}
      <section className="rounded border border-zinc-800 bg-zinc-900/50 p-5 space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
          API Endpoints Used
        </h2>
        <dl className="space-y-2 text-xs">
          <div>
            <dt className="text-zinc-400 font-medium">1. Hashtag ID Resolution</dt>
            <dd className="text-zinc-600 font-mono mt-0.5">
              GET /v21.0/ig_hashtag_search?user_id=&#123;id&#125;&q=&#123;hashtag&#125;&fields=id
            </dd>
          </div>
          <div>
            <dt className="text-zinc-400 font-medium">2. Recent Public Media</dt>
            <dd className="text-zinc-600 font-mono mt-0.5">
              GET /v21.0/&#123;hashtag_id&#125;/recent_media?user_id=&#123;id&#125;&fields=id,caption,timestamp,permalink,media_type,like_count
            </dd>
          </div>
        </dl>
        <p className="text-[11px] text-zinc-600">
          Access token is stored in Railway environment variables and is never
          transmitted to the browser or displayed in any UI.
        </p>
      </section>

      <div className="border-t border-zinc-800 pt-4">
        <p className="text-[10px] text-zinc-700">
          FragranceIndex.ai · Admin · Meta App Review Demo · IG1 Phase ·{" "}
          Access restricted to platform operators.
        </p>
      </div>
    </div>
  );
}
