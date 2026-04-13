import { clsx } from "clsx";
import { Inbox } from "lucide-react";

// ---------------------------------------------------------------------------
// EmptyState
//
// Shown when a data region has zero items to display.
// Optional action slot for a CTA (e.g. "Reset filters" button).
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  /** Primary empty message */
  message?: string;
  /** Secondary explanation line */
  detail?: string;
  /** Optional action element (button, link) */
  action?: React.ReactNode;
  /**
   * Compact mode — reduces vertical padding and icon size for use inside
   * tight panels (chart panels, signal feeds, short lists).
   */
  compact?: boolean;
  className?: string;
}

export function EmptyState({
  message = "No data available",
  detail,
  action,
  compact = false,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center gap-2 text-center",
        compact ? "py-6" : "py-12",
        className,
      )}
    >
      <Inbox
        size={compact ? 16 : 22}
        strokeWidth={1.5}
        className="text-zinc-700"
      />
      <div className="space-y-0.5">
        <p
          className={clsx(
            "font-medium text-zinc-500",
            compact ? "text-xs" : "text-sm",
          )}
        >
          {message}
        </p>
        {detail && (
          <p className={clsx("text-zinc-700", compact ? "text-[10px]" : "text-xs")}>
            {detail}
          </p>
        )}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
