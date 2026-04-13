import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// Skeleton primitives
//
// Exports:
//   LoadingSkeleton  — stacked row blocks (generic panel loading)
//   SkeletonBlock    — single rectangular placeholder block
//   SkeletonLine     — thin single-line placeholder (text-width)
//   SkeletonKpiStrip — matches KPI strip layout (8 equal cards)
//   TableSkeleton    — table body rows with realistic column shimmer
// ---------------------------------------------------------------------------

// Base shimmer style shared by all skeleton variants
const SHIMMER = "animate-pulse rounded bg-zinc-800";

// ---------------------------------------------------------------------------
// SkeletonBlock — arbitrary height rectangle
// ---------------------------------------------------------------------------

interface SkeletonBlockProps {
  height?: number | string;
  className?: string;
}

export function SkeletonBlock({ height = 32, className }: SkeletonBlockProps) {
  return (
    <div
      className={clsx(SHIMMER, className)}
      style={{ height }}
    />
  );
}

// ---------------------------------------------------------------------------
// SkeletonLine — short inline text placeholder
// ---------------------------------------------------------------------------

interface SkeletonLineProps {
  /** Tailwind width class, e.g. "w-32", "w-1/2" */
  width?: string;
  className?: string;
}

export function SkeletonLine({ width = "w-32", className }: SkeletonLineProps) {
  return <div className={clsx(SHIMMER, "h-3", width, className)} />;
}

// ---------------------------------------------------------------------------
// LoadingSkeleton — stacked rows with fading opacity
// ---------------------------------------------------------------------------

interface LoadingSkeletonProps {
  rows?: number;
  rowHeight?: number;
  className?: string;
}

export function LoadingSkeleton({
  rows = 5,
  rowHeight = 32,
  className,
}: LoadingSkeletonProps) {
  return (
    <div className={clsx("space-y-2", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className={clsx(SHIMMER)}
          style={{ height: rowHeight, opacity: Math.max(0.15, 1 - i * 0.15) }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SkeletonKpiStrip — matches 8-card KPI strip layout
// ---------------------------------------------------------------------------

export function SkeletonKpiStrip({ className }: { className?: string }) {
  return (
    <div
      className={clsx(
        "grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8",
        className,
      )}
    >
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="flex flex-col gap-2 rounded border border-zinc-800 bg-zinc-900 px-4 py-3"
        >
          <SkeletonLine width="w-12" />
          <SkeletonBlock height={28} className="w-16" />
          <SkeletonLine width="w-20" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TableSkeleton — realistic table row shimmer
// cols: number of columns to render per row
// ---------------------------------------------------------------------------

interface TableSkeletonProps {
  rows?: number;
  cols?: number;
  className?: string;
}

const COL_WIDTHS = ["w-8", "w-16", "w-40", "w-14", "w-14", "w-16", "w-14", "w-20"];

export function TableSkeleton({
  rows = 8,
  cols = 8,
  className,
}: TableSkeletonProps) {
  return (
    <div className={clsx("divide-y divide-zinc-800/50", className)}>
      {Array.from({ length: rows }).map((_, ri) => (
        <div
          key={ri}
          className="flex items-center gap-3 px-3 py-2.5"
          style={{ opacity: Math.max(0.2, 1 - ri * 0.1) }}
        >
          {Array.from({ length: cols }).map((_, ci) => (
            <SkeletonLine
              key={ci}
              width={COL_WIDTHS[ci % COL_WIDTHS.length]}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
