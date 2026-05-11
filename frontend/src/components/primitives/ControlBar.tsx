import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// ControlBar
//
// Horizontal strip below the page Header — holds quick controls, filters,
// counters, or status text.
//
// Layout:
//   < 2xl  — flex-col: each slot stacks as its own full-width row.
//   ≥ 2xl  — flex-row: left fills remaining space, right is fixed/shrink.
//
// This guarantees left and right slots never share a row (and therefore
// never visually collide) at any viewport narrower than 1536 px.
//
// Both slots are optional. Pass children directly for simple usage (also
// stacked by default).
//
// Also exports ControlBarDivider for a vertical separator between groups.
// ---------------------------------------------------------------------------

interface ControlBarProps {
  /** Left region (search, filter chips, status text) */
  left?: React.ReactNode;
  /** Right region (sort buttons, refresh, range selector, etc.) */
  right?: React.ReactNode;
  /** Fallback: if neither left nor right, renders children stacked */
  children?: React.ReactNode;
  className?: string;
}

export function ControlBar({
  left,
  right,
  children,
  className,
}: ControlBarProps) {
  const hasSlots = left != null || right != null;

  return (
    <div
      className={clsx(
        // Stack slots vertically at all widths below 2xl (1536px).
        // At 2xl+ switch to a single row with space-between alignment.
        "flex shrink-0 flex-col gap-y-2",
        "border-b border-zinc-800 bg-zinc-950 px-4 py-2",
        "2xl:flex-row 2xl:items-center 2xl:justify-between 2xl:gap-x-4 2xl:gap-y-0",
        className,
      )}
    >
      {hasSlots ? (
        <>
          {/*
           * Left slot.
           * flex-col children auto-stretch to full width (align-items:stretch).
           * At 2xl+ the parent switches to flex-row; left gets flex-1 so it
           * fills remaining space after the right slot.
           */}
          <div className="min-w-0 2xl:flex-1">
            {left}
          </div>

          {/*
           * Right slot.
           * Full-width row with horizontal scroll for button groups at narrow
           * viewports. At 2xl+ shrinks to its natural width alongside left.
           */}
          {right && (
            <div className="min-w-0 overflow-x-auto 2xl:shrink-0 2xl:w-auto">
              {right}
            </div>
          )}
        </>
      ) : (
        // Simple children mode: stacked column, row at 2xl+.
        <div className="flex flex-col gap-y-2 2xl:flex-row 2xl:flex-wrap 2xl:items-center 2xl:gap-x-2 2xl:gap-y-0">
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ControlBarDivider — thin vertical rule between control groups
// ---------------------------------------------------------------------------

export function ControlBarDivider({ className }: { className?: string }) {
  return (
    <div
      className={clsx("h-4 w-px shrink-0 bg-zinc-800", className)}
    />
  );
}
