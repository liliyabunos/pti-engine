import Link from "next/link";
import { PublicHeader } from "@/components/public/PublicHeader";
import { PublicFooter } from "@/components/public/PublicFooter";

// ─── Static data ────────────────────────────────────────────────────────────

const CAPABILITIES = [
  {
    accent: "text-emerald-400",
    border: "border-emerald-500/20",
    bg: "bg-emerald-500/5",
    icon: "▲",
    label: "Top Movers",
    desc: "Live leaderboard ranked by composite market score, momentum, and growth rate. Know which perfumes and brands are actually moving before the market catches up.",
  },
  {
    accent: "text-amber-400",
    border: "border-amber-500/20",
    bg: "bg-amber-500/5",
    icon: "⚡",
    label: "Signal Detection",
    desc: "Breakout, acceleration, reversal, and peak signals detected daily. Each signal includes strength score, entity context, and source attribution.",
  },
  {
    accent: "text-cyan-400",
    border: "border-cyan-500/20",
    bg: "bg-cyan-500/5",
    icon: "⌖",
    label: "Screener",
    desc: "Filter and sort 55,000+ perfumes and 1,600+ brands by score, mentions, trend state, signal type, notes, or accords. Search the full catalog, not just active movers.",
  },
  {
    accent: "text-violet-400",
    border: "border-violet-500/20",
    bg: "bg-violet-500/5",
    icon: "◈",
    label: "Entity Intelligence",
    desc: "Per-entity charts, signal timelines, source breakdowns, top drivers, notes & accords composition, semantic topic clusters, and competitor cross-references.",
  },
  {
    accent: "text-rose-400",
    border: "border-rose-500/20",
    bg: "bg-rose-500/5",
    icon: "◎",
    label: "Brand Portfolios",
    desc: "Brand-level market surface with portfolio aggregation. See how Creed, Dior, or Maison Francis Kurkdjian are moving as a whole — not just individual SKUs.",
  },
  {
    accent: "text-sky-400",
    border: "border-sky-500/20",
    bg: "bg-sky-500/5",
    icon: "≋",
    label: "Source Intelligence",
    desc: "Signals include source-category context such as platform, community/channel category, and source diversity where permitted. Weighted scoring separates viral noise from sustained market signal. FragranceIndex.ai does not sell personal profiles, follower lists, contact data, or raw social platform datasets.",
  },
];

const USE_CASES = [
  {
    role: "Fragrance Brand",
    color: "text-emerald-400",
    dot: "bg-emerald-400",
    items: [
      "Detect competitor breakouts 3–7 days before mainstream coverage",
      "Understand which public content channels and communities are contributing to brand momentum",
      "Monitor reformulation and dupe signals before they spike",
      "Track note and accord trends to inform next-season development",
    ],
  },
  {
    role: "Retail Buyer",
    color: "text-amber-400",
    dot: "bg-amber-400",
    items: [
      "Rank assortment candidates by real consumer signal, not sales rep claims",
      "Spot rising niche brands before they hit mainstream distribution",
      "Compare brand portfolio momentum ahead of buying season",
      "Identify gifting and blind-buy signals driving purchase intent",
    ],
  },
  {
    role: "Content Strategist",
    color: "text-cyan-400",
    dot: "bg-cyan-400",
    items: [
      "Find trending perfumes before they peak to create timely content",
      "Understand which topics drive engagement for each entity",
      "Map the public conversation landscape — which channels, communities, and topics are contributing to each trend",
      "Use signal data to pitch brand partnerships backed by market evidence",
    ],
  },
];

const SIGNAL_EXAMPLE = {
  entity: "Creed Aventus",
  type: "breakout",
  strength: 0.87,
  score: 72.4,
  growth: "+41%",
  mentions: 13,
  sources: "YouTube (8) · Reddit (5)",
  date: "Apr 25, 2026",
  drivers: ["Fragrance Therapy", "Redolessence", "r/fragrance"],
  topics: ["compliment getter", "signature scent", "men's fragrance"],
  queries: ["creed aventus review", "creed aventus 2026"],
};

const METHODOLOGY_STEPS = [
  {
    step: "01",
    label: "Ingest",
    color: "text-emerald-400",
    desc: "YouTube and Reddit content collected twice daily via YouTube Data API v3 and Reddit public endpoints. 47 tracked queries + channel-first polling of 50+ fragrance creators.",
  },
  {
    step: "02",
    label: "Resolve",
    color: "text-amber-400",
    desc: "55,000+ perfume alias database maps mentions to canonical entities. Multi-token sliding-window matching with single-word safety guards prevents false positives.",
  },
  {
    step: "03",
    label: "Score",
    color: "text-cyan-400",
    desc: "Composite market score weights mention count (35%), engagement (25%), growth (20%), momentum (10%), and source diversity (10%). YouTube and Reddit have platform-specific multipliers.",
  },
  {
    step: "04",
    label: "Detect",
    color: "text-violet-400",
    desc: "Breakout, acceleration, reversal, and peak signals detected daily using calibrated thresholds. Noise suppression prevents single-video spikes or source-transition artifacts.",
  },
  {
    step: "05",
    label: "Enrich",
    color: "text-rose-400",
    desc: "272,000+ note and accord associations from Parfumo dataset. Semantic topic extraction from 40 deterministic rules. Brand portfolio aggregation from resolver catalog.",
  },
];

const REPORT_SECTIONS = [
  { label: "Executive Summary", desc: "Plain-language market narrative for the period" },
  { label: "Top Trending Perfumes", desc: "Cross-source ranking with trend direction and signal type" },
  { label: "Rising Notes & Accords", desc: "Ingredient-level momentum — vanilla, oud, woody, fresh" },
  { label: "Source Breakdown", desc: "Creator-driven vs community-driven signal attribution" },
  { label: "Emerging Signals", desc: "New entities and early breakouts not yet in mainstream coverage" },
  { label: "Opportunity Summary", desc: "Dupe market, high-intent, gifting, and launch window flags" },
];

// ─── Page ───────────────────────────────────────────────────────────────────

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-950">
      <PublicHeader />

      {/* ── 1. Hero ─────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden border-b border-zinc-800/60">
        {/* Background grid */}
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.15) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        <div className="relative mx-auto w-full max-w-5xl px-6 py-24 sm:py-32">
          {/* Badge */}
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-emerald-400">
              Live · Early Access
            </span>
          </div>

          {/* FTI byline */}
          <p className="mb-4 font-mono text-xs font-semibold uppercase tracking-widest text-amber-400/70">
            Fragrance Trend Intelligence · FragranceIndex.ai
          </p>

          <h1 className="mb-5 max-w-3xl text-4xl font-bold tracking-tight text-zinc-100 sm:text-5xl lg:text-6xl">
            The Market Terminal{" "}
            <span className="text-amber-400">for Fragrance Trends</span>
          </h1>

          <p className="mb-4 max-w-2xl text-base leading-relaxed text-zinc-400 sm:text-lg">
            FragranceIndex.ai powers FTI Market Terminal — fragrance trend
            intelligence that monitors public YouTube and Reddit content
            to surface which perfumes and brands are breaking out, and why.
          </p>
          <p className="mb-10 max-w-xl text-sm leading-relaxed text-zinc-600">
            Composite market scores. Signal detection. Source-aware attribution. Entity
            intelligence. A complete market intelligence stack, updated twice daily.
          </p>

          <div className="flex flex-wrap gap-3">
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded bg-amber-500 px-6 py-3 text-sm font-semibold text-zinc-950 hover:bg-amber-400 transition-colors"
            >
              Enter the Terminal
              <span aria-hidden>→</span>
            </Link>
            <Link
              href="/glossary"
              className="inline-flex items-center gap-2 rounded border border-zinc-700 px-6 py-3 text-sm font-medium text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 transition-colors"
            >
              Signal Glossary
            </Link>
          </div>

          {/* Stats strip */}
          <div className="mt-14 flex flex-wrap gap-x-10 gap-y-4 border-t border-zinc-800/50 pt-8">
            {[
              { value: "55,000+", label: "Known perfumes" },
              { value: "1,600+", label: "Brands tracked" },
              { value: "2×", label: "Daily pipeline cycles" },
              { value: "YouTube + Reddit", label: "Signal sources" },
            ].map((s) => (
              <div key={s.label}>
                <p className="font-mono text-xl font-bold text-zinc-100">{s.value}</p>
                <p className="text-xs text-zinc-600">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 2. Problem ──────────────────────────────────────────────────── */}
      <section className="border-b border-zinc-800/60 bg-zinc-900/30">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            The Problem
          </p>
          <h2 className="mb-8 max-w-2xl text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            Fragrance trends move faster than the data you have access to
          </h2>
          <div className="grid gap-6 sm:grid-cols-3">
            {[
              {
                problem: "Delayed signals",
                desc: "Sales data lags by weeks. By the time a SKU spikes, the creator cycle has already peaked and the next trend is forming.",
              },
              {
                problem: "No attribution",
                desc: "You see that something is trending. You don't know if it's one viral video, a Reddit thread, or sustained creator coverage.",
              },
              {
                problem: "Market noise",
                desc: "Brand PR and paid influencer pushes are mixed in with organic community discovery. Raw mention counts mean nothing without weighting.",
              },
            ].map((item) => (
              <div key={item.problem} className="rounded border border-zinc-800 bg-zinc-900/50 p-5">
                <p className="mb-2 text-sm font-semibold text-zinc-300">{item.problem}</p>
                <p className="text-xs leading-relaxed text-zinc-500">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 3. What It Does ─────────────────────────────────────────────── */}
      <section className="border-b border-zinc-800/60">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            What It Does
          </p>
          <h2 className="mb-10 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            A full intelligence stack, not a dashboard
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {CAPABILITIES.map((cap) => (
              <div
                key={cap.label}
                className={`rounded border ${cap.border} ${cap.bg} p-5 transition-colors hover:border-zinc-700`}
              >
                <div className="mb-3 flex items-center gap-2">
                  <span className={`font-mono text-base ${cap.accent}`}>{cap.icon}</span>
                  <p className={`text-sm font-semibold ${cap.accent}`}>{cap.label}</p>
                </div>
                <p className="text-xs leading-relaxed text-zinc-500">{cap.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 4. Dashboard Preview (mock terminal) ────────────────────────── */}
      <section className="border-b border-zinc-800/60 bg-zinc-900/20">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            The Terminal
          </p>
          <h2 className="mb-8 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            Built like a trading terminal, not a beauty dashboard
          </h2>

          {/* Mock terminal */}
          <div className="overflow-hidden rounded-lg border border-zinc-700/60 bg-zinc-950 shadow-2xl">
            {/* Title bar */}
            <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900 px-4 py-2.5">
              <span className="h-2.5 w-2.5 rounded-full bg-rose-500/70" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-500/70" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
              <span className="ml-3 font-mono text-[10px] text-zinc-600">
                fragranceindex.ai — Dashboard · Apr 25 2026
              </span>
            </div>

            {/* KPI strip */}
            <div className="grid grid-cols-4 divide-x divide-zinc-800 border-b border-zinc-800">
              {[
                { label: "Known Perfumes", value: "55,622", color: "text-zinc-100" },
                { label: "Active Today", value: "130", color: "text-emerald-400" },
                { label: "Breakouts", value: "10", color: "text-amber-400" },
                { label: "Avg Score", value: "38.4", color: "text-zinc-100" },
              ].map((kpi) => (
                <div key={kpi.label} className="px-4 py-3">
                  <p className={`font-mono text-lg font-bold ${kpi.color}`}>{kpi.value}</p>
                  <p className="text-[10px] text-zinc-600">{kpi.label}</p>
                </div>
              ))}
            </div>

            {/* Table header */}
            <div className="grid grid-cols-12 gap-2 border-b border-zinc-800/60 bg-zinc-900/40 px-4 py-2">
              {["ENTITY", "SCORE", "TREND", "SIGNAL", "MENTIONS", "GROWTH"].map((h, i) => (
                <p
                  key={h}
                  className={`font-mono text-[9px] font-semibold uppercase tracking-wider text-zinc-600 ${
                    i === 0 ? "col-span-4" : i <= 3 ? "col-span-2" : "col-span-1"
                  }`}
                >
                  {h}
                </p>
              ))}
            </div>

            {/* Table rows */}
            {[
              {
                entity: "Creed Aventus",
                brand: "Creed",
                score: "72.4",
                trend: "breakout",
                trendColor: "text-emerald-400 bg-emerald-400/10 border-emerald-500/30",
                signal: "⚡ breakout",
                signalColor: "text-amber-400",
                mentions: "13",
                growth: "+41%",
                growthColor: "text-emerald-400",
              },
              {
                entity: "MFK Baccarat Rouge 540",
                brand: "Maison Francis Kurkdjian",
                score: "68.5",
                trend: "rising",
                trendColor: "text-green-400 bg-green-400/10 border-green-500/30",
                signal: "▲ rising",
                signalColor: "text-green-400",
                mentions: "9",
                growth: "+28%",
                growthColor: "text-emerald-400",
              },
              {
                entity: "Parfums de Marly Delina",
                brand: "Parfums de Marly",
                score: "55.2",
                trend: "stable",
                trendColor: "text-sky-400 bg-sky-400/10 border-sky-500/30",
                signal: "— stable",
                signalColor: "text-zinc-500",
                mentions: "6",
                growth: "+3%",
                growthColor: "text-zinc-400",
              },
              {
                entity: "Dior Sauvage",
                brand: "Dior",
                score: "49.8",
                trend: "peak",
                trendColor: "text-amber-400 bg-amber-400/10 border-amber-500/30",
                signal: "◎ peak",
                signalColor: "text-amber-400",
                mentions: "5",
                growth: "-2%",
                growthColor: "text-rose-400",
              },
            ].map((row) => (
              <div
                key={row.entity}
                className="grid grid-cols-12 gap-2 border-b border-zinc-800/30 px-4 py-2.5 hover:bg-zinc-900/50"
              >
                <div className="col-span-4">
                  <p className="text-xs font-medium text-zinc-200">{row.entity}</p>
                  <p className="text-[10px] text-zinc-600">{row.brand}</p>
                </div>
                <p className="col-span-2 self-center font-mono text-xs font-semibold text-zinc-100">
                  {row.score}
                </p>
                <div className="col-span-2 self-center">
                  <span
                    className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase ${row.trendColor}`}
                  >
                    {row.trend}
                  </span>
                </div>
                <p className={`col-span-2 self-center font-mono text-[10px] ${row.signalColor}`}>
                  {row.signal}
                </p>
                <p className="col-span-1 self-center font-mono text-xs text-zinc-400">
                  {row.mentions}
                </p>
                <p className={`col-span-1 self-center font-mono text-xs font-semibold ${row.growthColor}`}>
                  {row.growth}
                </p>
              </div>
            ))}

            <div className="px-4 py-2 text-right">
              <span className="font-mono text-[10px] text-zinc-700">
                130 active entities · sorted by composite market score
              </span>
            </div>
          </div>

          <p className="mt-4 text-center text-xs text-zinc-600">
            Live terminal data — updated twice daily via automated pipeline
          </p>
        </div>
      </section>

      {/* ── 5. Example Signal ───────────────────────────────────────────── */}
      <section className="border-b border-zinc-800/60">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Example Signal
          </p>
          <h2 className="mb-8 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            What a breakout looks like
          </h2>

          <div className="overflow-hidden rounded-lg border border-amber-500/20 bg-zinc-900/60">
            {/* Signal header */}
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-800 bg-amber-500/5 px-6 py-4">
              <div className="flex items-center gap-3">
                <span className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 font-mono text-xs font-bold text-amber-400 uppercase">
                  ⚡ Breakout
                </span>
                <p className="text-base font-semibold text-zinc-100">
                  {SIGNAL_EXAMPLE.entity}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <div>
                  <p className="font-mono text-xl font-bold text-zinc-100">{SIGNAL_EXAMPLE.score}</p>
                  <p className="text-[10px] text-zinc-600">Market score</p>
                </div>
                <div>
                  <p className="font-mono text-xl font-bold text-emerald-400">{SIGNAL_EXAMPLE.growth}</p>
                  <p className="text-[10px] text-zinc-600">Growth rate</p>
                </div>
                <div>
                  <p className="font-mono text-xl font-bold text-zinc-100">{SIGNAL_EXAMPLE.mentions}</p>
                  <p className="text-[10px] text-zinc-600">Mentions</p>
                </div>
              </div>
            </div>

            {/* Signal body */}
            <div className="grid gap-6 px-6 py-5 sm:grid-cols-3">
              <div>
                <p className="mb-2 font-mono text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
                  Signal strength
                </p>
                <div className="mb-1 h-2 overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className="h-full rounded-full bg-amber-500"
                    style={{ width: `${SIGNAL_EXAMPLE.strength * 100}%` }}
                  />
                </div>
                <p className="font-mono text-xs text-zinc-400">
                  {(SIGNAL_EXAMPLE.strength * 100).toFixed(0)}% — high confidence
                </p>
              </div>

              <div>
                <p className="mb-2 font-mono text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
                  Top drivers
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {SIGNAL_EXAMPLE.drivers.map((d) => (
                    <span
                      key={d}
                      className="rounded border border-zinc-700 bg-zinc-800/50 px-2 py-0.5 text-[10px] text-zinc-300"
                    >
                      {d}
                    </span>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-2 font-mono text-[9px] font-semibold uppercase tracking-widest text-zinc-600">
                  Why it&apos;s trending
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {SIGNAL_EXAMPLE.topics.map((t) => (
                    <span
                      key={t}
                      className="rounded border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[10px] text-sky-400"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="border-t border-zinc-800/60 px-6 py-3">
              <p className="font-mono text-[10px] text-zinc-600">
                Detected {SIGNAL_EXAMPLE.date} · Sources: {SIGNAL_EXAMPLE.sources}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 6. Use Cases ────────────────────────────────────────────────── */}
      <section className="border-b border-zinc-800/60 bg-zinc-900/20">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Use Cases
          </p>
          <h2 className="mb-10 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            Decision advantage at every role
          </h2>
          <div className="grid gap-6 sm:grid-cols-3">
            {USE_CASES.map((uc) => (
              <div key={uc.role} className="rounded border border-zinc-800 bg-zinc-900/50 p-5">
                <div className="mb-4 flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${uc.dot}`} />
                  <p className={`text-sm font-semibold ${uc.color}`}>{uc.role}</p>
                </div>
                <ul className="space-y-2.5">
                  {uc.items.map((item) => (
                    <li key={item} className="flex gap-2 text-xs leading-relaxed text-zinc-500">
                      <span className="mt-0.5 shrink-0 text-zinc-700">›</span>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 7. Reports ──────────────────────────────────────────────────── */}
      <section className="border-b border-zinc-800/60">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Intelligence Reports
          </p>
          <h2 className="mb-3 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            Structured market narrative, not raw data
          </h2>
          <p className="mb-10 max-w-2xl text-sm leading-relaxed text-zinc-500">
            Periodic intelligence reports combine YouTube and Reddit signals into a
            cross-source market narrative — readable by a brand founder, useful to an
            analyst. Each report covers:
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {REPORT_SECTIONS.map((section, i) => (
              <div
                key={section.label}
                className="flex items-start gap-3 rounded border border-zinc-800 bg-zinc-900/30 p-4"
              >
                <span className="font-mono text-xs font-bold text-zinc-700">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <p className="mb-0.5 text-xs font-semibold text-zinc-200">{section.label}</p>
                  <p className="text-xs leading-relaxed text-zinc-600">{section.desc}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-6 rounded border border-zinc-800 bg-zinc-900/30 px-5 py-4">
            <p className="text-xs text-zinc-500">
              <span className="font-semibold text-zinc-400">Report delivery:</span>{" "}
              Intelligence reports are in development for early access members. Access members
              will be notified when the first report cycle begins.
            </p>
          </div>
        </div>
      </section>

      {/* ── 8. Methodology ──────────────────────────────────────────────── */}
      <section className="border-b border-zinc-800/60 bg-zinc-900/20">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            How It Works
          </p>
          <h2 className="mb-10 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            Deterministic by design
          </h2>
          <div className="space-y-0 divide-y divide-zinc-800/60">
            {METHODOLOGY_STEPS.map((step) => (
              <div key={step.step} className="grid gap-4 py-5 sm:grid-cols-12">
                <div className="sm:col-span-2">
                  <span className={`font-mono text-xs font-bold ${step.color}`}>
                    {step.step}
                  </span>
                  <p className={`text-sm font-semibold ${step.color}`}>{step.label}</p>
                </div>
                <p className="text-xs leading-relaxed text-zinc-500 sm:col-span-10">
                  {step.desc}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-6 rounded border border-zinc-800/60 bg-zinc-900/30 px-5 py-4">
            <p className="text-xs leading-relaxed text-zinc-600">
              No AI required for core detection. All scoring, signal detection, and topic
              extraction is deterministic and rule-based. Every signal is reproducible and
              explainable from source data.
            </p>
          </div>
        </div>
      </section>

      {/* ── 9. Early Access Value ───────────────────────────────────────── */}
      <section className="border-b border-zinc-800/60">
        <div className="mx-auto max-w-5xl px-6 py-16">
          <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
            Early Access
          </p>
          <h2 className="mb-4 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            Get in before the signal becomes consensus
          </h2>
          <p className="mb-10 max-w-2xl text-sm leading-relaxed text-zinc-500">
            FragranceIndex is in soft launch. Early access members get full terminal
            access while the product is in active development — and direct input into
            what gets built next.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            {[
              {
                accent: "border-emerald-500/20 bg-emerald-500/5",
                title: "Full terminal access",
                color: "text-emerald-400",
                items: [
                  "Dashboard with live top movers",
                  "Signal feed — breakout, acceleration, reversal",
                  "Screener across 55,000+ perfumes",
                  "Entity pages with full intelligence view",
                  "Brand portfolio pages",
                  "Notes & accords intelligence",
                ],
              },
              {
                accent: "border-amber-500/20 bg-amber-500/5",
                title: "Coming next",
                color: "text-amber-400",
                items: [
                  "Watchlists — save entities, monitor changes",
                  "Alerts — breakout and threshold notifications",
                  "Intelligence reports — weekly market narrative",
                  "Source-context summaries — limited excerpts and links where permitted",
                  "Expanded source coverage",
                  "API access for data integration",
                ],
              },
            ].map((tier) => (
              <div key={tier.title} className={`rounded border ${tier.accent} p-6`}>
                <p className={`mb-4 text-sm font-semibold ${tier.color}`}>{tier.title}</p>
                <ul className="space-y-2">
                  {tier.items.map((item) => (
                    <li key={item} className="flex items-start gap-2 text-xs text-zinc-400">
                      <span className={`mt-0.5 shrink-0 ${tier.color}`}>✓</span>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 10. Final CTA ───────────────────────────────────────────────── */}
      <section className="bg-zinc-900/20">
        <div className="mx-auto max-w-5xl px-6 py-20 text-center">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
            <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-400">
              Invite only
            </span>
          </div>

          <h2 className="mb-4 text-3xl font-bold tracking-tight text-zinc-100 sm:text-4xl">
            Ready to enter the terminal?
          </h2>
          <p className="mb-8 mx-auto max-w-lg text-sm leading-relaxed text-zinc-500">
            If you have an access invitation, enter the terminal now.
            FragranceIndex is in active development — early members shape what
            the product becomes.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded bg-amber-500 px-7 py-3 text-sm font-semibold text-zinc-950 hover:bg-amber-400 transition-colors"
            >
              Enter the Terminal
              <span aria-hidden>→</span>
            </Link>
            <Link
              href="/glossary"
              className="inline-flex items-center gap-2 rounded border border-zinc-700 px-7 py-3 text-sm font-medium text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 transition-colors"
            >
              Signal Glossary
            </Link>
          </div>

          <p className="mt-8 text-xs text-zinc-700">
            No account required to explore the glossary. Terminal access requires invitation.
          </p>
        </div>
      </section>

      <PublicFooter />
    </div>
  );
}
