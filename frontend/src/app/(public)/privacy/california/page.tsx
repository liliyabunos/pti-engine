import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "California Privacy Notice · FragranceIndex.ai",
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

export default function CaliforniaPrivacyPage() {
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
          California Privacy Notice
        </h1>
        <p className="text-xs text-zinc-600">Last updated: {LAST_UPDATED} · Applies to California residents</p>
        <p className="mt-2 text-xs text-zinc-600">
          This notice supplements our{" "}
          <Link href="/privacy" className="text-amber-500/60 hover:text-amber-400 transition-colors">
            Privacy Policy
          </Link>. This notice should be reviewed by a licensed attorney before paid commercial launch.
        </p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed">
        <Section title="We do not sell or share your personal information">
          <p>
            FragranceIndex.ai does not sell or share personal information for cross-context
            behavioral advertising as those terms are defined under the California Consumer
            Privacy Act (CCPA) and California Privacy Rights Act (CPRA).
          </p>
          <p>
            FragranceIndex.ai does not sell personal profiles, follower lists, subscriber
            lists, email addresses, phone numbers, or raw personal datasets.
          </p>
          <p>
            FragranceIndex.ai does not knowingly sell or share the personal information of
            consumers under 16 years of age.
          </p>
        </Section>

        <Section title="Categories of personal information collected from users">
          <p>
            From users who access FTI Market Terminal, we may collect:
          </p>
          <Ul items={[
            "Identifiers: access code, and email/contact information only if you contact us directly",
            "Internet or other network activity: IP address, browser type, device type, server logs",
            "Commercial or business relationship information: your access status and usage of the service",
          ]} />
          <p>
            We do not collect sensitive personal information (as defined under CPRA) from terminal users.
          </p>
        </Section>

        <Section title="Categories of public source information processed for market intelligence">
          <p>
            To generate fragrance market intelligence (not personal information products), we process:
          </p>
          <Ul items={[
            "Public content metadata: source URLs, titles, publication timestamps",
            "Engagement metrics (views, likes, comment counts) where permitted",
            "Aggregated mention counts and trend signals by entity (perfume, brand, note, accord)",
            "Source category context: platform, channel/community category, source diversity",
            "Author/source counts stored only as aggregated integers",
          ]} />
        </Section>

        <Section title="Purposes of processing">
          <p>We process personal information for the following purposes:</p>
          <Ul items={[
            "Operating the FTI Market Terminal service",
            "Security, fraud prevention, and abuse detection",
            "Responding to support and privacy requests",
            "Generating aggregated fragrance market intelligence",
            "Legal compliance",
          ]} />
        </Section>

        <Section title="Your California privacy rights">
          <p>As a California resident, you may have the right to:</p>
          <Ul items={[
            "Know / Access: request information about the categories and specific pieces of personal information we have collected about you, the sources, purposes, and third parties we share with",
            "Delete: request deletion of personal information we hold about you, subject to certain exceptions",
            "Correct: request correction of inaccurate personal information we hold about you",
            "Opt out of sale / sharing: we do not sell or share personal information — no opt-out action required",
            "Limit use and disclosure of sensitive personal information: contact us if you believe we hold sensitive PI",
            "Non-discrimination: we will not discriminate against you for exercising your privacy rights",
          ]} />
        </Section>

        <Section title="How to submit a request">
          <p>To exercise your California privacy rights:</p>
          <Ul items={[
            "Email: privacy@fragranceindex.ai",
            "Subject line: California Privacy Request",
            "Include: your name, how you access the service, and the right(s) you wish to exercise",
          ]} />
          <p>
            We may need to verify your identity before acting on a request. We will respond
            within the timeframes required by applicable law (generally 45 days, with a
            possible 45-day extension). See our{" "}
            <Link href="/privacy/request" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Data Rights Request
            </Link>{" "}
            page for more information.
          </p>
        </Section>

        <Section title="Authorized agents">
          <p>
            California residents may designate an authorized agent to make requests on their
            behalf. We may require verification of the agent&rsquo;s authority before acting
            on a request submitted by an agent.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Privacy inquiries:{" "}
            <a
              href="mailto:privacy@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              privacy@fragranceindex.ai
            </a>
          </p>
        </Section>
      </div>
    </div>
  );
}
