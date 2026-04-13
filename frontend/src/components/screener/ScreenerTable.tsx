"use client";

import { useRouter } from "next/navigation";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { clsx } from "clsx";

import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
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
      return (
        <div className="min-w-0">
          <span className="block truncate max-w-[180px] text-xs text-zinc-200 group-hover:text-amber-300">
            {c.getValue()}
          </span>
          {row.brand_name && (
            <span className="block truncate max-w-[180px] text-[10px] text-zinc-600">
              {row.brand_name}
            </span>
          )}
        </div>
      );
    },
  }),
  col.accessor("entity_type", {
    header: "Type",
    size: 64,
    meta: { sortKey: undefined },
    cell: (c) => {
      const t = c.getValue() ?? "";
      return (
        <span className="inline-flex items-center rounded border border-zinc-700 bg-zinc-800/60 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500">
          {t.charAt(0).toUpperCase() + t.slice(1)}
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
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-zinc-800">
              {hg.headers.map((header) => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              onClick={() =>
                router.push(
                  `/entities/${encodeURIComponent(row.original.entity_id)}`,
                )
              }
              className="group cursor-pointer border-b border-zinc-800/40 transition-colors hover:bg-zinc-800/30"
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3 py-2">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
