"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type ColumnDef,
} from "@tanstack/react-table";
import { useState } from "react";
import { ChevronUp, ChevronDown } from "lucide-react";
import { clsx } from "clsx";

import { DeltaBadge } from "@/components/primitives/DeltaBadge";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { EmptyState } from "@/components/primitives/EmptyState";
import {
  fmtScore,
  fmtGrowth,
  fmtCount,
  fmtConfidence,
} from "@/lib/formatters";
import type { TopMoverRow } from "@/lib/api/types";

// Entity type pill — brand gets a distinct sky-blue tint
function EntityTypePill({ type }: { type: string }) {
  if (type === "brand") {
    return (
      <span
        title="Brand — composite score aggregated across perfume portfolio"
        className="ml-1 inline-flex cursor-default items-center rounded border border-sky-800/70 bg-sky-950/40 px-1 py-px text-[8px] font-semibold uppercase tracking-wide text-sky-500"
      >
        Brand
      </span>
    );
  }
  return null;
}

// Dampening pill shown next to score for single-author entities
function DampenedPill() {
  return (
    <span
      title="Flood-dampened: single author/post — effective score reduced"
      className="ml-1 rounded px-1 py-px text-[8px] font-semibold uppercase tracking-wide text-zinc-600 border border-zinc-700 cursor-default"
    >
      1×
    </span>
  );
}

// Variant merge badge shown next to entity name
function VariantBadge({ count, names }: { count: number; names: string[] }) {
  return (
    <span
      title={`Includes ${count} concentration variant${count > 1 ? "s" : ""}:\n${names.join("\n")}`}
      className="ml-1 inline-flex items-center rounded px-1 py-px text-[8px] font-semibold text-amber-600 border border-amber-900/50 cursor-default"
    >
      +{count}v
    </span>
  );
}

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

const col = createColumnHelper<TopMoverRow>();

function buildColumns(
  selectedId: string | null,
  onSelect: (id: string) => void,
) {
  return [
    col.accessor("rank", {
      header: "#",
      size: 28,
      enableSorting: false,
      cell: (c) => (
        <span className="text-[10px] tabular-nums text-zinc-600">
          {c.getValue()}
        </span>
      ),
    }),
    col.accessor("ticker", {
      header: "Ticker",
      size: 60,
      enableSorting: false,
      cell: (c) => (
        <span className="font-mono text-[11px] font-bold text-amber-400">
          {c.getValue()}
        </span>
      ),
    }),
    col.accessor("canonical_name", {
      header: "Name",
      enableSorting: true,
      cell: (c) => {
        const row = c.row.original;
        const hasVariants = row.variant_names && row.variant_names.length > 0;
        const isBrand = row.entity_type === "brand";
        return (
          <div className="min-w-0">
            <span className="inline-flex items-center">
              <span
                title={isBrand ? "Brand — score aggregated across perfume portfolio" : row.canonical_name}
                className="block truncate max-w-[150px] text-xs text-zinc-200 group-hover:text-amber-200 group-hover:underline"
              >
                {c.getValue()}
              </span>
              {hasVariants && (
                <VariantBadge
                  count={row.variant_names.length}
                  names={row.variant_names}
                />
              )}
              <EntityTypePill type={row.entity_type} />
            </span>
            {row.brand_name && !isBrand && (
              <span className="block truncate max-w-[160px] text-[10px] text-zinc-600">
                {row.brand_name}
              </span>
            )}
            {isBrand && (
              <span className="block text-[10px] text-sky-700/70">
                portfolio aggregate
              </span>
            )}
          </div>
        );
      },
    }),
    col.accessor("effective_rank_score", {
      header: "Score",
      size: 72,
      cell: (c) => {
        const row = c.row.original;
        return (
          <span className="inline-flex items-center">
            <span
              className={`text-xs font-semibold tabular-nums ${
                row.is_flood_dampened ? "text-zinc-400" : "text-zinc-100"
              }`}
            >
              {fmtScore(c.getValue())}
            </span>
            {row.is_flood_dampened && <DampenedPill />}
          </span>
        );
      },
    }),
    col.accessor("mention_count", {
      header: "Ment.",
      size: 52,
      cell: (c) => (
        <span className="text-xs tabular-nums text-zinc-400">
          {fmtCount(c.getValue())}
        </span>
      ),
    }),
    col.accessor("growth_rate", {
      header: "Growth",
      size: 68,
      cell: (c) => (
        <DeltaBadge value={c.getValue()} formatted={fmtGrowth(c.getValue())} />
      ),
    }),
    col.accessor("confidence_avg", {
      header: "Conf.",
      size: 50,
      cell: (c) => (
        <span className="text-xs tabular-nums text-zinc-500">
          {fmtConfidence(c.getValue())}
        </span>
      ),
    }),
    col.accessor("latest_signal", {
      header: "Signal",
      size: 96,
      enableSorting: false,
      cell: (c) => <SignalBadge type={c.getValue()} />,
    }),
    {
      id: "_nav",
      size: 16,
      enableSorting: false,
      header: () => null,
      cell: () => (
        <span className="text-[11px] text-zinc-600 opacity-0 transition-opacity group-hover:opacity-100">
          →
        </span>
      ),
    } as ColumnDef<TopMoverRow>,
  ];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TopMoversTableProps {
  rows: TopMoverRow[];
  selectedId: string | null;
  onSelect: (entityId: string) => void;
}

function entityHref(row: TopMoverRow): string {
  if (row.entity_type === "brand") return `/entities/brand/${encodeURIComponent(row.entity_id)}`;
  if (row.entity_type === "perfume") return `/entities/perfume/${encodeURIComponent(row.entity_id)}`;
  return `/entities/${encodeURIComponent(row.entity_id)}`;
}

export function TopMoversTable({
  rows,
  selectedId,
  onSelect,
}: TopMoversTableProps) {
  const router = useRouter();
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns = buildColumns(selectedId, onSelect);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (!rows.length) {
    return <EmptyState message="No movers found" />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-zinc-800">
              {hg.headers.map((header) => (
                <th
                  key={header.id}
                  style={{ width: header.getSize() }}
                  className={clsx(
                    "px-2.5 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500",
                    header.column.getCanSort() &&
                      "cursor-pointer select-none hover:text-zinc-300",
                  )}
                  onClick={header.column.getToggleSortingHandler()}
                >
                  <span className="inline-flex items-center gap-0.5">
                    {flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )}
                    {header.column.getIsSorted() === "asc" && (
                      <ChevronUp size={10} />
                    )}
                    {header.column.getIsSorted() === "desc" && (
                      <ChevronDown size={10} />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => {
            const entityId = row.original.entity_id;
            const isSelected = entityId === selectedId;
            const isBrand = row.original.entity_type === "brand";

            const href = entityHref(row.original);

            return (
              <tr
                key={row.id}
                onClick={() => {
                  onSelect(entityId);
                  router.push(href);
                }}
                className={clsx(
                  "group cursor-pointer border-b border-zinc-800/40 transition-colors",
                  isSelected
                    ? isBrand ? "bg-sky-950/30" : "bg-zinc-800/70"
                    : isBrand ? "hover:bg-sky-950/20" : "hover:bg-zinc-800/50",
                )}
              >
                {row.getVisibleCells().map((cell, ci) => (
                  <td
                    key={cell.id}
                    className={clsx(
                      "px-2.5 py-2",
                      ci === 0 && isSelected && isBrand && "border-l-2 border-sky-600",
                      ci === 0 && isSelected && !isBrand && "border-l-2 border-amber-400",
                      ci === 0 && !isSelected && "border-l-2 border-transparent",
                    )}
                  >
                    {cell.column.id === "canonical_name" ? (
                      <Link
                        href={href}
                        onClick={(e) => e.stopPropagation()}
                        className="block"
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </Link>
                    ) : (
                      flexRender(cell.column.columnDef.cell, cell.getContext())
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
