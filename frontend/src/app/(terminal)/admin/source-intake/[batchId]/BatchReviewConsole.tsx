"use client";

/**
 * SOURCE-INTAKE-V1A — Batch Candidate Review Console (client component).
 *
 * Default filter: NEEDS_OPERATOR_REVIEW.
 * Actions per candidate: approve, reject (reason required), defer, mark-duplicate,
 *                        edit override URL + rerun.
 * Batch actions: Apply Approved (writes to youtube_channels), Production Verify.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle, XCircle, Clock, Copy, RefreshCw, ExternalLink } from "lucide-react";
import {
  fetchBatchCandidates,
  approveCandidate,
  rejectCandidate,
  deferCandidate,
  markDuplicate,
  updateCandidateOverride,
  rerunCandidate,
  applyBatch,
  productionVerifyBatch,
  STATUS_LABELS,
  STATUS_COLORS,
  TERMINAL_STATUSES,
  APPLY_ELIGIBLE,
  type CandidateRow,
  type CandidateStatus,
  type ApplyResult,
} from "@/lib/api/source_intake";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";

// ---------------------------------------------------------------------------
// Status filter tab
// ---------------------------------------------------------------------------

const STATUS_FILTERS = [
  { value: "NEEDS_OPERATOR_REVIEW", label: "Needs Review" },
  { value: "VERIFIED_ADD_READY", label: "Add Ready" },
  { value: "OPERATOR_APPROVED", label: "Approved" },
  { value: "APPLIED", label: "Applied" },
  { value: "PRODUCTION_VERIFIED", label: "Verified" },
  { value: "all", label: "All" },
];

// ---------------------------------------------------------------------------
// Reject modal
// ---------------------------------------------------------------------------

function RejectModal({
  candidate,
  onConfirm,
  onCancel,
}: {
  candidate: CandidateRow;
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
        <p className="mb-1 text-sm font-semibold text-zinc-200">Reject Candidate</p>
        <p className="mb-4 text-[11px] text-zinc-500">
          {candidate.candidate_name}
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
              placeholder="Not fragrance-related, inactive channel, wrong identity…"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none focus:border-zinc-500 resize-none"
            />
          </div>
          {error && <p className="text-[11px] text-red-400">{error}</p>}
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
// Override URL editor
// ---------------------------------------------------------------------------

function OverrideEditor({
  candidate,
  onRerun,
  onCancel,
}: {
  candidate: CandidateRow;
  onRerun: (updated: CandidateRow) => void;
  onCancel: () => void;
}) {
  const [url, setUrl] = useState(candidate.operator_override_url ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRerun(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await updateCandidateOverride(candidate.id, url.trim());
      const updated = await rerunCandidate(candidate.id);
      onRerun(updated as CandidateRow);
    } catch (err: unknown) {
      setError((err as Error).message ?? "Rerun failed");
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
        <p className="mb-1 text-sm font-semibold text-zinc-200">Fix URL & Rerun Verification</p>
        <p className="mb-4 text-[11px] text-zinc-500">{candidate.candidate_name}</p>
        <p className="mb-3 text-[11px] text-zinc-600">
          Original: <span className="text-zinc-500 break-all">{candidate.input_url}</span>
        </p>
        <form onSubmit={handleRerun} className="space-y-4">
          <div className="space-y-1.5">
            <label className="block text-[11px] font-medium text-zinc-400">
              Correct YouTube URL or @handle <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/@channelname  or  @channelname  or  UC..."
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-[12px] text-zinc-200 placeholder-zinc-700 outline-none focus:border-zinc-500"
            />
          </div>
          <p className="text-[10px] text-zinc-600">
            Uses ~101 YouTube API quota units. Handle-based resolution preferred.
          </p>
          {error && <p className="text-[11px] text-red-400">{error}</p>}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!url.trim() || submitting}
              className="inline-flex items-center gap-1.5 rounded border border-amber-800/60 bg-amber-950/30 px-3 py-1.5 text-[12px] font-medium text-amber-300 hover:bg-amber-950/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <RefreshCw size={11} className={submitting ? "animate-spin" : ""} />
              {submitting ? "Running…" : "Save & Rerun"}
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
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: CandidateStatus }) {
  const color = STATUS_COLORS[status] ?? "text-zinc-400";
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span className={`inline-flex items-center text-[10px] font-semibold ${color}`}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Candidate row
// ---------------------------------------------------------------------------

function CandidateCard({
  candidate,
  actionLoading,
  onApprove,
  onReject,
  onDefer,
  onMarkDuplicate,
  onEditRerun,
}: {
  candidate: CandidateRow;
  actionLoading: string | null;
  onApprove: (id: string) => void;
  onReject: (c: CandidateRow) => void;
  onDefer: (id: string) => void;
  onMarkDuplicate: (id: string) => void;
  onEditRerun: (c: CandidateRow) => void;
}) {
  const isTerminal = TERMINAL_STATUSES.has(candidate.status);
  const isReviewing = candidate.status === "NEEDS_OPERATOR_REVIEW" || candidate.status === "DEFERRED";
  const isLoading = actionLoading === candidate.id;
  const subsK = candidate.subscriber_count
    ? candidate.subscriber_count >= 1000
      ? `${(candidate.subscriber_count / 1000).toFixed(0)}K`
      : String(candidate.subscriber_count)
    : "—";

  // Parse recent titles sample
  let titlesSample: string[] = [];
  if (candidate.recent_titles_sample) {
    try {
      const parsed = JSON.parse(candidate.recent_titles_sample);
      if (Array.isArray(parsed)) titlesSample = parsed.slice(0, 2);
    } catch {
      titlesSample = [candidate.recent_titles_sample];
    }
  }

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 px-4 py-3 space-y-2">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-[13px] font-medium text-zinc-200">
              {candidate.resolved_title ?? candidate.candidate_name}
            </p>
            <StatusBadge status={candidate.status} />
          </div>
          {candidate.resolved_platform_id && (
            <p className="text-[11px] text-zinc-600">{candidate.resolved_platform_id}</p>
          )}
        </div>
        {candidate.resolved_platform_id && (
          <a
            href={`https://www.youtube.com/channel/${candidate.resolved_platform_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-zinc-600 hover:text-zinc-400 transition-colors"
          >
            <ExternalLink size={12} />
          </a>
        )}
      </div>

      {/* Metadata row */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
        <span>Subs: <span className="text-zinc-400">{subsK}</span></span>
        <span>Videos/30d: <span className="text-zinc-400">{candidate.recent_content_count ?? 0}</span></span>
        <span>Confidence: <span className="text-zinc-400">{candidate.confidence ?? "—"}</span></span>
        <span>Tier: <span className="text-zinc-400">{candidate.quality_tier ?? "—"}</span></span>
        <span>Method: <span className="text-zinc-400">{candidate.resolve_method ?? "—"}</span></span>
      </div>

      {/* Original URL */}
      <p className="text-[10px] text-zinc-600 break-all">
        Input: <span className="text-zinc-500">{candidate.input_url}</span>
      </p>

      {/* Reason */}
      {candidate.decision_reason && (
        <p className="text-[11px] text-zinc-500">
          Reason: <span className="text-zinc-400">{candidate.decision_reason}</span>
        </p>
      )}

      {/* Recent titles */}
      {titlesSample.length > 0 && (
        <div className="text-[10px] text-zinc-600">
          {titlesSample.map((t, i) => (
            <p key={i} className="truncate">· {t}</p>
          ))}
        </div>
      )}

      {/* Override URL if set */}
      {candidate.operator_override_url && (
        <p className="text-[10px] text-zinc-500">
          Override URL: <span className="text-amber-600 break-all">{candidate.operator_override_url}</span>
        </p>
      )}

      {/* Actions */}
      {!isTerminal && (
        <div className="flex flex-wrap gap-2 pt-1">
          {isReviewing && (
            <>
              <button
                onClick={() => onApprove(candidate.id)}
                disabled={isLoading}
                className="inline-flex items-center gap-1 rounded border border-green-800/40 bg-green-950/20 px-2.5 py-1 text-[11px] font-medium text-green-400 hover:bg-green-950/40 disabled:opacity-40 transition-colors"
              >
                <CheckCircle size={11} />
                Approve
              </button>
              <button
                onClick={() => onEditRerun(candidate)}
                disabled={isLoading}
                className="inline-flex items-center gap-1 rounded border border-amber-800/40 bg-amber-950/20 px-2.5 py-1 text-[11px] font-medium text-amber-400 hover:bg-amber-950/40 disabled:opacity-40 transition-colors"
              >
                <RefreshCw size={11} />
                Fix URL & Rerun
              </button>
              <button
                onClick={() => onMarkDuplicate(candidate.id)}
                disabled={isLoading}
                className="inline-flex items-center gap-1 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 hover:text-zinc-300 disabled:opacity-40 transition-colors"
              >
                Mark Duplicate
              </button>
              <button
                onClick={() => onDefer(candidate.id)}
                disabled={isLoading}
                className="inline-flex items-center gap-1 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 hover:text-zinc-300 disabled:opacity-40 transition-colors"
              >
                Defer
              </button>
            </>
          )}
          <button
            onClick={() => onReject(candidate)}
            disabled={isLoading}
            className="inline-flex items-center gap-1 rounded border border-red-900/40 px-2.5 py-1 text-[11px] text-red-500 hover:text-red-400 disabled:opacity-40 transition-colors"
          >
            <XCircle size={11} />
            Reject
          </button>
        </div>
      )}

      {/* Reviewed by */}
      {candidate.reviewed_by && (
        <p className="text-[10px] text-zinc-700">
          Reviewed by {candidate.reviewed_by}
          {candidate.reviewed_at ? ` · ${new Date(candidate.reviewed_at).toLocaleDateString()}` : ""}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Apply result panel
// ---------------------------------------------------------------------------

function ApplyResultPanel({
  result,
  onDismiss,
}: {
  result: ApplyResult;
  onDismiss: () => void;
}) {
  return (
    <div className="rounded border border-green-800/40 bg-green-950/10 px-4 py-3 space-y-1">
      <div className="flex items-center justify-between">
        <p className="text-[13px] font-semibold text-green-400">Apply Complete</p>
        <button onClick={onDismiss} className="text-[11px] text-zinc-500 hover:text-zinc-300">Dismiss</button>
      </div>
      <p className="text-[12px] text-zinc-300">
        Inserted: <span className="text-green-400">{result.applied}</span> ·
        Already existed: <span className="text-zinc-400">{result.skipped}</span> ·
        Failed: <span className="text-red-400">{result.failed}</span>
      </p>
      {result.details.filter(d => d.result === "inserted").map((d, i) => (
        <p key={i} className="text-[11px] text-zinc-500">
          ✓ {d.name} ({d.channel_id})
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main console
// ---------------------------------------------------------------------------

export function BatchReviewConsole({
  batchId,
  adminEmail,
}: {
  batchId: string;
  adminEmail: string;
}) {
  const [candidates, setCandidates] = useState<CandidateRow[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("NEEDS_OPERATOR_REVIEW");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<CandidateRow | null>(null);
  const [rerunTarget, setRerunTarget] = useState<CandidateRow | null>(null);
  const [applyResult, setApplyResult] = useState<ApplyResult | null>(null);
  const [applyLoading, setApplyLoading] = useState(false);
  const [verifyLoading, setVerifyLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBatchCandidates(batchId, statusFilter);
      setCandidates(data.candidates);
      setTotal(data.total);
    } catch (err: unknown) {
      setError((err as Error).message ?? "Failed to load candidates");
    } finally {
      setLoading(false);
    }
  }, [batchId, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  // ---------------------------------------------------------------------------
  // Row-level actions
  // ---------------------------------------------------------------------------

  function mutateCandidate(id: string, updates: Partial<CandidateRow>) {
    setCandidates((prev) =>
      prev.map((c) => (c.id === id ? { ...c, ...updates } : c)),
    );
  }

  async function handleApprove(id: string) {
    setActionLoading(id);
    try {
      await approveCandidate(id);
      mutateCandidate(id, { status: "OPERATOR_APPROVED" });
    } catch (err: unknown) {
      setError((err as Error).message ?? "Approve failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleRejectConfirm(reason: string) {
    if (!rejectTarget) return;
    const id = rejectTarget.id;
    setRejectTarget(null);
    setActionLoading(id);
    try {
      await rejectCandidate(id, reason);
      mutateCandidate(id, { status: "OPERATOR_REJECTED", decision_reason: reason });
    } catch (err: unknown) {
      setError((err as Error).message ?? "Reject failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleDefer(id: string) {
    setActionLoading(id);
    try {
      await deferCandidate(id);
      mutateCandidate(id, { status: "DEFERRED" });
    } catch (err: unknown) {
      setError((err as Error).message ?? "Defer failed");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleMarkDuplicate(id: string) {
    setActionLoading(id);
    try {
      await markDuplicate(id);
      mutateCandidate(id, { status: "SKIP_DUPLICATE" });
    } catch (err: unknown) {
      setError((err as Error).message ?? "Mark duplicate failed");
    } finally {
      setActionLoading(null);
    }
  }

  function handleRerunComplete(updated: CandidateRow) {
    setRerunTarget(null);
    mutateCandidate(updated.id, updated);
  }

  // ---------------------------------------------------------------------------
  // Batch actions
  // ---------------------------------------------------------------------------

  async function handleApply() {
    setApplyLoading(true);
    setError(null);
    try {
      const result = await applyBatch(batchId);
      setApplyResult(result);
      await load(); // refresh candidates
    } catch (err: unknown) {
      setError((err as Error).message ?? "Apply failed");
    } finally {
      setApplyLoading(false);
    }
  }

  async function handleProductionVerify() {
    setVerifyLoading(true);
    setError(null);
    try {
      await productionVerifyBatch(batchId);
      await load();
    } catch (err: unknown) {
      setError((err as Error).message ?? "Production verify failed");
    } finally {
      setVerifyLoading(false);
    }
  }

  const applyEligibleCount = candidates.filter((c) => APPLY_ELIGIBLE.has(c.status)).length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {rejectTarget && (
        <RejectModal
          candidate={rejectTarget}
          onConfirm={handleRejectConfirm}
          onCancel={() => setRejectTarget(null)}
        />
      )}
      {rerunTarget && (
        <OverrideEditor
          candidate={rerunTarget}
          onRerun={handleRerunComplete}
          onCancel={() => setRerunTarget(null)}
        />
      )}

      <Header
        title="Source Intake — Candidates"
        subtitle={`Batch: ${batchId.slice(0, 8)}… · ${adminEmail}`}
        actions={
          <div className="flex items-center gap-2">
            <Link
              href="/admin/source-intake"
              className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-3 py-1.5 text-[12px] text-zinc-400 hover:text-zinc-200 transition-colors"
            >
              <ArrowLeft size={12} />
              All Batches
            </Link>
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-3 py-1.5 text-[12px] text-zinc-400 hover:text-zinc-200 transition-colors disabled:opacity-40"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-6 pb-12">
        {/* Error */}
        {error && (
          <div className="rounded border border-red-800/40 bg-red-950/20 px-3 py-2 text-[12px] text-red-400">
            {error}
          </div>
        )}

        {/* Apply result */}
        {applyResult && (
          <ApplyResultPanel result={applyResult} onDismiss={() => setApplyResult(null)} />
        )}

        {/* Status filter */}
        <TerminalPanel>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                className={`rounded border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  statusFilter === f.value
                    ? "border-amber-700 bg-amber-950/30 text-amber-400"
                    : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {f.label}
              </button>
            ))}
            <span className="ml-auto text-[11px] text-zinc-600">
              {total} candidate{total !== 1 ? "s" : ""}
            </span>
          </div>

          {/* Batch action bar */}
          <div className="mb-4 flex flex-wrap gap-2">
            <button
              onClick={handleApply}
              disabled={applyLoading || applyEligibleCount === 0}
              className="inline-flex items-center gap-1.5 rounded border border-green-800/40 bg-green-950/20 px-3 py-1.5 text-[12px] font-medium text-green-400 hover:bg-green-950/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {applyLoading ? <RefreshCw size={11} className="animate-spin" /> : <CheckCircle size={11} />}
              Apply Approved
              {applyEligibleCount > 0 && (
                <span className="ml-1 rounded bg-green-900/40 px-1 text-[10px]">{applyEligibleCount}</span>
              )}
            </button>
            <button
              onClick={handleProductionVerify}
              disabled={verifyLoading}
              className="inline-flex items-center gap-1.5 rounded border border-blue-800/40 bg-blue-950/20 px-3 py-1.5 text-[12px] font-medium text-blue-400 hover:bg-blue-950/40 disabled:opacity-40 transition-colors"
            >
              {verifyLoading ? <RefreshCw size={11} className="animate-spin" /> : <Copy size={11} />}
              Production Verify
            </button>
          </div>

          {/* Candidate list */}
          {loading && candidates.length === 0 ? (
            <p className="py-8 text-center text-[12px] text-zinc-600">Loading…</p>
          ) : candidates.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-[12px] text-zinc-500">
                No candidates with status &ldquo;{statusFilter}&rdquo;.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {candidates.map((c) => (
                <CandidateCard
                  key={c.id}
                  candidate={c}
                  actionLoading={actionLoading}
                  onApprove={handleApprove}
                  onReject={setRejectTarget}
                  onDefer={handleDefer}
                  onMarkDuplicate={handleMarkDuplicate}
                  onEditRerun={setRerunTarget}
                />
              ))}
            </div>
          )}
        </TerminalPanel>

        <p className="text-center text-[11px] text-zinc-700">
          Spot incorrect data? support@fragranceindex.ai
        </p>
      </div>
      </div>
    </div>
  );
}
