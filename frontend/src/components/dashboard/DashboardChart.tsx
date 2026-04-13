"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from "recharts";
import { ChartContainer } from "@/components/primitives/ChartContainer";
import { fmtScore } from "@/lib/formatters";
import type { TopMoverRow } from "@/lib/api/types";

interface DashboardChartProps {
  movers: TopMoverRow[];
  maxItems?: number;
}

export function DashboardChart({ movers, maxItems = 10 }: DashboardChartProps) {
  const data = movers.slice(0, maxItems).map((m) => ({
    name: m.ticker,
    score: m.composite_market_score,
    signal: m.latest_signal,
  }));

  return (
    <ChartContainer height={180}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="name"
            tick={{ fill: "#71717a", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#52525b", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={28}
            tickFormatter={(v: number) => fmtScore(v)}
          />
          <Tooltip
            contentStyle={{
              background: "#18181b",
              border: "1px solid #3f3f46",
              borderRadius: 4,
              fontSize: 11,
              color: "#e4e4e7",
            }}
            formatter={(value) => [fmtScore(Number(value)), "Score"]}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
          />
          <Bar dataKey="score" radius={[2, 2, 0, 0]}>
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={
                  entry.signal === "breakout"
                    ? "#f59e0b"
                    : entry.signal === "acceleration_spike"
                      ? "#38bdf8"
                      : "#6366f1"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}
