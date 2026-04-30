import { KpiCard } from "@/components/primitives/KpiCard";
import { fmtScore, fmtConfidence } from "@/lib/formatters";
import type { DashboardKPIs, CatalogCounts } from "@/lib/api/types";

interface KpiStripProps {
  kpis: DashboardKPIs;
  /** When provided, shows catalog-scale Known Brands / Known Perfumes instead of tracked counts. */
  catalogCounts?: CatalogCounts | null;
}

export function KpiStrip({ kpis, catalogCounts }: KpiStripProps) {
  const knownBrands = catalogCounts?.known_brands ?? null;
  const knownPerfumes = catalogCounts?.known_perfumes ?? null;
  const activeToday = catalogCounts?.active_today ?? null;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
      {/* Known Brands — catalog scale if available, else tracked count */}
      <KpiCard
        label="Known Brands"
        value={
          knownBrands != null
            ? knownBrands.toLocaleString()
            : kpis.tracked_brands
        }
        sub={
          knownBrands != null
            ? `${kpis.tracked_brands} tracked`
            : "tracked"
        }
        href="/screener?mode=catalog_brands"
      />

      {/* Known Perfumes — catalog scale if available, else tracked count */}
      <KpiCard
        label="Known Perfumes"
        value={
          knownPerfumes != null
            ? knownPerfumes.toLocaleString()
            : kpis.tracked_perfumes
        }
        sub={
          knownPerfumes != null
            ? `${kpis.tracked_perfumes} tracked`
            : "tracked"
        }
        href="/screener?mode=catalog_perfumes"
      />

      {/* Active Today — from catalog counts if available, else active_movers */}
      <KpiCard
        label="Active Today"
        value={activeToday != null ? activeToday : kpis.active_movers}
        sub="with signal data"
        accent="green"
        href="/screener"
      />

      <KpiCard
        label="Breakouts"
        value={kpis.breakout_signals_today}
        sub="today"
        accent={kpis.breakout_signals_today > 0 ? "amber" : "default"}
        href="/screener?signal_type=breakout&has_signals=true"
      />
      <KpiCard
        label="Accel Spikes"
        value={kpis.acceleration_signals_today}
        sub="today"
        accent={kpis.acceleration_signals_today > 0 ? "sky" : "default"}
        href="/screener?signal_type=acceleration_spike&has_signals=true"
      />
      <KpiCard
        label="Signals"
        value={kpis.total_signals_today}
        sub="total today"
        href="/screener?has_signals=true"
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
