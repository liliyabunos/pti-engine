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
import { fetchCatalogPerfumes, fetchCatalogBrands, fetchCatalogCounts } from "@/lib/api/catalog";
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
import { EmptyState } from "@/components/primitives/EmptyState";
import { TableSkeleton } from "@/components/primitives/LoadingSkeleton";
import { ScreenerFilters } from "@/components/screener/ScreenerFilters";
import { ScreenerTable } from "@/components/screener/ScreenerTable";
import type { ScreenerParams, CatalogPerfumeRow, CatalogBrandRow } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// V1 Known Limitations
// ---------------------------------------------------------------------------
//
// 1. TEXT SEARCH IS CLIENT-SIDE ONLY (active mode)
//    In "Active today" mode, search filters browser-side on current page.
//    In "All Perfumes" / "All Brands" modes, search is server-side via
//    /api/v1/catalog/perfumes?q=... and /api/v1/catalog/brands?q=...
//
// 2. ALL CATALOG ENTITIES ARE NOW NAVIGABLE (Phase U2)
//    Tracked rows → /entities/perfume/{entity_id} or /entities/brand/{entity_id}
//    Catalog-only rows → /entities/perfume/{resolver_id} or /entities/brand/{resolver_id}
//
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

type ScreenerMode = "active" | "catalog_perfumes" | "catalog_brands";

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

function paramsToSearch(p: ScreenerParams, mode: ScreenerMode): string {
  const q = new URLSearchParams();
  if (mode !== "active") q.set("mode", mode);
  if (p.sort_by) q.set("sort_by", p.sort_by);
  if (p.order) q.set("order", p.order);
  if (p.entity_type) q.set("entity_type", p.entity_type);
  if (p.signal_type) q.set("signal_type", p.signal_type);
  if (p.has_signals) q.set("has_signals", "true");
  if (p.note) q.set("note", p.note);
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
    note: sp.get("note") ?? undefined,
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
      if (pv === undefined) return true;
      return pv === cv;
    });
    if (match && p.params.signal_type === params.signal_type) return p.key;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Catalog table (simpler columns for resolver catalog rows)
// ---------------------------------------------------------------------------

function CatalogPerfumeTable({
  rows,
  isLoading,
}: {
  rows: CatalogPerfumeRow[];
  isLoading: boolean;
}) {
  const router = useRouter();

  if (isLoading) return <TableSkeleton rows={10} cols={3} />;
  if (!rows.length) {
    return (
      <EmptyState
        message="No perfumes found"
        detail="Try a different search term"
      />
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
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Brand
            </th>
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isTracked = !!row.entity_id;
            const isActive = row.has_activity_today;
            const href = isTracked
              ? `/entities/perfume/${encodeURIComponent(row.entity_id!)}`
              : `/entities/perfume/${row.resolver_id}`;
            return (
              <tr
                key={row.resolver_id}
                onClick={() => router.push(href)}
                className="group cursor-pointer border-b border-zinc-800/40 transition-colors hover:bg-zinc-800/30"
              >
                <td className="px-3 py-2">
                  <span className="block max-w-[240px] truncate text-xs text-zinc-200 group-hover:text-amber-300">
                    {row.canonical_name}
                  </span>
                </td>
                <td className="px-3 py-2 text-[11px] text-zinc-500">
                  {row.brand_name ?? "—"}
                </td>
                <td className="px-3 py-2">
                  {isActive ? (
                    <span className="inline-flex items-center rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-400">
                      Active
                    </span>
                  ) : isTracked ? (
                    <span className="inline-flex items-center rounded border border-emerald-800 bg-emerald-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-500">
                      Tracked
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-600">
                      In Catalog
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CatalogBrandTable({
  rows,
  isLoading,
}: {
  rows: CatalogBrandRow[];
  isLoading: boolean;
}) {
  const router = useRouter();

  if (isLoading) return <TableSkeleton rows={10} cols={3} />;
  if (!rows.length) {
    return (
      <EmptyState
        message="No brands found"
        detail="Try a different search term"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-800">
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Brand
            </th>
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500 w-20">
              Perfumes
            </th>
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isTracked = !!row.entity_id;
            const isActive = row.has_activity_today;
            const href = isTracked
              ? `/entities/brand/${encodeURIComponent(row.entity_id!)}`
              : `/entities/brand/${row.resolver_id}`;
            return (
              <tr
                key={row.resolver_id}
                onClick={() => router.push(href)}
                className="group cursor-pointer border-b border-zinc-800/40 transition-colors hover:bg-zinc-800/30"
              >
                <td className="px-3 py-2">
                  <span className="block max-w-[300px] truncate text-xs text-zinc-200 group-hover:text-amber-300">
                    {row.canonical_name}
                  </span>
                </td>
                <td className="px-3 py-2 tabular-nums text-[11px] text-zinc-500">
                  {row.perfume_count.toLocaleString()}
                </td>
                <td className="px-3 py-2">
                  {isActive ? (
                    <span className="inline-flex items-center rounded border border-amber-800 bg-amber-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-400">
                      Active
                    </span>
                  ) : isTracked ? (
                    <span className="inline-flex items-center rounded border border-emerald-800 bg-emerald-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-500">
                      Tracked
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-800/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-600">
                      In Catalog
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mode tabs
// ---------------------------------------------------------------------------

const MODE_TABS: { key: ScreenerMode; label: string; hint: string }[] = [
  { key: "active", label: "Active today", hint: "Entities with market signal data" },
  { key: "catalog_perfumes", label: "All Perfumes", hint: "56k+ perfumes in KB" },
  { key: "catalog_brands", label: "All Brands", hint: "Full brand catalog" },
];

// ---------------------------------------------------------------------------
// Inner page — reads URL search params
// ---------------------------------------------------------------------------

function ScreenerPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Mode: active (default) | catalog_perfumes | catalog_brands
  const [mode, setMode] = useState<ScreenerMode>(
    () => (searchParams.get("mode") as ScreenerMode) ?? "active",
  );

  // Initialize screener params from URL
  const [params, setParams] = useState<ScreenerParams>(() =>
    searchToParams(searchParams),
  );

  // Search — server-side in catalog modes, client-side in active mode
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Debounce search for catalog server-side calls
  const handleSearchChange = useCallback(
    (value: string) => {
      setSearch(value);
      // Simple debounce via setTimeout replacement in state
      setDebouncedSearch(value);
    },
    [],
  );

  // Catalog-specific pagination
  const [catalogOffset, setCatalogOffset] = useState(0);

  // Filter sidebar open/close (local — not synced to URL)
  const [filtersOpen, setFiltersOpen] = useState(false);

  // ---------------------------------------------------------------------------
  // Update params — syncs to URL
  // ---------------------------------------------------------------------------

  const pushParams = useCallback(
    (next: ScreenerParams, nextMode: ScreenerMode) => {
      const qs = paramsToSearch(next, nextMode);
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [pathname, router],
  );

  const updateParams = useCallback(
    (updates: Partial<ScreenerParams>) => {
      const next = { ...params, ...updates, offset: 0 };
      setParams(next);
      pushParams(next, mode);
    },
    [params, pushParams, mode],
  );

  const switchMode = useCallback(
    (nextMode: ScreenerMode) => {
      setMode(nextMode);
      setSearch("");
      setDebouncedSearch("");
      setCatalogOffset(0);
      pushParams(params, nextMode);
    },
    [params, pushParams],
  );

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
        note: undefined,
        ...preset.params,
      };
      setParams(next);
      pushParams(next, mode);
    },
    [pushParams, mode],
  );

  const resetAll = useCallback(() => {
    const next: ScreenerParams = {
      sort_by: "composite_market_score",
      order: "desc",
      limit: PAGE_SIZE,
      offset: 0,
      note: undefined,
    };
    setSearch("");
    setDebouncedSearch("");
    setParams(next);
    pushParams(next, mode);
  }, [pushParams, mode]);

  const goPage = useCallback(
    (dir: 1 | -1) => {
      if (mode === "active") {
        const next = {
          ...params,
          offset: Math.max(0, (params.offset ?? 0) + dir * PAGE_SIZE),
        };
        setParams(next);
        pushParams(next, mode);
      } else {
        setCatalogOffset((prev) => Math.max(0, prev + dir * PAGE_SIZE));
      }
    },
    [params, pushParams, mode],
  );

  // ---------------------------------------------------------------------------
  // Catalog counts (for header)
  // ---------------------------------------------------------------------------
  const { data: catalogCounts } = useQuery({
    queryKey: ["catalog-counts"],
    queryFn: fetchCatalogCounts,
    staleTime: 5 * 60_000, // 5 min — counts don't change during a session
  });

  // ---------------------------------------------------------------------------
  // Active mode query
  // ---------------------------------------------------------------------------
  const activeQuery = useQuery({
    queryKey: ["screener", params],
    queryFn: () => fetchScreener(params),
    staleTime: 30_000,
    enabled: mode === "active",
  });

  // ---------------------------------------------------------------------------
  // Catalog perfumes query
  // ---------------------------------------------------------------------------
  const catalogPerfumesQuery = useQuery({
    queryKey: ["catalog-perfumes", debouncedSearch, catalogOffset],
    queryFn: () =>
      fetchCatalogPerfumes({
        q: debouncedSearch || undefined,
        limit: PAGE_SIZE,
        offset: catalogOffset,
      }),
    staleTime: 60_000,
    enabled: mode === "catalog_perfumes",
  });

  // ---------------------------------------------------------------------------
  // Catalog brands query
  // ---------------------------------------------------------------------------
  const catalogBrandsQuery = useQuery({
    queryKey: ["catalog-brands", debouncedSearch, catalogOffset],
    queryFn: () =>
      fetchCatalogBrands({
        q: debouncedSearch || undefined,
        limit: PAGE_SIZE,
        offset: catalogOffset,
      }),
    staleTime: 60_000,
    enabled: mode === "catalog_brands",
  });

  // ---------------------------------------------------------------------------
  // Derived totals / pagination
  // ---------------------------------------------------------------------------
  const currentOffset =
    mode === "active" ? (params.offset ?? 0) : catalogOffset;

  const total =
    mode === "active"
      ? (activeQuery.data?.total ?? 0)
      : mode === "catalog_perfumes"
      ? (catalogPerfumesQuery.data?.total ?? 0)
      : (catalogBrandsQuery.data?.total ?? 0);

  const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  // ---------------------------------------------------------------------------
  // Active mode: client-side name filter (current page only)
  // ---------------------------------------------------------------------------
  const filteredRows = useMemo(() => {
    if (mode !== "active") return [];
    const rows = activeQuery.data?.rows ?? [];
    if (!search) return rows;
    const q = search.toLowerCase();
    return rows.filter(
      (r) =>
        r.canonical_name.toLowerCase().includes(q) ||
        r.ticker.toLowerCase().includes(q) ||
        (r.brand_name ?? "").toLowerCase().includes(q),
    );
  }, [activeQuery.data?.rows, search, mode]);

  const activePreset = detectPreset(params);
  const hasActiveFilters =
    mode === "active" &&
    (params.entity_type ||
      params.signal_type ||
      params.has_signals ||
      params.note ||
      (params.min_score ?? 0) > 0 ||
      (params.min_confidence ?? 0) > 0 ||
      (params.min_mentions ?? 0) > 0);

  // ---------------------------------------------------------------------------
  // Header subtitle — show catalog totals when available
  // ---------------------------------------------------------------------------
  const headerSubtitle = catalogCounts
    ? `${catalogCounts.known_perfumes.toLocaleString()} perfumes · ${catalogCounts.known_brands.toLocaleString()} brands · ${catalogCounts.active_today} active today`
    : mode === "active"
    ? activeQuery.data
      ? `${activeQuery.data.total} active entities`
      : undefined
    : undefined;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isError =
    mode === "active"
      ? activeQuery.isError
      : mode === "catalog_perfumes"
      ? catalogPerfumesQuery.isError
      : catalogBrandsQuery.isError;

  const error =
    mode === "active"
      ? activeQuery.error
      : mode === "catalog_perfumes"
      ? catalogPerfumesQuery.error
      : catalogBrandsQuery.error;

  const refetch =
    mode === "active"
      ? activeQuery.refetch
      : mode === "catalog_perfumes"
      ? catalogPerfumesQuery.refetch
      : catalogBrandsQuery.refetch;

  const isLoading =
    mode === "active"
      ? activeQuery.isLoading
      : mode === "catalog_perfumes"
      ? catalogPerfumesQuery.isLoading
      : catalogBrandsQuery.isLoading;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Screener"
        subtitle={headerSubtitle}
        actions={
          mode === "active" ? (
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
          ) : null
        }
      />

      {/* ── Mode tabs ───────────────────────────────────────────────────── */}
      <div className="flex items-center gap-0 border-b border-zinc-800 bg-zinc-950 px-4">
        {MODE_TABS.map((tab) => (
          <button
            key={tab.key}
            title={tab.hint}
            onClick={() => switchMode(tab.key)}
            className={clsx(
              "border-b-2 px-3 py-2 text-[11px] font-medium transition-colors",
              mode === tab.key
                ? "border-amber-400 text-amber-400"
                : "border-transparent text-zinc-500 hover:text-zinc-300",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Control bar ─────────────────────────────────────────────────── */}
      <ControlBar
        left={
          <div className="flex min-w-0 items-center gap-2 overflow-x-auto">
            {/* Search */}
            <SearchInput
              value={search}
              onChange={handleSearchChange}
              placeholder={
                mode === "active"
                  ? "Search name / ticker…"
                  : mode === "catalog_perfumes"
                  ? "Search perfumes…"
                  : "Search brands…"
              }
              className="w-44 shrink-0"
            />
            {mode === "active" && (
              <>
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
              </>
            )}
            {mode !== "active" && search && (
              <span className="text-[10px] text-zinc-600">
                server-side search
              </span>
            )}
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
            {mode === "active" && activeQuery.data && (
              <>
                <ControlBarDivider />
                <span className="text-[11px] text-zinc-600">
                  {filteredRows.length} shown
                  {search ? ` (filtered from ${activeQuery.data.rows.length})` : ""}
                </span>
              </>
            )}
          </>
        }
      />

      {/* ── Main layout ─────────────────────────────────────────────────── */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Filter sidebar (active mode only) */}
        {filtersOpen && mode === "active" && (
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
                  title={
                    mode === "active"
                      ? "Results"
                      : mode === "catalog_perfumes"
                      ? "Perfume Catalog"
                      : "Brand Catalog"
                  }
                  subtitle={
                    !isLoading
                      ? `${total.toLocaleString()} total · page ${currentPage} of ${totalPages}`
                      : undefined
                  }
                />
              </div>

              {/* Scrollable table */}
              <div className="flex-1 overflow-y-auto">
                {mode === "active" && (
                  <ScreenerTable
                    rows={filteredRows}
                    isLoading={isLoading}
                    sortBy={params.sort_by}
                    order={params.order}
                    onSort={handleSort}
                  />
                )}
                {mode === "catalog_perfumes" && (
                  <CatalogPerfumeTable
                    rows={catalogPerfumesQuery.data?.rows ?? []}
                    isLoading={isLoading}
                  />
                )}
                {mode === "catalog_brands" && (
                  <CatalogBrandTable
                    rows={catalogBrandsQuery.data?.rows ?? []}
                    isLoading={isLoading}
                  />
                )}
              </div>

              {/* Pagination footer */}
              <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-2">
                <span className="text-[11px] text-zinc-500">
                  Showing {currentOffset + 1}–
                  {Math.min(currentOffset + PAGE_SIZE, total)} of{" "}
                  {total.toLocaleString()}
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
