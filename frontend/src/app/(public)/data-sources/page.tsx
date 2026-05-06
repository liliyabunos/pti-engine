import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Data Sources & Platform Compliance · FragranceIndex.ai",
};

const LAST_UPDATED = "May 2026";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
        {title}
      </h2>
      <div className="space-y-2 text-zinc-400">{children}</div>
    </section>
  );
}

function Ul({ items }: { items: string[] }) {
  return (
    <ul className="ml-4 list-disc space-y-1 text-zinc-500">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export default function DataSourcesPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <div className="mb-10">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-px w-6 bg-amber-500/60" />
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-amber-500/80">
            Compliance
          </span>
        </div>
        <h1 className="mb-1 text-2xl font-bold tracking-tight text-zinc-100">
          Data Sources &amp; Platform Compliance Notice
        </h1>
        <p className="text-xs text-zinc-600">Last updated: {LAST_UPDATED}</p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed">
        <Section title="1. What FragranceIndex.ai does">
          <p>
            FragranceIndex.ai transforms publicly available or source-permitted
            fragrance-related content signals into aggregated market intelligence. We
            process these signals to surface which perfumes, brands, notes, accords, and
            topics are trending — and why — across public fragrance communities.
          </p>
          <p>
            Our product is aggregated market intelligence. It is not a raw content feed,
            platform mirror, creator directory, or personal data product.
          </p>
        </Section>

        <Section title="2. Source types">
          <p>FragranceIndex.ai currently processes signals from:</p>
          <Ul items={[
            "YouTube: public video metadata, titles, and engagement signals accessible via the YouTube Data API and public endpoints, in compliance with YouTube API Services Terms of Service",
            "Reddit: public community posts and engagement signals where permitted by Reddit's API terms and community guidelines",
            "Public or licensed fragrance reference datasets (e.g. fragrance catalog metadata, notes, accords) where applicable",
          ]} />
          <p>
            Future sources are evaluated against applicable platform terms, API policies,
            and rate limits before integration.
          </p>
        </Section>

        <Section title="3. What we do not do">
          <p>FragranceIndex.ai does not:</p>
          <Ul items={[
            "Sell raw YouTube, Reddit, or TikTok datasets",
            "Sell follower lists, subscriber lists, or audience databases",
            "Sell private contact information for creators or users",
            "Scrape content from behind login walls or authentication barriers",
            "Bypass CAPTCHAs, rate limits, or other technical access controls",
            "Claim ownership over third-party platform content",
            "Use source content as a substitute for or replacement of the original platform",
            "Store or display full post bodies or raw comment text in public-facing outputs",
          ]} />
        </Section>

        <Section title="4. Source links and attribution">
          <p>
            Where source references are displayed in the terminal, they are for context
            and attribution purposes — linking to the original public content on its
            original platform. Users should visit the original platform to view content
            in full.
          </p>
          <p>
            Limited title excerpts and source URLs may be shown to provide context for
            signal attribution. These references are not a substitute for the original
            content or creator relationship.
          </p>
        </Section>

        <Section title="5. Takedown and exclusion requests">
          <p>
            Creators, publishers, or platform representatives who believe their content
            is improperly referenced or displayed may contact us for review:
          </p>
          <p>
            <a
              href="mailto:legal@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              legal@fragranceindex.ai
            </a>
          </p>
          <p>
            Please include a description of the content in question, the URL or
            reference where it appears, and your contact information. We will review
            and respond in good faith.
          </p>
        </Section>

        <Section title="6. Platform terms and API compliance">
          <p>
            We aim to respect applicable platform terms of service, API usage policies,
            rate limits, and source restrictions. This includes:
          </p>
          <Ul items={[
            "YouTube API Services Terms of Service (developers.google.com/youtube/terms/api-services-terms-of-service)",
            "Reddit API Terms and community guidelines",
            "Applicable platform rate limits and access restrictions",
          ]} />
          <p>
            If you are a platform representative with a concern about our usage,
            contact <a
              href="mailto:legal@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >legal@fragranceindex.ai</a>.
          </p>
        </Section>
      </div>
    </div>
  );
}
