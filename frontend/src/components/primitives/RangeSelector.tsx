"use client";

/**
 * Phase UI-T1 — Time Range Selector
 * Renders preset buttons: Today | Yesterday | 7D | 30D | MTD | YTD | Custom
 *
 * Phase UI-T1.1 — Custom date range: when "Custom" is active, inline start/end
 * date inputs appear. Parent must manage customStartDate / customEndDate state.
 */

export type RangePreset =
  | "today"
  | "yesterday"
  | "7d"
  | "30d"
  | "mtd"
  | "ytd"
  | "custom";

export const RANGE_PRESETS: { key: RangePreset; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "7d", label: "7D" },
  { key: "30d", label: "30D" },
  { key: "mtd", label: "MTD" },
  { key: "ytd", label: "YTD" },
  { key: "custom", label: "Custom" },
];

interface RangeSelectorProps {
  value: RangePreset;
  onChange: (preset: RangePreset) => void;
  customStartDate?: string;
  customEndDate?: string;
  onCustomDatesChange?: (startDate: string, endDate: string) => void;
  className?: string;
}

export function RangeSelector({
  value,
  onChange,
  customStartDate = "",
  customEndDate = "",
  onCustomDatesChange,
  className = "",
}: RangeSelectorProps) {
  const isCustomValid =
    value === "custom" &&
    customStartDate &&
    customEndDate &&
    customStartDate <= customEndDate;

  return (
    <div className={`flex items-center gap-0.5 flex-wrap ${className}`}>
      {RANGE_PRESETS.map(({ key, label }) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={
            `px-2.5 py-1 text-xs font-mono rounded transition-colors ` +
            (value === key
              ? key === "custom" && !isCustomValid
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
              : "text-zinc-500 border border-transparent hover:text-zinc-300 hover:bg-zinc-800/60")
          }
        >
          {label}
        </button>
      ))}

      {value === "custom" && (
        <div className="flex items-center gap-1 ml-1">
          <input
            type="date"
            value={customStartDate}
            onChange={(e) =>
              onCustomDatesChange?.(e.target.value, customEndDate)
            }
            className="h-[26px] rounded border border-zinc-700 bg-zinc-900 px-1.5 text-[11px] font-mono text-zinc-300 focus:border-zinc-500 focus:outline-none [color-scheme:dark]"
          />
          <span className="text-[11px] text-zinc-600">–</span>
          <input
            type="date"
            value={customEndDate}
            min={customStartDate || undefined}
            onChange={(e) =>
              onCustomDatesChange?.(customStartDate, e.target.value)
            }
            className="h-[26px] rounded border border-zinc-700 bg-zinc-900 px-1.5 text-[11px] font-mono text-zinc-300 focus:border-zinc-500 focus:outline-none [color-scheme:dark]"
          />
          {customStartDate && customEndDate && customStartDate > customEndDate && (
            <span className="text-[10px] text-rose-500">start &gt; end</span>
          )}
        </div>
      )}
    </div>
  );
}
