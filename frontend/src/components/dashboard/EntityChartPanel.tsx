"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { clsx } from "clsx";

import { fetchEntity } from "@/lib/api/entities";
import { ChartContainer } from "@/components/primitives/ChartContainer";
import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";
import { ErrorState } from "@/components/primitives/ErrorState";
import { EmptyState } from "@/components/primitives/EmptyState";
import {
  fmtScore,
  fmtDate,
  fmtGrowth,
  fmtCount,
  fmtConfidence,
  fmtMomentum,
} from "@/lib/formatters";
import type { SnapshotRow, TopMoverRow } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mini entity header strip shown above the chart
// ---------------------------------------------------------------------------

interface EntityMiniHeaderProps {
  mover: TopMoverRow;
}

function EntityMiniHeader({ mover }: EntityMiniHeaderProps) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-4 py-2.5">
      {/* Left: identity */}
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="font-mono text-[11px] font-bold text-amber-400">
          {mover.ticker}
        </span>
        <span className="truncate text-xs font-semibold text-zinc-200">
          {mover.canonical_name}
        </span>
        {mover.brand_name && (
          <span className="hidden text-[10px] text-zinc-600 sm:block">
            {mover.brand_name}
          </span>
        )}
      </div>

      {/* Right: score + delta + signal + entity link */}
      <div className="flex shrink-0 items-center gap-3">
        <div className="text-right">
          <span className="block text-sm font-bold tabular-nums text-zinc-100">
            {fmtScore(mover.composite_market_score)}
          </span>
        </div>
        <DeltaBadge
          value={mover.growth_rate}
          formatted={fmtGrowth(mover.growth_rate)}
        />
        {mover.latest_signal && (
          <SignalBadge type={mover.latest_signal} />
        )}
        <Link
          href={`/entities/${mover.entity_type ?? "perfume"}/${encodeURIComponent(mover.entity_id)}`}
          className="flex items-center gap-0.5 text-[10px] text-zinc-600 hover:text-amber-400"
          title="Open entity page"
        >
          <ArrowUpRight size={12} />
        </Link>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Metric stat row below the chart
// ---------------------------------------------------------------------------

function StatRow({ history }: { history: SnapshotRow[] }) {
  if (!history.length) return null;

  const latest = history[history.length - 1];
  const prev = history.length > 1 ? history[history.length - 2] : null;

  const scoreChange =
    prev != null
      ? latest.composite_market_score - prev.composite_market_score
      : null;

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-zinc-800 px-4 py-2">
      <StatCell label="Score" value={fmtScore(latest.composite_market_score)} />
      <StatCell label="Mentions" value={fmtCount(latest.mention_count)} />
      {latest.confidence_avg != null && (
        <StatCell label="Conf." value={fmtConfidence(latest.confidence_avg)} />
      )}
      {latest.momentum != null && (
        <StatCell label="Mom." value={fmtMomentum(latest.momentum)} />
      )}
      {scoreChange != null && (
        <StatCell
          label="Δ Score"
          value={scoreChange >= 0 ? `+${scoreChange.toFixed(1)}` : scoreChange.toFixed(1)}
          color={scoreChange > 0 ? "text-emerald-400" : scoreChange < 0 ? "text-red-400" : "text-zinc-500"}
        />
      )}
      <StatCell label="As of" value={fmtDate(latest.date)} />
    </div>
  );
}

function StatCell({
  label,
  value,
  color = "text-zinc-300",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[9px] uppercase tracking-widest text-zinc-600">
        {label}
      </span>
      <span className={clsx("text-[11px] font-semibold tabular-nums", color)}>
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

interface TooltipPayload {
  value: number;
  dataKey: string;
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;

  const score = payload.find((p) => p.dataKey === "score");
  const mentions = payload.find((p) => p.dataKey === "mentions");
  const confidence = payload.find((p) => p.dataKey === "confidence");

  return (
    <div className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 shadow-xl">
      <p className="mb-1.5 text-[10px] font-semibold text-zinc-400">
        {fmtDate(label)}
      </p>
      {score && (
        <p className="text-xs">
          <span className="text-zinc-500">Score </span>
          <span className="font-semibold text-amber-300">
            {fmtScore(score.value)}
          </span>
        </p>
      )}
      {mentions && (
        <p className="text-xs">
          <span className="text-zinc-500">Mentions </span>
          <span className="font-semibold text-zinc-200">
            {fmtCount(mentions.value)}
          </span>
        </p>
      )}
      {confidence && (
        <p className="text-xs">
          <span className="text-zinc-500">Conf. </span>
          <span className="font-semibold text-zinc-200">
            {fmtConfidence(confidence.value)}
          </span>
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface EntityChartPanelProps {
  /** The currently selected mover row — used for the mini-header */
  selectedMover: TopMoverRow | null;
}

export function EntityChartPanel({ selectedMover }: EntityChartPanelProps) {
  const entityId = selectedMover?.entity_id ?? null;

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["entity-chart", entityId],
    queryFn: () => fetchEntity(entityId!, { history_days: 30 }),
    enabled: entityId != null,
    staleTime: 60_000,
  });

  // No entity selected yet
  if (!selectedMover) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center">
        <EmptyState
          compact
          message="Select a mover to view chart"
          detail="Click any row in the top movers table"
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Mini entity header */}
      <EntityMiniHeader mover={selectedMover} />

      {/* Chart area */}
      <div className="flex-1 px-4 py-3">
        {isLoading && <LoadingSkeleton rows={4} rowHeight={24} />}

        {isError && (
          <ErrorState
            message={String(error)}
            onRetry={() => refetch()}
          />
        )}

        {data && !isLoading && (
          <>
            {data.history.length === 0 ? (
              <EmptyState compact message="No historical data available" />
            ) : (
              <ChartContainer height={200}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={data.history.map((r) => ({
                      date: r.date,
                      score: r.composite_market_score,
                      mentions: r.mention_count,
                      confidence: r.confidence_avg,
                    }))}
                    margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
                  >
                    <CartesianGrid
                      stroke="#27272a"
                      strokeDasharray="3 3"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "#71717a", fontSize: 9 }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={fmtDate}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      yAxisId="score"
                      tick={{ fill: "#52525b", fontSize: 9 }}
                      axisLine={false}
                      tickLine={false}
                      width={28}
                      tickFormatter={(v: number) => fmtScore(v)}
                    />
                    <Tooltip content={<ChartTooltip />} />
                    {/* Score — primary line */}
                    <Line
                      yAxisId="score"
                      type="monotone"
                      dataKey="score"
                      stroke="#f59e0b"
                      strokeWidth={1.5}
                      dot={false}
                      activeDot={{ r: 3, fill: "#f59e0b" }}
                    />
                    {/* Mention count — secondary dashed line, same axis */}
                    <Line
                      yAxisId="score"
                      type="monotone"
                      dataKey="mentions"
                      stroke="#6366f1"
                      strokeWidth={1}
                      strokeDasharray="3 3"
                      dot={false}
                      activeDot={{ r: 2, fill: "#6366f1" }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </ChartContainer>
            )}
          </>
        )}
      </div>

      {/* Stat row */}
      {data?.history && data.history.length > 0 && (
        <StatRow history={data.history} />
      )}

      {/* Chart legend */}
      <div className="flex items-center gap-4 border-t border-zinc-800/60 px-4 py-1.5">
        <LegendDot hex="#f59e0b" label="Score" />
        <LegendDot hex="#818cf8" label="Mentions" dashed />
      </div>
    </div>
  );
}

function LegendDot({
  hex,
  label,
  dashed,
}: {
  hex: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span className="flex items-center gap-1.5">
      {dashed ? (
        <span
          className="w-5"
          style={{ height: 1.5, borderTop: `1.5px dashed ${hex}` }}
        />
      ) : (
        <span
          className="w-5 rounded-full"
          style={{ height: 2, background: hex }}
        />
      )}
      <span className="text-[9px] text-zinc-600">{label}</span>
    </span>
  );
}
