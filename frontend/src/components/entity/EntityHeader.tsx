import { Bookmark, Bell } from "lucide-react";
import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { fmtGrowth, fmtScore, fmtCount, fmtConfidence } from "@/lib/formatters";
import type { EntitySummaryBlock } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function EntityTypePill({ type }: { type: string }) {
  const label =
    type === "perfume"
      ? "Perfume"
      : type === "brand"
        ? "Brand"
        : type.charAt(0).toUpperCase() + type.slice(1);

  return (
    <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-800/60 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// EntityHeader
// ---------------------------------------------------------------------------

interface EntityHeaderProps {
  summary: EntitySummaryBlock;
  latestSignal?: string | null;
  onWatch?: () => void;
  onAlert?: () => void;
}

export function EntityHeader({ summary, latestSignal, onWatch, onAlert }: EntityHeaderProps) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
      {/* Left: identity */}
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-bold text-amber-400">
            {summary.ticker}
          </span>
          <EntityTypePill type={summary.entity_type} />
          {latestSignal && <SignalBadge type={latestSignal} />}
        </div>

        <h1 className="mt-1 text-xl font-bold leading-tight text-zinc-100">
          {summary.name}
        </h1>

        {summary.brand_name && (
          <p className="mt-0.5 text-xs text-zinc-500">{summary.brand_name}</p>
        )}
      </div>

      {/* Right: score + secondary stats + actions */}
      <div className="flex shrink-0 flex-col items-end gap-3">
        {/* Score + growth */}
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-2xl font-bold tabular-nums leading-none text-zinc-100">
              {fmtScore(summary.last_score)}
            </p>
            <p className="mt-0.5 text-[9px] uppercase tracking-wider text-zinc-600">
              Market Score
            </p>
          </div>
          <div className="text-right">
            <DeltaBadge
              value={summary.growth_rate}
              formatted={fmtGrowth(summary.growth_rate)}
              size="md"
            />
            <p className="mt-1 text-[9px] uppercase tracking-wider text-zinc-600">
              Growth
            </p>
          </div>
        </div>

        {/* Secondary stats */}
        <div className="flex items-center gap-3 text-right">
          <div>
            <span className="block text-xs font-semibold tabular-nums text-zinc-300">
              {fmtCount(summary.mention_count)}
            </span>
            <span className="block text-[9px] uppercase tracking-wider text-zinc-600">
              Mentions
            </span>
          </div>
          <div className="h-6 w-px bg-zinc-800" />
          <div>
            <span className="block text-xs font-semibold tabular-nums text-zinc-300">
              {fmtConfidence(summary.confidence_avg)}
            </span>
            <span className="block text-[9px] uppercase tracking-wider text-zinc-600">
              Confidence
            </span>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={onWatch}
            disabled={!onWatch}
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
            title="Add to watchlist"
          >
            <Bookmark size={11} />
            Watch
          </button>
          <button
            onClick={onAlert}
            disabled={!onAlert}
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
            title="Create alert for this entity"
          >
            <Bell size={11} />
            Alert
          </button>
        </div>
      </div>
    </div>
  );
}
