import { clsx } from "clsx";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

// ---------------------------------------------------------------------------
// KpiCard
//
// Headline metric card for the dashboard KPI strip.
//
// Props:
//   label    — short all-caps label above the value
//   value    — the formatted metric (string or number)
//   sub      — tiny caption below the value (date, unit, etc.)
//   delta    — optional numeric growth/change value (shows trend arrow)
//   deltaFmt — pre-formatted string for the delta (e.g. "+12.4%")
//   accent   — color of the value text
// ---------------------------------------------------------------------------

type KpiAccent = "default" | "green" | "amber" | "sky" | "red";

interface KpiCardProps {
  label: string;
  value: string | number;
  sub?: string;
  /** Raw numeric delta used to pick arrow direction (positive/negative/zero) */
  delta?: number | null;
  /** Pre-formatted string shown next to the trend arrow */
  deltaFmt?: string;
  accent?: KpiAccent;
  className?: string;
}

const VALUE_COLOR: Record<KpiAccent, string> = {
  default: "text-zinc-100",
  green:   "text-emerald-400",
  amber:   "text-amber-400",
  sky:     "text-sky-400",
  red:     "text-red-400",
};

const DELTA_COLOR = (v: number | null | undefined) => {
  if (v == null) return "text-zinc-600";
  if (v > 0)    return "text-emerald-400";
  if (v < 0)    return "text-red-400";
  return "text-zinc-500";
};

const DeltaIcon = ({ v }: { v: number | null | undefined }) => {
  const Icon = v == null ? null : v > 0 ? TrendingUp : v < 0 ? TrendingDown : Minus;
  if (!Icon) return null;
  return <Icon size={10} strokeWidth={2.2} />;
};

export function KpiCard({
  label,
  value,
  sub,
  delta,
  deltaFmt,
  accent = "default",
  className,
}: KpiCardProps) {
  return (
    <div
      className={clsx(
        "flex flex-col gap-1 rounded border border-zinc-800 bg-zinc-900 px-4 py-3",
        className,
      )}
    >
      {/* Label */}
      <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        {label}
      </span>

      {/* Value */}
      <span
        className={clsx(
          "text-xl font-bold leading-none tabular-nums",
          VALUE_COLOR[accent],
        )}
      >
        {value}
      </span>

      {/* Delta + sub */}
      <div className="flex items-center gap-2">
        {delta != null && deltaFmt && (
          <span
            className={clsx(
              "inline-flex items-center gap-0.5 text-[10px] font-semibold tabular-nums",
              DELTA_COLOR(delta),
            )}
          >
            <DeltaIcon v={delta} />
            {deltaFmt}
          </span>
        )}
        {sub && (
          <span className="text-[10px] text-zinc-700">{sub}</span>
        )}
      </div>
    </div>
  );
}
