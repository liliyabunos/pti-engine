"use client";

import { useCallback, useMemo, useState, Suspense } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  X,
} from "lucide-react";
import { clsx } from "clsx";

import { fetchScreener } from "@/lib/api/screener";
import { Header } from "@/components/shell/Header";
import {
  ControlBar,
  ControlBarDivider,
} from "@/components/primitives/ControlBar";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { SearchInput } from "@/components/primitives/SearchInput";
import { FilterChip } from "@/components/primitives/FilterChip";
import { ErrorState } from "@/components/primitives/ErrorState";
import { ScreenerFilters } from "@/components/screener/ScreenerFilters";
import { ScreenerTable } from "@/components/screener/ScreenerTable";
import type { ScreenerParams } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// V1 Known Limitations
// ---------------------------------------------------------------------------
//
// 1. TEXT SEARCH IS CLIENT-SIDE ONLY
//    The SearchInput filters `data.rows` in the browser after the backend
//    returns results. It does NOT send a `q` param to the backend.
//    This means search only covers the current page (limit=50 by default).
//    To fix: add a `q` / `search` param to GET /api/v1/screener backend route.
//
// 2. WATCHLISTS + ALERTS ARE SCAFFOLD ONLY
//    /watchlists and /alerts exist as placeholder routes with no backend wiring.
//
// 3. COMPARE MODE IS PLACEHOLDER
//    The "Related Entities & Compare Mode" block on entity pages is a
//    non-functional placeholder. No compare API exists yet.
//
// 4. RECENT MENTION LINKS DEPEND ON BACKEND SOURCE URL QUALITY
//    RecentMentions shows an external link only when source_url starts with
//    "http". Internal-only records show a lock icon. URL quality depends on
//    what the backend ingestion pipeline stores.
//
// 5. BRAND ANALYTICS MAY BE SHALLOWER THAN PERFUME ANALYTICS
//    Brand-level entities aggregate mentions across all child perfumes.
//    Signal density, timeseries depth, and confidence may be lower for brands.
//
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

// Preset configurations — each prefills a specific set of screener params
const PRESETS: {
  key: string;
  label: string;
  params: Partial<ScreenerParams>;
}[] = [
  {
    key: "top",
    label: "Top Score",
    params: {
      sort_by: "composite_market_score",
      order: "desc",
      signal_type: undefined,
      entity_type: undefined,
      min_score: undefined,
    },
  },
  {
    key: "breakouts",
    label: "Breakouts",
    params: {
      signal_type: "breakout",
      has_signals: true,
      sort_by: "composite_market_score",
      order: "desc",
    },
  },
  {
    key: "momentum",
    label: "Momentum",
    params: {
      sort_by: "momentum",
      order: "desc",
      signal_type: undefined,
      entity_type: undefined,
    },
  },
  {
    key: "discovery",
    label: "Discovery",
    params: {
      sort_by: "mention_count",
      order: "desc",
      signal_type: "new_entry",
      has_signals: true,
    },
  },
];

// ---------------------------------------------------------------------------
// URL param serialization helpers
// ---------------------------------------------------------------------------

function paramsToSearch(p: ScreenerParams): string {
  const q = new URLSearchParams();
  if (p.sort_by) q.set("sort_by", p.sort_by);
  if (p.order) q.set("order", p.order);
  if (p.entity_type) q.set("entity_type", p.entity_type);
  if (p.signal_type) q.set("signal_type", p.signal_type);
  if (p.has_signals) q.set("has_signals", "true");
  if (p.min_score != null && p.min_score > 0)
    q.set("min_score", String(p.min_score));
  if (p.min_confidence != null && p.min_confidence > 0)
    q.set("min_confidence", String(p.min_confidence));
  if (p.min_mentions != null && p.min_mentions > 0)
    q.set("min_mentions", String(p.min_mentions));
  if (p.offset && p.offset > 0) q.set("offset", String(p.offset));
  return q.toString();
}

function searchToParams(sp: URLSearchParams): ScreenerParams {
  return {
    sort_by: sp.get("sort_by") ?? "composite_market_score",
    order: (sp.get("order") as "asc" | "desc") ?? "desc",
    limit: PAGE_SIZE,
    offset: Number(sp.get("offset") ?? 0),
    entity_type: sp.get("entity_type") ?? undefined,
    signal_type: sp.get("signal_type") ?? undefined,
    has_signals: sp.get("has_signals") === "true" ? true : undefined,
    min_score: sp.get("min_score") ? Number(sp.get("min_score")) : undefined,
    min_confidence: sp.get("min_confidence")
      ? Number(sp.get("min_confidence"))
      : undefined,
    min_mentions: sp.get("min_mentions")
      ? Number(sp.get("min_mentions"))
      : undefined,
  };
}

// ---------------------------------------------------------------------------
// Detect active preset (loose match on key fields)
// ---------------------------------------------------------------------------

function detectPreset(params: ScreenerParams): string | null {
  for (const p of PRESETS) {
    const keys = Object.keys(p.params) as (keyof ScreenerParams)[];
    const match = keys.every((k) => {
      const pv = p.params[k];
      const cv = params[k];
      if (pv === undefined) return true; // preset doesn't constrain this field
      return pv === cv;
    });
    if (match && p.params.signal_type === params.signal_type) return p.key;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Inner page — reads URL search params
// ---------------------------------------------------------------------------

function ScreenerPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Initialize screener params from URL
  const [params, setParams] = useState<ScreenerParams>(() =>
    searchToParams(searchParams),
  );

  // Client-side search (backend /screener has no text search param in V1)
  const [search, setSearch] = useState("");

  // Filter sidebar open/close (local — not synced to URL)
  const [filtersOpen, setFiltersOpen] = useState(false);

  // ---------------------------------------------------------------------------
  // Update params — syncs to URL
  // ---------------------------------------------------------------------------

  const pushParams = useCallback(
    (next: ScreenerParams) => {
      const qs = paramsToSearch(next);
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [pathname, router],
  );

  const updateParams = useCallback(
    (updates: Partial<ScreenerParams>) => {
      const next = { ...params, ...updates, offset: 0 };
      setParams(next);
      pushParams(next);
    },
    [params, pushParams],
  );

  // Handle column header sort click — toggle direction if same key
  const handleSort = useCallback(
    (key: string) => {
      const next: Partial<ScreenerParams> = {
        sort_by: key,
        order:
          params.sort_by === key && params.order === "desc" ? "asc" : "desc",
      };
      updateParams(next);
    },
    [params.sort_by, params.order, updateParams],
  );

  const applyPreset = useCallback(
    (preset: (typeof PRESETS)[number]) => {
      const next: ScreenerParams = {
        sort_by: "composite_market_score",
        order: "desc",
        limit: PAGE_SIZE,
        offset: 0,
        entity_type: undefined,
        signal_type: undefined,
        has_signals: undefined,
        min_score: undefined,
        min_confidence: undefined,
        min_mentions: undefined,
        ...preset.params,
      };
      setParams(next);
      pushParams(next);
    },
    [pushParams],
  );

  const resetAll = useCallback(() => {
    const next: ScreenerParams = {
      sort_by: "composite_market_score",
      order: "desc",
      limit: PAGE_SIZE,
      offset: 0,
    };
    setSearch("");
    setParams(next);
    pushParams(next);
  }, [pushParams]);

  const goPage = useCallback(
    (dir: 1 | -1) => {
      const next = {
        ...params,
        offset: Math.max(0, (params.offset ?? 0) + dir * PAGE_SIZE),
      };
      setParams(next);
      pushParams(next);
    },
    [params, pushParams],
  );

  // ---------------------------------------------------------------------------
  // Query
  // ---------------------------------------------------------------------------

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["screener", params],
    queryFn: () => fetchScreener(params),
    staleTime: 30_000,
  });

  // ---------------------------------------------------------------------------
  // Client-side name filter (within current page results only)
  // Note: backend /screener does not support text search in V1.
  //       Search applies to the current page only.
  // ---------------------------------------------------------------------------

  const filteredRows = useMemo(() => {
    const rows = data?.rows ?? [];
    if (!search) return rows;
    const q = search.toLowerCase();
    return rows.filter(
      (r) =>
        r.canonical_name.toLowerCase().includes(q) ||
        r.ticker.toLowerCase().includes(q) ||
        (r.brand_name ?? "").toLowerCase().includes(q),
    );
  }, [data?.rows, search]);

  // ---------------------------------------------------------------------------
  // Pagination state
  // ---------------------------------------------------------------------------

  const total = data?.total ?? 0;
  const currentOffset = params.offset ?? 0;
  const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  // Detect active preset for visual hint
  const activePreset = detectPreset(params);

  // Has any non-default filter active
  const hasActiveFilters =
    params.entity_type ||
    params.signal_type ||
    params.has_signals ||
    (params.min_score ?? 0) > 0 ||
    (params.min_confidence ?? 0) > 0 ||
    (params.min_mentions ?? 0) > 0;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Screener"
        subtitle={data ? `${data.total} entities` : undefined}
        actions={
          <button
            onClick={() => setFiltersOpen((o) => !o)}
            className={clsx(
              "flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] transition-colors",
              filtersOpen
                ? "border-zinc-500 bg-zinc-800 text-zinc-200"
                : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200",
            )}
          >
            <SlidersHorizontal size={11} />
            Filters
            {hasActiveFilters && (
              <span className="ml-0.5 h-1.5 w-1.5 rounded-full bg-amber-400" />
            )}
          </button>
        }
      />

      {/* ── Control bar ─────────────────────────────────────────────────── */}
      <ControlBar
        left={
          <div className="flex min-w-0 items-center gap-2 overflow-x-auto">
            {/* Search — client-side within current page (V1 limitation) */}
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search name / ticker…"
              className="w-40 shrink-0"
            />
            <ControlBarDivider />
            {/* Presets */}
            <div className="flex shrink-0 items-center gap-1">
              {PRESETS.map((p) => (
                <FilterChip
                  key={p.key}
                  label={p.label}
                  active={activePreset === p.key}
                  onClick={() => applyPreset(p)}
                />
              ))}
            </div>
          </div>
        }
        right={
          <>
            {hasActiveFilters && (
              <button
                onClick={resetAll}
                className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-300"
              >
                <X size={11} />
                Clear filters
              </button>
            )}
            {data && (
              <>
                <ControlBarDivider />
                <span className="text-[11px] text-zinc-600">
                  {filteredRows.length} shown
                  {search ? ` (filtered from ${data.rows.length})` : ""}
                </span>
              </>
            )}
          </>
        }
      />

      {/* ── Main layout ─────────────────────────────────────────────────── */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Filter sidebar */}
        {filtersOpen && (
          <aside className="w-56 shrink-0 overflow-y-auto border-r border-zinc-800 bg-zinc-950">
            <ScreenerFilters params={params} onChange={updateParams} />
          </aside>
        )}

        {/* Results area */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-4">
          {isError ? (
            <ErrorState
              message={String(error)}
              onRetry={() => refetch()}
            />
          ) : (
            <TerminalPanel
              noPad
              className="flex flex-1 flex-col overflow-hidden"
            >
              {/* Panel header */}
              <div className="flex items-center justify-between px-4 py-3">
                <SectionHeader
                  title="Results"
                  subtitle={
                    data
                      ? `${data.total} total · page ${currentPage} of ${totalPages}`
                      : undefined
                  }
                />
              </div>

              {/* Scrollable table */}
              <div className="flex-1 overflow-y-auto">
                <ScreenerTable
                  rows={filteredRows}
                  isLoading={isLoading}
                  sortBy={params.sort_by}
                  order={params.order}
                  onSort={handleSort}
                />
              </div>

              {/* Pagination footer */}
              <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-2">
                <span className="text-[11px] text-zinc-500">
                  Showing {currentOffset + 1}–
                  {Math.min(currentOffset + PAGE_SIZE, total)} of {total}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    disabled={currentPage <= 1}
                    onClick={() => goPage(-1)}
                    className="rounded border border-zinc-700 p-1 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    <ChevronLeft size={13} />
                  </button>
                  <span className="px-1.5 text-[11px] tabular-nums text-zinc-500">
                    {currentPage} / {totalPages}
                  </span>
                  <button
                    disabled={currentPage >= totalPages}
                    onClick={() => goPage(1)}
                    className="rounded border border-zinc-700 p-1 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    <ChevronRight size={13} />
                  </button>
                </div>
              </div>
            </TerminalPanel>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page export — Suspense required for useSearchParams in static pages
// ---------------------------------------------------------------------------

export default function ScreenerPage() {
  return (
    <Suspense>
      <ScreenerPageInner />
    </Suspense>
  );
}
