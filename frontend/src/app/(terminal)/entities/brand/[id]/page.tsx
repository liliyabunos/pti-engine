"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { clsx } from "clsx";

import { fetchBrandEntity } from "@/lib/api/entities";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { PanelDivider } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";
import { ErrorState } from "@/components/primitives/ErrorState";
import { EmptyState } from "@/components/primitives/EmptyState";
import { SignalTimeline } from "@/components/entity/SignalTimeline";
import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { fmtScore, fmtGrowth } from "@/lib/formatters";
import type { BrandPerfumeRow } from "@/lib/api/types";

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

function LinkedPerfumesTable({ rows }: { rows: BrandPerfumeRow[] }) {
  const router = useRouter();

  if (!rows.length) {
    return (
      <EmptyState message="No tracked perfumes" detail="Perfumes appear here once mentions are detected." />
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
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500 w-20">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.entity_id ?? i}
              onClick={
                row.entity_id
                  ? () => router.push(`/entities/perfume/${encodeURIComponent(row.entity_id!)}`)
                  : undefined
              }
              className={clsx(
                "border-b border-zinc-800/40 transition-colors",
                row.entity_id
                  ? "group cursor-pointer hover:bg-zinc-800/30"
                  : "opacity-60",
              )}
            >
              <td className="px-3 py-2">
                <span
                  className={clsx(
                    "block max-w-[280px] truncate text-xs",
                    row.entity_id
                      ? "text-zinc-200 group-hover:text-amber-300"
                      : "text-zinc-400",
                  )}
                >
                  {row.canonical_name}
                </span>
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px] text-zinc-300">
                {fmtScore(row.latest_score)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[11px] text-zinc-500">
                {row.mention_count != null ? Math.round(row.mention_count) : "—"}
              </td>
              <td className="px-3 py-2">
                {row.has_activity_today ? (
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
    </div>
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

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["brand-entity", decoded],
    queryFn: () => fetchBrandEntity(decoded, { history_days: 30 }),
    staleTime: 60_000,
  });

  const isTracked = data?.state !== "catalog_only";
  const latestSignal = data?.recent_signals?.[0]?.signal_type ?? null;

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
              <div className="flex items-start gap-3 rounded border border-zinc-700/50 bg-zinc-900/60 px-4 py-3">
                <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  Catalog
                </span>
                <p className="text-[11px] text-zinc-500">
                  This brand is known to the catalog but has not appeared in
                  any ingested content yet. Market data will populate
                  automatically once mentions are detected.
                </p>
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
                  </div>
                  <h1 className="mt-1 text-xl font-bold leading-tight text-zinc-100">
                    {data.canonical_name}
                  </h1>
                </div>

                {isTracked && (
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
                  value={data.top_perfumes.length}
                />
                <KpiBox
                  label="Active today"
                  value={data.active_perfume_count}
                />
              </div>
            </TerminalPanel>

            {/* ── Top tracked perfumes ────────────────────────────────────── */}
            <TerminalPanel noPad>
              <div className="p-4">
                <SectionHeader
                  title="Tracked Perfumes"
                  subtitle={
                    data.top_perfumes.length
                      ? `top ${data.top_perfumes.length} by score`
                      : undefined
                  }
                />
              </div>
              <PanelDivider />
              <LinkedPerfumesTable rows={data.top_perfumes} />
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
