import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy · PTI Market Terminal",
};

const LAST_UPDATED = "April 2026";

export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <div className="mb-10">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-px w-6 bg-amber-500/60" />
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-500/80">
            Legal
          </span>
        </div>
        <h1 className="mb-1 text-2xl font-bold tracking-tight text-zinc-100">
          Privacy Policy
        </h1>
        <p className="text-xs text-zinc-600">Last updated: {LAST_UPDATED}</p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed text-zinc-400">
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            What this product is
          </h2>
          <p>
            PTI Market Terminal is a market intelligence tool that aggregates and
            analyzes publicly available content from social platforms (YouTube,
            Reddit) to produce trend signals for the fragrance industry. It does
            not collect, store, or process personal data about end users beyond
            what is described in this policy.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Data shown in the terminal
          </h2>
          <p className="mb-2">
            The terminal displays aggregated, anonymized trend data derived from
            public posts and videos. Specifically:
          </p>
          <ul className="ml-4 list-disc space-y-1 text-zinc-500">
            <li>Mention counts and engagement metrics, aggregated by entity (perfume or brand)</li>
            <li>Signal events (breakouts, reversals, accelerations) computed from aggregated data</li>
            <li>Source platform attribution (YouTube, Reddit) at the aggregate level</li>
            <li>Author count per day (stored as an integer, not linked to individual accounts)</li>
          </ul>
          <p className="mt-2 text-zinc-500">
            No personally identifiable information about content creators or
            social media users is displayed or stored in user-visible form.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Access and authentication
          </h2>
          <p>
            PTI is currently in invite-only soft launch. Access requires a code
            provided directly by the PTI team. The access code is stored in your
            browser (localStorage and a browser cookie) to maintain your session.
            No email address, password, or personal profile is collected at this
            stage.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            No analytics or tracking
          </h2>
          <p>
            PTI does not use third-party analytics, advertising trackers, or
            session recording tools. No data about your browsing behavior within
            the terminal is sent to external parties.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            No guarantee of accuracy or commercial outcome
          </h2>
          <p>
            Trend signals and market scores displayed in this terminal are derived
            from automated analysis of public social content. They do not
            constitute commercial, financial, or investment advice. PTI makes no
            guarantees about the accuracy, completeness, or commercial relevance
            of any data displayed.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Data retention
          </h2>
          <p>
            Aggregated market data is retained indefinitely to support historical
            trend analysis. Raw source content (video metadata, post text) is
            stored only as long as it is needed for aggregation and is not
            displayed in identifiable form.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Contact
          </h2>
          <p>
            For questions about this policy, contact:{" "}
            <a
              href="mailto:privacy@pti.market"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              privacy@pti.market
            </a>
          </p>
        </section>
      </div>
    </div>
  );
}
