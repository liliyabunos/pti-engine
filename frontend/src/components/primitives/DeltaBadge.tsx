import { clsx } from "clsx";
import { TrendingDown, TrendingUp, Minus } from "lucide-react";

// ---------------------------------------------------------------------------
// DeltaBadge
//
// Inline directional indicator for numeric change values.
// Shows a directional arrow icon + the pre-formatted string.
//
// value    — raw numeric (drives icon + color selection)
// formatted — pre-formatted display string (e.g. "+12.4%", "1.30×")
// size     — "sm" (default) or "md"
// ---------------------------------------------------------------------------

type DeltaSize = "sm" | "md";

interface DeltaBadgeProps {
  /** Raw numeric value — drives icon and color selection */
  value: number | null | undefined;
  /** Pre-formatted display string */
  formatted: string;
  size?: DeltaSize;
  className?: string;
}

function resolveColor(v: number | null | undefined): string {
  if (v == null) return "text-zinc-600";
  if (v > 0)    return "text-emerald-400";
  if (v < 0)    return "text-red-400";
  return "text-zinc-500";
}

function resolveIcon(v: number | null | undefined) {
  if (v == null || v === 0) return Minus;
  return v > 0 ? TrendingUp : TrendingDown;
}

const SIZE_TEXT: Record<DeltaSize, string> = {
  sm: "text-xs",
  md: "text-sm",
};

const SIZE_ICON: Record<DeltaSize, number> = {
  sm: 11,
  md: 13,
};

export function DeltaBadge({
  value,
  formatted,
  size = "sm",
  className,
}: DeltaBadgeProps) {
  const Icon = resolveIcon(value);
  const color = resolveColor(value);

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 font-semibold tabular-nums",
        SIZE_TEXT[size],
        color,
        className,
      )}
    >
      <Icon size={SIZE_ICON[size]} strokeWidth={2.2} />
      {formatted}
    </span>
  );
}
