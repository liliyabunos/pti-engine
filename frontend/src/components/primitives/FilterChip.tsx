"use client";

import { clsx } from "clsx";
import { X } from "lucide-react";

// ---------------------------------------------------------------------------
// FilterChip
//
// Toggle/select chip for filter bars.
//
// Props:
//   label    — display text
//   count    — optional numeric badge appended to the label
//   active   — highlights the chip as selected
//   disabled — prevents interaction, dims the chip
//   onRemove — if provided, renders an × button to clear the chip value
//   onClick  — toggle/select handler
// ---------------------------------------------------------------------------

interface FilterChipProps {
  label: string;
  /** Optional count appended after the label, e.g. "(12)" */
  count?: number;
  active?: boolean;
  disabled?: boolean;
  onRemove?: () => void;
  onClick?: () => void;
  className?: string;
  title?: string;
}

export function FilterChip({
  label,
  count,
  active = false,
  disabled = false,
  onRemove,
  onClick,
  className,
  title,
}: FilterChipProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      title={title}
      onClick={disabled ? undefined : onClick}
      className={clsx(
        // base
        "inline-flex h-6 items-center gap-1 rounded border px-2 text-[11px] font-medium",
        "transition-colors select-none",
        // active
        active && !disabled && [
          "border-zinc-500 bg-zinc-700 text-zinc-100",
        ],
        // idle + hover
        !active && !disabled && [
          "border-zinc-700 bg-zinc-900 text-zinc-400",
          "hover:border-zinc-600 hover:text-zinc-200",
        ],
        // disabled
        disabled && "cursor-not-allowed border-zinc-800 bg-transparent text-zinc-700",
        className,
      )}
    >
      {label}

      {/* Count badge */}
      {count != null && (
        <span
          className={clsx(
            "rounded px-1 text-[9px] tabular-nums",
            active ? "bg-zinc-600 text-zinc-300" : "text-zinc-600",
          )}
        >
          {count}
        </span>
      )}

      {/* Remove button */}
      {onRemove && !disabled && (
        <span
          role="button"
          aria-label={`Remove ${label} filter`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 flex items-center text-zinc-500 hover:text-zinc-200"
        >
          <X size={10} />
        </span>
      )}
    </button>
  );
}
