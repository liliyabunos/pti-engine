import { EmptyState } from "@/components/primitives";
import { fmtDatetime } from "@/lib/formatters";
import type { AlertEventRow } from "@/lib/api/types";

interface AlertHistoryPanelProps {
  events: AlertEventRow[];
}

export function AlertHistoryPanel({ events }: AlertHistoryPanelProps) {
  if (!events.length) {
    return <EmptyState compact message="No alert history" />;
  }

  return (
    <ul className="divide-y divide-zinc-800/40">
      {events.map((ev) => (
        <li key={ev.id} className="px-3 py-2.5">
          {/* Status pill + timestamp */}
          <div className="mb-0.5 flex items-center justify-between gap-2">
            <span
              className={
                ev.status === "triggered"
                  ? "rounded border border-amber-800/60 bg-amber-900/30 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-400"
                  : "rounded border border-zinc-700 bg-zinc-800/50 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500"
              }
            >
              {ev.status}
            </span>
            <span className="text-[9px] text-zinc-600">
              {fmtDatetime(ev.triggered_at)}
            </span>
          </div>

          {/* Entity name */}
          <div className="truncate text-[11px] text-zinc-300">
            {ev.canonical_name ?? ev.entity_id}
          </div>

          {/* Alert name */}
          {ev.alert_name && (
            <div className="truncate text-[10px] text-zinc-600">{ev.alert_name}</div>
          )}
        </li>
      ))}
    </ul>
  );
}
