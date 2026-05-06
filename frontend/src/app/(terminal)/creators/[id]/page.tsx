"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { clsx } from "clsx";

import {
  fetchCreatorProfile,
  type EntityRelationshipRow,
  type RecentContentRow,
} from "@/lib/api/creators";
import { fmtCount, fmtDate } from "@/lib/formatters";
import { Header } from "@/components/shell/Header";
import { TerminalPanel } from "@/components/primitives/TerminalPanel";
import { PanelDivider } from "@/components/primitives/TerminalPanel";
import { SectionHeader } from "@/components/primitives/SectionHeader";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";
import { ErrorState } from "@/components/primitives/ErrorState";

// ---------------------------------------------------------------------------
// Local formatters
// ---------------------------------------------------------------------------

function fmtInfluence(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(3);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return (v * 100).toFixed(0) + "%";
}

// ---------------------------------------------------------------------------
// Tier / badge helpers
// ---------------------------------------------------------------------------

function tierColor(tier: string | null): string {
  if (!tier) return "text-zinc-600";
  const map: Record<string, string> = {
    tier_1: "text-amber-400",
    tier_2: "text-sky-400",
    tier_3: "text-emerald-400",
    tier_4: "text-zinc-400",
  };
  return map[tier] ?? "text-zinc-500";
}

function tierBorderColor(tier: string | null): string {
  if (!tier) return "border-zinc-700 text-zinc-600";
  const map: Record<string, string> = {
    tier_1: "border-amber-800 text-amber-400",
    tier_2: "border-sky-800 text-sky-400",
    tier_3: "border-emerald-800 text-emerald-500",
    tier_4: "border-zinc-700 text-zinc-500",
  };
  return map[tier] ?? "border-zinc-700 text-zinc-500";
}

function tierLabel(tier: string | null): string {
  if (!tier) return "—";
  return tier.replace("tier_", "Tier ");
}

// ---------------------------------------------------------------------------
// Score component bar
// ---------------------------------------------------------------------------

const SCORE_COMPONENT_META: Record<string, { label: string; description: string }> = {
  reach: { label: "Reach", description: "Subscriber scale" },
  signal_quality: { label: "Signal Quality", description: "Low-noise, entity-focused content" },
  entity_breadth: { label: "Entity Breadth", description: "Variety of fragrances covered" },
  volume: { label: "Volume", description: "Total entity mention count" },
  early_signal: { label: "Early Signal", description: "Pre-breakout mention behavior" },
  engagement: { label: "Engagement", description: "Avg engagement rate" },
};

const COMPONENT_ORDER = [
  "reach",
  "signal_quality",
  "entity_breadth",
  "volume",
  "early_signal",
  "engagement",
];

function ScoreComponentBar({ name, value }: { name: string; value: number }) {
  const pct = Math.round(value * 100);
  const meta = SCORE_COMPONENT_META[name];
  const barColor =
    pct >= 70 ? "bg-amber-400" : pct >= 40 ? "bg-sky-500" : "bg-zinc-600";
  return (
    <div className="flex items-center gap-3 border-b border-zinc-800/50 px-4 py-2 last:border-b-0">
      <div className="w-28 shrink-0">
        <p className="text-[11px] font-medium text-zinc-300">
          {meta?.label ?? name}
        </p>
        {meta?.description && (
          <p className="text-[9px] text-zinc-600">{meta.description}</p>
        )}
      </div>
      <div className="flex flex-1 items-center gap-2">
        <div className="h-1.5 flex-1 rounded-full bg-zinc-800">
          <div
            className={clsx("h-full rounded-full transition-all", barColor)}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-8 text-right text-[11px] tabular-nums text-zinc-400">
          {value.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

function ScoreComponents({
  components,
  influenceScore,
}: {
  components: Record<string, number> | null;
  influenceScore: number | null;
}) {
  if (!components) return null;
  return (
    <TerminalPanel noPad>
      <div className="flex items-baseline justify-between p-4">
        <SectionHeader title="Influence Score Breakdown" />
        <span className="text-xl font-bold tabular-nums text-zinc-100">
          {fmtInfluence(influenceScore)}
        </span>
      </div>
      <PanelDivider />
      <div className="px-0">
        {COMPONENT_ORDER.filter((k) => k in components).map((k) => (
          <ScoreComponentBar key={k} name={k} value={components[k]} />
        ))}
      </div>
      <div className="border-t border-zinc-800/50 px-4 py-2">
        <p className="text-[10px] text-zinc-600">
          Influence Score combines reach, entity relevance, mention volume,
          early-signal behavior, engagement, and low-noise quality.
        </p>
      </div>
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Top entities portfolio
// ---------------------------------------------------------------------------

function EntityPortfolioRow({ row }: { row: EntityRelationshipRow }) {
  const isEarlySignal = row.mentions_before_first_breakout > 0;
  const href =
    row.entity_type === "perfume" && row.canonical_name
      ? `/entities/perfume/${encodeURIComponent(row.canonical_name)}`
      : null;

  return (
    <div className="flex items-center gap-3 border-b border-zinc-800/40 px-4 py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          {href ? (
            <Link
              href={href}
              className="text-[12px] font-medium text-zinc-200 hover:text-amber-300 transition-colors truncate"
            >
              {row.canonical_name ?? row.entity_id}
            </Link>
          ) : (
            <span className="text-[12px] font-medium text-zinc-200 truncate">
              {row.canonical_name ?? row.entity_id}
            </span>
          )}
          {isEarlySignal && (
            <span className="inline-flex items-center rounded border border-amber-800/60 bg-amber-950/30 px-1 py-px text-[8px] font-semibold uppercase tracking-wider text-amber-400">
              Early Signal
            </span>
          )}
        </div>
        {row.brand_name && (
          <span className="text-[10px] text-zinc-600">{row.brand_name}</span>
        )}
      </div>
      <div className="hidden shrink-0 items-center gap-4 sm:flex">
        <div className="w-12 text-right">
          <p className="text-[11px] tabular-nums text-zinc-300">
            {row.mention_count}
          </p>
          <p className="text-[9px] text-zinc-700">mentions</p>
        </div>
        <div className="w-14 text-right">
          <p className="text-[11px] tabular-nums text-zinc-400">
            {row.avg_views != null ? fmtCount(Math.round(row.avg_views)) : "—"}
          </p>
          <p className="text-[9px] text-zinc-700">avg views</p>
        </div>
        <div className="w-14 text-right">
          <p className="text-[11px] tabular-nums text-zinc-500">
            {row.first_mention_date ? fmtDate(row.first_mention_date) : "—"}
          </p>
          <p className="text-[9px] text-zinc-700">first seen</p>
        </div>
        <div className="w-14 text-right">
          <p className="text-[11px] tabular-nums text-zinc-500">
            {row.last_mention_date ? fmtDate(row.last_mention_date) : "—"}
          </p>
          <p className="text-[9px] text-zinc-700">last seen</p>
        </div>
      </div>
    </div>
  );
}

function EntityPortfolio({ rows }: { rows: EntityRelationshipRow[] }) {
  return (
    <TerminalPanel noPad>
      <div className="p-4">
        <SectionHeader
          title="Fragrance Portfolio"
          subtitle={
            rows.length > 0
              ? `${rows.length} entities mentioned`
              : undefined
          }
        />
      </div>
      <PanelDivider />
      {rows.length === 0 ? (
        <p className="px-4 py-4 text-[12px] text-zinc-600">
          No entity attribution available yet.
        </p>
      ) : (
        <div>
          {rows.map((row) => (
            <EntityPortfolioRow key={row.entity_id} row={row} />
          ))}
        </div>
      )}
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Recent content
// ---------------------------------------------------------------------------

function ingestionLabel(method: string | null | undefined): string {
  if (!method) return "";
  if (method === "channel_poll") return "Channel";
  if (method === "search") return "Search";
  return method;
}

function RecentContentRow({ row }: { row: RecentContentRow }) {
  return (
    <div className="flex items-start gap-3 border-b border-zinc-800/40 px-4 py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        {row.source_url ? (
          <a
            href={row.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-[12px] text-blue-400 hover:underline"
          >
            <span className="truncate">{row.title ?? row.source_url}</span>
            <ExternalLink size={10} className="shrink-0 opacity-60" />
          </a>
        ) : (
          <span className="text-[12px] text-zinc-300">
            {row.title ?? "Untitled"}
          </span>
        )}
        <div className="mt-0.5 flex items-center gap-2 text-[10px] text-zinc-600">
          {row.published_at && <span>{row.published_at.slice(0, 10)}</span>}
          {row.ingestion_method && (
            <span className="rounded border border-zinc-800 px-1 py-px text-[9px] text-zinc-700">
              {ingestionLabel(row.ingestion_method)}
            </span>
          )}
        </div>
      </div>
      <div className="hidden shrink-0 items-center gap-4 sm:flex">
        {row.views != null && (
          <div className="w-16 text-right">
            <p className="text-[11px] tabular-nums text-zinc-300">
              {fmtCount(row.views)}
            </p>
            <p className="text-[9px] text-zinc-700">views</p>
          </div>
        )}
        {row.likes != null && (
          <div className="w-10 text-right">
            <p className="text-[11px] tabular-nums text-zinc-500">
              {fmtCount(row.likes)}
            </p>
            <p className="text-[9px] text-zinc-700">likes</p>
          </div>
        )}
        {row.comments != null && (
          <div className="w-10 text-right">
            <p className="text-[11px] tabular-nums text-zinc-500">
              {fmtCount(row.comments)}
            </p>
            <p className="text-[9px] text-zinc-700">comments</p>
          </div>
        )}
      </div>
    </div>
  );
}

function RecentContent({ rows }: { rows: RecentContentRow[] }) {
  return (
    <TerminalPanel noPad>
      <div className="p-4">
        <SectionHeader
          title="Recent Content"
          subtitle={rows.length > 0 ? `${rows.length} items` : undefined}
        />
      </div>
      <PanelDivider />
      {rows.length === 0 ? (
        <p className="px-4 py-4 text-[12px] text-zinc-600">
          No recent content indexed.
        </p>
      ) : (
        <div>
          {rows.map((row, i) => (
            <RecentContentRow key={row.source_url ?? i} row={row} />
          ))}
        </div>
      )}
    </TerminalPanel>
  );
}

// ---------------------------------------------------------------------------
// Stat pill
// ---------------------------------------------------------------------------

function StatCell({
  label,
  value,
  highlight,
}: {
  label: string;
  value: React.ReactNode;
  highlight?: boolean;
}) {
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span
        className={clsx(
          "text-sm font-bold tabular-nums leading-none",
          highlight ? "text-amber-400" : "text-zinc-100",
        )}
      >
        {value}
      </span>
      <span className="text-[9px] uppercase tracking-wider text-zinc-600">
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function CreatorProfilePage({ params }: PageProps) {
  const { id } = use(params);
  const decoded = decodeURIComponent(id);
  const router = useRouter();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["creator-profile", decoded],
    queryFn: () => fetchCreatorProfile(decoded),
    staleTime: 60_000,
  });

  const displayName = data?.creator_handle ?? data?.title ?? decoded;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Header
        title={displayName}
        subtitle={
          data
            ? [data.quality_tier ? tierLabel(data.quality_tier) : null, data.category]
                .filter(Boolean)
                .join(" · ") || undefined
            : undefined
        }
        actions={
          <button
            onClick={() => router.back()}
            className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300"
          >
            <ArrowLeft size={12} />
            Back
          </button>
        }
      />

      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="space-y-4 p-4">
            <LoadingSkeleton rows={3} rowHeight={32} />
            <LoadingSkeleton rows={6} rowHeight={20} />
          </div>
        )}

        {isError && (
          <div className="p-5">
            <ErrorState message={String(error)} onRetry={() => refetch()} />
          </div>
        )}

        {data && (
          <div className="space-y-4 p-4">
            {/* ── Creator header panel ───────────────────────────────────── */}
            <TerminalPanel noPad>
              <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
                {/* Identity */}
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={clsx(
                        "inline-flex rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide",
                        tierBorderColor(data.quality_tier),
                      )}
                    >
                      {tierLabel(data.quality_tier)}
                    </span>
                    <span className="rounded border border-zinc-800 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500">
                      {data.platform}
                    </span>
                    {data.early_signal_count > 0 && (
                      <span className="inline-flex items-center rounded border border-amber-800/60 bg-amber-950/30 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-400">
                        {data.early_signal_count} Early Signals
                      </span>
                    )}
                  </div>
                  <h1 className="mt-1 text-xl font-bold leading-tight text-zinc-100">
                    {displayName}
                  </h1>
                  {data.category && (
                    <p className="mt-0.5 text-xs capitalize text-zinc-500">
                      {data.category}
                    </p>
                  )}
                </div>

                {/* Key stats */}
                <div className="flex shrink-0 flex-wrap items-start gap-5">
                  <StatCell
                    label="Influence"
                    value={fmtInfluence(data.influence_score)}
                    highlight
                  />
                  <StatCell
                    label="Subscribers"
                    value={fmtCount(data.subscriber_count)}
                  />
                  <StatCell
                    label="Entities"
                    value={data.unique_entities_mentioned}
                  />
                  <StatCell
                    label="Mentions"
                    value={data.total_entity_mentions}
                  />
                  <StatCell
                    label="Noise Rate"
                    value={fmtPct(data.noise_rate)}
                  />
                  {data.avg_engagement_rate != null && (
                    <StatCell
                      label="Engagement"
                      value={fmtPct(data.avg_engagement_rate)}
                    />
                  )}
                </div>
              </div>

              {/* Secondary stats row */}
              <PanelDivider />
              <div className="flex flex-wrap gap-6 px-5 py-3">
                {data.channel_video_count != null && (
                  <div>
                    <p className="text-[11px] tabular-nums text-zinc-400">
                      {data.channel_video_count.toLocaleString()}
                    </p>
                    <p className="text-[9px] uppercase tracking-wider text-zinc-600">
                      Videos
                    </p>
                  </div>
                )}
                {data.channel_view_count != null && (
                  <div>
                    <p className="text-[11px] tabular-nums text-zinc-400">
                      {fmtCount(data.channel_view_count)}
                    </p>
                    <p className="text-[9px] uppercase tracking-wider text-zinc-600">
                      Total Channel Views
                    </p>
                  </div>
                )}
                {data.breakout_contributions > 0 && (
                  <div>
                    <p className="text-[11px] tabular-nums text-zinc-400">
                      {data.breakout_contributions}
                    </p>
                    <p className="text-[9px] uppercase tracking-wider text-zinc-600">
                      Breakout Contributions
                    </p>
                  </div>
                )}
                {data.computed_at && (
                  <div>
                    <p className="text-[11px] tabular-nums text-zinc-600">
                      {data.computed_at.slice(0, 10)}
                    </p>
                    <p className="text-[9px] uppercase tracking-wider text-zinc-700">
                      Score Computed
                    </p>
                  </div>
                )}
              </div>
            </TerminalPanel>

            {/* ── Score breakdown ────────────────────────────────────────── */}
            <ScoreComponents
              components={data.score_components}
              influenceScore={data.influence_score}
            />

            {/* ── Entity portfolio ───────────────────────────────────────── */}
            <EntityPortfolio rows={data.top_entities} />

            {/* ── Recent content ─────────────────────────────────────────── */}
            <RecentContent rows={data.recent_content} />
          </div>
        )}
      </div>
    </div>
  );
}
