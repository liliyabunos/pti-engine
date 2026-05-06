"use client";

/**
 * Phase I8 — Market Intelligence Block
 *
 * Surfaces actionable decision intelligence:
 *   - narrative: plain-language reason why this entity is trending
 *   - opportunities: rule-based market flags (dupe_market, high_intent, gifting, …)
 *   - competitors: detected competing entities
 *
 * This is NOT analytics. It is decision intelligence.
 */

// ---------------------------------------------------------------------------
// Opportunity flag display config
// ---------------------------------------------------------------------------

const OPPORTUNITY_LABELS: Record<string, { label: string; color: string; description: string }> = {
  // Phase 3 — role-aware dupe/alternative flags
  alternative_demand: {
    label: "Alternative Demand",
    color: "bg-amber-950/60 text-amber-300 border border-amber-800/50",
    description: "Consumers are searching for dupes, clones, or alternatives to this reference scent",
  },
  alternative_search_interest: {
    label: "Alternative Search Interest",
    color: "bg-zinc-800/60 text-zinc-300 border border-zinc-600/50",
    description: "Alternative-related search activity detected around this entity",
  },
  clone_market: {
    label: "Clone-Positioned",
    color: "bg-lime-950/60 text-lime-300 border border-lime-800/50",
    description: "Positioned as an alternative to a reference scent",
  },
  // Legacy — kept for any data in transit; no longer generated for new requests
  dupe_market: {
    label: "Dupe Market",
    color: "bg-amber-950/60 text-amber-300 border border-amber-800/50",
    description: "Consumers actively seeking alternatives to this perfume",
  },
  affordable_alt: {
    label: "Affordable Alt",
    color: "bg-lime-950/60 text-lime-300 border border-lime-800/50",
    description: "Price-value positioning driving demand",
  },
  high_intent: {
    label: "High Intent",
    color: "bg-emerald-950/60 text-emerald-300 border border-emerald-800/50",
    description: "Multiple strong buy and discovery signals active",
  },
  competitive_comparison: {
    label: "Comparison Active",
    color: "bg-sky-950/60 text-sky-300 border border-sky-800/50",
    description: "Being compared against competitors in content",
  },
  gifting: {
    label: "Gift Demand",
    color: "bg-pink-950/60 text-pink-300 border border-pink-800/50",
    description: "Active gifting intent driving search volume",
  },
  viral_momentum: {
    label: "Viral Momentum",
    color: "bg-violet-950/60 text-violet-300 border border-violet-800/50",
    description: "Viral / trending signals detected — monitor for peak",
  },
  launch_window: {
    label: "Launch Window",
    color: "bg-indigo-950/60 text-indigo-300 border border-indigo-800/50",
    description: "New release or flanker activity driving awareness",
  },
  social_validation: {
    label: "Social Proof",
    color: "bg-teal-950/60 text-teal-300 border border-teal-800/50",
    description: "Compliment-getter reputation generating word-of-mouth",
  },
  performance_leader: {
    label: "Performance",
    color: "bg-cyan-950/60 text-cyan-300 border border-cyan-800/50",
    description: "Longevity and projection standing out in comparisons",
  },
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function OpportunityBadge({ flag }: { flag: string }) {
  const config = OPPORTUNITY_LABELS[flag];
  if (!config) return null;
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-mono cursor-default ${config.color}`}
      title={config.description}
    >
      {config.label}
    </span>
  );
}

function CompetitorChip({ name }: { name: string }) {
  return (
    <span className="inline-block px-2 py-0.5 rounded text-xs font-mono bg-rose-950/60 text-rose-300 border border-rose-800/50">
      {name}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface MarketInsightProps {
  narrative?: string | null;
  opportunities?: string[];
  competitors?: string[];
}

export function MarketInsight({
  narrative,
  opportunities = [],
  competitors = [],
}: MarketInsightProps) {
  const hasData = narrative || opportunities.length > 0 || competitors.length > 0;

  if (!hasData) return null;

  // Only show known flags (filter unknown flags from future API versions)
  const knownOpportunities = opportunities.filter((f) => f in OPPORTUNITY_LABELS);

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/60 p-4">
      <h3 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider mb-3">
        Market Insight
      </h3>

      {/* Narrative */}
      {narrative && (
        <p className="text-sm text-zinc-300 leading-relaxed mb-3">{narrative}</p>
      )}

      {/* Opportunity flags */}
      {knownOpportunities.length > 0 && (
        <div className="mb-3">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wide block mb-1.5">
            Opportunities
          </span>
          <div className="flex flex-wrap gap-1.5">
            {knownOpportunities.map((flag) => (
              <OpportunityBadge key={flag} flag={flag} />
            ))}
          </div>
        </div>
      )}

      {/* Competitors */}
      {competitors.length > 0 && (
        <div>
          <span className="text-[10px] text-zinc-500 uppercase tracking-wide block mb-1.5">
            Compared Against
          </span>
          <div className="flex flex-wrap gap-1.5">
            {competitors.map((c) => (
              <CompetitorChip key={c} name={c} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
