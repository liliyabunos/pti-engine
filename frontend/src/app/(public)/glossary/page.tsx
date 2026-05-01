import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Signal Glossary · FTI Market Terminal",
  description: "Definitions for all signals, metrics, and terms used in the FTI Market Terminal.",
};

const METRICS = [
  {
    term: "Composite Market Score",
    abbr: "CMS",
    definition:
      "The primary ranking metric for each entity. Combines mention volume (35%), engagement (25%), growth rate (20%), momentum (10%), and source diversity (10%). Weighted by platform — YouTube content scores higher than unverified sources.",
  },
  {
    term: "Effective Rank Score",
    abbr: "ERS",
    definition:
      "The score used for leaderboard ordering. Equal to the Composite Market Score for most entities, but reduced by a flood-dampening factor (0.6×) when fewer than 2 unique authors are responsible for all mentions on a given day. Prevents single-post events from distorting the ranking.",
  },
  {
    term: "Momentum",
    abbr: null,
    definition:
      "Rate of change in the Composite Market Score over a rolling window. Positive momentum means the entity is accelerating; negative momentum means it is cooling. Contributes 10% to the Composite Market Score.",
  },
  {
    term: "Growth Rate",
    abbr: null,
    definition:
      "Percentage change in mention count relative to the prior period. Expressed as a decimal (e.g. 0.45 = 45% growth). Drives 20% of the Composite Market Score.",
  },
  {
    term: "Confidence",
    abbr: null,
    definition:
      "Average resolver confidence across all mentions that map to this entity. Higher confidence means the entity's mentions were unambiguous. Low confidence may indicate aliases, misspellings, or brand overlap.",
  },
  {
    term: "Breakout",
    abbr: null,
    definition:
      "Signal fired when an entity's Composite Market Score exceeds a minimum threshold and its growth rate exceeds 35% within a single aggregation period. Requires at least 2 unique mention sources to suppress single-post noise.",
  },
  {
    term: "Acceleration Spike",
    abbr: null,
    definition:
      "Signal fired when an entity's momentum ratio exceeds 1.5× its prior-period momentum. Indicates the rate of growth itself is increasing — earlier than a breakout signal.",
  },
  {
    term: "Reversal",
    abbr: null,
    definition:
      "Signal fired when an entity's score drops significantly after sustained activity. Suppressed if the previous score was more than 4× the current score (prevents false reversals caused by source transitions or synthetic-to-real data handoffs).",
  },
  {
    term: "New Entry",
    abbr: null,
    definition:
      "Signal fired when an entity appears in the time series for the first time. Does not require a minimum mention count — even a single resolved mention on the first day qualifies.",
  },
  {
    term: "Source Type",
    abbr: null,
    definition:
      "The platform that contributed a mention. Current verified sources: YouTube (1.2× weight), Reddit (1.0× weight). TikTok is implemented but deferred from the serving layer pending production API approval. Unverified sources are weighted at 0.8×.",
  },
  {
    term: "Top Movers",
    abbr: null,
    definition:
      "Leaderboard of entities ranked by Effective Rank Score for the most recent aggregation period. Concentration variants (e.g. EDP vs base form) are collapsed into a single row at display time — the base form is elected primary when available.",
  },
  {
    term: "Screener",
    abbr: null,
    definition:
      "Filterable, sortable view of all tracked entities. Supports filtering by entity type (perfume / brand), minimum score, minimum confidence, minimum mentions, and signal type. Pagination is offset-based.",
  },
];

export default function GlossaryPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      {/* Page header */}
      <div className="mb-10">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-px w-6 bg-amber-500/60" />
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-500/80">
            Reference
          </span>
        </div>
        <h1 className="mb-2 text-2xl font-bold tracking-tight text-zinc-100">
          Signal Glossary
        </h1>
        <p className="text-sm leading-relaxed text-zinc-500">
          Definitions for all metrics, signals, and terms used in the FTI Market Terminal.
          The terminal is designed around market intelligence logic — treat these like
          financial instrument concepts applied to fragrance trend data.
        </p>
      </div>

      {/* Term list */}
      <div className="divide-y divide-zinc-800/60">
        {METRICS.map((item) => (
          <div key={item.term} className="py-6">
            <div className="mb-2 flex flex-wrap items-baseline gap-2">
              <h2 className="text-sm font-semibold text-zinc-100">{item.term}</h2>
              {item.abbr && (
                <span className="font-mono text-[10px] font-bold tracking-wider text-amber-500/70 uppercase">
                  {item.abbr}
                </span>
              )}
            </div>
            <p className="text-sm leading-relaxed text-zinc-500">{item.definition}</p>
          </div>
        ))}
      </div>

      {/* Footer note */}
      <div className="mt-10 rounded border border-zinc-800 bg-zinc-900/50 p-5">
        <p className="text-xs leading-relaxed text-zinc-600">
          <span className="font-semibold text-zinc-500">Note on data sources.</span>{" "}
          All signals are derived from real-source ingestion (YouTube API, Reddit public JSON endpoints).
          Scores and rankings are recomputed daily. Historical data is preserved for trend analysis.
          No data in this terminal constitutes commercial, financial, or investment advice.
        </p>
      </div>
    </div>
  );
}
