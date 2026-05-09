"use client";

/**
 * C2.1 — Admin Creator Claims Console (client component).
 *
 * Rendered only after the server component confirms admin identity.
 * Makes requests to /api/admin/creator-claims (Next.js server routes),
 * never to FastAPI directly.
 *
 * Actions: filter by status, approve, reject (reason required).
 * No bulk actions in C2.1.
 */

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import {
  adminListClaims,
  adminApproveClaim,
  adminRejectClaim,
  type AdminClaimEntry,
  type ClaimStatusFilter,
} from "@/lib/api/admin_creator_claims";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";

// ---------------------------------------------------------------------------
// Reject modal
// ---------------------------------------------------------------------------

function RejectModal({
  claim,
  onConfirm,
  onCancel,
}: {
  claim: AdminClaimEntry;
  onConfirm: (reason: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
    } catch (err: unknown) {
      setError((err as Error).message ?? "Reject failed");
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-sm rounded border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
        <p className="mb-1 text-sm font-semibold text-zinc-200">Reject Claim</p>
        <p className="mb-4 text-[11px] text-zinc-500">
          Creator:{" "}
          <span className="text-zinc-400">
            {claim.creator_display_name ?? claim.creator_id}
          </span>
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="block text-[11px] font-medium text-zinc-400">
              Rejection reason <span className="text-red-400">*</span>
            </label>
            <textarea
              rows={3}
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why this claim is rejected..."
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none focus:border-zinc-500 resize-none"
            />
          </div>
          {error && (
            <p className="text-[11px] text-red-400">{error}</p>
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!reason.trim() || submitting}
              className="inline-flex items-center rounded border border-red-800/60 bg-red-950/30 px-3 py-1.5 text-[12px] font-medium text-red-300 hover:bg-red-950/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? "Rejecting…" : "Confirm Reject"}
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="inline-flex items-center rounded border border-zinc-700 px-3 py-1.5 text-[12px] text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Claim row
// ---------------------------------------------------------------------------

function ClaimRow({
  claim,
  onApprove,
  onReject,
  actionLoading,
}: {
  claim: AdminClaimEntry;
  onApprove: (id: string) => void;
  onReject: (claim: AdminClaimEntry) => void;
  actionLoading: string | null;
}) {
  const isPending = claim.claim_status === "pending";
  const isLoading = actionLoading === claim.claim_id;

  const methodLabel =
    claim.claim_method === "bio_code"
      ? "Bio-code"
      : claim.claim_method === "screenshot"
      ? "Screenshot"
      : "Manual";

  const statusColor =
    claim.claim_status === "verified"
      ? "text-emerald-400"
      : claim.claim_status === "rejected"
      ? "text-red-400"
      : claim.claim_status === "revoked"
      ? "text-zinc-600"
      : "text-amber-400";

  return (
    <tr className="border-b border-zinc-800/60 hover:bg-zinc-900/40">
      {/* Creator */}
      <td className="px-3 py-3 align-top">
        <div className="space-y-0.5">
          <div className="flex items-center gap-1.5">
            <span className="rounded border border-zinc-700 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-600">
              {claim.platform}
            </span>
            {claim.creator_profile_url ? (
              <a
                href={claim.creator_profile_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 text-[12px] font-medium text-zinc-200 hover:text-amber-300 transition-colors"
              >
                {claim.creator_display_name ?? claim.creator_id}
                <ExternalLink size={9} className="text-zinc-600" />
              </a>
            ) : (
              <span className="text-[12px] font-medium text-zinc-300">
                {claim.creator_display_name ?? claim.creator_id}
              </span>
            )}
          </div>
          <p className="text-[10px] text-zinc-700 font-mono">{claim.creator_id}</p>
        </div>
      </td>

      {/* Method */}
      <td className="px-3 py-3 align-top text-[11px] text-zinc-400 whitespace-nowrap">
        {methodLabel}
      </td>

      {/* Status */}
      <td className={`px-3 py-3 align-top text-[11px] font-medium whitespace-nowrap ${statusColor}`}>
        {claim.claim_status}
      </td>

      {/* Evidence */}
      <td className="px-3 py-3 align-top">
        {claim.evidence_url ? (
          <a
            href={claim.evidence_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-[11px] text-blue-400 hover:underline max-w-[200px] truncate"
          >
            {claim.evidence_url}
            <ExternalLink size={9} className="shrink-0" />
          </a>
        ) : (
          <span className="text-[11px] text-zinc-700">—</span>
        )}
        {claim.reviewer_notes && (
          <p className="mt-0.5 text-[10px] text-zinc-600 italic">
            Note: {claim.reviewer_notes}
          </p>
        )}
      </td>

      {/* Submitted */}
      <td className="px-3 py-3 align-top text-[11px] text-zinc-500 whitespace-nowrap">
        {claim.claimed_at ? claim.claimed_at.slice(0, 10) : "—"}
      </td>

      {/* Reviewer info */}
      <td className="px-3 py-3 align-top text-[10px] text-zinc-600">
        {claim.reviewed_by && (
          <div>
            <span className="block">{claim.reviewed_by}</span>
            {claim.reviewed_at && (
              <span className="text-zinc-700">{claim.reviewed_at.slice(0, 10)}</span>
            )}
          </div>
        )}
        {claim.rejection_reason && (
          <p className="mt-0.5 text-red-800 italic">{claim.rejection_reason}</p>
        )}
      </td>

      {/* Actions */}
      <td className="px-3 py-3 align-top">
        {isPending && (
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => onApprove(claim.claim_id)}
              disabled={isLoading}
              title="Approve"
              className="inline-flex items-center gap-1 rounded border border-emerald-800/60 bg-emerald-950/30 px-2 py-1 text-[10px] font-medium text-emerald-400 hover:bg-emerald-950/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <CheckCircle size={11} />
              Approve
            </button>
            <button
              onClick={() => onReject(claim)}
              disabled={isLoading}
              title="Reject"
              className="inline-flex items-center gap-1 rounded border border-red-800/60 bg-red-950/20 px-2 py-1 text-[10px] font-medium text-red-400 hover:bg-red-950/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <XCircle size={11} />
              Reject
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------

const STATUS_TABS: { label: string; value: ClaimStatusFilter }[] = [
  { label: "Pending", value: "pending" },
  { label: "Verified", value: "verified" },
  { label: "Rejected", value: "rejected" },
  { label: "All", value: "all" },
];

export function ClaimsConsole({ adminEmail }: { adminEmail: string }) {
  const [statusFilter, setStatusFilter] = useState<ClaimStatusFilter>("pending");
  const [claims, setClaims] = useState<AdminClaimEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const [rejectTarget, setRejectTarget] = useState<AdminClaimEntry | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setActionMsg(null);
    try {
      const data = await adminListClaims(statusFilter);
      setClaims(data.claims);
      setTotal(data.total);
    } catch (err: unknown) {
      setError((err as Error).message ?? "Failed to load claims");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleApprove(claimId: string) {
    setActionLoading(claimId);
    setActionMsg(null);
    try {
      await adminApproveClaim(claimId);
      setActionMsg(`Claim ${claimId.slice(0, 8)}… approved.`);
      await load();
    } catch (err: unknown) {
      setActionMsg(`Error: ${(err as Error).message}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function handleRejectConfirm(reason: string) {
    if (!rejectTarget) return;
    const claimId = rejectTarget.claim_id;
    setActionLoading(claimId);
    setRejectTarget(null);
    setActionMsg(null);
    try {
      await adminRejectClaim(claimId, reason);
      setActionMsg(`Claim ${claimId.slice(0, 8)}… rejected.`);
      await load();
    } catch (err: unknown) {
      setActionMsg(`Error: ${(err as Error).message}`);
    } finally {
      setActionLoading(null);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Creator Claims — Operator Console"
        subtitle={`Logged in as ${adminEmail}`}
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
        <div className="mx-auto max-w-5xl space-y-4">

          {/* Status tabs */}
          <div className="flex border-b border-zinc-800">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.value}
                onClick={() => setStatusFilter(tab.value)}
                className={`px-4 py-2 text-[11px] font-medium transition-colors ${
                  statusFilter === tab.value
                    ? "border-b-2 border-amber-500 text-amber-300"
                    : "text-zinc-600 hover:text-zinc-400"
                }`}
              >
                {tab.label}
              </button>
            ))}
            <div className="ml-auto flex items-center pr-1 text-[10px] text-zinc-700">
              {!loading && `${total} total`}
            </div>
          </div>

          {/* Action message */}
          {actionMsg && (
            <p className="rounded border border-zinc-700 bg-zinc-900/40 px-3 py-2 text-[11px] text-zinc-400">
              {actionMsg}
            </p>
          )}

          {/* Error */}
          {error && (
            <p className="rounded border border-red-900/50 bg-red-950/20 px-3 py-2 text-[11px] text-red-400">
              {error}
            </p>
          )}

          {/* Table */}
          <TerminalPanel noPad>
            {loading ? (
              <div className="px-4 py-8 text-center text-[12px] text-zinc-600">
                Loading…
              </div>
            ) : claims.length === 0 ? (
              <div className="px-4 py-8 text-center text-[12px] text-zinc-600">
                No {statusFilter === "all" ? "" : statusFilter} claims.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-zinc-800">
                      {["Creator", "Method", "Status", "Evidence", "Submitted", "Reviewer", "Actions"].map(
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
                      <ClaimRow
                        key={c.claim_id}
                        claim={c}
                        onApprove={handleApprove}
                        onReject={setRejectTarget}
                        actionLoading={actionLoading}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </TerminalPanel>

          {/* Compliance note */}
          <p className="text-[10px] text-zinc-700">
            C2.1 operator console. Access gated by ADMIN_EMAILS / ADMIN_USER_IDS environment
            allowlist (temporary — future hardening: app_admins table or Supabase custom claims).
            No OAuth. No pipeline changes. No private data accessed.
          </p>
        </div>
      </div>

      {/* Reject modal */}
      {rejectTarget && (
        <RejectModal
          claim={rejectTarget}
          onConfirm={handleRejectConfirm}
          onCancel={() => setRejectTarget(null)}
        />
      )}
    </div>
  );
}
