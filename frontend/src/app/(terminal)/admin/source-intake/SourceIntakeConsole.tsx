"use client";

/**
 * SOURCE-INTAKE-V1A — Admin Source Intake Batch List Console (client component).
 *
 * Shows all intake batches. Each batch links to /admin/source-intake/{batchId}
 * for candidate-level review.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { fetchBatches, type BatchSummary } from "@/lib/api/source_intake";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";

// ---------------------------------------------------------------------------
// Batch status badge
// ---------------------------------------------------------------------------

function BatchStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    open: "bg-amber-950/40 text-amber-400 border-amber-800/40",
    closed: "bg-zinc-800/60 text-zinc-400 border-zinc-700",
    applied: "bg-blue-950/40 text-blue-400 border-blue-800/40",
    production_verified: "bg-emerald-950/40 text-emerald-400 border-emerald-800/40",
  };
  const cls = styles[status] ?? "bg-zinc-800/60 text-zinc-400 border-zinc-700";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>
      {status.replace("_", " ").toUpperCase()}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Batch row
// ---------------------------------------------------------------------------

function BatchRow({ batch }: { batch: BatchSummary }) {
  const hasReview = batch.count_needs_review > 0;

  return (
    <Link
      href={`/admin/source-intake/${batch.id}`}
      className="group flex items-center gap-4 rounded border border-zinc-800 bg-zinc-900/40 px-4 py-3 hover:border-zinc-700 hover:bg-zinc-900/70 transition-colors"
    >
      {/* Batch label + platform */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium text-zinc-200 group-hover:text-white">
          {batch.batch_label}
        </p>
        <p className="text-[11px] text-zinc-500">
          {batch.platform} · {batch.created_by} ·{" "}
          {batch.created_at ? new Date(batch.created_at).toLocaleDateString() : "—"}
        </p>
      </div>

      {/* Status */}
      <BatchStatusBadge status={batch.status} />

      {/* Counts */}
      <div className="hidden gap-3 sm:flex text-[11px]">
        <span className="text-zinc-500">
          Total: <span className="text-zinc-300">{batch.candidate_count}</span>
        </span>
        <span className="text-green-600">
          Ready: <span className="text-green-400">{batch.count_verified_add_ready + batch.count_operator_approved}</span>
        </span>
        {hasReview && (
          <span className="text-amber-600">
            Review: <span className="text-amber-400">{batch.count_needs_review}</span>
          </span>
        )}
        <span className="text-blue-600">
          Applied: <span className="text-blue-400">{batch.count_applied}</span>
        </span>
      </div>

      <span className="text-[11px] text-zinc-600 group-hover:text-zinc-400">→</span>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------

export function SourceIntakeConsole({ adminEmail }: { adminEmail: string }) {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBatches({ limit: 100 });
      setBatches(data.batches);
      setTotal(data.total);
    } catch (err: unknown) {
      setError((err as Error).message ?? "Failed to load batches");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <Header
        title="Source Intake"
        subtitle={`Operator: ${adminEmail}`}
        actions={
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-3 py-1.5 text-[12px] text-zinc-400 hover:text-zinc-200 transition-colors disabled:opacity-40"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />

      <div className="mx-auto max-w-4xl space-y-6 p-6">
        <TerminalPanel>
          <div className="mb-4 flex items-center justify-between">
            <p className="text-[12px] font-medium text-zinc-400">
              Intake Batches{" "}
              <span className="text-zinc-600">({total})</span>
            </p>
          </div>

          {error && (
            <p className="mb-4 rounded border border-red-800/40 bg-red-950/20 px-3 py-2 text-[12px] text-red-400">
              {error}
            </p>
          )}

          {loading && batches.length === 0 ? (
            <p className="py-8 text-center text-[12px] text-zinc-600">Loading…</p>
          ) : batches.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-[12px] text-zinc-500">No intake batches yet.</p>
              <p className="mt-1 text-[11px] text-zinc-600">
                Run <code className="text-zinc-400">verify_candidate_channels.py --persist</code> to create one.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {batches.map((b) => (
                <BatchRow key={b.id} batch={b} />
              ))}
            </div>
          )}
        </TerminalPanel>

        <p className="text-center text-[11px] text-zinc-700">
          Spot an issue? support@fragranceindex.ai
        </p>
      </div>
    </>
  );
}
