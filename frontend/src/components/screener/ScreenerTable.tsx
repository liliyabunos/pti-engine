"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import { ChevronUp, ChevronDown, ChevronsUpDown, Bookmark } from "lucide-react";
import { clsx } from "clsx";

import { AddToWatchlistModal } from "@/components/entity/AddToWatchlistModal";

import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { TrendStateBadge } from "@/components/primitives/TrendStateBadge";
import { TableSkeleton } from "@/components/primitives/LoadingSkeleton";
import { EmptyState } from "@/components/primitives/EmptyState";
import {
  fmtScore,
  fmtGrowth,
  fmtMomentum,
  fmtCount,
  fmtConfidence,
  fmtVolatility,
} from "@/lib/formatters";
import type { EntitySummary } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

const col = createColumnHelper<EntitySummary>();

const COLUMNS = [
  col.accessor("ticker", {
    header: "Ticker",
    size: 60,
    meta: { sortKey: undefined },
    cell: (c) => (
      <span className="font-mono text-[11px] font-bold text-amber-400">
        {c.getValue()}
      </span>
    ),
  }),
  col.accessor("canonical_name", {
    header: "Name",
    meta: { sortKey: undefined },
    cell: (c) => {
      const row = c.row.original;
      const isBrand = row.entity_type === "brand";
      return (
        <div className="min-w-0">
          <span
            title={isBrand ? "Brand — score aggregated across perfume portfolio" : undefined}
            className="block truncate max-w-[180px] text-xs text-zinc-200 group-hover:text-amber-300"
          >
            {c.getValue()}
          </span>
          {isBrand ? (
            <span className="block text-[10px] text-sky-700/70">
              portfolio aggregate
            </span>
          ) : row.brand_name ? (
            <span className="block truncate max-w-[180px] text-[10px] text-zinc-600">
              {row.brand_name}
            </span>
          ) : null}
        </div>
      );
    },
  }),
  col.accessor("entity_type", {
    header: "Type",
    size: 72,
    meta: { sortKey: undefined },
    cell: (c) => {
      const t = c.getValue() ?? "";
      if (t === "brand") {
        return (
          <span
            title="Brand — composite score aggregated across perfume portfolio"
            className="inline-flex cursor-default items-center rounded border border-sky-800/70 bg-sky-950/40 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-sky-400"
          >
            Brand
          </span>
        );
      }
      return (
        <span
          title="Individual fragrance"
          className="inline-flex cursor-default items-center rounded border border-zinc-700 bg-zinc-800/60 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500"
        >
          Perfume
        </span>
      );
    },
  }),
  col.accessor("composite_market_score", {
    header: "Score",
    size: 64,
    meta: { sortKey: "composite_market_score" },
    cell: (c) => (
      <span className="text-xs font-semibold tabular-nums text-zinc-100">
        {fmtScore(c.getValue())}
      </span>
    ),
  }),
  col.accessor("growth_rate", {
    header: "Growth",
    size: 80,
    meta: { sortKey: "growth_rate" },
    cell: (c) => (
      <DeltaBadge value={c.getValue()} formatted={fmtGrowth(c.getValue())} />
    ),
  }),
  col.accessor("mention_count", {
    header: "Ment.",
    size: 60,
    meta: { sortKey: "mention_count" },
    cell: (c) => (
      <span className="text-xs tabular-nums text-zinc-400">
        {fmtCount(c.getValue())}
      </span>
    ),
  }),
  col.accessor("confidence_avg", {
    header: "Conf.",
    size: 56,
    meta: { sortKey: "confidence_avg" },
    cell: (c) => (
      <span className="text-xs tabular-nums text-zinc-500">
        {fmtConfidence(c.getValue())}
      </span>
    ),
  }),
  col.accessor("momentum", {
    header: "Mom.",
    size: 60,
    meta: { sortKey: "momentum" },
    cell: (c) => (
      <span className="text-xs tabular-nums text-zinc-400">
        {fmtMomentum(c.getValue())}
      </span>
    ),
  }),
  col.accessor("volatility", {
    header: "Vol.",
    size: 56,
    meta: { sortKey: "volatility" },
    cell: (c) => (
      <span className="text-xs tabular-nums text-zinc-500">
        {fmtVolatility(c.getValue())}
      </span>
    ),
  }),
  col.accessor("latest_signal_type", {
    header: "Signal",
    size: 110,
    meta: { sortKey: undefined },
    cell: (c) => <SignalBadge type={c.getValue()} />,
  }),
  col.accessor("trend_state", {
    header: "Trend",
    size: 76,
    meta: { sortKey: undefined },
    cell: (c) => <TrendStateBadge state={c.getValue()} />,
  }),
  col.accessor("top_notes", {
    header: "Notes",
    size: 160,
    meta: { sortKey: undefined },
    cell: (c) => {
      const notes = c.getValue() ?? [];
      if (!notes.length) return <span className="text-zinc-700">—</span>;
      return (
        <div className="flex flex-wrap gap-0.5">
          {notes.slice(0, 3).map((n) => (
            <span
              key={n}
              className="inline-flex rounded border border-zinc-700 bg-zinc-800/40 px-1 py-0 text-[9px] text-zinc-500"
            >
              {n}
            </span>
          ))}
        </div>
      );
    },
  }),
];

// ---------------------------------------------------------------------------
// Sort indicator icon
// ---------------------------------------------------------------------------

function SortIcon({
  active,
  direction,
}: {
  active: boolean;
  direction?: "asc" | "desc";
}) {
  if (!active) return <ChevronsUpDown size={10} className="opacity-30" />;
  return direction === "asc" ? (
    <ChevronUp size={10} className="text-amber-400" />
  ) : (
    <ChevronDown size={10} className="text-amber-400" />
  );
}

// ---------------------------------------------------------------------------
// ScreenerTable
// ---------------------------------------------------------------------------

interface ScreenerTableProps {
  rows: EntitySummary[];
  isLoading?: boolean;
  sortBy?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
}

export function ScreenerTable({
  rows,
  isLoading,
  sortBy,
  order,
  onSort,
}: ScreenerTableProps) {
  const router = useRouter();
  const [watchTarget, setWatchTarget] = useState<{
    entityId: string;
    entityType: string;
    canonicalName: string;
  } | null>(null);

  const table = useReactTable({
    data: rows,
    columns: COLUMNS,
    getCoreRowModel: getCoreRowModel(),
  });

  if (isLoading) {
    return <TableSkeleton rows={10} cols={10} />;
  }

  if (!rows.length) {
    return (
      <EmptyState
        message="No entities match the current filters"
        detail="Try adjusting the filter criteria or clearing filters"
      />
    );
  }

  return (
    <>
      {watchTarget && (
        <AddToWatchlistModal
          entityId={watchTarget.entityId}
          entityType={watchTarget.entityType}
          canonicalName={watchTarget.canonicalName}
          onClose={() => setWatchTarget(null)}
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-zinc-800">
                {hg.headers.map((header) => {
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  const sk: string | undefined = (header.column.columnDef as any).meta?.sortKey;
                  const isSortable = !!sk;
                  const isActive = sortBy === sk;

                  return (
                    <th
                      key={header.id}
                      style={{ width: header.getSize() }}
                      className={clsx(
                        "px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500",
                        isSortable &&
                          "cursor-pointer select-none hover:text-zinc-300",
                        isActive && "text-zinc-300",
                      )}
                      onClick={() => {
                        if (isSortable && sk) onSort?.(sk);
                      }}
                    >
                      <span className="inline-flex items-center gap-0.5">
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                        {isSortable && (
                          <SortIcon
                            active={isActive}
                            direction={isActive ? order : undefined}
                          />
                        )}
                      </span>
                    </th>
                  );
                })}
                {/* Watch column header */}
                <th className="w-8 px-2 py-2" />
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const isBrand = row.original.entity_type === "brand";
              return (
                <tr
                  key={row.id}
                  onClick={() => {
                    const { entity_id, entity_type } = row.original;
                    const path =
                      entity_type === "brand"
                        ? `/entities/brand/${encodeURIComponent(entity_id)}`
                        : entity_type === "perfume"
                        ? `/entities/perfume/${encodeURIComponent(entity_id)}`
                        : `/entities/${encodeURIComponent(entity_id)}`;
                    router.push(path);
                  }}
                  className={clsx(
                    "group cursor-pointer border-b border-zinc-800/40 transition-colors",
                    isBrand ? "hover:bg-sky-950/10" : "hover:bg-zinc-800/30",
                  )}
                >
                  {row.getVisibleCells().map((cell, ci) => (
                    <td
                      key={cell.id}
                      className={clsx(
                        "px-3 py-2",
                        ci === 0 && isBrand && "border-l-2 border-sky-800/50",
                        ci === 0 && !isBrand && "border-l-2 border-transparent",
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                  {/* Watch button cell */}
                  <td
                    className="px-2 py-2"
                    onClick={(e) => {
                      e.stopPropagation();
                      setWatchTarget({
                        entityId: row.original.entity_id,
                        entityType: row.original.entity_type,
                        canonicalName: row.original.canonical_name,
                      });
                    }}
                  >
                    <button
                      title="Add to watchlist"
                      className="text-zinc-700 opacity-0 transition-opacity group-hover:opacity-100 hover:text-amber-400"
                    >
                      <Bookmark size={12} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
