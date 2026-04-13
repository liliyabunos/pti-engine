import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// MetricBadge
//
// A compact metric tile used in the entity metrics rail.
// Shows a label above a value — stacked vertically, center-aligned.
//
// color variants affect the value text only.
// ---------------------------------------------------------------------------

type MetricColor = "default" | "green" | "amber" | "sky" | "red" | "dim";

interface MetricBadgeProps {
  label: string;
  value: string;
  color?: MetricColor;
  className?: string;
}

const VALUE_COLOR: Record<MetricColor, string> = {
  default: "text-zinc-200",
  green:   "text-emerald-400",
  amber:   "text-amber-400",
  sky:     "text-sky-400",
  red:     "text-red-400",
  dim:     "text-zinc-500",
};

export function MetricBadge({
  label,
  value,
  color = "default",
  className,
}: MetricBadgeProps) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center gap-0.5 rounded border border-zinc-800 bg-zinc-950 px-3 py-2",
        className,
      )}
    >
      <span className="text-[10px] font-semibold uppercase tracking-[0.10em] text-zinc-600">
        {label}
      </span>
      <span
        className={clsx(
          "text-sm font-semibold leading-none tabular-nums",
          VALUE_COLOR[color],
        )}
      >
        {value}
      </span>
    </div>
  );
}
