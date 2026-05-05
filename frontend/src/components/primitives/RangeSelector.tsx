"use client";

/**
 * Phase UI-T1 — Time Range Selector
 * Renders preset buttons: Today | Yesterday | 7D | 30D | MTD | YTD
 */

export type RangePreset = "today" | "yesterday" | "7d" | "30d" | "mtd" | "ytd";

export const RANGE_PRESETS: { key: RangePreset; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "7d", label: "7D" },
  { key: "30d", label: "30D" },
  { key: "mtd", label: "MTD" },
  { key: "ytd", label: "YTD" },
];

interface RangeSelectorProps {
  value: RangePreset;
  onChange: (preset: RangePreset) => void;
  className?: string;
}

export function RangeSelector({ value, onChange, className = "" }: RangeSelectorProps) {
  return (
    <div className={`flex items-center gap-0.5 ${className}`}>
      {RANGE_PRESETS.map(({ key, label }) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={
            `px-2.5 py-1 text-xs font-mono rounded transition-colors ` +
            (value === key
              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
              : "text-zinc-500 border border-transparent hover:text-zinc-300 hover:bg-zinc-800/60")
          }
        >
          {label}
        </button>
      ))}
    </div>
  );
}
