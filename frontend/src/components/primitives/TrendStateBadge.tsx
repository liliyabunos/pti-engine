import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// TrendStateBadge  (Phase I3 — Trend State Layer)
//
// Displays a directional trend state label with semantic color coding.
//
// States:
//   breakout  — bright emerald (strongest upward signal)
//   rising    — green (positive momentum)
//   peak      — amber (top of wave, slowing)
//   stable    — blue/slate (active but flat)
//   declining — rose/red (losing momentum)
//   emerging  — violet (first appearance, small but growing)
//
// variant:
//   pill  — bordered pill with background fill (default, table/list use)
//   dot   — colored dot + text (compact inline)
//   label — text-only (dense cell)
// ---------------------------------------------------------------------------

type TrendVariant = "pill" | "dot" | "label";

interface TrendStateBadgeProps {
  state: string | null | undefined;
  variant?: TrendVariant;
  className?: string;
}

const STATE_LABELS: Record<string, string> = {
  breakout:  "Breakout",
  rising:    "Rising",
  peak:      "Peak",
  stable:    "Stable",
  declining: "Declining",
  emerging:  "Emerging",
};

const COLORS: Record<string, { dot: string; text: string; pill: string }> = {
  breakout: {
    dot:  "bg-emerald-400",
    text: "text-emerald-400",
    pill: "bg-emerald-900/30 text-emerald-400 border-emerald-700/60",
  },
  rising: {
    dot:  "bg-green-400",
    text: "text-green-400",
    pill: "bg-green-900/25 text-green-400 border-green-700/50",
  },
  peak: {
    dot:  "bg-amber-400",
    text: "text-amber-400",
    pill: "bg-amber-900/30 text-amber-400 border-amber-700/60",
  },
  stable: {
    dot:  "bg-sky-400",
    text: "text-sky-400",
    pill: "bg-sky-900/25 text-sky-400 border-sky-800/50",
  },
  declining: {
    dot:  "bg-rose-400",
    text: "text-rose-400",
    pill: "bg-rose-900/30 text-rose-400 border-rose-800/60",
  },
  emerging: {
    dot:  "bg-violet-400",
    text: "text-violet-400",
    pill: "bg-violet-900/25 text-violet-400 border-violet-800/50",
  },
};

const FALLBACK = {
  dot:  "bg-zinc-600",
  text: "text-zinc-500",
  pill: "bg-zinc-800 text-zinc-500 border-zinc-700",
};

export function TrendStateBadge({
  state,
  variant = "pill",
  className,
}: TrendStateBadgeProps) {
  if (!state) return null;

  const colors = COLORS[state] ?? FALLBACK;
  const label = STATE_LABELS[state] ?? state;

  if (variant === "dot") {
    return (
      <span className={clsx("inline-flex items-center gap-1.5", className)}>
        <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", colors.dot)} />
        <span className={clsx("text-[11px] font-medium", colors.text)}>{label}</span>
      </span>
    );
  }

  if (variant === "label") {
    return (
      <span
        className={clsx(
          "text-[10px] font-semibold uppercase tracking-wide",
          colors.text,
          className,
        )}
      >
        {label}
      </span>
    );
  }

  // pill (default)
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded border px-1.5 py-0.5",
        "text-[10px] font-semibold uppercase tracking-wide",
        colors.pill,
        className,
      )}
    >
      {label}
    </span>
  );
}
