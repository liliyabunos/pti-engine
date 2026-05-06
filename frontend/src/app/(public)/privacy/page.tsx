import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy · FragranceIndex.ai",
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

function EmailLink({ email }: { email: string }) {
  return (
    <a
      href={`mailto:${email}`}
      className="text-amber-500/70 hover:text-amber-400 transition-colors"
    >
      {email}
    </a>
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
        <p className="mt-2 text-xs text-zinc-600">
          This policy should be reviewed by a licensed attorney before paid commercial launch.
        </p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed">
        {/* 1. Overview */}
        <Section title="1. Overview">
          <p>
            FragranceIndex.ai provides FTI Market Terminal — an aggregated fragrance market
            intelligence platform. We transform publicly available or source-permitted fragrance
            conversation signals into perfume, brand, note, accord, topic, and momentum analytics.
          </p>
          <p>
            <strong className="text-zinc-300">We do not sell personal profiles, follower lists,
            subscriber lists, contact data, private messages, or raw social platform datasets.</strong>{" "}
            We sell access to aggregated fragrance market intelligence, not personal information.
          </p>
          <p>
            Our{" "}
            <Link href="/data-sources" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Data Sources &amp; Platform Compliance Notice
            </Link>{" "}
            describes our source practices in more detail.
          </p>
        </Section>

        {/* 2. Information we collect from visitors/users */}
        <Section title="2. Information we collect from visitors and users">
          <p>When you access FragranceIndex.ai, we may collect:</p>
          <Ul items={[
            "Access code and session information to verify your invite-only access",
            "Basic technical information: IP address, browser type, device info, and server logs",
            "Contact information only if you contact us directly (e.g. by email)",
            "Authentication session data stored in localStorage and a browser cookie to maintain your session",
          ]} />
          <p>
            We do not currently use third-party advertising trackers or session recording tools.
            No data about your browsing behavior within the terminal is sent to external analytics
            or advertising parties.
          </p>
        </Section>

        {/* 3. Information processed for market intelligence */}
        <Section title="3. Information processed for market intelligence">
          <p>
            To generate fragrance market intelligence, we process publicly available or
            source-permitted content signals including:
          </p>
          <Ul items={[
            "Public content metadata: source URLs, publication timestamps, titles",
            "Engagement metrics (views, likes, comment counts) where permitted by the source platform",
            "Aggregated mention counts and derived trend signals by entity (perfume, brand, note, accord)",
            "Entity extraction outputs: which fragrances and brands appear in public content",
            "Author/source counts stored only as aggregated integers where possible, not linked to individual accounts",
            "Source category context: platform, community/channel category, and source diversity",
          ]} />
          <p>
            Raw source text and post bodies are used for entity extraction and quality control
            only and are not displayed in public-facing API responses.
          </p>
        </Section>

        {/* 4. What we do not collect or sell */}
        <Section title="4. What we do not collect or sell">
          <p>FragranceIndex.ai does not collect, sell, or share:</p>
          <Ul items={[
            "Follower lists or subscriber lists",
            "Emails, phone numbers, or contact data from creators or social media users",
            "Private messages or direct messages",
            "Precise geolocation data",
            "Sensitive personal inferences (health, politics, religion, or similar)",
            "Raw social platform dataset exports",
            "Personal profiles, people-scoring products, or contact enrichment data",
          ]} />
        </Section>

        {/* 5. How we use information */}
        <Section title="5. How we use information">
          <p>We use the information we collect and process to:</p>
          <Ul items={[
            "Operate and maintain the FTI Market Terminal",
            "Generate aggregated fragrance trend analytics and market signals",
            "Detect breakout signals and trend momentum",
            "Improve the accuracy and coverage of entity resolution",
            "Maintain security, prevent unauthorized access, and detect abuse",
            "Respond to support and privacy requests",
            "Comply with applicable law",
          ]} />
        </Section>

        {/* 6. Legal bases (EEA/UK) */}
        <Section title="6. Legal bases for processing (EEA / UK GDPR)">
          <p>Where EU/UK GDPR applies, our legal bases for processing include:</p>
          <Ul items={[
            "Contract / steps prior to contract: to provide the service you have requested access to",
            "Legitimate interests: for security, fraud prevention, service operation, and aggregated market intelligence where such interests are not overridden by your rights",
            "Consent: where required by applicable law (e.g. non-essential cookies, if added in future)",
            "Legal obligation: where we are required to process or retain data by law",
          ]} />
        </Section>

        {/* 7. California privacy */}
        <Section title="7. California privacy rights (CCPA / CPRA)">
          <p>
            FragranceIndex.ai does not sell or share personal information for cross-context
            behavioral advertising as those terms are defined under California law.
          </p>
          <p>
            FragranceIndex.ai does not knowingly sell or share the personal information of
            minors under 16 years of age.
          </p>
          <p>California residents may have the right to:</p>
          <Ul items={[
            "Know / Access: request information about personal data we collect and how we use it",
            "Delete: request deletion of personal data we hold about you",
            "Correct: request correction of inaccurate personal data",
            "Opt out of sale / share: we do not sell or share personal information",
            "Limit use of sensitive personal information: contact us if applicable",
            "Non-discrimination: we will not discriminate against you for exercising your rights",
          ]} />
          <p>
            To exercise your rights, email{" "}
            <EmailLink email="privacy@fragranceindex.ai" />.
            We may need to verify your identity before acting on a request. See also our{" "}
            <Link href="/privacy/california" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              California Privacy Notice
            </Link>{" "}
            and{" "}
            <Link href="/privacy/request" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Data Rights Request
            </Link>{" "}
            page.
          </p>
        </Section>

        {/* 8. Data broker statement */}
        <Section title="8. Data broker statement">
          <p>
            FragranceIndex.ai is designed as an aggregated fragrance market intelligence platform,
            not a personal information data broker. We do not sell personal profiles, contact data,
            follower or subscriber lists, or raw personal datasets.
          </p>
          <p>
            If our business practices change in ways that affect this classification, we will update
            this policy and evaluate applicable data broker registration or notice obligations
            under state law.
          </p>
        </Section>

        {/* 9. EEA/UK rights */}
        <Section title="9. EEA / UK GDPR rights">
          <p>If EU or UK GDPR applies to you, you may have the right to:</p>
          <Ul items={[
            "Access: obtain a copy of the personal data we hold about you",
            "Rectification: correct inaccurate or incomplete personal data",
            "Erasure: request deletion of your personal data in certain circumstances",
            "Restriction: request that we restrict processing in certain circumstances",
            "Objection: object to processing based on legitimate interests",
            "Portability: receive your data in a portable format where applicable",
            "Lodge a complaint with your local supervisory authority",
          ]} />
          <p>
            Contact <EmailLink email="privacy@fragranceindex.ai" /> to exercise these rights.
          </p>
        </Section>

        {/* 10. Data retention */}
        <Section title="10. Data retention">
          <Ul items={[
            "Account, session, and contact data is retained only as long as needed to operate the service or comply with legal obligations",
            "Aggregated market data and trend signals may be retained for historical trend analysis",
            "Raw source text and metadata is retained only as long as needed for entity extraction, quality control, security, or legal compliance",
            "We prefer aggregated and de-identified long-term storage over raw content retention",
          ]} />
        </Section>

        {/* 11. Security */}
        <Section title="11. Security">
          <p>
            We apply reasonable technical and organizational safeguards to protect data in our
            custody, including access controls, secrets management, and periodic review. No system
            is perfectly secure. If you believe there is a security issue, contact{" "}
            <EmailLink email="privacy@fragranceindex.ai" />.
          </p>
        </Section>

        {/* 12. International transfers */}
        <Section title="12. International data transfers">
          <p>
            FragranceIndex.ai is operated from the United States. Data may be processed and
            stored in the United States. If you are located in the EEA or UK, please be aware
            that applicable transfer safeguards (such as standard contractual clauses) should
            apply where required by law. Contact us for more information.
          </p>
        </Section>

        {/* 13. Children */}
        <Section title="13. Children">
          <p>
            FTI Market Terminal is not directed to children under 13 years of age (or under 16
            in the EEA/UK). We do not knowingly collect personal information from children.
            If you believe we have collected such information, contact{" "}
            <EmailLink email="privacy@fragranceindex.ai" />.
          </p>
        </Section>

        {/* 14. Changes */}
        <Section title="14. Changes to this policy">
          <p>
            We may update this Privacy Policy from time to time. We will update the
            &ldquo;Last updated&rdquo; date when we do. Continued use of the service after
            changes are posted constitutes acceptance of the updated policy.
          </p>
        </Section>

        {/* 15. Contact */}
        <Section title="15. Contact">
          <p>
            For privacy questions, rights requests, or concerns:
          </p>
          <Ul items={[
            "Email: privacy@fragranceindex.ai",
            "Support: support@fragranceindex.ai",
          ]} />
          <p>
            See also:{" "}
            <Link href="/privacy/request" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Data Rights Request
            </Link>
            {" · "}
            <Link href="/privacy/california" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              California Privacy Notice
            </Link>
            {" · "}
            <Link href="/cookies" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Cookie Notice
            </Link>
          </p>
        </Section>
      </div>
    </div>
  );
}
