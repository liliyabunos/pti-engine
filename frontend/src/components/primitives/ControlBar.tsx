import { clsx } from "clsx";

// ---------------------------------------------------------------------------
// ControlBar
//
// Horizontal strip below the page Header — holds quick controls, filters,
// counters, or status text.
//
// Layout: left slot fills available width; right slot is fixed/shrink.
// Both slots are optional. You can pass children directly for simple usage.
//
// Also exports ControlBarDivider for a vertical separator between groups.
// ---------------------------------------------------------------------------

interface ControlBarProps {
  /** Left region (search, filter chips, status text) */
  left?: React.ReactNode;
  /** Right region (sort buttons, refresh, etc.) */
  right?: React.ReactNode;
  /** Fallback: if neither left nor right, renders children in a flex row */
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
        "flex shrink-0 flex-wrap items-start gap-x-2 gap-y-1",
        "min-h-[36px] border-b border-zinc-800 bg-zinc-950 px-4 py-1.5",
        className,
      )}
    >
      {hasSlots ? (
        <>
          {/* Left fills remaining space; wraps on small screens */}
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            {left}
          </div>
          {/* Right: on small screens becomes full-width row below */}
          {right && (
            <div className="flex w-full min-w-0 items-center gap-2 overflow-x-auto sm:w-auto sm:shrink-0">
              {right}
            </div>
          )}
        </>
      ) : (
        // Simple children mode — flex row that wraps
        <div className="flex flex-1 flex-wrap items-center gap-2">{children}</div>
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
