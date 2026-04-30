"use client";

import React, { useCallback, useState, Suspense } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  X,
  Search,
} from "lucide-react";
import { clsx } from "clsx";

import { fetchScreener } from "@/lib/api/screener";
import { fetchCatalogPerfumes, fetchCatalogBrands, fetchCatalogCounts } from "@/lib/api/catalog";
import { fetchTopNotes, fetchTopAccords } from "@/lib/api/notes";
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
import type { ScreenerParams, CatalogPerfumeRow, CatalogBrandRow, NoteRow, AccordRow } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Architecture:
//   Layer "market"      → modes: active | catalog_perfumes | catalog_brands
//   Layer "composition" → modes: notes | accords
//
// Search is server-side in all modes.
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

type ScreenerLayer = "market" | "composition";
type MarketMode = "active" | "catalog_perfumes" | "catalog_brands";
type CompositionMode = "notes" | "accords";
type ScreenerMode = MarketMode | CompositionMode;

// Preset configurations for active market mode
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
// URL param serialization
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

function modeToLayer(mode: ScreenerMode): ScreenerLayer {
  return mode === "notes" || mode === "accords" ? "composition" : "market";
}

// ---------------------------------------------------------------------------
// Catalog tables (perfumes / brands)
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
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-wider text-zinc-600">
          <th className="px-4 py-2 font-medium">Perfume</th>
          <th className="px-4 py-2 font-medium">Brand</th>
          <th className="px-4 py-2 font-medium">Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.resolver_id}
            onClick={() =>
              router.push(
                row.entity_id
                  ? `/entities/perfume/${row.entity_id}`
                  : `/entities/perfume/${row.resolver_id}`,
              )
            }
            className="cursor-pointer border-b border-zinc-900 transition-colors hover:bg-zinc-900"
          >
            <td className="px-4 py-2 text-zinc-200">{row.canonical_name}</td>
            <td className="px-4 py-2 text-zinc-500">{row.brand_name ?? "—"}</td>
            <td className="px-4 py-2">
              {row.entity_id ? (
                <span className="rounded border border-emerald-800 bg-emerald-950 px-1.5 py-0.5 text-[10px] text-emerald-400">
                  Tracked
                </span>
              ) : (
                <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-500">
                  In Catalog
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
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
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-wider text-zinc-600">
          <th className="px-4 py-2 font-medium">Brand</th>
          <th className="px-4 py-2 font-medium">Perfumes</th>
          <th className="px-4 py-2 font-medium">Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.resolver_id}
            onClick={() =>
              router.push(
                row.entity_id
                  ? `/entities/brand/${row.entity_id}`
                  : `/entities/brand/${row.resolver_id}`,
              )
            }
            className="cursor-pointer border-b border-zinc-900 transition-colors hover:bg-zinc-900"
          >
            <td className="px-4 py-2 text-zinc-200">{row.canonical_name}</td>
            <td className="px-4 py-2 text-zinc-500">{row.perfume_count.toLocaleString()}</td>
            <td className="px-4 py-2">
              {row.entity_id ? (
                <span className="rounded border border-emerald-800 bg-emerald-950 px-1.5 py-0.5 text-[10px] text-emerald-400">
                  Tracked
                </span>
              ) : (
                <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-500">
                  In Catalog
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// Composition tables (notes / accords)
// ---------------------------------------------------------------------------

function NotesTable({
  rows,
  isLoading,
  search,
}: {
  rows: NoteRow[];
  isLoading: boolean;
  search: string;
}) {
  const router = useRouter();
  const filtered = search
    ? rows.filter((r) => r.note_name.toLowerCase().includes(search.toLowerCase()))
    : rows;

  if (isLoading) return <TableSkeleton rows={15} cols={2} />;
  if (!filtered.length) {
    return <EmptyState message="No notes found" detail="Try a different search term" />;
  }

  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-wider text-zinc-600">
          <th className="px-4 py-2 font-medium">Note</th>
          <th className="px-4 py-2 font-medium text-right">Perfumes</th>
        </tr>
      </thead>
      <tbody>
        {filtered.map((row) => (
          <tr
            key={row.note_name}
            onClick={() => router.push(`/entities/note/${encodeURIComponent(row.note_name)}`)}
            className="cursor-pointer border-b border-zinc-900 transition-colors hover:bg-zinc-900"
          >
            <td className="px-4 py-2 text-zinc-200">{row.note_name}</td>
            <td className="px-4 py-2 text-right tabular-nums text-zinc-500">
              {row.perfume_count.toLocaleString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AccordsTable({
  rows,
  isLoading,
  search,
}: {
  rows: AccordRow[];
  isLoading: boolean;
  search: string;
}) {
  const router = useRouter();
  const filtered = search
    ? rows.filter((r) => r.accord_name.toLowerCase().includes(search.toLowerCase()))
    : rows;

  if (isLoading) return <TableSkeleton rows={15} cols={2} />;
  if (!filtered.length) {
    return <EmptyState message="No accords found" detail="Try a different search term" />;
  }

  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-wider text-zinc-600">
          <th className="px-4 py-2 font-medium">Accord</th>
          <th className="px-4 py-2 font-medium text-right">Perfumes</th>
        </tr>
      </thead>
      <tbody>
        {filtered.map((row) => (
          <tr
            key={row.accord_name}
            onClick={() => router.push(`/entities/accord/${encodeURIComponent(row.accord_name)}`)}
            className="cursor-pointer border-b border-zinc-900 transition-colors hover:bg-zinc-900"
          >
            <td className="px-4 py-2 text-violet-300">{row.accord_name}</td>
            <td className="px-4 py-2 text-right tabular-nums text-zinc-500">
              {row.perfume_count.toLocaleString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// Active Today empty state
// ---------------------------------------------------------------------------

function ActiveEmptyState({
  search,
  onSearchCatalog,
}: {
  search: string;
  onSearchCatalog: () => void;
}) {
  if (!search) {
    return <EmptyState message="No active entities" detail="No market data for this period" />;
  }
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <p className="text-sm text-zinc-400">
        No active entities match{" "}
        <span className="font-mono text-zinc-200">&ldquo;{search}&rdquo;</span>
      </p>
      <p className="mt-1 text-xs text-zinc-600">
        This entity may exist in the catalog but has no market signal today.
      </p>
      <button
        onClick={onSearchCatalog}
        className="mt-4 flex items-center gap-1.5 rounded border border-zinc-700 px-3 py-1.5 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
      >
        <Search size={11} />
        Search full catalog for &ldquo;{search}&rdquo;
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

const LAYER_TABS: { key: ScreenerLayer; label: string; hint: string }[] = [
  { key: "market", label: "Market", hint: "Perfumes and brands — scored, ranked, signalled" },
  { key: "composition", label: "Notes & Accords", hint: "Ingredient intelligence — explains why entities move" },
];

const MARKET_TABS: { key: MarketMode; label: string; hint: string }[] = [
  { key: "active", label: "Active today", hint: "Entities with market signal data" },
  { key: "catalog_perfumes", label: "All Perfumes", hint: "56k+ perfumes in KB" },
  { key: "catalog_brands", label: "All Brands", hint: "Full brand catalog" },
];

const COMPOSITION_TABS: { key: CompositionMode; label: string; hint: string }[] = [
  { key: "notes", label: "Notes", hint: "Ingredient notes across perfume catalog" },
  { key: "accords", label: "Accords", hint: "Scent accords across perfume catalog" },
];

// ---------------------------------------------------------------------------
// Inner page
// ---------------------------------------------------------------------------

function ScreenerPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const urlMode = (searchParams.get("mode") as ScreenerMode) ?? "active";
  const [mode, setMode] = useState<ScreenerMode>(urlMode);
  const layer = modeToLayer(mode);

  const [params, setParams] = useState<ScreenerParams>(() =>
    searchToParams(searchParams),
  );

  // Search — server-side in market modes; client-side filter for notes/accords (already loaded)
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const debounceRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedSearch(value);
      setParams((prev) => ({ ...prev, offset: 0 }));
    }, 300);
  }, []);

  const [catalogOffset, setCatalogOffset] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(false);

  // ---------------------------------------------------------------------------
  // URL / param sync
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
    (nextMode: ScreenerMode, keepSearch = false) => {
      setMode(nextMode);
      if (!keepSearch) {
        setSearch("");
        setDebouncedSearch("");
      }
      setCatalogOffset(0);
      pushParams(params, nextMode);
    },
    [params, pushParams],
  );

  const switchLayer = useCallback(
    (nextLayer: ScreenerLayer) => {
      const defaultMode: ScreenerMode =
        nextLayer === "market" ? "active" : "notes";
      setSearch("");
      setDebouncedSearch("");
      setCatalogOffset(0);
      setMode(defaultMode);
      pushParams(params, defaultMode);
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
      entity_type: undefined,
      signal_type: undefined,
      has_signals: undefined,
      min_score: undefined,
      min_confidence: undefined,
      min_mentions: undefined,
    };
    setSearch("");
    setDebouncedSearch("");
    setParams(next);
    pushParams(next, mode);
    setFiltersOpen(false);
  }, [pushParams, mode]);

  const handleSearchCatalog = useCallback(() => {
    switchMode("catalog_perfumes", true);
  }, [switchMode]);

  const goPage = useCallback(
    (delta: number) => {
      if (layer === "market") {
        if (mode === "active") {
          const next = { ...params, offset: (params.offset ?? 0) + delta * PAGE_SIZE };
          setParams(next);
          pushParams(next, mode);
        } else {
          setCatalogOffset((o) => o + delta * PAGE_SIZE);
        }
      }
    },
    [layer, mode, params, pushParams],
  );

  // ---------------------------------------------------------------------------
  // Queries — Market
  // ---------------------------------------------------------------------------

  const activeQuery = useQuery({
    queryKey: ["screener", params, debouncedSearch],
    queryFn: () => fetchScreener({ ...params, q: debouncedSearch || undefined }),
    staleTime: 30_000,
    enabled: mode === "active",
  });

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

  const { data: catalogCounts } = useQuery({
    queryKey: ["catalog-counts"],
    queryFn: fetchCatalogCounts,
    staleTime: 5 * 60_000,
  });

  // ---------------------------------------------------------------------------
  // Queries — Composition (load once, filter client-side)
  // ---------------------------------------------------------------------------

  const notesQuery = useQuery({
    queryKey: ["screener-notes"],
    queryFn: () => fetchTopNotes(200),
    staleTime: 10 * 60_000,
    enabled: layer === "composition",
  });

  const accordsQuery = useQuery({
    queryKey: ["screener-accords"],
    queryFn: () => fetchTopAccords(200),
    staleTime: 10 * 60_000,
    enabled: layer === "composition",
  });

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const currentOffset =
    mode === "active" ? (params.offset ?? 0) : catalogOffset;

  const total =
    mode === "active"
      ? (activeQuery.data?.total ?? 0)
      : mode === "catalog_perfumes"
      ? (catalogPerfumesQuery.data?.total ?? 0)
      : mode === "catalog_brands"
      ? (catalogBrandsQuery.data?.total ?? 0)
      : mode === "notes"
      ? (notesQuery.data?.length ?? 0)
      : (accordsQuery.data?.length ?? 0);

  const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  const activeRows = activeQuery.data?.rows ?? [];
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

  const headerSubtitle = catalogCounts
    ? `${catalogCounts.known_perfumes.toLocaleString()} perfumes · ${catalogCounts.known_brands.toLocaleString()} brands · ${catalogCounts.active_today} active today`
    : mode === "active"
    ? activeQuery.data
      ? `${activeQuery.data.total} active entities`
      : undefined
    : undefined;

  const isError =
    mode === "active"
      ? activeQuery.isError
      : mode === "catalog_perfumes"
      ? catalogPerfumesQuery.isError
      : mode === "catalog_brands"
      ? catalogBrandsQuery.isError
      : false;

  const error =
    mode === "active"
      ? activeQuery.error
      : mode === "catalog_perfumes"
      ? catalogPerfumesQuery.error
      : mode === "catalog_brands"
      ? catalogBrandsQuery.error
      : null;

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
      : mode === "catalog_brands"
      ? catalogBrandsQuery.isLoading
      : mode === "notes"
      ? notesQuery.isLoading
      : accordsQuery.isLoading;

  const panelTitle =
    mode === "active" ? "Results"
    : mode === "catalog_perfumes" ? "Perfume Catalog"
    : mode === "catalog_brands" ? "Brand Catalog"
    : mode === "notes" ? "Notes"
    : "Accords";

  // For composition, total is the filtered count (client-side)
  const compositionTotal = layer === "composition"
    ? (mode === "notes"
        ? (notesQuery.data ?? []).filter((r) =>
            !search || r.note_name.toLowerCase().includes(search.toLowerCase())
          ).length
        : (accordsQuery.data ?? []).filter((r) =>
            !search || r.accord_name.toLowerCase().includes(search.toLowerCase())
          ).length)
    : total;

  const displayTotal = layer === "composition" ? compositionTotal : total;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

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

      {/* ── Layer tabs (Market | Notes & Accords) ───────────────────────── */}
      <div className="flex items-center gap-0 border-b border-zinc-800 bg-zinc-950 px-4">
        {LAYER_TABS.map((tab) => (
          <button
            key={tab.key}
            title={tab.hint}
            onClick={() => switchLayer(tab.key)}
            className={clsx(
              "border-b-2 px-4 py-2.5 text-[12px] font-semibold transition-colors",
              layer === tab.key
                ? "border-amber-400 text-amber-400"
                : "border-transparent text-zinc-500 hover:text-zinc-300",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Sub-tabs ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-0 border-b border-zinc-800/60 bg-zinc-950 px-4">
        {(layer === "market" ? MARKET_TABS : COMPOSITION_TABS).map((tab) => (
          <button
            key={tab.key}
            title={tab.hint}
            onClick={() => switchMode(tab.key as ScreenerMode)}
            className={clsx(
              "border-b-2 px-3 py-2 text-[11px] font-medium transition-colors",
              mode === tab.key
                ? layer === "composition"
                  ? "border-violet-400 text-violet-400"
                  : "border-sky-400 text-sky-400"
                : "border-transparent text-zinc-600 hover:text-zinc-400",
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
            <SearchInput
              value={search}
              onChange={handleSearchChange}
              placeholder={
                mode === "active"
                  ? "Search name / brand / ticker…"
                  : mode === "catalog_perfumes"
                  ? "Search perfumes…"
                  : mode === "catalog_brands"
                  ? "Search brands…"
                  : mode === "notes"
                  ? "Filter notes…"
                  : "Filter accords…"
              }
              className="w-48 shrink-0"
            />
            {mode === "active" && (
              <>
                <ControlBarDivider />
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
          </div>
        }
        right={
          <>
            {(hasActiveFilters || search) && (
              <button
                onClick={resetAll}
                className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-300"
              >
                <X size={11} />
                Clear
              </button>
            )}
            {mode === "active" && activeQuery.data && (
              <>
                <ControlBarDivider />
                <span className="text-[11px] text-zinc-600">
                  {total} shown
                </span>
              </>
            )}
          </>
        }
      />

      {/* ── Main layout ─────────────────────────────────────────────────── */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Filter sidebar (active market mode only) */}
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
                  title={panelTitle}
                  subtitle={
                    !isLoading
                      ? layer === "composition"
                        ? `${displayTotal.toLocaleString()} ${mode === "notes" ? "notes" : "accords"}`
                        : `${displayTotal.toLocaleString()} total · page ${currentPage} of ${totalPages}`
                      : undefined
                  }
                />
              </div>

              {/* Scrollable table */}
              <div className="flex-1 overflow-y-auto">
                {/* Market modes */}
                {mode === "active" && (
                  activeQuery.isFetched && activeRows.length === 0 ? (
                    <ActiveEmptyState
                      search={debouncedSearch}
                      onSearchCatalog={handleSearchCatalog}
                    />
                  ) : (
                    <ScreenerTable
                      rows={activeRows}
                      isLoading={isLoading}
                      sortBy={params.sort_by}
                      order={params.order}
                      onSort={handleSort}
                    />
                  )
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

                {/* Composition modes */}
                {mode === "notes" && (
                  <NotesTable
                    rows={notesQuery.data ?? []}
                    isLoading={notesQuery.isLoading}
                    search={search}
                  />
                )}
                {mode === "accords" && (
                  <AccordsTable
                    rows={accordsQuery.data ?? []}
                    isLoading={accordsQuery.isLoading}
                    search={search}
                  />
                )}
              </div>

              {/* Pagination footer — only for market modes */}
              {layer === "market" && (
                <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-2">
                  <span className="text-[11px] text-zinc-500">
                    Showing {total === 0 ? 0 : currentOffset + 1}–
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
              )}
            </TerminalPanel>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page export
// ---------------------------------------------------------------------------

export default function ScreenerPage() {
  return (
    <Suspense>
      <ScreenerPageInner />
    </Suspense>
  );
}
