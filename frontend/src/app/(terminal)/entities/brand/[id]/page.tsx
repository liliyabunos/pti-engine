"use client";

import { useQuery } from "@tanstack/react-query";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { clsx } from "clsx";

import { fetchBrandEntity, startTracking } from "@/lib/api/entities";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { PanelDivider } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";
import { ErrorState } from "@/components/primitives/ErrorState";
import { EmptyState } from "@/components/primitives/EmptyState";
import { SignalTimeline } from "@/components/entity/SignalTimeline";
import { AddToWatchlistModal } from "@/components/entity/AddToWatchlistModal";
import { CreateAlertModal } from "@/components/alerts/CreateAlertModal";
import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { TrendStateBadge } from "@/components/primitives/TrendStateBadge";
import { fmtScore, fmtGrowth } from "@/lib/formatters";
import type { BrandPerfumeRow, DriverRow } from "@/lib/api/types";
import { WhyTrending } from "@/components/entity/WhyTrending";

// ---------------------------------------------------------------------------
// State badge
// ---------------------------------------------------------------------------

function StateBadge({ state }: { state: string }) {
  if (state === "active")
    return (
      <span className="inline-flex items-center rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-400">
        Active
      </span>
    );
  if (state === "tracked")
    return (
      <span className="inline-flex items-center rounded border border-emerald-800 bg-emerald-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-500">
        Tracked
      </span>
    );
  return (
    <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500">
      Catalog
    </span>
  );
}

// ---------------------------------------------------------------------------
// Metric card (for the brand KPI row)
// ---------------------------------------------------------------------------

function KpiBox({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-center">
      <p className="text-lg font-bold tabular-nums text-zinc-100">{value}</p>
      <p className="mt-0.5 text-[9px] uppercase tracking-wider text-zinc-600">{label}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Linked perfumes table
// ---------------------------------------------------------------------------

function LinkedPerfumesTable({ rows, totalCount }: { rows: BrandPerfumeRow[]; totalCount: number }) {
  const router = useRouter();

  if (!rows.length) {
    return (
      <EmptyState message="No perfumes in catalog" detail="No perfumes found for this brand in the knowledge base." />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-800">
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Name
            </th>
            <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-wider text-zinc-500 w-20">
              Score
            </th>
            <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-wider text-zinc-500 w-20">
              Mentions
            </th>
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500 w-24">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.entity_id ?? `${row.canonical_name}-${i}`}
              onClick={
                row.entity_id
                  ? () => router.push(`/entities/perfume/${encodeURIComponent(row.entity_id!)}`)
                  : undefined
              }
              className={clsx(
                "border-b border-zinc-800/40 transition-colors",
                row.entity_id
                  ? "group cursor-pointer hover:bg-zinc-800/30"
                  : "opacity-50",
              )}
            >
              <td className="px-3 py-2">
                <span
                  className={clsx(
                    "block max-w-[280px] truncate text-xs",
                    row.entity_id
                      ? "text-zinc-200 group-hover:text-amber-300"
                      : "text-zinc-500",
                  )}
                >
                  {row.canonical_name}
                </span>
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px] text-zinc-300">
                {row.latest_score != null ? fmtScore(row.latest_score) : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px] text-zinc-500">
                {row.mention_count != null ? Math.round(row.mention_count) : "—"}
              </td>
              <td className="px-3 py-2">
                {!row.entity_id ? (
                  <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-600">
                    In Catalog
                  </span>
                ) : row.has_activity_today ? (
                  <span className="inline-flex items-center rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-400">
                    Active
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded border border-emerald-800 bg-emerald-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-600">
                    Tracked
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {totalCount > rows.length && (
        <p className="px-3 py-2 text-[10px] text-zinc-600">
          Showing {rows.length} of {totalCount.toLocaleString()} catalog perfumes
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top Drivers (Phase I4)
// ---------------------------------------------------------------------------

function platformLabel(platform: string | null | undefined): string {
  if (!platform) return "—";
  if (platform === "youtube") return "YT";
  if (platform === "reddit") return "RD";
  return platform.slice(0, 2).toUpperCase();
}

function TopDrivers({ drivers }: { drivers: DriverRow[] }) {
  if (!drivers.length) return null;
  return (
    <TerminalPanel noPad>
      <div className="p-4">
        <SectionHeader
          title="Top Drivers"
          subtitle={`${drivers.length} highest-impact content items`}
        />
      </div>
      <PanelDivider />
      <div className="divide-y divide-zinc-800/40">
        {drivers.map((d, i) => (
          <div key={d.source_url ?? i} className="flex items-start gap-3 px-4 py-2.5">
            <span className="mt-0.5 w-4 shrink-0 text-[10px] tabular-nums text-zinc-600">
              {i + 1}
            </span>
            <span className="mt-0.5 shrink-0 rounded border border-zinc-700 bg-zinc-800/40 px-1 py-0.5 text-[8px] font-bold uppercase tracking-wide text-zinc-400">
              {platformLabel(d.source_platform)}
            </span>
            <div className="min-w-0 flex-1">
              {d.source_url ? (
                <a
                  href={d.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block truncate text-[11px] text-blue-400 hover:underline"
                >
                  {d.source_name ?? d.source_url}
                </a>
              ) : (
                <span className="block truncate text-[11px] text-zinc-400">
                  {d.source_name ?? "Unknown source"}
                </span>
              )}
              {d.occurred_at && (
                <span className="text-[9px] text-zinc-600">
                  {d.occurred_at.slice(0, 10)}
                </span>
              )}
            </div>
            <div className="shrink-0 text-right">
              {d.views != null && (
                <p className="text-[10px] tabular-nums text-zinc-300">
                  {d.views >= 1_000_000
                    ? `${(d.views / 1_000_000).toFixed(1)}M`
                    : d.views >= 1_000
                    ? `${(d.views / 1_000).toFixed(0)}K`
                    : String(d.views)}{" "}
                  views
                </p>
              )}
              {d.source_score != null && (
                <p className="text-[9px] tabular-nums text-zinc-600">
                  score {d.source_score.toFixed(2)}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function BrandEntityPage({ params }: PageProps) {
  const { id } = use(params);
  const decoded = decodeURIComponent(id);
  const router = useRouter();

  const [showWatchModal, setShowWatchModal] = useState(false);
  const [showAlertModal, setShowAlertModal] = useState(false);
  const [isStartingTracking, setIsStartingTracking] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["brand-entity", decoded],
    queryFn: () => fetchBrandEntity(decoded, { history_days: 30 }),
    staleTime: 60_000,
  });

  const isTracked = data?.state !== "catalog_only";
  const latestSignal = data?.recent_signals?.[0]?.signal_type ?? null;
  // catalog_perfumes includes all KB entries; entity_id non-null = tracked in market
  const catalogRows = data?.catalog_perfumes ?? data?.top_perfumes ?? [];
  const trackedCount = catalogRows.filter((p) => p.entity_id != null).length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title={data?.canonical_name ?? decoded}
        subtitle={data ? `Brand · ${data.perfume_count.toLocaleString()} perfumes in catalog` : undefined}
        actions={
          <button
            onClick={() => router.back()}
            className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300"
          >
            <ArrowLeft size={12} />
            Back
          </button>
        }
      />

      {showWatchModal && data && isTracked && (
        <AddToWatchlistModal
          entityId={data.id}
          entityType={data.entity_type}
          canonicalName={data.canonical_name}
          onClose={() => setShowWatchModal(false)}
        />
      )}

      {showAlertModal && data && isTracked && (
        <CreateAlertModal
          prefill={{
            entity_id: data.id,
            entity_type: data.entity_type,
            canonical_name: data.canonical_name,
          }}
          onClose={() => setShowAlertModal(false)}
          onCreated={() => setShowAlertModal(false)}
        />
      )}

      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="space-y-4 p-4">
            <LoadingSkeleton rows={3} rowHeight={32} />
            <LoadingSkeleton rows={6} rowHeight={20} />
          </div>
        )}

        {isError && (
          <div className="p-5">
            <ErrorState message={String(error)} onRetry={() => refetch()} />
          </div>
        )}

        {data && (
          <div className="space-y-4 p-4">
            {/* ── Catalog quiet state ─────────────────────────────────────── */}
            {data.state === "catalog_only" && (
              <div className="flex items-start justify-between gap-3 rounded border border-zinc-700/50 bg-zinc-900/60 px-4 py-3">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                    Catalog
                  </span>
                  <p className="text-[11px] text-zinc-500">
                    This brand is known to the catalog but has not appeared in
                    any ingested content yet. Market data will populate
                    automatically once mentions are detected.
                  </p>
                </div>
                {data.resolver_id && (
                  <button
                    disabled={isStartingTracking}
                    onClick={async () => {
                      if (!data.resolver_id) return;
                      setIsStartingTracking(true);
                      try {
                        const result = await startTracking(data.resolver_id, "brand");
                        router.replace(`/entities/brand/${encodeURIComponent(result.entity_id)}`);
                      } finally {
                        setIsStartingTracking(false);
                      }
                    }}
                    className="shrink-0 inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-40"
                  >
                    {isStartingTracking ? "Starting…" : "Start Tracking"}
                  </button>
                )}
              </div>
            )}

            {/* ── Brand header ───────────────────────────────────────────── */}
            <TerminalPanel noPad>
              <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {data.ticker && (
                      <span className="font-mono text-sm font-bold text-amber-400">
                        {data.ticker}
                      </span>
                    )}
                    <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-800/60 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                      Brand
                    </span>
                    <StateBadge state={data.state} />
                    {latestSignal && <SignalBadge type={latestSignal} />}
                    {data.trend_state && <TrendStateBadge state={data.trend_state} />}
                  </div>
                  <h1 className="mt-1 text-xl font-bold leading-tight text-zinc-100">
                    {data.canonical_name}
                  </h1>
                </div>

                {isTracked && (
                  <div className="flex shrink-0 flex-col items-end gap-3">
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-2xl font-bold tabular-nums leading-none text-zinc-100">
                          {fmtScore(data.latest_score)}
                        </p>
                        <p className="mt-0.5 text-[9px] uppercase tracking-wider text-zinc-600">
                          Market Score
                        </p>
                      </div>
                      <div className="text-right">
                        <DeltaBadge
                          value={data.latest_growth}
                          formatted={fmtGrowth(data.latest_growth)}
                          size="md"
                        />
                        <p className="mt-1 text-[9px] uppercase tracking-wider text-zinc-600">
                          Growth
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => setShowWatchModal(true)}
                        className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
                      >
                        Watch
                      </button>
                      <button
                        onClick={() => setShowAlertModal(true)}
                        className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
                      >
                        Alert
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <PanelDivider />

              {/* KPI row */}
              <div className="grid grid-cols-3 gap-3 px-5 py-4">
                <KpiBox
                  label="Catalog perfumes"
                  value={data.perfume_count.toLocaleString()}
                />
                <KpiBox
                  label="Tracked"
                  value={trackedCount}
                />
                <KpiBox
                  label="Active today"
                  value={data.active_perfume_count}
                />
              </div>
            </TerminalPanel>

            {/* ── Catalog perfumes ────────────────────────────────────────── */}
            <TerminalPanel noPad>
              <div className="p-4">
                <SectionHeader
                  title="Perfumes"
                  subtitle={
                    catalogRows.length
                      ? `${catalogRows.length < data.perfume_count ? `top ${catalogRows.length} of ${data.perfume_count.toLocaleString()}` : catalogRows.length.toLocaleString()} · tracked shown first`
                      : undefined
                  }
                />
              </div>
              <PanelDivider />
              <LinkedPerfumesTable rows={catalogRows} totalCount={data.perfume_count} />
            </TerminalPanel>

            {/* ── Top notes & accords ─────────────────────────────────────── */}
            {(data.top_notes?.length > 0 || data.top_accords?.length > 0) && (
              <TerminalPanel>
                <SectionHeader
                  title="Notes & Accords"
                  subtitle="aggregated across brand portfolio"
                />
                <div className="mt-3 space-y-3">
                  {data.top_accords?.length > 0 && (
                    <div>
                      <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
                        Top Accords
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {data.top_accords.map((a) => (
                          <span
                            key={a}
                            className="inline-flex rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[10px] text-zinc-400"
                          >
                            {a}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {data.top_notes?.length > 0 && (
                    <div>
                      <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
                        Top Notes
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {data.top_notes.map((n) => (
                          <span
                            key={n}
                            className="inline-flex rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[10px] text-zinc-400"
                          >
                            {n}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </TerminalPanel>
            )}

            {/* ── Top Drivers (Phase I4, tracked only) ───────────────────── */}
            {isTracked && (data.top_drivers?.length ?? 0) > 0 && (
              <TopDrivers drivers={data.top_drivers!} />
            )}

            {/* ── Why It's Trending (Phase I5) ────────────────────────────── */}
            <WhyTrending
              top_topics={data.top_topics}
              top_queries={data.top_queries}
              top_subreddits={data.top_subreddits}
            />

            {/* ── Signal timeline (tracked only) ─────────────────────────── */}
            {isTracked && data.recent_signals.length > 0 && (
              <TerminalPanel noPad>
                <div className="p-4">
                  <SectionHeader
                    title="Signal Timeline"
                    subtitle={`${data.recent_signals.length} events`}
                  />
                </div>
                <PanelDivider />
                <div className="max-h-72 overflow-y-auto px-2 py-2">
                  <SignalTimeline signals={data.recent_signals} />
                </div>
              </TerminalPanel>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
