import Link from "next/link";
import { PublicHeader } from "@/components/public/PublicHeader";
import { PublicFooter } from "@/components/public/PublicFooter";

const FEATURES = [
  {
    label: "Top Movers",
    desc: "Live leaderboard of perfumes and brands ranked by composite market score, momentum, and growth.",
  },
  {
    label: "Signal Feed",
    desc: "Breakout, acceleration, and reversal signals detected daily across YouTube and Reddit.",
  },
  {
    label: "Screener",
    desc: "Filter and sort all tracked entities by score, confidence, mentions, and signal type.",
  },
  {
    label: "Entity Pages",
    desc: "Per-entity time series charts, signal history, source breakdown, and recent mentions.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-950">
      <PublicHeader />

      {/* ── Hero ── */}
      <section className="mx-auto w-full max-w-5xl px-6 py-20">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-px w-8 bg-amber-500/60" />
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-500/80">
            Soft launch · Invite only
          </span>
        </div>

        <h1 className="mb-4 text-4xl font-bold tracking-tight text-zinc-100 sm:text-5xl">
          Perfume Trend Intelligence
        </h1>
        <p className="mb-8 max-w-xl text-base leading-relaxed text-zinc-400">
          A market terminal for fragrance trends. Track what&apos;s moving, why
          it&apos;s moving, and where the signal is coming from — across YouTube
          and Reddit in real time.
        </p>

        <div className="flex flex-wrap gap-3">
          <Link
            href="/login"
            className="inline-flex items-center gap-2 rounded bg-amber-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-amber-400 transition-colors"
          >
            Enter access code
            <span aria-hidden>→</span>
          </Link>
          <Link
            href="/glossary"
            className="inline-flex items-center gap-2 rounded border border-zinc-700 px-5 py-2.5 text-sm font-medium text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 transition-colors"
          >
            Signal glossary
          </Link>
        </div>
      </section>

      {/* ── Who it&apos;s for ── */}
      <section className="border-t border-zinc-800/60 bg-zinc-900/40">
        <div className="mx-auto max-w-5xl px-6 py-12">
          <p className="mb-8 text-xs font-semibold uppercase tracking-widest text-zinc-600">
            Built for
          </p>
          <div className="flex flex-wrap gap-3">
            {[
              "Fragrance brands",
              "Retail buyers",
              "Content strategists",
              "Market researchers",
              "Brand founders",
            ].map((tag) => (
              <span
                key={tag}
                className="rounded border border-zinc-700/60 px-3 py-1.5 text-xs text-zinc-400"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── Feature list ── */}
      <section className="mx-auto w-full max-w-5xl px-6 py-16">
        <p className="mb-10 text-xs font-semibold uppercase tracking-widest text-zinc-600">
          What&apos;s inside
        </p>
        <div className="grid gap-6 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <div
              key={f.label}
              className="rounded border border-zinc-800 bg-zinc-900/50 p-5"
            >
              <p className="mb-1.5 text-sm font-semibold text-zinc-100">
                {f.label}
              </p>
              <p className="text-xs leading-relaxed text-zinc-500">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Access gate callout ── */}
      <section className="border-t border-zinc-800/60 bg-zinc-900/40">
        <div className="mx-auto max-w-5xl px-6 py-12 text-center">
          <p className="mb-2 text-sm text-zinc-400">
            PTI is currently in invite-only soft launch.
          </p>
          <p className="mb-6 text-xs text-zinc-600">
            If you received an access code, enter it to open the terminal.
          </p>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 rounded bg-zinc-800 px-5 py-2.5 text-sm font-medium text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100 transition-colors"
          >
            Enter access code →
          </Link>
        </div>
      </section>

      <PublicFooter />
    </div>
  );
}
