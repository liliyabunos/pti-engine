"use client";

import { useCallback, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";

import { fetchWatchlists, fetchWatchlist } from "@/lib/api/watchlists";
import { fetchSignals } from "@/lib/api/signals";
import { Header } from "@/components/shell/Header";
import { ControlBar } from "@/components/primitives/ControlBar";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { CreateWatchlistModal } from "@/components/watchlists/CreateWatchlistModal";
import { WatchlistTable } from "@/components/watchlists/WatchlistTable";
import { fmtDatetime } from "@/lib/formatters";

export default function WatchlistsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const { data: listData, isError: listError, refetch: refetchList } = useQuery({
    queryKey: ["watchlists"],
    queryFn: fetchWatchlists,
    staleTime: 15_000,
  });

  const { data: detail, isLoading: detailLoading, isError: detailError } = useQuery({
    queryKey: ["watchlist", selectedId],
    queryFn: () => fetchWatchlist(selectedId!),
    enabled: !!selectedId,
    staleTime: 15_000,
  });

  // Recent signals — fetch and filter to watched entity_ids (client-side)
  const { data: signalsData } = useQuery({
    queryKey: ["signals", "watchlist-activity"],
    queryFn: () => fetchSignals({ days: 7, limit: 200 }),
    staleTime: 30_000,
    enabled: !!detail?.items.length,
  });

  const watchedEntityIds = useMemo(
    () => new Set(detail?.items.map((i) => i.entity_id) ?? []),
    [detail?.items],
  );

  const activitySignals = useMemo(() => {
    if (!signalsData?.rows) return [];
    return signalsData.rows.filter(
      (s) => s.entity_id && watchedEntityIds.has(s.entity_id),
    );
  }, [signalsData?.rows, watchedEntityIds]);

  const handleCreated = useCallback((id: string) => {
    setShowCreate(false);
    setSelectedId(id);
  }, []);

  const watchlists = listData?.watchlists ?? [];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Watchlists"
        subtitle={
          watchlists.length > 0
            ? `${watchlists.length} list${watchlists.length !== 1 ? "s" : ""}`
            : undefined
        }
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
          >
            <Plus size={11} />
            New Watchlist
          </button>
        }
      />

      <ControlBar />

      {listError ? (
        <div className="p-4">
          <ErrorState message="Failed to load watchlists" onRetry={() => refetchList()} />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* ── Watchlist sidebar ─────────────────────────────────────── */}
          <aside className="flex w-48 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
            <div className="border-b border-zinc-800 px-3 py-2">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-600">
                Lists
              </span>
            </div>
            <div className="flex-1 overflow-y-auto py-1">
              {watchlists.length === 0 ? (
                <div className="px-3 py-3">
                  <p className="text-[11px] text-zinc-600">No watchlists yet.</p>
                </div>
              ) : (
                watchlists.map((wl) => (
                  <button
                    key={wl.id}
                    onClick={() => setSelectedId(wl.id)}
                    className={clsx(
                      "flex w-full items-center justify-between px-3 py-2 text-left transition-colors",
                      selectedId === wl.id
                        ? "bg-zinc-800 text-zinc-200"
                        : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200",
                    )}
                  >
                    <span className="min-w-0 truncate text-[12px]">{wl.name}</span>
                    <span className="ml-2 shrink-0 text-[10px] text-zinc-600">
                      {wl.item_count}
                    </span>
                  </button>
                ))
              )}
            </div>
            <div className="border-t border-zinc-800 p-2">
              <button
                onClick={() => setShowCreate(true)}
                className="flex w-full items-center justify-center gap-1 rounded border border-zinc-700 py-1.5 text-[11px] text-zinc-500 hover:border-zinc-600 hover:text-zinc-300"
              >
                <Plus size={10} />
                New list
              </button>
            </div>
          </aside>

          {/* ── Main area ─────────────────────────────────────────────── */}
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-4 pr-2">
            {!selectedId ? (
              <TerminalPanel className="flex flex-1 items-center justify-center">
                <EmptyState
                  message="Select a watchlist"
                  detail="Choose a list from the sidebar or create a new one."
                />
              </TerminalPanel>
            ) : detailError ? (
              <ErrorState message="Failed to load watchlist" />
            ) : (
              <TerminalPanel noPad className="flex flex-1 flex-col overflow-hidden">
                <div className="border-b border-zinc-800 px-4 py-3">
                  <SectionHeader
                    title={detail?.name ?? "…"}
                    subtitle={
                      detail
                        ? `${detail.items.length} entit${detail.items.length !== 1 ? "ies" : "y"}`
                        : undefined
                    }
                  />
                  {detail?.description && (
                    <p className="mt-0.5 text-[11px] text-zinc-500">
                      {detail.description}
                    </p>
                  )}
                </div>
                <div className="flex-1 overflow-y-auto">
                  <WatchlistTable
                    watchlistId={selectedId}
                    items={detail?.items ?? []}
                    isLoading={detailLoading}
                  />
                </div>
              </TerminalPanel>
            )}
          </div>

          {/* ── Activity panel ────────────────────────────────────────── */}
          <aside className="flex w-52 shrink-0 flex-col border-l border-zinc-800 p-0">
            <TerminalPanel noPad className="flex h-full flex-col overflow-hidden">
              <div className="border-b border-zinc-800 px-3 py-2">
                <SectionHeader title="Activity" subtitle="last 7 days" />
              </div>
              <div className="flex-1 overflow-y-auto">
                {!selectedId ? (
                  <EmptyState compact message="No list selected" />
                ) : activitySignals.length === 0 ? (
                  <EmptyState compact message="No recent signals" />
                ) : (
                  <ul className="divide-y divide-zinc-800/40">
                    {activitySignals.slice(0, 30).map((sig, i) => (
                      <li key={`${sig.entity_id}-${sig.detected_at}-${i}`} className="px-3 py-2">
                        <div className="mb-0.5 flex items-center justify-between gap-1">
                          <SignalBadge type={sig.signal_type} variant="dot" />
                          <span className="tabular-nums text-[9px] text-zinc-600">
                            {sig.strength.toFixed(2)}
                          </span>
                        </div>
                        <div className="truncate text-[11px] text-zinc-300">
                          {sig.canonical_name ?? sig.entity_id}
                        </div>
                        <div className="text-[9px] text-zinc-600">
                          {fmtDatetime(sig.detected_at)}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </TerminalPanel>
          </aside>
        </div>
      )}

      {showCreate && (
        <CreateWatchlistModal
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
