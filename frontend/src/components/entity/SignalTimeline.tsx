import { SignalBadge } from "@/components/primitives/SignalBadge";
import { EmptyState } from "@/components/primitives/EmptyState";
import { fmtDatetime, fmtSignalType } from "@/lib/formatters";
import type { SignalRow } from "@/lib/api/types";

interface SignalTimelineProps {
  signals: SignalRow[];
}

export function SignalTimeline({ signals }: SignalTimelineProps) {
  if (!signals.length) {
    return <EmptyState compact message="No signals recorded" />;
  }

  // Newest first
  const sorted = [...signals].sort(
    (a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime(),
  );

  return (
    <ul className="space-y-px">
      {sorted.map((sig, i) => (
        <li
          key={`${sig.detected_at}-${i}`}
          className="flex items-center gap-3 rounded px-2 py-2 hover:bg-zinc-800/30"
        >
          {/* Badge */}
          <SignalBadge type={sig.signal_type} variant="dot" />

          {/* Signal type label */}
          <span className="w-24 shrink-0 text-xs font-medium text-zinc-300">
            {fmtSignalType(sig.signal_type)}
          </span>

          {/* Strength + confidence */}
          <div className="flex flex-1 items-center gap-2 text-[11px] text-zinc-500">
            <span>
              str{" "}
              <span className="tabular-nums text-zinc-300">
                {sig.strength.toFixed(2)}
              </span>
            </span>
            {sig.confidence != null && (
              <span>
                conf{" "}
                <span className="tabular-nums text-zinc-400">
                  {(sig.confidence * 100).toFixed(0)}%
                </span>
              </span>
            )}
          </div>

          {/* Timestamp */}
          <span className="shrink-0 text-[10px] tabular-nums text-zinc-600">
            {fmtDatetime(sig.detected_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}
