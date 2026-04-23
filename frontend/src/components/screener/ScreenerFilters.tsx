"use client";

import { FilterChip } from "@/components/primitives/FilterChip";
import { fmtSignalType } from "@/lib/formatters";
import type { ScreenerParams } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SIGNAL_TYPES = [
  "breakout",
  "acceleration_spike",
  "reversal",
  "new_entry",
] as const;

const SORT_FIELDS: { value: string; label: string }[] = [
  { value: "composite_market_score", label: "Score" },
  { value: "mention_count", label: "Mentions" },
  { value: "growth_rate", label: "Growth" },
  { value: "momentum", label: "Momentum" },
  { value: "acceleration", label: "Accel." },
  { value: "volatility", label: "Vol." },
  { value: "engagement_sum", label: "Engagement" },
];

// ---------------------------------------------------------------------------
// Section heading
// ---------------------------------------------------------------------------

function FilterSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-zinc-700">
        {label}
      </p>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ScreenerFilters
// ---------------------------------------------------------------------------

interface ScreenerFiltersProps {
  params: ScreenerParams;
  onChange: (updates: Partial<ScreenerParams>) => void;
}

export function ScreenerFilters({ params, onChange }: ScreenerFiltersProps) {
  return (
    <div className="space-y-4 p-4">
      {/* ── Entity type ──────────────────────────────────────────────── */}
      <FilterSection label="Type">
        <div className="flex flex-wrap gap-1.5">
          {(
            [
              [undefined, "All"],
              ["perfume", "Perfume"],
              ["brand", "Brand"],
            ] as const
          ).map(([value, label]) => (
            <FilterChip
              key={label}
              label={label}
              active={
                value === undefined
                  ? !params.entity_type
                  : params.entity_type === value
              }
              onClick={() => onChange({ entity_type: value })}
            />
          ))}
        </div>
      </FilterSection>

      {/* ── Signal type ──────────────────────────────────────────────── */}
      <FilterSection label="Signal">
        <div className="flex flex-wrap gap-1.5">
          <FilterChip
            label="Any"
            active={!params.signal_type}
            onClick={() =>
              onChange({ signal_type: undefined, has_signals: undefined })
            }
          />
          {SIGNAL_TYPES.map((s) => (
            <FilterChip
              key={s}
              label={fmtSignalType(s)}
              active={params.signal_type === s}
              onClick={() => onChange({ signal_type: s, has_signals: true })}
            />
          ))}
          <FilterChip
            label="Has signal"
            active={params.has_signals === true && !params.signal_type}
            onClick={() =>
              onChange({
                has_signals: params.has_signals ? undefined : true,
                signal_type: undefined,
              })
            }
          />
        </div>
      </FilterSection>

      {/* ── Sort ─────────────────────────────────────────────────────── */}
      <FilterSection label="Sort by">
        <div className="flex flex-wrap gap-1.5">
          {SORT_FIELDS.map((f) => (
            <FilterChip
              key={f.value}
              label={f.label}
              active={params.sort_by === f.value}
              onClick={() => onChange({ sort_by: f.value })}
            />
          ))}
        </div>
      </FilterSection>

      {/* ── Order ────────────────────────────────────────────────────── */}
      <FilterSection label="Order">
        <div className="flex gap-1.5">
          <FilterChip
            label="Desc ↓"
            active={!params.order || params.order === "desc"}
            onClick={() => onChange({ order: "desc" })}
          />
          <FilterChip
            label="Asc ↑"
            active={params.order === "asc"}
            onClick={() => onChange({ order: "asc" })}
          />
        </div>
      </FilterSection>

      {/* ── Min Score ────────────────────────────────────────────────── */}
      <FilterSection label={`Min Score: ${params.min_score ?? 0}`}>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={params.min_score ?? 0}
          onChange={(e) =>
            onChange({
              min_score: Number(e.target.value) || undefined,
            })
          }
          className="w-full accent-amber-400"
        />
        <div className="mt-0.5 flex justify-between text-[9px] text-zinc-700">
          <span>0</span>
          <span>50</span>
          <span>100</span>
        </div>
      </FilterSection>

      {/* ── Min Confidence ───────────────────────────────────────────── */}
      <FilterSection
        label={`Min Confidence: ${params.min_confidence != null ? Math.round(params.min_confidence * 100) : 0}%`}
      >
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={params.min_confidence ?? 0}
          onChange={(e) =>
            onChange({
              min_confidence: Number(e.target.value) || undefined,
            })
          }
          className="w-full accent-indigo-400"
        />
        <div className="mt-0.5 flex justify-between text-[9px] text-zinc-700">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </FilterSection>

      {/* ── Min Mentions ─────────────────────────────────────────────── */}
      <FilterSection label="Min Mentions">
        <input
          type="number"
          min={0}
          step={1}
          placeholder="0"
          value={params.min_mentions ?? ""}
          onChange={(e) =>
            onChange({
              min_mentions: e.target.value
                ? Number(e.target.value)
                : undefined,
            })
          }
          className="h-7 w-full rounded border border-zinc-700 bg-zinc-900 px-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
        />
      </FilterSection>

      {/* ── Note ─────────────────────────────────────────────────────── */}
      <FilterSection label="Contains Note">
        <input
          type="text"
          placeholder="e.g. Vanilla"
          value={params.note ?? ""}
          onChange={(e) =>
            onChange({ note: e.target.value || undefined })
          }
          className="h-7 w-full rounded border border-zinc-700 bg-zinc-900 px-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
        />
        {params.note && (
          <button
            onClick={() => onChange({ note: undefined })}
            className="mt-1 text-[9px] text-zinc-600 hover:text-zinc-400"
          >
            Clear
          </button>
        )}
      </FilterSection>
    </div>
  );
}
