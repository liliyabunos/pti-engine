"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createAlert } from "@/lib/api/alerts";
import { ALERT_CONDITION_TYPES } from "@/lib/api/types";
import type { AlertConditionType } from "@/lib/api/types";

// Conditions that require a threshold value
const THRESHOLD_REQUIRED = new Set(["score_above", "growth_above", "confidence_below"]);

const CONDITION_LABELS: Record<AlertConditionType, string> = {
  breakout_detected: "Breakout Detected",
  acceleration_detected: "Acceleration Detected",
  any_new_signal: "Any New Signal",
  score_above: "Score Above",
  growth_above: "Growth Rate Above",
  confidence_below: "Confidence Below",
};

const THRESHOLD_HINTS: Partial<Record<AlertConditionType, string>> = {
  score_above: "e.g. 75 (composite market score)",
  growth_above: "e.g. 0.2 (20% growth rate)",
  confidence_below: "e.g. 0.5 (50% confidence)",
};

interface CreateAlertModalProps {
  /** Pre-fill entity fields when opened from an entity page */
  prefill?: {
    entity_id: string;
    entity_type: string;
    canonical_name: string;
  };
  onClose: () => void;
  onCreated: () => void;
}

export function CreateAlertModal({ prefill, onClose, onCreated }: CreateAlertModalProps) {
  const [name, setName] = useState(
    prefill ? `Alert: ${prefill.canonical_name}` : "",
  );
  const [entityId, setEntityId] = useState(prefill?.entity_id ?? "");
  const [entityType, setEntityType] = useState(prefill?.entity_type ?? "perfume");
  const [condition, setCondition] = useState<AlertConditionType>("breakout_detected");
  const [threshold, setThreshold] = useState("");
  const [cooldown, setCooldown] = useState("24");

  const qc = useQueryClient();

  const needsThreshold = THRESHOLD_REQUIRED.has(condition);

  const mutation = useMutation({
    mutationFn: () =>
      createAlert({
        name: name.trim(),
        entity_id: entityId.trim(),
        entity_type: entityType,
        condition_type: condition,
        threshold_value: needsThreshold ? Number(threshold) : undefined,
        cooldown_hours: Number(cooldown) || 24,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] });
      onCreated();
    },
  });

  const valid =
    name.trim() &&
    entityId.trim() &&
    (!needsThreshold || (threshold !== "" && !isNaN(Number(threshold))));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    mutation.mutate();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded border border-zinc-700 bg-zinc-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <span className="text-sm font-medium text-zinc-200">Create Alert</span>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">
            <X size={14} />
          </button>
        </div>

        <form onSubmit={submit} className="space-y-3 p-4">
          {/* Name */}
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">Alert Name *</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Breakout alert for Dior Sauvage"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
            />
          </div>

          {/* Entity ID — disabled when prefilled from entity page */}
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">Entity ID *</label>
            <input
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              disabled={!!prefill}
              placeholder="canonical entity_id"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
            />
            {prefill && (
              <p className="mt-0.5 text-[10px] text-zinc-600">
                {prefill.canonical_name} · {prefill.entity_type}
              </p>
            )}
          </div>

          {/* Entity type — hidden when prefilled */}
          {!prefill && (
            <div>
              <label className="mb-1 block text-[11px] text-zinc-400">Entity Type *</label>
              <select
                value={entityType}
                onChange={(e) => setEntityType(e.target.value)}
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 focus:border-zinc-500 focus:outline-none"
              >
                <option value="perfume">Perfume</option>
                <option value="brand">Brand</option>
              </select>
            </div>
          )}

          {/* Condition */}
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">Condition *</label>
            <select
              value={condition}
              onChange={(e) => setCondition(e.target.value as AlertConditionType)}
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 focus:border-zinc-500 focus:outline-none"
            >
              {ALERT_CONDITION_TYPES.map((c) => (
                <option key={c} value={c}>
                  {CONDITION_LABELS[c]}
                </option>
              ))}
            </select>
          </div>

          {/* Threshold — shown only when required */}
          {needsThreshold && (
            <div>
              <label className="mb-1 block text-[11px] text-zinc-400">
                Threshold Value *
              </label>
              <input
                type="number"
                step="any"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                placeholder={THRESHOLD_HINTS[condition] ?? "Enter threshold"}
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
              />
            </div>
          )}

          {/* Cooldown */}
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">
              Cooldown (hours)
            </label>
            <input
              type="number"
              min={1}
              max={8760}
              value={cooldown}
              onChange={(e) => setCooldown(e.target.value)}
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 focus:border-zinc-500 focus:outline-none"
            />
            <p className="mt-0.5 text-[10px] text-zinc-600">
              Default 24 h. Alert won&apos;t re-fire within this window.
            </p>
          </div>

          {mutation.isError && (
            <p className="text-[11px] text-red-400">
              {String((mutation.error as Error)?.message ?? "Error creating alert")}
            </p>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-[11px] text-zinc-400 hover:text-zinc-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!valid || mutation.isPending}
              className="rounded border border-zinc-600 bg-zinc-800 px-3 py-1.5 text-[11px] text-zinc-200 hover:border-zinc-500 hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {mutation.isPending ? "Creating…" : "Create Alert"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
