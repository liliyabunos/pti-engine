"use client";

/**
 * SIG-ID1 — Admin Signal Candidates Console (client component).
 *
 * Read-only operator visibility for brand-qualified unresolved phrases
 * surfaced from resolved_signals.unresolved_mentions_json by
 * scripts/harvest_unresolved_brand_signals.py.
 *
 * This layer surfaces Class 2 and Class 3 identity failures:
 *   - A phrase appears in content but has no resolver alias
 *   - A brand token is present, making it likely a real product
 *
 * Actions:
 *   - Filter by status: pending | dismissed | all
 *   - Dismiss: mark candidate as not actionable
 *   - Refresh
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, XCircle } from "lucide-react";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SignalCandidateRow {
  id: string;
  phrase: string;
  brand_token: string;
  brand_canonical_name: string;
  occurrence_count: number;
  source_count: number;
  first_seen: string | null;
  last_seen: string | null;
  candidate_status: string;
  operator_notes: string | null;
  created_at: string;
  updated_at: string;
}

interface SignalCandidatesResponse {
  total: number;
  items: SignalCandidateRow[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_FILTER_OPTIONS = [
  { label: "Pending", value: "pending" },
  { label: "Dismissed", value: "dismissed" },
  { label: "All", value: "all" },
];

const STATUS_BADGE: Record<string, string> = {
  pending: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  dismissed: "bg-zinc-700/40 text-zinc-500 border-zinc-600/30",
  added_to_catalog: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
};

// ---------------------------------------------------------------------------
// Console Component
// ---------------------------------------------------------------------------

export function SignalCandidatesConsole({ adminEmail }: { adminEmail: string }) {
  const [filter, setFilter] = useState<string>("pending");
  const [items, setItems] = useState<SignalCandidateRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dismissing, setDismissing] = useState<string | null>(null);

  const fetchCandidates = useCallback(async (status: string) => {
    setLoading(true);
    setError(null);
    try {
      const qs = status === "all" ? "?status=all&limit=200" : `?status=${status}&limit=200`;
      const resp = await fetch(`/api/admin/signal-candidates${qs}`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setError(err.detail ?? "Request failed");
        return;
      }
      const data: SignalCandidatesResponse = await resp.json();
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCandidates(filter);
  }, [filter, fetchCandidates]);

  const dismiss = async (id: string) => {
    setDismissing(id);
    try {
      const resp = await fetch(`/api/admin/signal-candidates/${id}/dismiss`, {
        method: "POST",
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        alert(`Dismiss failed: ${err.detail ?? "Unknown error"}`);
        return;
      }
      setItems((prev) => prev.filter((r) => r.id !== id));
      setTotal((prev) => prev - 1);
    } catch {
      alert("Network error during dismiss");
    } finally {
      setDismissing(null);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <Header title="Signal Candidates" />
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* Admin identity */}
        <p className="text-[11px] text-zinc-500">
          Viewing as: <span className="text-zinc-400">{adminEmail}</span>
        </p>

        {/* Controls */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex gap-1">
            {STATUS_FILTER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setFilter(opt.value)}
                className={`px-3 py-1 text-[12px] rounded border transition-colors ${
                  filter === opt.value
                    ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                    : "bg-zinc-800/50 text-zinc-400 border-zinc-700/40 hover:bg-zinc-700/40"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => fetchCandidates(filter)}
            disabled={loading}
            className="p-1.5 text-zinc-500 hover:text-zinc-300 disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
          <span className="text-[11px] text-zinc-500 ml-auto">
            {total} candidate{total !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Context note */}
        <TerminalPanel className="text-[11px] text-zinc-500 p-3 leading-relaxed">
          Brand-qualified phrases seen in content but missing from the resolver catalog.
          These are candidates for catalog addition (ENTITY-DISC1) or guard expansion (RES-AMB).
          Populated daily by <code className="text-zinc-400">harvest_unresolved_brand_signals.py</code>.
        </TerminalPanel>

        {/* Error */}
        {error && (
          <div className="text-[12px] text-red-400 border border-red-500/20 rounded p-3">
            Error: {error}
          </div>
        )}

        {/* Table */}
        {!loading && items.length === 0 && !error && (
          <p className="text-[12px] text-zinc-500 py-8 text-center">
            No {filter === "all" ? "" : filter} candidates.
          </p>
        )}

        {items.length > 0 && (
          <div className="overflow-x-auto rounded border border-zinc-800/50">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-zinc-800/50 bg-zinc-900/50">
                  <th className="text-left px-3 py-2 text-zinc-500 font-medium">Phrase</th>
                  <th className="text-left px-3 py-2 text-zinc-500 font-medium">Brand</th>
                  <th className="text-right px-3 py-2 text-zinc-500 font-medium">Occ</th>
                  <th className="text-right px-3 py-2 text-zinc-500 font-medium">Src</th>
                  <th className="text-left px-3 py-2 text-zinc-500 font-medium">Last Seen</th>
                  <th className="text-left px-3 py-2 text-zinc-500 font-medium">Status</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr
                    key={row.id}
                    className="border-b border-zinc-800/30 hover:bg-zinc-800/20 transition-colors"
                  >
                    <td className="px-3 py-2 text-zinc-200 font-mono">{row.phrase}</td>
                    <td className="px-3 py-2 text-zinc-400">{row.brand_canonical_name}</td>
                    <td className="px-3 py-2 text-right text-zinc-300">{row.occurrence_count}</td>
                    <td className="px-3 py-2 text-right text-zinc-500">{row.source_count}</td>
                    <td className="px-3 py-2 text-zinc-500">{row.last_seen ?? "—"}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-1.5 py-0.5 text-[10px] rounded border ${
                          STATUS_BADGE[row.candidate_status] ?? "bg-zinc-700/40 text-zinc-500 border-zinc-600/30"
                        }`}
                      >
                        {row.candidate_status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      {row.candidate_status === "pending" && (
                        <button
                          onClick={() => dismiss(row.id)}
                          disabled={dismissing === row.id}
                          className="p-1 text-zinc-600 hover:text-zinc-400 disabled:opacity-40 transition-colors"
                          title="Dismiss"
                        >
                          <XCircle size={13} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
