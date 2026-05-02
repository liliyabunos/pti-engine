"use client";

import { EmptyState } from "@/components/primitives/EmptyState";
import type { EmergingSignalRow } from "@/lib/api/types";

interface EmergingPanelProps {
  candidates: EmergingSignalRow[];
  totalInQueue: number;
  isLoading?: boolean;
}

function CandidateTypeBadge({ type }: { type: string }) {
  const map: Record<string, string> = {
    perfume: "text-violet-400 bg-violet-400/10",
    brand: "text-sky-400 bg-sky-400/10",
    clone_reference: "text-amber-400 bg-amber-400/10",
    flanker: "text-emerald-400 bg-emerald-400/10",
    unknown: "text-zinc-500 bg-zinc-500/10",
  };
  const cls = map[type] ?? "text-zinc-500 bg-zinc-500/10";
  const label = type === "clone_reference" ? "clone" : type;
  return (
    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${cls}`}>
      {label}
    </span>
  );
}

function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  const map: Record<string, string> = {
    tier_1: "text-emerald-400",
    tier_2: "text-sky-400",
    tier_3: "text-zinc-400",
    tier_4: "text-zinc-600",
    unrated: "text-zinc-600",
  };
  const cls = map[tier] ?? "text-zinc-600";
  return (
    <span className={`text-[10px] font-mono ${cls} shrink-0 hidden xl:inline`} title={tier}>
      {tier.replace("tier_", "T")}
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
    return <EmptyState compact message="No emerging signals in window" />;
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

            {/* Channel count */}
            <span
              className="text-xs text-zinc-500 tabular-nums shrink-0"
              title={`${c.distinct_channels_count} channel${c.distinct_channels_count !== 1 ? "s" : ""}`}
            >
              {c.distinct_channels_count}ch
            </span>

            {/* Days active */}
            <span className="text-xs text-zinc-600 tabular-nums shrink-0 hidden sm:inline">
              {c.days_active}d
            </span>

            {/* Top channel tier */}
            <TierBadge tier={c.top_channel_tier} />

            {/* Top channel title — abbreviated */}
            {c.top_channel_title && (
              <span
                className="text-[10px] text-zinc-600 shrink-0 max-w-[100px] truncate hidden lg:inline"
                title={c.top_channel_title}
              >
                {c.top_channel_title}
              </span>
            )}

            {/* Candidate type badge */}
            <CandidateTypeBadge type={c.candidate_type} />

            {/* Emerging score */}
            <span
              className="text-[10px] font-mono text-zinc-500 tabular-nums shrink-0"
              title={`emerging score: ${c.emerging_score}`}
            >
              {c.emerging_score.toFixed(2)}
            </span>

            {/* Not tracked indicator */}
            <span className="text-[10px] text-zinc-600 shrink-0 hidden xl:inline">
              untracked
            </span>
          </li>
        ))}
      </ul>

      {totalInQueue > candidates.length && (
        <p className="mt-2 text-[11px] text-zinc-600 text-right">
          {totalInQueue.toLocaleString()} signals in table
        </p>
      )}
    </div>
  );
}
