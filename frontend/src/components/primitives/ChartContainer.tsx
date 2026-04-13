import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// ChartContainer
//
// Wrapper that gives a Recharts ResponsiveContainer a fixed height and
// consistent outer structure.
//
// Optional label + actions slot renders a mini-header above the chart area.
// This keeps chart titles co-located with the chart rather than using a
// separate SectionHeader in the parent.
// ---------------------------------------------------------------------------

interface ChartContainerProps {
  children: React.ReactNode;
  /** Fixed pixel height of the chart area (not including the label row) */
  height?: number;
  /** Optional chart label shown above-left */
  label?: string;
  /** Optional controls shown above-right (metric toggles, time range) */
  actions?: React.ReactNode;
  className?: string;
}

export function ChartContainer({
  children,
  height = 200,
  label,
  actions,
  className,
}: ChartContainerProps) {
  const hasHeader = label != null || actions != null;

  return (
    <div className={clsx("flex flex-col gap-2", className)}>
      {/* Optional inline header */}
      {hasHeader && (
        <div className="flex items-center justify-between">
          {label && (
            <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">
              {label}
            </span>
          )}
          {actions && (
            <div className="flex items-center gap-1">{actions}</div>
          )}
        </div>
      )}

      {/* Chart area — fixed height, full width */}
      <div className="w-full" style={{ height }}>
        {children}
      </div>
    </div>
  );
}
