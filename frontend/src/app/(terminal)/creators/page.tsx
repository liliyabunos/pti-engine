"use client";

import React, { Suspense, useCallback, useMemo, useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { clsx } from "clsx";

import { fetchCreators, type FetchCreatorsParams, type CreatorRow } from "@/lib/api/creators";
import { fmtCount } from "@/lib/formatters";
import { Header } from "@/components/shell/Header";
import { ControlBar, ControlBarDivider } from "@/components/primitives/ControlBar";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { FilterChip } from "@/components/primitives/FilterChip";
import { ErrorState } from "@/components/primitives/ErrorState";
import { EmptyState } from "@/components/primitives/EmptyState";
import { TableSkeleton } from "@/components/primitives/LoadingSkeleton";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

const SORT_OPTIONS: { key: string; label: string }[] = [
  { key: "influence_score", label: "Influence" },
  { key: "early_signal_count", label: "Early Signals" },
  { key: "avg_views", label: "Avg Views" },
  { key: "total_entity_mentions", label: "Mentions" },
  { key: "unique_entities_mentioned", label: "Entities" },
  { key: "noise_rate", label: "Noise" },
];

const TIER_FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All Tiers" },
  { key: "tier_1", label: "Tier 1" },
  { key: "tier_2", label: "Tier 2" },
  { key: "tier_3", label: "Tier 3" },
  { key: "tier_4", label: "Tier 4" },
];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtInfluence(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(3);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return (v * 100).toFixed(0) + "%";
}

function fmtAvgViews(v: number | null | undefined): string {
  if (v == null) return "—";
  return fmtCount(Math.round(v));
}

function tierLabel(tier: string | null): string {
  if (!tier) return "—";
  return tier.replace("tier_", "T");
}

function tierColor(tier: string | null): string {
  if (!tier) return "text-zinc-600";
  const map: Record<string, string> = {
    tier_1: "text-amber-400",
    tier_2: "text-sky-400",
    tier_3: "text-emerald-400",
    tier_4: "text-zinc-400",
  };
  return map[tier] ?? "text-zinc-500";
}

// ---------------------------------------------------------------------------
// Score bar
// ---------------------------------------------------------------------------

function ScoreBar({ value }: { value: number | null }) {
  const pct = Math.round((value ?? 0) * 100);
  const color =
    pct >= 70 ? "bg-amber-400" : pct >= 40 ? "bg-sky-500" : "bg-zinc-600";
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 text-right tabular-nums text-zinc-200">
        {fmtInfluence(value)}
      </span>
      <div className="h-1.5 w-16 rounded-full bg-zinc-800">
        <div
          className={clsx("h-full rounded-full transition-all", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

const COLS: {
  key: string;
  label: string;
  sortable: boolean;
  align?: "right";
  className?: string;
}[] = [
  { key: "creator_handle", label: "Creator", sortable: false, className: "min-w-[160px]" },
  { key: "influence_score", label: "Influence", sortable: true, align: "right" },
  { key: "subscriber_count", label: "Subscribers", sortable: false, align: "right" },
  { key: "avg_views", label: "Avg Views", sortable: true, align: "right" },
  { key: "total_entity_mentions", label: "Mentions", sortable: true, align: "right" },
  { key: "unique_entities_mentioned", label: "Entities", sortable: true, align: "right" },
  { key: "unique_brands_mentioned", label: "Brands", sortable: false, align: "right" },
  { key: "early_signal_count", label: "Early Signals", sortable: true, align: "right" },
  { key: "noise_rate", label: "Noise Rate", sortable: true, align: "right" },
  { key: "quality_tier", label: "Tier", sortable: false, align: "right" },
  { key: "category", label: "Category", sortable: false },
];

function CreatorTable({
  rows,
  isLoading,
  sortBy,
  order,
  onSort,
}: {
  rows: CreatorRow[];
  isLoading: boolean;
  sortBy: string;
  order: "asc" | "desc";
  onSort: (key: string) => void;
}) {
  if (isLoading) return <TableSkeleton rows={15} cols={COLS.length} />;
  if (!rows.length) {
    return <EmptyState message="No creators found" detail="Adjust filters or try a different sort" />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-wider text-zinc-600">
            {COLS.map((col) => (
              <th
                key={col.key}
                className={clsx(
                  "px-4 py-2 font-medium whitespace-nowrap",
                  col.align === "right" && "text-right",
                  col.sortable && "cursor-pointer select-none hover:text-zinc-400",
                  col.className,
                )}
                onClick={col.sortable ? () => onSort(col.key) : undefined}
              >
                {col.label}
                {col.sortable && sortBy === col.key && (
                  <span className="ml-1 text-amber-400">
                    {order === "desc" ? "↓" : "↑"}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.creator_id}
              className="border-b border-zinc-900 transition-colors hover:bg-zinc-900/50"
            >
              {/* Creator */}
              <td className="px-4 py-2 text-zinc-200">
                <span className="font-medium">
                  {row.creator_handle ?? row.creator_id}
                </span>
              </td>

              {/* Influence Score */}
              <td className="px-4 py-2 text-right">
                <ScoreBar value={row.influence_score} />
              </td>

              {/* Subscribers */}
              <td className="px-4 py-2 text-right tabular-nums text-zinc-400">
                {fmtCount(row.subscriber_count)}
              </td>

              {/* Avg Views */}
              <td className="px-4 py-2 text-right tabular-nums text-zinc-400">
                {fmtAvgViews(row.avg_views)}
              </td>

              {/* Total Mentions */}
              <td className="px-4 py-2 text-right tabular-nums text-zinc-400">
                {row.total_entity_mentions.toLocaleString()}
              </td>

              {/* Unique Entities */}
              <td className="px-4 py-2 text-right tabular-nums text-zinc-400">
                {row.unique_entities_mentioned.toLocaleString()}
              </td>

              {/* Unique Brands */}
              <td className="px-4 py-2 text-right tabular-nums text-zinc-400">
                {row.unique_brands_mentioned.toLocaleString()}
              </td>

              {/* Early Signals */}
              <td className="px-4 py-2 text-right tabular-nums">
                <span
                  className={clsx(
                    row.early_signal_count > 5
                      ? "text-amber-400"
                      : row.early_signal_count > 0
                      ? "text-zinc-300"
                      : "text-zinc-600",
                  )}
                >
                  {row.early_signal_count}
                </span>
              </td>

              {/* Noise Rate */}
              <td className="px-4 py-2 text-right tabular-nums text-zinc-500">
                {fmtPct(row.noise_rate)}
              </td>

              {/* Tier */}
              <td className={clsx("px-4 py-2 text-right font-semibold", tierColor(row.quality_tier))}>
                {tierLabel(row.quality_tier)}
              </td>

              {/* Category */}
              <td className="px-4 py-2 text-zinc-500 capitalize">
                {row.category ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

function paramsToSearch(p: FetchCreatorsParams): string {
  const q = new URLSearchParams();
  if (p.sort_by && p.sort_by !== "influence_score") q.set("sort_by", p.sort_by);
  if (p.order && p.order !== "desc") q.set("order", p.order);
  if (p.quality_tier) q.set("tier", p.quality_tier);
  if (p.category) q.set("category", p.category);
  if (p.offset && p.offset > 0) q.set("offset", String(p.offset));
  return q.toString();
}

function searchToParams(sp: URLSearchParams): FetchCreatorsParams {
  return {
    sort_by: sp.get("sort_by") ?? "influence_score",
    order: (sp.get("order") as "asc" | "desc") ?? "desc",
    quality_tier: sp.get("tier") ?? undefined,
    category: sp.get("category") ?? undefined,
    offset: Number(sp.get("offset") ?? 0),
    limit: PAGE_SIZE,
  };
}

// ---------------------------------------------------------------------------
// Inner page
// ---------------------------------------------------------------------------

function CreatorsPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [params, setParams] = useState<FetchCreatorsParams>(() =>
    searchToParams(searchParams),
  );

  const pushParams = useCallback(
    (next: FetchCreatorsParams) => {
      const qs = paramsToSearch(next);
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [pathname, router],
  );

  const updateParams = useCallback(
    (updates: Partial<FetchCreatorsParams>) => {
      const next: FetchCreatorsParams = { ...params, ...updates, offset: 0 };
      setParams(next);
      pushParams(next);
    },
    [params, pushParams],
  );

  const handleSort = useCallback(
    (key: string) => {
      const newOrder =
        params.sort_by === key && params.order === "desc" ? "asc" : "desc";
      updateParams({ sort_by: key, order: newOrder });
    },
    [params.sort_by, params.order, updateParams],
  );

  const goPage = useCallback(
    (delta: number) => {
      const next: FetchCreatorsParams = {
        ...params,
        offset: (params.offset ?? 0) + delta * PAGE_SIZE,
      };
      setParams(next);
      pushParams(next);
    },
    [params, pushParams],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["creators", params],
    queryFn: () => fetchCreators(params),
    staleTime: 60_000,
  });

  // Derive unique categories from loaded data for dynamic filter
  const categories = useMemo(() => {
    if (!data?.creators) return [];
    const cats = new Set<string>();
    data.creators.forEach((c) => {
      if (c.category) cats.add(c.category);
    });
    return Array.from(cats).sort();
  }, [data?.creators]);

  const total = data?.total ?? 0;
  const offset = params.offset ?? 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Creators"
        subtitle={
          data
            ? `${data.total.toLocaleString()} creators tracked`
            : undefined
        }
      />

      {/* ── Control bar ──────────────────────────────────────────────────── */}
      <ControlBar
        left={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {/* Sort */}
            <div className="flex items-center gap-1">
              <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                Sort
              </span>
              <div className="flex items-center gap-0.5">
                {SORT_OPTIONS.map((opt) => (
                  <FilterChip
                    key={opt.key}
                    label={opt.label}
                    active={params.sort_by === opt.key}
                    onClick={() => handleSort(opt.key)}
                  />
                ))}
              </div>
            </div>

            <ControlBarDivider />

            {/* Tier filter */}
            <div className="flex items-center gap-1">
              <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                Tier
              </span>
              <div className="flex items-center gap-0.5">
                {TIER_FILTERS.map((t) => (
                  <FilterChip
                    key={t.key}
                    label={t.label}
                    active={(params.quality_tier ?? "") === t.key}
                    onClick={() =>
                      updateParams({ quality_tier: t.key || undefined })
                    }
                  />
                ))}
              </div>
            </div>

            {/* Category filter — only if categories are available */}
            {categories.length > 0 && (
              <>
                <ControlBarDivider />
                <div className="flex items-center gap-1">
                  <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                    Category
                  </span>
                  <div className="flex items-center gap-0.5">
                    <FilterChip
                      label="All"
                      active={!params.category}
                      onClick={() => updateParams({ category: undefined })}
                    />
                    {categories.map((cat) => (
                      <FilterChip
                        key={cat}
                        label={cat.charAt(0).toUpperCase() + cat.slice(1)}
                        active={params.category === cat}
                        onClick={() => updateParams({ category: cat })}
                      />
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        }
        right={
          data && (
            <span className="text-[11px] text-zinc-600">
              {total} creators
            </span>
          )
        }
      />

      {/* ── Main ─────────────────────────────────────────────────────────── */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
        {isError ? (
          <ErrorState
            message={String(error)}
            onRetry={() => refetch()}
          />
        ) : (
          <TerminalPanel noPad className="flex flex-1 flex-col overflow-hidden">
            {/* Panel header */}
            <div className="flex items-center justify-between px-4 py-3">
              <SectionHeader
                title="Creator Leaderboard"
                subtitle={
                  !isLoading
                    ? `${total.toLocaleString()} total · page ${currentPage} of ${totalPages}`
                    : undefined
                }
              />
            </div>

            {/* Caption */}
            <div className="px-4 pb-2">
              <p className="text-[11px] text-zinc-600">
                Influence Score combines reach, entity relevance, mention volume,
                early-signal behavior, engagement, and low-noise quality.
              </p>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-y-auto">
              <CreatorTable
                rows={data?.creators ?? []}
                isLoading={isLoading}
                sortBy={params.sort_by ?? "influence_score"}
                order={params.order ?? "desc"}
                onSort={handleSort}
              />
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-2">
              <span className="text-[11px] text-zinc-500">
                Showing {total === 0 ? 0 : offset + 1}–
                {Math.min(offset + PAGE_SIZE, total)} of{" "}
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
  );
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export default function CreatorsPage() {
  return (
    <Suspense>
      <CreatorsPageInner />
    </Suspense>
  );
}
