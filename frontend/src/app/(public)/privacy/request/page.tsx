import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Data Rights Request · FragranceIndex.ai",
};

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

export default function PrivacyRequestPage() {
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
          Data Rights Request
        </h1>
        <p className="text-xs text-zinc-600">
          Submit privacy rights requests, access requests, deletion requests,
          correction requests, source exclusion requests, or general privacy inquiries.
        </p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed">
        <Section title="How to submit a request">
          <p>
            Email your request to:{" "}
            <a
              href="mailto:privacy@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              privacy@fragranceindex.ai
            </a>
          </p>
          <p>In your email, please include:</p>
          <Ul items={[
            "Your name and how you access the service (e.g. as an invited user, or as a creator/public figure whose content may be referenced)",
            "The type of request (access, deletion, correction, opt-out, source exclusion, or other)",
            "Enough information to help us locate any relevant data",
            "Your preferred contact method for our response",
          ]} />
        </Section>

        <Section title="Types of requests we can process">
          <Ul items={[
            "Access: request a summary of personal information we hold about you",
            "Deletion: request deletion of personal information we hold about you",
            "Correction: request correction of inaccurate personal information",
            "Opt out of sale or sharing: we do not sell or share personal information — no opt-out action required",
            "Source exclusion: request that your public content channel or profile be excluded from our market intelligence processing",
            "Privacy review: request a review of how your information is handled",
          ]} />
        </Section>

        <Section title="Verification">
          <p>
            We may need to verify your identity or authorization before acting on a request.
            Verification may require you to provide additional information to confirm your
            identity or your connection to the content or data in question.
          </p>
          <p>
            We will not discriminate against you for exercising your privacy rights.
          </p>
        </Section>

        <Section title="Source exclusion requests">
          <p>
            If you are a content creator, publisher, or platform representative and believe
            your content is improperly referenced or you wish to be excluded from our
            market intelligence processing, contact us at{" "}
            <a
              href="mailto:privacy@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              privacy@fragranceindex.ai
            </a>{" "}
            or{" "}
            <a
              href="mailto:legal@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              legal@fragranceindex.ai
            </a>.
          </p>
          <p>
            Please note that content may also need to be removed at the original platform
            (e.g. YouTube or Reddit) for it to no longer be accessible to any aggregator.
            Removal from our system does not affect what is publicly available on the
            original platform.
          </p>
        </Section>

        <Section title="Response timeframe">
          <p>
            We will acknowledge your request promptly and respond within the timeframes
            required by applicable law (generally 30–45 days, with possible extensions
            as permitted by law).
          </p>
        </Section>

        <Section title="Related pages">
          <p>
            <Link href="/privacy" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Privacy Policy
            </Link>
            {" · "}
            <Link href="/privacy/california" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              California Privacy Notice
            </Link>
            {" · "}
            <Link href="/data-sources" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Data Sources Notice
            </Link>
            {" · "}
            <Link href="/copyright" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Copyright / DMCA
            </Link>
          </p>
        </Section>
      </div>
    </div>
  );
}
