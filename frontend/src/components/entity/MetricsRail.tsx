import type { ReactNode } from "react";
import { clsx } from "clsx";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import {
  fmtScore,
  fmtGrowth,
  fmtCount,
  fmtConfidence,
  fmtMomentum,
  fmtAcceleration,
  fmtVolatility,
  fmtSignalType,
  growthColor,
  accelColor,
} from "@/lib/formatters";
import type { EntitySummaryBlock } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// MetricsRail — compact vertical list of metric rows for the entity page
// ---------------------------------------------------------------------------

interface MetricsRailProps {
  summary: EntitySummaryBlock;
  signalCount?: number;
  latestSignal?: string | null;
  latestSignalStrength?: number | null;
}

// Individual metric row
function Row({
  label,
  value,
  valueClass = "text-zinc-200",
}: {
  label: string;
  value: string | ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-zinc-800/60 px-4 py-2 last:border-b-0">
      <span className="shrink-0 text-[10px] uppercase tracking-wider text-zinc-600">
        {label}
      </span>
      <span
        className={clsx(
          "text-right text-xs font-semibold tabular-nums",
          valueClass,
        )}
      >
        {value}
      </span>
    </div>
  );
}

// Section divider — slightly darker strip for visual separation inside a zinc-900 panel
function Divider({ label }: { label: string }) {
  return (
    <div className="border-b border-t border-zinc-800/80 bg-zinc-950/50 px-4 py-1">
      <span className="text-[9px] font-bold uppercase tracking-widest text-zinc-600">
        {label}
      </span>
    </div>
  );
}

export function MetricsRail({
  summary,
  signalCount,
  latestSignal,
  latestSignalStrength,
}: MetricsRailProps) {
  return (
    <div className="flex flex-col">
      {/* Score section */}
      <Divider label="Market" />
      <Row
        label="Score"
        value={fmtScore(summary.last_score)}
        valueClass="text-amber-400 text-sm"
      />
      <Row
        label="Growth"
        value={fmtGrowth(summary.growth_rate)}
        valueClass={growthColor(summary.growth_rate)}
      />
      <Row label="Mentions" value={fmtCount(summary.mention_count)} />
      <Row label="Confidence" value={fmtConfidence(summary.confidence_avg)} />

      {/* Momentum section */}
      <Divider label="Momentum" />
      <Row label="Momentum" value={fmtMomentum(summary.momentum)} />
      <Row
        label="Acceleration"
        value={fmtAcceleration(summary.acceleration)}
        valueClass={accelColor(summary.acceleration)}
      />
      <Row label="Volatility" value={fmtVolatility(summary.volatility)} />

      {/* Signals section */}
      <Divider label="Signals" />
      <div className="flex items-center justify-between gap-3 border-b border-zinc-800/60 px-4 py-2">
        <span className="text-[10px] uppercase tracking-wider text-zinc-600">
          Latest
        </span>
        <span className="text-right">
          {latestSignal ? (
            <SignalBadge type={latestSignal} />
          ) : (
            <span className="text-xs text-zinc-600">—</span>
          )}
        </span>
      </div>
      {latestSignal && (
        <Row
          label="Strength"
          value={
            latestSignalStrength != null
              ? latestSignalStrength.toFixed(2)
              : "—"
          }
        />
      )}
      {signalCount != null && (
        <Row label="Total" value={String(signalCount)} />
      )}

      {/* Date */}
      {summary.latest_date && (
        <>
          <Divider label="Data" />
          <Row label="As of" value={summary.latest_date} />
        </>
      )}
    </div>
  );
}
