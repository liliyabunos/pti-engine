"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { SignalBadge } from "@/components/primitives/SignalBadge";
import { EmptyState } from "@/components/primitives/EmptyState";
import { fmtDatetime } from "@/lib/formatters";
import type { SignalRow } from "@/lib/api/types";

interface SignalFeedProps {
  signals: SignalRow[];
  selectedEntityId?: string | null;
  onSelectEntity?: (entityId: string) => void;
  /** Set of entity_ids present in the top movers list. Non-mover signals navigate directly. */
  moverEntityIds?: Set<string>;
}

export function SignalFeed({ signals, selectedEntityId, onSelectEntity, moverEntityIds }: SignalFeedProps) {
  const router = useRouter();

  if (!signals.length) {
    return <EmptyState compact message="No recent signals" />;
  }

  return (
    <ul className="space-y-1">
      {signals.map((sig, i) => {
        const isInMovers = !moverEntityIds || moverEntityIds.has(sig.entity_id);
        const isSelected = isInMovers && sig.entity_id === selectedEntityId;
        const entityHref = `/entities/${sig.entity_type ?? "perfume"}/${encodeURIComponent(sig.entity_id)}`;

        return (
          <li
            key={`${sig.entity_id}-${sig.detected_at}-${i}`}
            className={`flex items-start gap-3 rounded px-2 py-2 transition-colors ${
              isSelected
                ? "bg-zinc-800/70"
                : "hover:bg-zinc-800/40"
            } cursor-pointer`}
            onClick={() => {
              if (isInMovers) {
                onSelectEntity?.(sig.entity_id);
              } else {
                router.push(entityHref);
              }
            }}
          >
            <SignalBadge type={sig.signal_type} />
            <div className="min-w-0 flex-1">
              <Link
                href={entityHref}
                onClick={(e) => {
                  if (isInMovers) {
                    // mover row: suppress navigation; li click drives preview chart
                    if (!e.metaKey && !e.ctrlKey) e.preventDefault();
                  } else {
                    // non-mover row: allow navigation, but stop li from double-navigating
                    e.stopPropagation();
                  }
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
