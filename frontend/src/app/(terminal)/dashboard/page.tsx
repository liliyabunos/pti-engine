"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import { fetchDashboard } from "@/lib/api/dashboard";
import { useUIStore } from "@/lib/stores/ui";
import { Header } from "@/components/shell/Header";
import {
  ControlBar,
  ControlBarDivider,
} from "@/components/primitives/ControlBar";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { SearchInput } from "@/components/primitives/SearchInput";
import { FilterChip } from "@/components/primitives/FilterChip";
import {
  SkeletonKpiStrip,
  TableSkeleton,
  LoadingSkeleton,
} from "@/components/primitives/LoadingSkeleton";
import { ErrorState } from "@/components/primitives/ErrorState";
import { KpiStrip } from "@/components/dashboard/KpiStrip";
import { TopMoversTable } from "@/components/dashboard/TopMoversTable";
import { SignalFeed } from "@/components/dashboard/SignalFeed";
import { EntityChartPanel } from "@/components/dashboard/EntityChartPanel";
import type { TopMoverRow } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Entity type filter options
// ---------------------------------------------------------------------------

const ENTITY_TYPES = [
  { key: "all", label: "All" },
  { key: "perfume", label: "Perfume" },
  { key: "brand", label: "Brand" },
] as const;

type EntityTypeFilter = (typeof ENTITY_TYPES)[number]["key"];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const { selectedEntityId, setSelectedEntityId } = useUIStore();

  const [search, setSearch] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] =
    useState<EntityTypeFilter>("all");

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => fetchDashboard({ top_n: 20, signal_days: 7 }),
    refetchInterval: 60_000,
  });

  // ---------------------------------------------------------------------------
  // Client-side filtering of movers list
  // ---------------------------------------------------------------------------

  const filteredMovers = useMemo<TopMoverRow[]>(() => {
    const movers = data?.top_movers ?? [];
    return movers.filter((m) => {
      const matchesSearch =
        !search ||
        m.canonical_name.toLowerCase().includes(search.toLowerCase()) ||
        m.ticker.toLowerCase().includes(search.toLowerCase()) ||
        (m.brand_name ?? "").toLowerCase().includes(search.toLowerCase());

      const matchesType =
        entityTypeFilter === "all" ||
        (m.entity_type ?? "").toLowerCase() === entityTypeFilter;

      return matchesSearch && matchesType;
    });
  }, [data?.top_movers, search, entityTypeFilter]);

  // ---------------------------------------------------------------------------
  // Auto-select first mover; reset if selected entity disappears
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!filteredMovers.length) return;

    const stillPresent = filteredMovers.some(
      (m) => m.entity_id === selectedEntityId,
    );

    if (!selectedEntityId || !stillPresent) {
      setSelectedEntityId(filteredMovers[0].entity_id);
    }
  }, [filteredMovers, selectedEntityId, setSelectedEntityId]);

  // Derive the full mover row for the selected entity (for EntityChartPanel header)
  const selectedMover =
    filteredMovers.find((m) => m.entity_id === selectedEntityId) ??
    data?.top_movers.find((m) => m.entity_id === selectedEntityId) ??
    null;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Dashboard"
        subtitle={
          data
            ? `as of ${data.kpis?.as_of_date ?? data.generated_at.slice(0, 10)}`
            : undefined
        }
        actions={
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-40"
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />

      {/* Control bar */}
      <ControlBar
        left={
          <div className="flex items-center gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Filter movers…"
              className="w-48"
            />
            <ControlBarDivider />
            {ENTITY_TYPES.map(({ key, label }) => (
              <FilterChip
                key={key}
                label={label}
                active={entityTypeFilter === key}
                onClick={() => setEntityTypeFilter(key)}
              />
            ))}
          </div>
        }
        right={
          data?.kpis && (
            <>
              <span className="text-[11px] text-zinc-600">
                {data.total_entities} entities
              </span>
              <ControlBarDivider />
              <span className="text-[11px] text-zinc-600">
                {data.kpis.total_signals_today} signals today
              </span>
              <ControlBarDivider />
              <span className="text-[11px] text-zinc-600">
                {data.kpis.active_movers} movers
              </span>
            </>
          )
        }
      />

      {/* Scrollable content region */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {/* KPI strip */}
        {isLoading && <SkeletonKpiStrip />}
        {isError && (
          <ErrorState message={String(error)} onRetry={() => refetch()} />
        )}
        {data?.kpis && <KpiStrip kpis={data.kpis} />}

        {/* Main 3-column grid */}
        {!isError && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_2fr_1fr]">
            {/* Left: Top Movers table */}
            <TerminalPanel noPad>
              <div className="p-4">
                <SectionHeader
                  title="Top Movers"
                  subtitle={
                    data
                      ? `${filteredMovers.length} of ${data.top_movers.length}`
                      : undefined
                  }
                />
              </div>
              {isLoading ? (
                <TableSkeleton rows={8} cols={8} />
              ) : (
                <TopMoversTable
                  rows={filteredMovers}
                  selectedId={selectedEntityId}
                  onSelect={setSelectedEntityId}
                />
              )}
            </TerminalPanel>

            {/* Center: Entity chart panel */}
            <TerminalPanel noPad>
              {isLoading ? (
                <div className="p-4">
                  <LoadingSkeleton rows={6} rowHeight={24} />
                </div>
              ) : (
                <EntityChartPanel selectedMover={selectedMover} />
              )}
            </TerminalPanel>

            {/* Right: Signal feed */}
            <TerminalPanel noPad>
              <div className="p-4">
                <SectionHeader title="Recent Signals" subtitle="last 7 days" />
              </div>
              <div className="max-h-[calc(100%-60px)] overflow-y-auto px-2 pb-2">
                {isLoading ? (
                  <LoadingSkeleton rows={5} rowHeight={36} className="p-2" />
                ) : (
                  <SignalFeed
                    signals={data?.recent_signals ?? []}
                    selectedEntityId={selectedEntityId}
                    onSelectEntity={setSelectedEntityId}
                  />
                )}
              </div>
            </TerminalPanel>
          </div>
        )}

        {/* Breakouts */}
        {data?.breakouts && data.breakouts.length > 0 && (
          <TerminalPanel noPad>
            <div className="p-4">
              <SectionHeader
                title="Breakouts"
                subtitle={`${data.breakouts.length} entities`}
              />
            </div>
            <TopMoversTable
              rows={data.breakouts}
              selectedId={selectedEntityId}
              onSelect={setSelectedEntityId}
            />
          </TerminalPanel>
        )}
      </div>
    </div>
  );
}
