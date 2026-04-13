"use client";

import { useState } from "react";
import { Bell, Plus, Pause, Play } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";

import { fetchAlerts, fetchAlertHistory, patchAlert } from "@/lib/api/alerts";
import { Header } from "@/components/shell/Header";
import { ControlBar } from "@/components/primitives/ControlBar";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { EmptyState } from "@/components/primitives/EmptyState";
import { ErrorState } from "@/components/primitives/ErrorState";
import { TableSkeleton } from "@/components/primitives/LoadingSkeleton";
import { CreateAlertModal } from "@/components/alerts/CreateAlertModal";
import { AlertHistoryPanel } from "@/components/alerts/AlertHistoryPanel";
import { fmtDatetime } from "@/lib/formatters";
import type { AlertRow } from "@/lib/api/types";

// Condition display labels
const COND_LABEL: Record<string, string> = {
  breakout_detected: "Breakout",
  acceleration_detected: "Accel",
  any_new_signal: "Any Signal",
  score_above: "Score ↑",
  growth_above: "Growth ↑",
  confidence_below: "Conf ↓",
};

function fmtCondition(row: AlertRow): string {
  const base = COND_LABEL[row.condition_type] ?? row.condition_type;
  if (row.threshold_value != null) {
    return `${base} ${row.threshold_value}`;
  }
  return base;
}

export default function AlertsPage() {
  const [showCreate, setShowCreate] = useState(false);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data: alertsData, isLoading, isError, refetch } = useQuery({
    queryKey: ["alerts"],
    queryFn: fetchAlerts,
    staleTime: 15_000,
  });

  const { data: historyData } = useQuery({
    queryKey: ["alert-history", selectedAlertId],
    queryFn: () =>
      fetchAlertHistory({ limit: 50, ...(selectedAlertId ? { alert_id: selectedAlertId } : {}) }),
    staleTime: 15_000,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      patchAlert(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const alerts = alertsData?.alerts ?? [];
  const activeCount = alerts.filter((a) => a.is_active).length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title="Alerts"
        subtitle={
          alerts.length > 0
            ? `${activeCount} active · ${alerts.length} total`
            : undefined
        }
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
          >
            <Plus size={11} />
            New Alert
          </button>
        }
      />

      <ControlBar />

      {isError ? (
        <div className="p-4">
          <ErrorState message="Failed to load alerts" onRetry={() => refetch()} />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden p-4 gap-4">
          {/* ── Alerts table ──────────────────────────────────────────── */}
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <TerminalPanel noPad className="flex flex-1 flex-col overflow-hidden">
              <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
                <SectionHeader
                  title="All Alerts"
                  subtitle={alerts.length > 0 ? `${alerts.length} configured` : undefined}
                />
              </div>

              <div className="flex-1 overflow-y-auto">
                {isLoading ? (
                  <TableSkeleton rows={5} cols={5} />
                ) : alerts.length === 0 ? (
                  <EmptyState
                    message="No alerts configured"
                    detail="Create an alert to be notified when entity conditions change."
                  />
                ) : (
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-zinc-800">
                        {["Status", "Name", "Entity", "Condition", "Cooldown", "Last Fired", ""].map(
                          (col) => (
                            <th
                              key={col}
                              className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-600"
                            >
                              {col}
                            </th>
                          ),
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {alerts.map((alert) => (
                        <tr
                          key={alert.id}
                          onClick={() =>
                            setSelectedAlertId((prev) =>
                              prev === alert.id ? null : alert.id,
                            )
                          }
                          className={clsx(
                            "cursor-pointer border-b border-zinc-800/60 transition-colors",
                            selectedAlertId === alert.id
                              ? "bg-zinc-800/50"
                              : "hover:bg-zinc-800/30",
                          )}
                        >
                          {/* Status */}
                          <td className="px-3 py-2">
                            <span
                              className={clsx(
                                "inline-block h-1.5 w-1.5 rounded-full",
                                alert.is_active ? "bg-emerald-400" : "bg-zinc-600",
                              )}
                            />
                          </td>

                          {/* Name */}
                          <td className="px-3 py-2 text-xs font-medium text-zinc-200">
                            {alert.name}
                          </td>

                          {/* Entity */}
                          <td className="px-3 py-2">
                            <div className="text-xs text-zinc-300">
                              {alert.canonical_name ?? alert.entity_id}
                            </div>
                            {alert.ticker && (
                              <div className="text-[10px] text-zinc-600">{alert.ticker}</div>
                            )}
                          </td>

                          {/* Condition */}
                          <td className="px-3 py-2">
                            <span className="rounded border border-zinc-700 bg-zinc-800/60 px-1.5 py-0.5 text-[10px] text-zinc-300">
                              {fmtCondition(alert)}
                            </span>
                          </td>

                          {/* Cooldown */}
                          <td className="px-3 py-2 tabular-nums text-[11px] text-zinc-500">
                            {alert.cooldown_hours}h
                          </td>

                          {/* Last fired */}
                          <td className="px-3 py-2 tabular-nums text-[10px] text-zinc-500">
                            {alert.last_triggered_at
                              ? fmtDatetime(alert.last_triggered_at)
                              : "Never"}
                          </td>

                          {/* Toggle pause/resume */}
                          <td
                            className="px-3 py-2"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <button
                              onClick={() =>
                                toggleMutation.mutate({
                                  id: alert.id,
                                  is_active: !alert.is_active,
                                })
                              }
                              disabled={toggleMutation.isPending}
                              title={alert.is_active ? "Pause alert" : "Resume alert"}
                              className="text-zinc-600 hover:text-zinc-300 disabled:opacity-30"
                            >
                              {alert.is_active ? <Pause size={12} /> : <Play size={12} />}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </TerminalPanel>
          </div>

          {/* ── History panel ─────────────────────────────────────────── */}
          <aside className="w-52 shrink-0">
            <TerminalPanel noPad className="flex h-full flex-col overflow-hidden">
              <div className="border-b border-zinc-800 px-3 py-2">
                <SectionHeader
                  title="History"
                  subtitle={
                    selectedAlertId
                      ? "selected alert"
                      : "all alerts"
                  }
                />
              </div>
              <div className="flex-1 overflow-y-auto">
                <AlertHistoryPanel events={historyData?.events ?? []} />
              </div>
              {historyData && historyData.total > 0 && (
                <div className="border-t border-zinc-800 px-3 py-1.5">
                  <span className="text-[10px] text-zinc-600">
                    {historyData.total} total events
                  </span>
                </div>
              )}
            </TerminalPanel>
          </aside>
        </div>
      )}

      {showCreate && (
        <CreateAlertModal
          onClose={() => setShowCreate(false)}
          onCreated={() => setShowCreate(false)}
        />
      )}
    </div>
  );
}
