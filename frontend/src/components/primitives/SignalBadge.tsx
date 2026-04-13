import { clsx } from "clsx";
import { fmtSignalType } from "@/lib/formatters";

// ---------------------------------------------------------------------------
// SignalBadge
//
// Displays a market signal type with semantic color coding.
//
// variant:
//   pill  — bordered pill with background fill (default, table/list use)
//   dot   — colored dot + text (compact inline use, e.g. signal feeds)
//   label — text-only, no border/bg (dense table cell use)
//
// Signal type → color mapping lives in formatters/index.ts (signalBgColor)
// so it stays in one place across the app.
// ---------------------------------------------------------------------------

type SignalVariant = "pill" | "dot" | "label";

interface SignalBadgeProps {
  type: string | null | undefined;
  variant?: SignalVariant;
  className?: string;
}

// Color tokens per signal type
const COLORS: Record<string, { dot: string; text: string; pill: string }> = {
  breakout: {
    dot:  "bg-amber-400",
    text: "text-amber-400",
    pill: "bg-amber-900/30 text-amber-400 border-amber-800/60",
  },
  acceleration_spike: {
    dot:  "bg-sky-400",
    text: "text-sky-400",
    pill: "bg-sky-900/30 text-sky-400 border-sky-800/60",
  },
  reversal: {
    dot:  "bg-rose-400",
    text: "text-rose-400",
    pill: "bg-rose-900/30 text-rose-400 border-rose-800/60",
  },
  new_entry: {
    dot:  "bg-emerald-400",
    text: "text-emerald-400",
    pill: "bg-emerald-900/30 text-emerald-400 border-emerald-800/60",
  },
};

const FALLBACK = {
  dot:  "bg-zinc-600",
  text: "text-zinc-400",
  pill: "bg-zinc-800 text-zinc-400 border-zinc-700",
};

export function SignalBadge({
  type,
  variant = "pill",
  className,
}: SignalBadgeProps) {
  if (!type) return null;

  const colors = COLORS[type] ?? FALLBACK;
  const label = fmtSignalType(type);

  if (variant === "dot") {
    return (
      <span
        className={clsx("inline-flex items-center gap-1.5", className)}
      >
        <span
          className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", colors.dot)}
        />
        <span className={clsx("text-[11px] font-medium", colors.text)}>
          {label}
        </span>
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
