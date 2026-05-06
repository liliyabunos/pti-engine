"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";

import { fetchDashboard } from "@/lib/api/dashboard";
import { fetchCatalogCounts } from "@/lib/api/catalog";
import { fetchTopNotes, fetchTopAccords } from "@/lib/api/notes";
import { fetchEmerging } from "@/lib/api/emerging";
import { useUIStore } from "@/lib/stores/ui";
import { Header } from "@/components/shell/Header";
import {
  ControlBar,
  ControlBarDivider,
} from "@/components/primitives/ControlBar";
import { RangeSelector, type RangePreset } from "@/components/primitives/RangeSelector";
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
import { EmergingPanel } from "@/components/dashboard/EmergingPanel";
import type { TopMoverRow, NoteRow, AccordRow } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Entity type filter options
// ---------------------------------------------------------------------------

const ENTITY_TYPES = [
  { key: "all", label: "All", hint: "Perfumes and brands" },
  { key: "perfume", label: "Perfume", hint: "Individual fragrances only" },
  { key: "brand", label: "Brand", hint: "Brands — scores aggregate their perfume portfolio" },
] as const;

type EntityTypeFilter = (typeof ENTITY_TYPES)[number]["key"];

// ---------------------------------------------------------------------------
// Composition panels
// ---------------------------------------------------------------------------

function NotesPanel({ notes, isLoading }: { notes: NoteRow[]; isLoading: boolean }) {
  const router = useRouter();
  if (isLoading) return <LoadingSkeleton rows={8} rowHeight={20} className="px-4 pb-4" />;
  return (
    <div className="flex flex-wrap gap-1.5 px-4 pb-4">
      {notes.slice(0, 30).map((n) => (
        <button
          key={n.note_name}
          onClick={() => router.push(`/entities/note/${encodeURIComponent(n.note_name)}`)}
          className="inline-flex items-center gap-1 rounded border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[11px] text-zinc-300 transition-colors hover:border-zinc-600 hover:text-zinc-100"
        >
          {n.note_name}
          <span className="text-zinc-600">{n.perfume_count.toLocaleString()}</span>
        </button>
      ))}
    </div>
  );
}

function AccordsPanel({ accords, isLoading }: { accords: AccordRow[]; isLoading: boolean }) {
  const router = useRouter();
  if (isLoading) return <LoadingSkeleton rows={6} rowHeight={20} className="px-4 pb-4" />;
  return (
    <div className="flex flex-wrap gap-1.5 px-4 pb-4">
      {accords.slice(0, 20).map((a) => (
        <button
          key={a.accord_name}
          onClick={() => router.push(`/entities/accord/${encodeURIComponent(a.accord_name)}`)}
          className="inline-flex items-center gap-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[11px] text-violet-300 transition-colors hover:border-violet-700 hover:text-violet-100"
        >
          {a.accord_name}
          <span className="text-zinc-600">{a.perfume_count.toLocaleString()}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const { selectedEntityId, setSelectedEntityId } = useUIStore();

  const [search, setSearch] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] =
    useState<EntityTypeFilter>("all");
  const [rangePreset, setRangePreset] = useState<RangePreset>("today");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");

  const isCustomReady =
    rangePreset === "custom" &&
    !!customStartDate &&
    !!customEndDate &&
    customStartDate <= customEndDate;

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["dashboard", rangePreset, customStartDate, customEndDate],
    queryFn: () =>
      fetchDashboard({
        top_n: 20,
        signal_days: 7,
        range_preset: rangePreset,
        ...(isCustomReady
          ? { start_date: customStartDate, end_date: customEndDate }
          : {}),
      }),
    enabled: rangePreset !== "custom" || isCustomReady,
    refetchInterval: 60_000,
  });

  const { data: catalogCounts } = useQuery({
    queryKey: ["catalog-counts"],
    queryFn: fetchCatalogCounts,
    staleTime: 5 * 60_000,
  });

  const { data: topNotes = [], isLoading: notesLoading } = useQuery({
    queryKey: ["top-notes-dashboard"],
    queryFn: () => fetchTopNotes(30),
    staleTime: 10 * 60_000,
  });

  const { data: topAccords = [], isLoading: accordsLoading } = useQuery({
    queryKey: ["top-accords-dashboard"],
    queryFn: () => fetchTopAccords(20),
    staleTime: 10 * 60_000,
  });

  const { data: emergingData, isLoading: emergingLoading } = useQuery({
    queryKey: ["emerging-candidates"],
    queryFn: () => fetchEmerging({ limit: 15, days: 14, min_channels: 2 }),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  // ---------------------------------------------------------------------------
  // Client-side filtering of movers list (dashboard — limited set, OK here)
  // ---------------------------------------------------------------------------

  const moverEntityIds = useMemo(
    () => new Set((data?.top_movers ?? []).map((m) => m.entity_id)),
    [data?.top_movers],
  );

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
            ? data.range_label
              ? `${data.range_label} · as of ${data.kpis?.as_of_date ?? data.generated_at.slice(0, 10)}`
              : `as of ${data.kpis?.as_of_date ?? data.generated_at.slice(0, 10)}`
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
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Filter movers…"
              className="w-36 shrink-0 sm:w-48"
            />
            <ControlBarDivider />
            <div className="flex items-center gap-1">
              {ENTITY_TYPES.map(({ key, label, hint }) => (
                <FilterChip
                  key={key}
                  label={label}
                  active={entityTypeFilter === key}
                  onClick={() => setEntityTypeFilter(key)}
                  title={hint}
                />
              ))}
            </div>
          </div>
        }
        right={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <RangeSelector
              value={rangePreset}
              onChange={setRangePreset}
              customStartDate={customStartDate}
              customEndDate={customEndDate}
              onCustomDatesChange={(s, e) => {
                setCustomStartDate(s);
                setCustomEndDate(e);
              }}
            />
            {data?.kpis && (
              <div className="flex items-center gap-2">
                <ControlBarDivider />
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
              </div>
            )}
          </div>
        }
      />

      {/* Scrollable content region */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {/* KPI strip */}
        {isLoading && <SkeletonKpiStrip />}
        {isError && (
          <ErrorState message={String(error)} onRetry={() => refetch()} />
        )}
        {data?.kpis && <KpiStrip kpis={data.kpis} catalogCounts={catalogCounts} />}

        {/* ── MARKET ─────────────────────────────────────────────────────── */}
        {!isError && (
          <>
            <div className="flex items-center gap-2 pt-1">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                Market
              </span>
              <div className="h-px flex-1 bg-zinc-800" />
            </div>

            {/* 3-column grid: movers | chart | signals */}
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
                      moverEntityIds={moverEntityIds}
                    />
                  )}
                </div>
              </TerminalPanel>
            </div>

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
          </>
        )}

        {/* ── EMERGING ───────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 pt-1">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Emerging
          </span>
          <div className="h-px flex-1 bg-zinc-800" />
          <span className="text-[10px] text-zinc-700">
            Not yet in knowledge base · ranked by recency × frequency
          </span>
        </div>

        <TerminalPanel noPad>
          <div className="p-4 pb-3">
            <SectionHeader
              title="Emerging Candidates"
              subtitle={
                emergingData
                  ? `${emergingData.candidates.length} signals · ${emergingData.total_in_table.toLocaleString()} in table`
                  : "last 14 days · min 2 channels"
              }
            />
          </div>
          <div className="px-2 pb-3">
            <EmergingPanel
              candidates={emergingData?.candidates ?? []}
              totalInQueue={emergingData?.total_in_table ?? 0}
              isLoading={emergingLoading}
            />
          </div>
        </TerminalPanel>

        {/* ── COMPOSITION ────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 pt-1">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Composition
          </span>
          <div className="h-px flex-1 bg-zinc-800" />
          <span className="text-[10px] text-zinc-700">
            Why market movements happen
          </span>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Trending Notes */}
          <TerminalPanel noPad>
            <div className="p-4 pb-3">
              <SectionHeader
                title="Trending Notes"
                subtitle={`${topNotes.length} notes · by catalog coverage`}
              />
            </div>
            <NotesPanel notes={topNotes} isLoading={notesLoading} />
          </TerminalPanel>

          {/* Trending Accords */}
          <TerminalPanel noPad>
            <div className="p-4 pb-3">
              <SectionHeader
                title="Trending Accords"
                subtitle={`${topAccords.length} accords · by catalog coverage`}
              />
            </div>
            <AccordsPanel accords={topAccords} isLoading={accordsLoading} />
          </TerminalPanel>
        </div>
      </div>
    </div>
  );
}
