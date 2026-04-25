"use client";

/**
 * Phase I7 — Semantic Topic Intelligence
 *
 * Replaces raw topic/query/subreddit chips (I5) with 3 structured sections:
 *   1. Differentiators — what makes this perfume stand out
 *   2. Positioning     — what it is (notes, tier, gender, season, origin)
 *   3. Why People Search — intent signals (queries + search-intent labels)
 *
 * Communities (subreddits) shown as an optional footer row.
 * Falls back to "Low signal" if no data in any section.
 */

interface WhyTrendingProps {
  /** Phase I7 semantic fields */
  differentiators?: string[];
  positioning?: string[];
  intents?: string[];
  /** Phase I5 raw — communities shown separately */
  top_subreddits?: string[];
}

// ---------------------------------------------------------------------------
// Chip primitive
// ---------------------------------------------------------------------------

type ChipVariant = "diff" | "pos" | "intent" | "sub";

function Chip({ label, variant }: { label: string; variant: ChipVariant }) {
  const colors: Record<ChipVariant, string> = {
    diff:   "bg-emerald-950/60 text-emerald-300 border border-emerald-800/50",
    pos:    "bg-sky-950/60 text-sky-300 border border-sky-800/50",
    intent: "bg-violet-950/60 text-violet-300 border border-violet-800/50",
    sub:    "bg-orange-950/60 text-orange-300 border border-orange-800/50",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono ${colors[variant]}`}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Section row
// ---------------------------------------------------------------------------

function Section({
  label,
  items,
  variant,
}: {
  label: string;
  items: string[];
  variant: ChipVariant;
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <span className="text-[10px] text-zinc-500 uppercase tracking-wide">{label}</span>
      <div className="flex flex-wrap gap-1.5 mt-1">
        {items.map((item) => (
          <Chip key={item} label={item} variant={variant} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function WhyTrending({
  differentiators = [],
  positioning = [],
  intents = [],
  top_subreddits = [],
}: WhyTrendingProps) {
  const hasData =
    differentiators.length > 0 ||
    positioning.length > 0 ||
    intents.length > 0 ||
    top_subreddits.length > 0;

  if (!hasData) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">
          Why It&apos;s Trending
        </h3>
        <p className="text-xs text-zinc-600 italic">
          Low signal — insufficient data to determine topics
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
        Why It&apos;s Trending
      </h3>
      <div className="space-y-2.5">
        <Section label="Differentiators" items={differentiators} variant="diff" />
        <Section label="Positioning" items={positioning} variant="pos" />
        <Section label="Why People Search" items={intents} variant="intent" />
        {top_subreddits.length > 0 && (
          <Section
            label="Communities"
            items={top_subreddits.map((s) => `r/${s}`)}
            variant="sub"
          />
        )}
      </div>
    </div>
  );
}
