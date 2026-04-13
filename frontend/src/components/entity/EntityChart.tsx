"use client";

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
import { ChartContainer } from "@/components/primitives/ChartContainer";
import { EmptyState } from "@/components/primitives/EmptyState";
import { fmtScore, fmtDate, fmtCount, fmtMomentum } from "@/lib/formatters";
import type { SnapshotRow } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Metric config
// ---------------------------------------------------------------------------

export type EntityChartMetric =
  | "composite_market_score"
  | "mention_count"
  | "momentum";

const METRIC_CONFIG: Record<
  EntityChartMetric,
  {
    label: string;
    color: string;
    formatter: (v: number) => string;
    yWidth: number;
  }
> = {
  composite_market_score: {
    label: "Market Score",
    color: "#f59e0b",
    formatter: fmtScore,
    yWidth: 36,
  },
  mention_count: {
    label: "Mentions",
    color: "#6366f1",
    formatter: (v) => fmtCount(v),
    yWidth: 40,
  },
  momentum: {
    label: "Momentum",
    color: "#38bdf8",
    formatter: (v) => fmtMomentum(v),
    yWidth: 40,
  },
};

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

interface TooltipPayload {
  value: number;
}

function ChartTooltip({
  active,
  payload,
  label,
  metricLabel,
  formatter,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
  metricLabel: string;
  formatter: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 shadow-xl">
      <p className="mb-1.5 text-[10px] font-semibold text-zinc-400">
        {fmtDate(label)}
      </p>
      <p className="text-xs">
        <span className="text-zinc-500">{metricLabel} </span>
        <span className="font-semibold text-zinc-100">
          {formatter(payload[0].value)}
        </span>
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EntityChart
// ---------------------------------------------------------------------------

interface EntityChartProps {
  history: SnapshotRow[];
  metric?: EntityChartMetric;
}

export function EntityChart({
  history,
  metric = "composite_market_score",
}: EntityChartProps) {
  if (!history.length) {
    return <EmptyState message="No chart data available" />;
  }

  const config = METRIC_CONFIG[metric];

  const data = history.map((row) => ({
    date: row.date,
    value: row[metric] ?? 0,
  }));

  // Average reference line
  const values = data.map((d) => d.value);
  const avg = values.reduce((a, b) => a + b, 0) / values.length;

  return (
    <ChartContainer height={240}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
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
            tick={{ fill: "#52525b", fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            width={config.yWidth}
            tickFormatter={config.formatter}
          />
          <Tooltip
            content={
              <ChartTooltip
                metricLabel={config.label}
                formatter={config.formatter}
              />
            }
            cursor={{ stroke: "#52525b", strokeWidth: 1 }}
          />
          {/* Average reference line */}
          <ReferenceLine
            y={avg}
            stroke="#3f3f46"
            strokeDasharray="4 4"
            strokeWidth={1}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={config.color}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: config.color }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}
