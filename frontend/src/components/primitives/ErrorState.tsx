import { clsx } from "clsx";
import { AlertTriangle, RefreshCw } from "lucide-react";

// ---------------------------------------------------------------------------
// ErrorState
//
// Shown when a data fetch or render fails.
// Optional onRetry prop renders a retry button.
// ---------------------------------------------------------------------------

interface ErrorStateProps {
  message?: string;
  /** If provided, renders a "Retry" button */
  onRetry?: () => void;
  className?: string;
}

// Truncate long API error strings so they don't overflow the panel
function trimMessage(msg: string | undefined): string {
  if (!msg) return "Failed to load data";
  // Strip common prefixes like "Error: "
  const cleaned = msg.replace(/^(Error:\s*|ApiError:\s*)/i, "");
  return cleaned.length > 120 ? cleaned.slice(0, 117) + "…" : cleaned;
}

export function ErrorState({ message, onRetry, className }: ErrorStateProps) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center gap-3 py-12 text-center",
        className,
      )}
    >
      <AlertTriangle
        size={24}
        strokeWidth={1.5}
        className="text-red-500/70"
      />
      <p className="max-w-sm text-sm text-red-400/80">
        {trimMessage(message)}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
        >
          <RefreshCw size={11} />
          Retry
        </button>
      )}
    </div>
  );
}
