"use client";

import { useQuery } from "@tanstack/react-query";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { fetchPerfumeEntity, startTracking } from "@/lib/api/entities";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { PanelDivider } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";
import { ErrorState } from "@/components/primitives/ErrorState";
import { EntityChart } from "@/components/entity/EntityChart";
import { SignalTimeline } from "@/components/entity/SignalTimeline";
import { RecentMentions } from "@/components/entity/RecentMentions";
import { AddToWatchlistModal } from "@/components/entity/AddToWatchlistModal";
import { CreateAlertModal } from "@/components/alerts/CreateAlertModal";
import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { fmtScore, fmtGrowth, fmtCount, fmtConfidence, fmtMomentum } from "@/lib/formatters";
import type { EntityChartMetric } from "@/components/entity/EntityChart";
import type { SimilarPerfumeRow } from "@/lib/api/types";

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
// Notes section
// ---------------------------------------------------------------------------

function NotesPill({ name }: { name: string }) {
  return (
    <span className="inline-flex rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[10px] text-zinc-400">
      {name}
    </span>
  );
}

function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null;
  const label = source === "fragrantica" ? "Fragrantica" : "Parfumo Dataset";
  const color =
    source === "fragrantica"
      ? "border-violet-800 bg-violet-950/40 text-violet-400"
      : "border-zinc-700 bg-zinc-800/40 text-zinc-500";
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${color}`}
    >
      {label}
    </span>
  );
}

function NotesSection({
  top,
  middle,
  base,
  accords,
  source,
}: {
  top: string[];
  middle: string[];
  base: string[];
  accords: string[];
  source?: string | null;
}) {
  const hasNotes = top.length || middle.length || base.length;
  const hasAccords = accords.length > 0;
  if (!hasNotes && !hasAccords) return null;

  return (
    <TerminalPanel>
      <div className="flex items-center justify-between">
        <SectionHeader title="Notes & Accords" />
        <SourceBadge source={source} />
      </div>
      <div className="mt-3 space-y-3">
        {hasAccords && (
          <div>
            <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
              Accords
            </p>
            <div className="flex flex-wrap gap-1">
              {accords.map((a) => (
                <NotesPill key={a} name={a} />
              ))}
            </div>
          </div>
        )}
        {top.length > 0 && (
          <div>
            <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
              Top notes
            </p>
            <div className="flex flex-wrap gap-1">
              {top.map((n) => (
                <NotesPill key={n} name={n} />
              ))}
            </div>
          </div>
        )}
        {middle.length > 0 && (
          <div>
            <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
              Middle notes
            </p>
            <div className="flex flex-wrap gap-1">
              {middle.map((n) => (
                <NotesPill key={n} name={n} />
              ))}
            </div>
          </div>
        )}
        {base.length > 0 && (
          <div>
            <p className="mb-1.5 text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
              Base notes
            </p>
            <div className="flex flex-wrap gap-1">
              {base.map((n) => (
                <NotesPill key={n} name={n} />
              ))}
            </div>
          </div>
        )}
      </div>
    </TerminalPanel>
  );
}

function SimilarByNotes({ rows }: { rows: SimilarPerfumeRow[] }) {
  const router = useRouter();
  if (!rows.length) return null;
  return (
    <TerminalPanel noPad>
      <div className="p-4">
        <SectionHeader
          title="Similar by Notes"
          subtitle={`${rows.length} perfumes sharing ingredients`}
        />
      </div>
      <PanelDivider />
      <div className="divide-y divide-zinc-800/40">
        {rows.map((r) => {
          const href = r.entity_id
            ? `/entities/perfume/${encodeURIComponent(r.entity_id)}`
            : r.resolver_id
            ? `/entities/perfume/${r.resolver_id}`
            : null;
          return (
            <div
              key={r.resolver_id ?? r.canonical_name}
              onClick={href ? () => router.push(href) : undefined}
              className={`flex items-center justify-between px-4 py-2 transition-colors ${href ? "cursor-pointer hover:bg-zinc-800/30" : ""}`}
            >
              <div className="min-w-0">
                <span className="block truncate text-xs text-zinc-200">
                  {r.canonical_name}
                </span>
                {r.brand_name && (
                  <span className="block text-[10px] text-zinc-600">
                    {r.brand_name}
                  </span>
                )}
              </div>
              <span className="ml-4 shrink-0 text-[10px] tabular-nums text-zinc-500">
                {r.shared_notes} shared
              </span>
            </div>
          );
        })}
      </div>
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Metric row helper
// ---------------------------------------------------------------------------

function MetricRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-zinc-800/60 px-4 py-2 last:border-b-0">
      <span className="text-[10px] uppercase tracking-wider text-zinc-600">{label}</span>
      <span className="text-right text-xs font-semibold tabular-nums text-zinc-200">{value}</span>
    </div>
  );
}

const CHART_TABS: { key: EntityChartMetric; label: string }[] = [
  { key: "composite_market_score", label: "Score" },
  { key: "mention_count", label: "Mentions" },
  { key: "momentum", label: "Momentum" },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PerfumeEntityPage({ params }: PageProps) {
  const { id } = use(params);
  const decoded = decodeURIComponent(id);
  const router = useRouter();

  const [chartMetric, setChartMetric] = useState<EntityChartMetric>("composite_market_score");
  const [showWatchModal, setShowWatchModal] = useState(false);
  const [showAlertModal, setShowAlertModal] = useState(false);
  const [isStartingTracking, setIsStartingTracking] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["perfume-entity", decoded],
    queryFn: () => fetchPerfumeEntity(decoded, { history_days: 30 }),
    staleTime: 60_000,
  });

  const isTracked = data?.state !== "catalog_only";
  const latestSignal = data?.recent_signals?.[0]?.signal_type ?? null;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title={data?.canonical_name ?? decoded}
        subtitle={data?.brand_name ?? data?.ticker ?? undefined}
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
                    This perfume is known to the catalog but has not appeared in
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
                        const result = await startTracking(data.resolver_id, "perfume");
                        router.replace(`/entities/perfume/${encodeURIComponent(result.entity_id)}`);
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

            {/* ── Entity header panel ─────────────────────────────────────── */}
            <TerminalPanel noPad>
              <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
                {/* Identity */}
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {data.ticker && (
                      <span className="font-mono text-sm font-bold text-amber-400">
                        {data.ticker}
                      </span>
                    )}
                    <StateBadge state={data.state} />
                    {latestSignal && <SignalBadge type={latestSignal} />}
                    {data.aliases_count > 0 && (
                      <span className="text-[10px] text-zinc-600">
                        {data.aliases_count} aliases
                      </span>
                    )}
                  </div>
                  <h1 className="mt-1 text-xl font-bold leading-tight text-zinc-100">
                    {data.canonical_name}
                  </h1>
                  {data.brand_name && (
                    <p className="mt-0.5 text-xs text-zinc-500">{data.brand_name}</p>
                  )}
                </div>

                {/* Score + actions (tracked only) */}
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
            </TerminalPanel>

            {/* ── Chart + metrics (tracked only) ─────────────────────────── */}
            {isTracked && data.timeseries.length > 0 && (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
                <TerminalPanel>
                  <div className="mb-3 flex items-center justify-between">
                    <SectionHeader title="Market Score · 30 Day" />
                    <div className="flex gap-1">
                      {CHART_TABS.map(({ key, label }) => (
                        <button
                          key={key}
                          onClick={() => setChartMetric(key)}
                          className={`rounded border px-2 py-0.5 text-[10px] transition-colors ${
                            chartMetric === key
                              ? "border-zinc-500 bg-zinc-700 text-zinc-100"
                              : "border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <EntityChart history={data.timeseries} metric={chartMetric} />
                </TerminalPanel>

                <TerminalPanel noPad>
                  <div className="px-4 py-3">
                    <SectionHeader title="Metrics" />
                  </div>
                  <PanelDivider />
                  <div className="flex flex-col">
                    <div className="border-b border-zinc-800/80 bg-zinc-950/50 px-4 py-1">
                      <span className="text-[9px] font-bold uppercase tracking-widest text-zinc-600">
                        Market
                      </span>
                    </div>
                    <MetricRow label="Score" value={fmtScore(data.latest_score)} />
                    <MetricRow label="Growth" value={fmtGrowth(data.latest_growth)} />
                    <MetricRow label="Confidence" value={fmtConfidence(data.confidence_avg)} />
                    <div className="border-b border-zinc-800/80 bg-zinc-950/50 px-4 py-1">
                      <span className="text-[9px] font-bold uppercase tracking-widest text-zinc-600">
                        Momentum
                      </span>
                    </div>
                    <MetricRow label="Momentum" value={fmtMomentum(data.momentum)} />
                    {data.latest_date && (
                      <>
                        <div className="border-b border-zinc-800/80 bg-zinc-950/50 px-4 py-1">
                          <span className="text-[9px] font-bold uppercase tracking-widest text-zinc-600">
                            Data
                          </span>
                        </div>
                        <MetricRow label="As of" value={data.latest_date} />
                      </>
                    )}
                  </div>
                </TerminalPanel>
              </div>
            )}

            {/* ── Notes & Accords ─────────────────────────────────────────── */}
            <NotesSection
              top={data.notes_top}
              middle={data.notes_middle}
              base={data.notes_base}
              accords={data.accords}
              source={data.notes_source}
            />

            {/* ── Similar by notes ────────────────────────────────────────── */}
            {data.similar_perfumes?.length > 0 && (
              <SimilarByNotes rows={data.similar_perfumes} />
            )}

            {/* ── Signals + mentions (tracked only) ──────────────────────── */}
            {isTracked && (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
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

                <TerminalPanel noPad>
                  <div className="p-4">
                    <SectionHeader
                      title="Recent Mentions"
                      subtitle={`${data.recent_mentions.length} sources`}
                    />
                  </div>
                  <PanelDivider />
                  <div className="max-h-72 overflow-y-auto">
                    <RecentMentions mentions={data.recent_mentions} />
                  </div>
                </TerminalPanel>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
