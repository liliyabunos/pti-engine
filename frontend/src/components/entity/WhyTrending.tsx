"use client";

/**
 * Phase I5 — Topic Intelligence
 * Shows why an entity is trending: matched topics, search queries, subreddits.
 */

interface WhyTrendingProps {
  top_topics?: string[];
  top_queries?: string[];
  top_subreddits?: string[];
}

function Chip({ label, variant }: { label: string; variant: "topic" | "query" | "subreddit" }) {
  const colors = {
    topic:
      "bg-sky-950/60 text-sky-300 border border-sky-800/50",
    query:
      "bg-violet-950/60 text-violet-300 border border-violet-800/50",
    subreddit:
      "bg-orange-950/60 text-orange-300 border border-orange-800/50",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono ${colors[variant]}`}>
      {label}
    </span>
  );
}

export function WhyTrending({ top_topics = [], top_queries = [], top_subreddits = [] }: WhyTrendingProps) {
  const hasData = top_topics.length > 0 || top_queries.length > 0 || top_subreddits.length > 0;
  if (!hasData) return null;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
        Why It&apos;s Trending
      </h3>
      <div className="space-y-2.5">
        {top_topics.length > 0 && (
          <div>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide mr-2">Topics</span>
            <div className="inline-flex flex-wrap gap-1.5 mt-1">
              {top_topics.map((t) => (
                <Chip key={t} label={t} variant="topic" />
              ))}
            </div>
          </div>
        )}
        {top_queries.length > 0 && (
          <div>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide mr-2">Queries</span>
            <div className="inline-flex flex-wrap gap-1.5 mt-1">
              {top_queries.map((q) => (
                <Chip key={q} label={q} variant="query" />
              ))}
            </div>
          </div>
        )}
        {top_subreddits.length > 0 && (
          <div>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide mr-2">Communities</span>
            <div className="inline-flex flex-wrap gap-1.5 mt-1">
              {top_subreddits.map((s) => (
                <Chip key={s} label={`r/${s}`} variant="subreddit" />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
