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

interface PublicPerfumeDetail {
  slug: string;
  canonical_name: string;
  brand_name: string | null;
  brand_slug: string | null;
  entity_role: string;
  reference_original: string | null;
  relation_type: string | null;
  notes_top: string[];
  notes_middle: string[];
  notes_base: string[];
  accords: string[];
  latest_score: number | null;
  trend_state: string | null;
  top_opportunity: string | null;
  top_2_differentiators: string[];
  top_3_creator_names: string[];
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function fetchPublicPerfume(slug: string): Promise<PublicPerfumeDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/public/perfumes/${encodeURIComponent(slug)}`, {
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
  const perfume = await fetchPublicPerfume(slug);
  if (!perfume) {
    return { title: "Perfume not found — FragranceIndex.ai" };
  }

  const title = perfume.brand_name
    ? `${perfume.canonical_name} by ${perfume.brand_name} — Market Intelligence · FragranceIndex.ai`
    : `${perfume.canonical_name} — Market Intelligence · FragranceIndex.ai`;

  const description = `Track ${perfume.canonical_name} fragrance trends. Market score, momentum, and signal data from YouTube and Reddit. Updated daily.`;

  return {
    title,
    description,
    openGraph: {
      title: `${perfume.canonical_name} — Fragrance Trend Data`,
      description,
      url: `https://fragranceindex.ai/perfumes/${slug}`,
      type: "article",
    },
    twitter: {
      title: `${perfume.canonical_name} — Fragrance Trend Data`,
      description,
    },
    alternates: {
      canonical: `https://fragranceindex.ai/perfumes/${slug}`,
    },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROLE_META: Record<string, { label: string; className: string }> = {
  designer_original:     { label: "Designer Original",    className: "border-sky-800 bg-sky-950/40 text-sky-400" },
  niche_original:        { label: "Niche Original",       className: "border-violet-800 bg-violet-950/40 text-violet-400" },
  original:              { label: "Original",             className: "border-zinc-600 bg-zinc-800/40 text-zinc-300" },
  dupe_alternative:      { label: "Dupe / Alternative",   className: "border-amber-700 bg-amber-950/40 text-amber-300" },
  designer_alternative:  { label: "Designer Alternative", className: "border-blue-700 bg-blue-950/40 text-blue-300" },
  celebrity_alternative: { label: "Celebrity Alternative",className: "border-pink-700 bg-pink-950/40 text-pink-300" },
  clone_positioned:      { label: "Clone-Positioned",     className: "border-amber-800 bg-amber-950/40 text-amber-400" },
};

function TrendBadge({ state }: { state: string | null }) {
  if (!state) return null;
  const map: Record<string, { label: string; className: string }> = {
    rising:    { label: "▲ Rising",   className: "text-emerald-400" },
    stable:    { label: "◆ Stable",   className: "text-zinc-400" },
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

function NotesList({ notes, label }: { notes: string[]; label: string }) {
  if (!notes.length) return null;
  return (
    <div>
      <span className="text-[11px] uppercase tracking-widest text-zinc-600">{label}</span>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {notes.map((n) => (
          <span
            key={n}
            className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-xs text-zinc-300"
          >
            {n}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function PublicPerfumePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const perfume = await fetchPublicPerfume(slug);

  if (!perfume) {
    notFound();
  }

  const roleMeta = ROLE_META[perfume.entity_role];
  const hasNotes =
    perfume.notes_top.length > 0 ||
    perfume.notes_middle.length > 0 ||
    perfume.notes_base.length > 0 ||
    perfume.accords.length > 0;

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      {/* Breadcrumb */}
      <nav className="mb-6 text-xs text-zinc-600">
        <Link href="/" className="hover:text-zinc-400 transition-colors">
          FragranceIndex.ai
        </Link>
        <span className="mx-2">/</span>
        {perfume.brand_slug ? (
          <Link href={`/brands/${perfume.brand_slug}`} className="hover:text-zinc-400 transition-colors">
            {perfume.brand_name ?? "Brand"}
          </Link>
        ) : (
          <span>{perfume.brand_name ?? "Brand"}</span>
        )}
        <span className="mx-2">/</span>
        <span className="text-zinc-400">{perfume.canonical_name}</span>
      </nav>

      {/* Hero */}
      <div className="mb-8">
        {perfume.brand_name && (
          <p className="mb-1 text-sm text-zinc-500">
            by{" "}
            {perfume.brand_slug ? (
              <Link href={`/brands/${perfume.brand_slug}`} className="hover:text-zinc-300 transition-colors">
                {perfume.brand_name}
              </Link>
            ) : (
              perfume.brand_name
            )}
          </p>
        )}
        <h1 className="text-2xl font-bold text-zinc-100">{perfume.canonical_name}</h1>

        {/* Role badge + dupe context */}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {roleMeta && (
            <span
              className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${roleMeta.className}`}
            >
              {roleMeta.label}
            </span>
          )}
          {perfume.reference_original && (
            <span className="text-xs text-amber-400/70">
              {perfume.relation_type === "dupe_of"
                ? "Dupe of:"
                : "Alternative to:"}{" "}
              {perfume.reference_original}
            </span>
          )}
        </div>

        {/* Score + trend */}
        <div className="mt-3 flex items-center gap-3">
          <ScorePill score={perfume.latest_score} />
          <TrendBadge state={perfume.trend_state} />
        </div>
      </div>

      {/* Notes & Accords */}
      {hasNotes && (
        <section className="mb-8 rounded border border-zinc-800 bg-zinc-900/50 p-4">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-zinc-500">
            Notes &amp; Accords
          </h2>
          <div className="space-y-3">
            <NotesList notes={perfume.notes_top} label="Top" />
            <NotesList notes={perfume.notes_middle} label="Middle" />
            <NotesList notes={perfume.notes_base} label="Base" />
            <NotesList notes={perfume.accords} label="Accords" />
          </div>
        </section>
      )}

      {/* Why it's trending */}
      {(perfume.top_opportunity || perfume.top_2_differentiators.length > 0) && (
        <section className="mb-8 rounded border border-zinc-800 bg-zinc-900/50 p-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-zinc-500">
            Why It&apos;s Trending
          </h2>
          {perfume.top_opportunity && (
            <div className="mb-2 flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-widest text-zinc-600">Signal</span>
              <span className="rounded bg-amber-950/40 px-2 py-0.5 text-xs text-amber-300 border border-amber-800/50">
                {perfume.top_opportunity}
              </span>
            </div>
          )}
          {perfume.top_2_differentiators.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-widest text-zinc-600">What makes it stand out</span>
              <div className="flex flex-wrap gap-1.5">
                {perfume.top_2_differentiators.map((d) => (
                  <span
                    key={d}
                    className="rounded border border-zinc-700 bg-zinc-800/40 px-2 py-0.5 text-xs text-zinc-300"
                  >
                    {d}
                  </span>
                ))}
              </div>
            </div>
          )}
          <p className="mt-3 text-[11px] text-zinc-600">
            Full signal timeline, drivers, and attribution available in the terminal.
          </p>
        </section>
      )}

      {/* Community voices */}
      {perfume.top_3_creator_names.length > 0 && (
        <section className="mb-8 rounded border border-zinc-800 bg-zinc-900/50 p-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-zinc-500">
            Community Voices
          </h2>
          <div className="flex flex-wrap gap-2">
            {perfume.top_3_creator_names.map((name) => (
              <span
                key={name}
                className="rounded border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs text-zinc-300"
              >
                {name}
              </span>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-zinc-600">
            Full creator attribution, engagement data, and early-signal badges in the terminal.
          </p>
        </section>
      )}

      {/* CTA */}
      <div className="rounded border border-amber-500/20 bg-amber-950/10 p-5 text-center">
        <p className="mb-1 text-sm font-medium text-zinc-200">
          See full market intelligence for {perfume.canonical_name}
        </p>
        <p className="mb-4 text-xs text-zinc-500">
          90-day chart · signal timeline · source attribution · opportunity analysis
        </p>
        <Link
          href={`/login?next=/entities/perfume/${encodeURIComponent(perfume.slug)}`}
          className="inline-flex items-center rounded border border-amber-500/60 px-4 py-2 text-sm text-amber-400 hover:border-amber-400 hover:text-amber-300 transition-colors"
        >
          Sign in to open terminal
        </Link>
      </div>
    </div>
  );
}
