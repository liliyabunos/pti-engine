import { KpiCard } from "@/components/primitives/KpiCard";
import { fmtScore, fmtConfidence } from "@/lib/formatters";
import type { DashboardKPIs } from "@/lib/api/types";

interface KpiStripProps {
  kpis: DashboardKPIs;
}

export function KpiStrip({ kpis }: KpiStripProps) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
      <KpiCard
        label="Brands"
        value={kpis.tracked_brands}
        sub="tracked"
      />
      <KpiCard
        label="Perfumes"
        value={kpis.tracked_perfumes}
        sub="tracked"
      />
      <KpiCard
        label="Movers"
        value={kpis.active_movers}
        sub="active today"
        accent="green"
      />
      <KpiCard
        label="Breakouts"
        value={kpis.breakout_signals_today}
        sub="today"
        accent={kpis.breakout_signals_today > 0 ? "amber" : "default"}
      />
      <KpiCard
        label="Accel Spikes"
        value={kpis.acceleration_signals_today}
        sub="today"
        accent={kpis.acceleration_signals_today > 0 ? "sky" : "default"}
      />
      <KpiCard
        label="Signals"
        value={kpis.total_signals_today}
        sub="total today"
      />
      <KpiCard
        label="Avg Score"
        value={fmtScore(kpis.avg_market_score_today)}
        sub="market avg"
      />
      <KpiCard
        label="Avg Confidence"
        value={fmtConfidence(kpis.avg_confidence_today)}
        sub={kpis.as_of_date ?? undefined}
      />
    </div>
  );
}
