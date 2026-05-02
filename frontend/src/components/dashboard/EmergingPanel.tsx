"use client";

import { EmptyState } from "@/components/primitives/EmptyState";
import type { EmergingCandidateRow } from "@/lib/api/types";

interface EmergingPanelProps {
  candidates: EmergingCandidateRow[];
  totalInQueue: number;
  isLoading?: boolean;
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.7
      ? "text-emerald-400 bg-emerald-400/10"
      : value >= 0.4
      ? "text-amber-400 bg-amber-400/10"
      : "text-zinc-500 bg-zinc-500/10";
  return (
    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${color}`}>
      {pct}%
    </span>
  );
}

function EntityTypeBadge({ type }: { type: string | null }) {
  if (!type) return null;
  const map: Record<string, string> = {
    perfume: "text-violet-400 bg-violet-400/10",
    brand: "text-sky-400 bg-sky-400/10",
    note: "text-emerald-400 bg-emerald-400/10",
  };
  const cls = map[type] ?? "text-zinc-400 bg-zinc-400/10";
  return (
    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${cls}`}>
      {type}
    </span>
  );
}

export function EmergingPanel({ candidates, totalInQueue, isLoading }: EmergingPanelProps) {
  if (isLoading) {
    return (
      <ul className="space-y-1">
        {Array.from({ length: 5 }).map((_, i) => (
          <li key={i} className="h-8 bg-zinc-800/50 rounded animate-pulse" />
        ))}
      </ul>
    );
  }

  if (!candidates.length) {
    return <EmptyState compact message="No emerging candidates in window" />;
  }

  return (
    <div>
      <ul className="space-y-0.5">
        {candidates.map((c) => (
          <li
            key={c.id}
            className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-zinc-800/50 transition-colors"
          >
            {/* Name */}
            <span className="flex-1 text-sm text-zinc-200 font-medium truncate">
              {c.display_name}
            </span>

            {/* Mentions */}
            <span className="text-xs text-zinc-500 tabular-nums shrink-0">
              {c.mention_count}×
            </span>

            {/* Days active */}
            <span className="text-xs text-zinc-600 tabular-nums shrink-0 hidden sm:inline">
              {c.days_active}d
            </span>

            {/* Entity type badge */}
            <EntityTypeBadge type={c.approved_entity_type} />

            {/* Confidence badge */}
            <ConfidenceBadge value={c.confidence_normalized} />

            {/* Not tracked indicator */}
            <span className="text-[10px] text-zinc-600 shrink-0 hidden lg:inline">
              untracked
            </span>
          </li>
        ))}
      </ul>

      {totalInQueue > candidates.length && (
        <p className="mt-2 text-[11px] text-zinc-600 text-right">
          {totalInQueue.toLocaleString()} total in queue
        </p>
      )}
    </div>
  );
}
