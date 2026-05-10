"use client";

/**
 * C2.2 — Account Console (client component).
 *
 * Fetches this user's creator claims from /api/creator-claims (Next.js
 * server route → FastAPI GET /api/v1/creator-claims/me).
 * No N+1 fetches: creator_id used as fallback display name.
 * verification_code_hash is never returned by the /me endpoint.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink, RefreshCw, BadgeCheck } from "lucide-react";
import { fetchMyClaims, type ClaimSummary } from "@/lib/api/creator_claims";
import { Header } from "@/components/shell/Header";
import { TerminalPanel, PanelDivider } from "@/components/primitives/TerminalPanel";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: ClaimSummary["claim_status"] }) {
  if (status === "verified") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-emerald-800/60 bg-emerald-950/20 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
        <BadgeCheck size={9} />
        Verified
      </span>
    );
  }
  if (status === "pending") {
    return (
      <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-900/40 px-1.5 py-0.5 text-[10px] font-medium text-zinc-400">
        Pending review
      </span>
    );
  }
  if (status === "rejected") {
    return (
      <span className="inline-flex items-center rounded border border-red-900/50 bg-red-950/10 px-1.5 py-0.5 text-[10px] font-medium text-red-400">
        Not approved
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded border border-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-600">
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Claim row
// ---------------------------------------------------------------------------

function ClaimRow({ claim }: { claim: ClaimSummary }) {
  const methodLabel =
    claim.claim_method === "bio_code"
      ? "Bio-code"
      : claim.claim_method === "screenshot"
      ? "Screenshot"
      : "Manual review";

  return (
    <tr className="border-b border-zinc-800/60 hover:bg-zinc-900/30">
      {/* Creator */}
      <td className="px-3 py-3 align-top">
        <div className="space-y-0.5">
          <div className="flex items-center gap-1.5">
            <span className="rounded border border-zinc-800 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-zinc-700">
              {claim.platform}
            </span>
            <span className="text-[12px] font-medium text-zinc-300">
              {claim.creator_id}
            </span>
          </div>
        </div>
      </td>

      {/* Method */}
      <td className="px-3 py-3 align-top text-[11px] text-zinc-500 whitespace-nowrap">
        {methodLabel}
      </td>

      {/* Status */}
      <td className="px-3 py-3 align-top whitespace-nowrap">
        <StatusBadge status={claim.claim_status} />
        {claim.claim_status === "rejected" && claim.rejection_reason && (
          <p className="mt-1.5 max-w-[220px] text-[10px] text-zinc-600 leading-relaxed">
            {claim.rejection_reason}
          </p>
        )}
      </td>

      {/* Evidence */}
      <td className="px-3 py-3 align-top">
        {claim.evidence_url ? (
          <a
            href={claim.evidence_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-[11px] text-blue-400 hover:underline max-w-[180px] truncate"
          >
            {claim.evidence_url}
            <ExternalLink size={9} className="shrink-0" />
          </a>
        ) : (
          <span className="text-[11px] text-zinc-700">—</span>
        )}
      </td>

      {/* Submitted */}
      <td className="px-3 py-3 align-top text-[11px] text-zinc-600 whitespace-nowrap">
        {claim.claimed_at ? claim.claimed_at.slice(0, 10) : "—"}
      </td>

      {/* Actions */}
      <td className="px-3 py-3 align-top">
        <div className="flex flex-col gap-1.5">
          <Link
            href={`/creators/${encodeURIComponent(claim.creator_id)}`}
            className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors whitespace-nowrap"
          >
            View profile →
          </Link>
          {claim.claim_status === "rejected" && (
            <Link
              href={`/creator/claim/${encodeURIComponent(claim.creator_id)}`}
              className="text-[10px] text-amber-500 hover:text-amber-300 transition-colors whitespace-nowrap"
            >
              Try again →
            </Link>
          )}
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="px-4 py-10 text-center space-y-4">
      <p className="text-[12px] text-zinc-500">No creator claims submitted yet.</p>
      <p className="text-[11px] text-zinc-600 max-w-xs mx-auto leading-relaxed">
        Find your creator profile in the Creators directory and click{" "}
        <span className="text-zinc-400">Claim this Profile</span> to start
        the verification process.
      </p>
      <Link
        href="/creators"
        className="inline-flex items-center rounded border border-zinc-700/60 bg-zinc-800/40 px-3 py-1.5 text-[12px] text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 transition-colors"
      >
        Browse Creators
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------

export function AccountConsole({ userEmail }: { userEmail: string }) {
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMyClaims();
      setClaims(data.claims);
    } catch {
      setError("Could not load your claims. Please refresh.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Account"
        actions={
          <button
            onClick={load}
            className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <RefreshCw size={11} />
            Refresh
          </button>
        }
      />

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-4xl space-y-5">

          {/* Account info */}
          <TerminalPanel>
            <div className="px-5 py-4 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                Signed in as
              </p>
              <p className="text-[13px] text-zinc-200">{userEmail}</p>
            </div>
            <PanelDivider />
            <div className="px-5 py-3 text-[11px] text-zinc-600 leading-relaxed">
              Creator claims verify that you control a public creator profile.
              No OAuth, password, or private account access is required.
            </div>
          </TerminalPanel>

          {/* Claims */}
          <div className="space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600 px-1">
              My Creator Claims
            </p>

            <TerminalPanel noPad>
              {loading ? (
                <div className="px-4 py-8 text-center text-[12px] text-zinc-600">
                  Loading…
                </div>
              ) : error ? (
                <div className="px-4 py-8 text-center text-[12px] text-red-400">
                  {error}
                </div>
              ) : claims.length === 0 ? (
                <EmptyState />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-zinc-800">
                        {["Creator", "Method", "Status", "Evidence", "Submitted", "Actions"].map(
                          (h) => (
                            <th
                              key={h}
                              className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-600"
                            >
                              {h}
                            </th>
                          )
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {claims.map((c) => (
                        <ClaimRow key={c.claim_id} claim={c} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </TerminalPanel>
          </div>

          {/* Browse CTA (shown even when claims exist) */}
          {!loading && !error && (
            <p className="text-[11px] text-zinc-600 px-1">
              Want to claim another profile?{" "}
              <Link href="/creators" className="text-zinc-400 hover:text-zinc-200 transition-colors">
                Browse Creators →
              </Link>
            </p>
          )}

        </div>
      </div>
    </div>
  );
}
