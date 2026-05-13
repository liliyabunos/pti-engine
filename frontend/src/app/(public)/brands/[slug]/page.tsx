import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

// ---------------------------------------------------------------------------
// ISR — revalidate every hour; data changes at most twice daily (pipeline)
// ---------------------------------------------------------------------------
export const revalidate = 3600;

// ---------------------------------------------------------------------------
// Types (M0-approved public fields only)
// ---------------------------------------------------------------------------

interface PublicPerfumeRow {
  slug: string;
  canonical_name: string;
  latest_score: number | null;
  trend_state: string | null;
}

interface PublicBrandDetail {
  slug: string;
  canonical_name: string;
  latest_score: number | null;
  trend_state: string | null;
  perfume_count: number;
  top_5_perfumes: PublicPerfumeRow[];
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function fetchPublicBrand(slug: string): Promise<PublicBrandDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/brands/${encodeURIComponent(slug)}`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const brand = await fetchPublicBrand(slug);
  if (!brand) {
    return { title: "Brand not found — FragranceIndex.ai" };
  }

  const title = `${brand.canonical_name} Perfume Brand — Market Intelligence · FragranceIndex.ai`;
  const description = `Track ${brand.canonical_name} fragrance trends. Portfolio performance, market score, and momentum data from YouTube and Reddit. Updated daily.`;

  return {
    title,
    description,
    openGraph: {
      title: `${brand.canonical_name} — Fragrance Brand Trend Data`,
      description,
      url: `https://fragranceindex.ai/brands/${slug}`,
      type: "article",
    },
    twitter: {
      title: `${brand.canonical_name} — Fragrance Brand Trend Data`,
      description,
    },
    alternates: {
      canonical: `https://fragranceindex.ai/brands/${slug}`,
    },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function TrendBadge({ state }: { state: string | null }) {
  if (!state) return null;
  const map: Record<string, { label: string; className: string }> = {
    rising:    { label: "▲ Rising",    className: "text-emerald-400" },
    stable:    { label: "◆ Stable",    className: "text-zinc-400" },
    declining: { label: "▼ Declining", className: "text-rose-400" },
  };
  const m = map[state.toLowerCase()];
  if (!m) return null;
  return <span className={`text-sm font-medium ${m.className}`}>{m.label}</span>;
}

function ScorePill({ score }: { score: number | null }) {
  if (score === null) return null;
  return (
    <span className="rounded bg-zinc-800 px-2 py-0.5 font-mono text-sm text-amber-400">
      {score.toFixed(1)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function PublicBrandPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const brand = await fetchPublicBrand(slug);

  if (!brand) {
    notFound();
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      {/* Breadcrumb */}
      <nav className="mb-6 text-xs text-zinc-600">
        <Link href="/" className="hover:text-zinc-400 transition-colors">
          FragranceIndex.ai
        </Link>
        <span className="mx-2">/</span>
        <span className="text-zinc-400">{brand.canonical_name}</span>
      </nav>

      {/* Hero */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-zinc-100">{brand.canonical_name}</h1>
        <p className="mt-1 text-sm text-zinc-500">
          {brand.perfume_count.toLocaleString()} perfumes in catalog
        </p>

        <div className="mt-3 flex items-center gap-3">
          <ScorePill score={brand.latest_score} />
          <TrendBadge state={brand.trend_state} />
        </div>
      </div>

      {/* Top tracked perfumes */}
      {brand.top_5_perfumes.length > 0 && (
        <section className="mb-8 rounded border border-zinc-800 bg-zinc-900/50 p-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-zinc-500">
            Top Tracked Perfumes
          </h2>
          <div className="space-y-2">
            {brand.top_5_perfumes.map((p) => (
              <div
                key={p.slug}
                className="flex items-center justify-between rounded border border-zinc-800/60 bg-zinc-900 px-3 py-2"
              >
                <Link
                  href={`/perfumes/${p.slug}`}
                  className="text-sm text-zinc-200 hover:text-amber-400 transition-colors"
                >
                  {p.canonical_name}
                </Link>
                <div className="flex items-center gap-2">
                  {p.latest_score !== null && (
                    <span className="font-mono text-xs text-amber-400">
                      {p.latest_score.toFixed(1)}
                    </span>
                  )}
                  <TrendBadge state={p.trend_state} />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-zinc-600">
            Full portfolio with all tracked perfumes available in the terminal.
          </p>
        </section>
      )}

      {/* CTA */}
      <div className="rounded border border-amber-500/20 bg-amber-950/10 p-5 text-center">
        <p className="mb-1 text-sm font-medium text-zinc-200">
          See full {brand.canonical_name} portfolio intelligence
        </p>
        <p className="mb-4 text-xs text-zinc-500">
          Full catalog · signal history · portfolio aggregation · brand-level analytics
        </p>
        <Link
          href={`/login?next=/entities/brand/${encodeURIComponent(`brand-${slug}`)}`}
          className="inline-flex items-center rounded border border-amber-500/60 px-4 py-2 text-sm text-amber-400 hover:border-amber-400 hover:text-amber-300 transition-colors"
        >
          Sign in to open terminal
        </Link>
      </div>
    </div>
  );
}
