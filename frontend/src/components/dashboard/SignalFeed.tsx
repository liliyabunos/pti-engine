import Link from "next/link";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { EmptyState } from "@/components/primitives/EmptyState";
import { fmtDatetime } from "@/lib/formatters";
import type { SignalRow } from "@/lib/api/types";

interface SignalFeedProps {
  signals: SignalRow[];
  selectedEntityId?: string | null;
  onSelectEntity?: (entityId: string) => void;
}

export function SignalFeed({ signals, selectedEntityId, onSelectEntity }: SignalFeedProps) {
  if (!signals.length) {
    return <EmptyState compact message="No recent signals" />;
  }

  return (
    <ul className="space-y-1">
      {signals.map((sig, i) => {
        const isSelected = sig.entity_id === selectedEntityId;
        return (
          <li
            key={`${sig.entity_id}-${sig.detected_at}-${i}`}
            className={`flex items-start gap-3 rounded px-2 py-2 transition-colors ${
              isSelected
                ? "bg-zinc-800/70"
                : "hover:bg-zinc-800/40"
            } ${onSelectEntity ? "cursor-pointer" : ""}`}
            onClick={() => onSelectEntity?.(sig.entity_id)}
          >
            <SignalBadge type={sig.signal_type} />
            <div className="min-w-0 flex-1">
              <Link
                href={`/entities/${sig.entity_type ?? "perfume"}/${encodeURIComponent(sig.entity_id)}`}
                onClick={(e) => {
                  if (!e.metaKey && !e.ctrlKey) e.preventDefault();
                }}
                className={`block truncate text-xs font-medium hover:text-amber-300 ${
                  isSelected ? "text-amber-300" : "text-zinc-200"
                }`}
              >
                {sig.canonical_name ?? sig.entity_id}
              </Link>
              {sig.brand_name && (
                <span className="text-[10px] text-zinc-500">{sig.brand_name}</span>
              )}
            </div>
            <div className="shrink-0 text-right">
              <span className="block text-[10px] tabular-nums text-zinc-400">
                {sig.strength.toFixed(2)}
              </span>
              <span className="block text-[9px] text-zinc-600">
                {fmtDatetime(sig.detected_at)}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
