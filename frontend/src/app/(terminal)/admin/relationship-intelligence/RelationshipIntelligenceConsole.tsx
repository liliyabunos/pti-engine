"use client";

/**
 * FTG-3 / RI1-QA — Admin Relationship Intelligence Console (client component).
 *
 * Operator review queue for fragrance relationship claims.
 *
 * Actions:
 *   - Filter: all | public | non_public
 *   - Approve: set is_public=TRUE, operator_reviewed=TRUE
 *   - Unpublish: set is_public=FALSE
 *   - Edit confidence_score: float 0.0–1.0
 *   - Edit relation_type: one of the 4 approved types
 *
 * Public quality gate (FTG-3):
 *   A row appears publicly only when:
 *     is_public=TRUE AND operator_reviewed=TRUE AND confidence_score >= 0.700
 */

import { useCallback, useEffect, useState } from "react";
import { CheckCircle, EyeOff, RefreshCw, Edit2, ChevronDown, ChevronUp } from "lucide-react";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EvidenceRow {
  id: string;
  evidence_type: string;
  note: string | null;
  query_text: string | null;
  observed_date: string;
}

interface RelationshipRow {
  id: string;
  subject_canonical_name: string;
  relation_type: string;
  object_canonical_name: string;
  confidence_score: number;
  is_public: boolean;
  operator_reviewed: boolean;
  first_observed_date: string;
  last_confirmed_date: string;
  evidence_summary: string | null;
  formula_version: number;
  created_at: string;
  evidence: EvidenceRow[];
}

type FilterType = "all" | "public" | "non_public";

const VALID_RELATION_TYPES = [
  "dupe_of",
  "market_alternative_to",
  "inspired_by",
  "commonly_compared_to",
] as const;

// ---------------------------------------------------------------------------
// Public quality gate helper
// ---------------------------------------------------------------------------

function meetsPublicGate(r: RelationshipRow): boolean {
  return r.is_public && r.operator_reviewed && r.confidence_score >= 0.7;
}

// ---------------------------------------------------------------------------
// Edit modal
// ---------------------------------------------------------------------------

function EditModal({
  row,
  onSave,
  onCancel,
}: {
  row: RelationshipRow;
  onSave: (confidence: number | null, relType: string | null) => Promise<void>;
  onCancel: () => void;
}) {
  const [confidence, setConfidence] = useState(String(row.confidence_score));
  const [relType, setRelType] = useState(row.relation_type);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const confVal = parseFloat(confidence);
    if (isNaN(confVal) || confVal < 0 || confVal > 1) {
      setError("Confidence must be between 0.0 and 1.0");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const newConf = confVal !== row.confidence_score ? confVal : null;
      const newType = relType !== row.relation_type ? relType : null;
      await onSave(newConf, newType);
    } catch (err: unknown) {
      setError((err as Error).message ?? "Save failed");
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-sm rounded border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
        <p className="mb-1 text-sm font-semibold text-zinc-200">Edit Relationship</p>
        <p className="mb-4 truncate text-[11px] text-zinc-500">
          {row.subject_canonical_name}
        </p>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
              Relation Type
            </label>
            <select
              value={relType}
              onChange={(e) => setRelType(e.target.value)}
              className="w-full rounded border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-200"
            >
              {VALID_RELATION_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
              Confidence Score (0.0–1.0)
            </label>
            <input
              type="number"
              step="0.001"
              min="0"
              max="1"
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
              className="w-full rounded border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-200"
            />
          </div>
          {error && <p className="text-[11px] text-red-400">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onCancel}
              className="rounded border border-zinc-700 px-3 py-1 text-[11px] text-zinc-400 hover:text-zinc-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded bg-amber-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-amber-500 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single relationship row
// ---------------------------------------------------------------------------

function RelRow({
  row,
  onApprove,
  onUnpublish,
  onEdit,
}: {
  row: RelationshipRow;
  onApprove: () => Promise<void>;
  onUnpublish: () => Promise<void>;
  onEdit: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);

  const gatePass = meetsPublicGate(row);

  async function act(fn: () => Promise<void>) {
    setActing(true);
    try { await fn(); } finally { setActing(false); }
  }

  return (
    <div className="border-b border-zinc-800 py-3">
      <div className="flex items-start gap-2">
        {/* Status indicator */}
        <div
          title={gatePass ? "Public quality gate: PASS" : "Public quality gate: FAIL"}
          className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${gatePass ? "bg-emerald-500" : "bg-zinc-600"}`}
        />
        <div className="min-w-0 flex-1">
          {/* Main line */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="text-xs font-semibold text-zinc-100 truncate max-w-[200px]">
              {row.subject_canonical_name}
            </span>
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${
              row.relation_type === "dupe_of"
                ? "border border-amber-700/50 bg-amber-950/40 text-amber-400"
                : "border border-sky-800/50 bg-sky-950/40 text-sky-400"
            }`}>
              {row.relation_type.replace(/_/g, " ")}
            </span>
            <span className="text-xs text-zinc-400 truncate max-w-[200px]">
              {row.object_canonical_name}
            </span>
          </div>
          {/* Meta */}
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[10px] text-zinc-600">
            <span>conf: <span className={`font-mono ${row.confidence_score >= 0.7 ? "text-zinc-400" : "text-red-500"}`}>{row.confidence_score.toFixed(3)}</span></span>
            <span>public: <span className={row.is_public ? "text-emerald-500" : "text-zinc-500"}>{row.is_public ? "yes" : "no"}</span></span>
            <span>reviewed: <span className={row.operator_reviewed ? "text-emerald-500" : "text-zinc-500"}>{row.operator_reviewed ? "yes" : "no"}</span></span>
            <span>first: {row.first_observed_date}</span>
          </div>
          {row.evidence_summary && (
            <p className="mt-0.5 text-[10px] text-zinc-600 line-clamp-1">{row.evidence_summary}</p>
          )}
          {/* Evidence (expandable) */}
          {row.evidence.length > 0 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-1 flex items-center gap-0.5 text-[10px] text-zinc-600 hover:text-zinc-400"
            >
              {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
              {row.evidence.length} evidence
            </button>
          )}
          {expanded && (
            <div className="mt-1 space-y-0.5 border-l border-zinc-800 pl-2">
              {row.evidence.map((ev) => (
                <div key={ev.id} className="text-[10px] text-zinc-600">
                  <span className="text-zinc-500">{ev.evidence_type}</span>
                  {ev.note && <span> — {ev.note}</span>}
                  <span className="ml-2 text-zinc-700">{ev.observed_date}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        {/* Actions */}
        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={() => act(onApprove)}
            disabled={acting || row.is_public}
            title="Approve for public display"
            className="rounded p-1 text-zinc-600 hover:text-emerald-400 disabled:opacity-30"
          >
            <CheckCircle size={13} />
          </button>
          <button
            onClick={() => act(onUnpublish)}
            disabled={acting || !row.is_public}
            title="Unpublish (remove from public)"
            className="rounded p-1 text-zinc-600 hover:text-amber-400 disabled:opacity-30"
          >
            <EyeOff size={13} />
          </button>
          <button
            onClick={onEdit}
            disabled={acting}
            title="Edit confidence / relation type"
            className="rounded p-1 text-zinc-600 hover:text-sky-400 disabled:opacity-30"
          >
            <Edit2 size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main console
// ---------------------------------------------------------------------------

export function RelationshipIntelligenceConsole({ adminEmail }: { adminEmail: string }) {
  const [filter, setFilter] = useState<FilterType>("all");
  const [rows, setRows] = useState<RelationshipRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<RelationshipRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(
        `/api/admin/relationship-intelligence?filter=${filter}`,
        { cache: "no-store" },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setRows(data.relationships ?? []);
      setTotal(data.total ?? 0);
    } catch (err: unknown) {
      setError((err as Error).message ?? "Load failed");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  async function handleApprove(id: string) {
    const resp = await fetch(`/api/admin/relationship-intelligence/${id}/approve`, {
      method: "POST",
      cache: "no-store",
    });
    if (!resp.ok) throw new Error(`Approve failed: HTTP ${resp.status}`);
    await load();
  }

  async function handleUnpublish(id: string) {
    const resp = await fetch(`/api/admin/relationship-intelligence/${id}/unpublish`, {
      method: "POST",
      cache: "no-store",
    });
    if (!resp.ok) throw new Error(`Unpublish failed: HTTP ${resp.status}`);
    await load();
  }

  async function handleEdit(id: string, confidence: number | null, relType: string | null) {
    const body: Record<string, unknown> = {};
    if (confidence !== null) body.confidence_score = confidence;
    if (relType !== null) body.relation_type = relType;
    const resp = await fetch(`/api/admin/relationship-intelligence/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      throw new Error(d.detail ?? `Edit failed: HTTP ${resp.status}`);
    }
    setEditTarget(null);
    await load();
  }

  const FILTERS: { key: FilterType; label: string }[] = [
    { key: "all", label: "All" },
    { key: "public", label: "Public" },
    { key: "non_public", label: "Non-Public" },
  ];

  return (
    <>
      {editTarget && (
        <EditModal
          row={editTarget}
          onSave={(conf, type) => handleEdit(editTarget.id, conf, type)}
          onCancel={() => setEditTarget(null)}
        />
      )}
      <div className="flex h-full flex-col">
        <Header title="Relationship Intelligence" subtitle="FTG-3 / RI1-QA operator review" />
        <div className="flex-1 overflow-y-auto p-4">
          <TerminalPanel>
            <div className="mb-3 flex items-center justify-between">
              <div className="flex gap-1">
                {FILTERS.map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => setFilter(key)}
                    className={`rounded px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide transition-colors ${
                      filter === key
                        ? "bg-amber-600/20 text-amber-400"
                        : "text-zinc-600 hover:text-zinc-400"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-zinc-600">
                  {total} relationship{total !== 1 ? "s" : ""}
                </span>
                <button
                  onClick={load}
                  disabled={loading}
                  className="text-zinc-600 hover:text-zinc-400 disabled:opacity-30"
                >
                  <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
                </button>
              </div>
            </div>

            {/* Quality gate legend */}
            <div className="mb-3 flex items-center gap-3 text-[9px] text-zinc-700">
              <span className="flex items-center gap-1">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
                Public gate pass (is_public + reviewed + conf≥0.700)
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-600" />
                Not public / gate fail
              </span>
            </div>

            {error && (
              <p className="py-4 text-center text-[11px] text-red-400">{error}</p>
            )}

            {!error && !loading && rows.length === 0 && (
              <p className="py-4 text-center text-[11px] text-zinc-600">No relationships found</p>
            )}

            {rows.map((row) => (
              <RelRow
                key={row.id}
                row={row}
                onApprove={() => handleApprove(row.id)}
                onUnpublish={() => handleUnpublish(row.id)}
                onEdit={() => setEditTarget(row)}
              />
            ))}
          </TerminalPanel>
        </div>
      </div>
    </>
  );
}
