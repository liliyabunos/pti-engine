"use client";

import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { removeWatchlistItem } from "@/lib/api/watchlists";
import { TableSkeleton, EmptyState, SignalBadge, DeltaBadge } from "@/components/primitives";
import {
  fmtScore,
  fmtGrowth,
  fmtCount,
  fmtConfidence,
  fmtDate,
  growthColor,
} from "@/lib/formatters";
import type { WatchlistItemRow } from "@/lib/api/types";

interface WatchlistTableProps {
  watchlistId: string;
  items: WatchlistItemRow[];
  isLoading: boolean;
}

export function WatchlistTable({ watchlistId, items, isLoading }: WatchlistTableProps) {
  const router = useRouter();
  const qc = useQueryClient();

  const removeMutation = useMutation({
    mutationFn: (entityId: string) => removeWatchlistItem(watchlistId, entityId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlist", watchlistId] });
    },
  });

  if (isLoading) return <TableSkeleton rows={6} cols={6} />;

  if (!items.length) {
    return (
      <EmptyState
        message="No entities in this watchlist"
        detail="Navigate to an entity page and click Watch to add it here."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-zinc-800">
            {["Entity", "Type", "Score", "Growth", "Mentions", "Confidence", "Signal", "As of", ""].map(
              (col) => (
                <th
                  key={col}
                  className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-600"
                >
                  {col}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr
              key={row.entity_id}
              onClick={() => {
                const path =
                  row.entity_type === "brand"
                    ? `/entities/brand/${encodeURIComponent(row.entity_id)}`
                    : `/entities/perfume/${encodeURIComponent(row.entity_id)}`;
                router.push(path);
              }}
              className={`cursor-pointer border-b border-zinc-800/60 transition-colors ${
                row.entity_type === "brand"
                  ? "hover:bg-sky-950/10"
                  : "hover:bg-zinc-800/30"
              }`}
            >
              {/* Entity */}
              <td className="px-3 py-2">
                <div className="text-xs font-medium text-zinc-200">
                  {row.canonical_name}
                </div>
                {row.brand_name && (
                  <div className="text-[10px] text-zinc-500">{row.brand_name}</div>
                )}
              </td>

              {/* Type */}
              <td className="px-3 py-2">
                {row.entity_type === "brand" ? (
                  <span
                    title="Brand — composite score aggregated across perfume portfolio"
                    className="inline-flex cursor-default items-center rounded border border-sky-800/70 bg-sky-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-sky-400"
                  >
                    Brand
                  </span>
                ) : (
                  <span className="rounded border border-zinc-700 bg-zinc-800/60 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500">
                    Perfume
                  </span>
                )}
              </td>

              {/* Score */}
              <td className="px-3 py-2 tabular-nums text-xs text-zinc-300">
                {fmtScore(row.composite_market_score)}
              </td>

              {/* Growth */}
              <td className="px-3 py-2">
                <DeltaBadge
                  value={row.growth_rate}
                  formatted={fmtGrowth(row.growth_rate)}
                />
              </td>

              {/* Mentions */}
              <td className="px-3 py-2 tabular-nums text-xs text-zinc-400">
                {fmtCount(row.mention_count)}
              </td>

              {/* Confidence */}
              <td className="px-3 py-2 tabular-nums text-xs text-zinc-400">
                {fmtConfidence(row.confidence_avg)}
              </td>

              {/* Signal */}
              <td className="px-3 py-2">
                {row.latest_signal ? (
                  <SignalBadge type={row.latest_signal} variant="pill" />
                ) : (
                  <span className="text-[10px] text-zinc-700">—</span>
                )}
              </td>

              {/* As of */}
              <td className="px-3 py-2 tabular-nums text-[10px] text-zinc-500">
                {fmtDate(row.latest_date)}
              </td>

              {/* Remove */}
              <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                <button
                  onClick={() => removeMutation.mutate(row.entity_id)}
                  disabled={removeMutation.isPending}
                  title="Remove from watchlist"
                  className="text-zinc-700 hover:text-red-400 disabled:opacity-30"
                >
                  <Trash2 size={12} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
