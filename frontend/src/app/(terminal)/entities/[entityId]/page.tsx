"use client";

import { useQuery } from "@tanstack/react-query";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, GitCompare } from "lucide-react";

import { fetchEntity } from "@/lib/api/entities";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { PanelDivider } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";
import { ErrorState } from "@/components/primitives/ErrorState";
import { EmptyState } from "@/components/primitives/EmptyState";
import { EntityHeader } from "@/components/entity/EntityHeader";
import { MetricsRail } from "@/components/entity/MetricsRail";
import { EntityChart } from "@/components/entity/EntityChart";
import { SignalTimeline } from "@/components/entity/SignalTimeline";
import { RecentMentions } from "@/components/entity/RecentMentions";
import { AddToWatchlistModal } from "@/components/entity/AddToWatchlistModal";
import { CreateAlertModal } from "@/components/alerts/CreateAlertModal";
import type { EntitySummaryBlock } from "@/lib/api/types";
import type { EntityChartMetric } from "@/components/entity/EntityChart";

type ChartMetric = EntityChartMetric;

const CHART_TABS: { key: ChartMetric; label: string }[] = [
  { key: "composite_market_score", label: "Score" },
  { key: "mention_count", label: "Mentions" },
  { key: "momentum", label: "Momentum" },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ entityId: string }>;
}

export default function EntityPage({ params }: PageProps) {
  const { entityId } = use(params);
  const decoded = decodeURIComponent(entityId);
  const router = useRouter();

  const [chartMetric, setChartMetric] = useState<ChartMetric>(
    "composite_market_score",
  );
  const [showWatchModal, setShowWatchModal] = useState(false);
  const [showAlertModal, setShowAlertModal] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["entity", decoded],
    queryFn: () => fetchEntity(decoded, { history_days: 30 }),
    staleTime: 60_000,
  });

  const summary = data?.summary as EntitySummaryBlock | null | undefined;
  const latestSignal = data?.signals?.[0]?.signal_type ?? null;
  const latestSignalStrength = data?.signals?.[0]?.strength ?? null;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title={summary?.name ?? decoded}
        subtitle={summary?.ticker}
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

      {/* Watch modal */}
      {showWatchModal && summary && (
        <AddToWatchlistModal
          entityId={summary.entity_id}
          entityType={summary.entity_type}
          canonicalName={summary.name}
          onClose={() => setShowWatchModal(false)}
        />
      )}

      {/* Alert modal */}
      {showAlertModal && summary && (
        <CreateAlertModal
          prefill={{
            entity_id: summary.entity_id,
            entity_type: summary.entity_type,
            canonical_name: summary.name,
          }}
          onClose={() => setShowAlertModal(false)}
          onCreated={() => setShowAlertModal(false)}
        />
      )}

      {/* Scrollable content */}
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

        {data && !summary && (
          <div className="p-5">
            <EmptyState message="Entity data unavailable" />
          </div>
        )}

        {data && summary && (
          <div className="space-y-4 p-4">
            {/* ── Entity header panel ──────────────────────────────────── */}
            <TerminalPanel noPad>
              <EntityHeader
                summary={summary}
                latestSignal={latestSignal}
                onWatch={() => setShowWatchModal(true)}
                onAlert={() => setShowAlertModal(true)}
              />
            </TerminalPanel>

            {/* ── Main 2-col: chart (2/3) + metrics rail (1/3) ─────────── */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
              {/* Chart panel */}
              <TerminalPanel>
                <div className="mb-3 flex items-center justify-between">
                  <SectionHeader title="Market Score · 30 Day" />
                  {/* Metric toggle */}
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
                <EntityChart history={data.history} metric={chartMetric} />
              </TerminalPanel>

              {/* Metrics rail */}
              <TerminalPanel noPad>
                <div className="px-4 py-3">
                  <SectionHeader title="Metrics" />
                </div>
                <PanelDivider />
                <MetricsRail
                  summary={summary}
                  signalCount={data.signals.length}
                  latestSignal={latestSignal}
                  latestSignalStrength={latestSignalStrength}
                />
              </TerminalPanel>
            </div>

            {/* ── Signal timeline + recent mentions ─────────────────────── */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {/* Signal timeline */}
              <TerminalPanel noPad>
                <div className="p-4">
                  <SectionHeader
                    title="Signal Timeline"
                    subtitle={`${data.signals.length} events`}
                  />
                </div>
                <PanelDivider />
                <div className="max-h-72 overflow-y-auto px-2 py-2">
                  <SignalTimeline signals={data.signals} />
                </div>
              </TerminalPanel>

              {/* Recent mentions */}
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

            {/* ── Related / Compare placeholder ─────────────────────────── */}
            <TerminalPanel noPad>
              <div className="flex items-center gap-3 p-4">
                <GitCompare size={14} className="shrink-0 text-zinc-700" />
                <div>
                  <p className="text-xs font-semibold text-zinc-500">
                    Related Entities &amp; Compare Mode
                  </p>
                  <p className="text-[10px] text-zinc-700">
                    Compare similar movers and related brands — coming in a
                    future release.
                  </p>
                </div>
              </div>
            </TerminalPanel>
          </div>
        )}
      </div>
    </div>
  );
}
