import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Use · FragranceIndex.ai",
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

export default function TermsPage() {
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
          Terms of Use
        </h1>
        <p className="text-xs text-zinc-600">Last updated: {LAST_UPDATED}</p>
        <p className="mt-2 text-xs text-zinc-600">
          These terms should be reviewed by a licensed attorney before paid commercial launch.
        </p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed">
        {/* 1. Eligibility */}
        <Section title="1. Eligibility and invite-only access">
          <p>
            FTI Market Terminal by FragranceIndex.ai is currently in invite-only soft launch.
            Access requires an explicit invitation from the FragranceIndex.ai team. By
            accessing the terminal, you confirm that you are at least 18 years old (or the
            age of majority in your jurisdiction, if higher).
          </p>
          <p>
            Access codes are personal and non-transferable. Sharing your access code with
            unauthorized parties is a violation of these terms and may result in immediate
            access revocation.
          </p>
        </Section>

        {/* 2. License */}
        <Section title="2. License to use the terminal">
          <p>
            Subject to these terms, FragranceIndex.ai grants you a limited, personal,
            non-exclusive, non-transferable, revocable license to access and use FTI Market
            Terminal for your internal research, brand strategy, or editorial purposes during
            the period your access is active.
          </p>
          <p>
            This license does not include any right to sublicense, distribute, resell, or
            provide access to the terminal to any third party.
          </p>
        </Section>

        {/* 3. Acceptable use */}
        <Section title="3. Acceptable use">
          <p>You may use FTI Market Terminal to:</p>
          <Ul items={[
            "View aggregated fragrance trend data, signals, and market scores",
            "Use insights for internal research, brand strategy, or editorial purposes",
            "Monitor watchlists and receive in-app signal notifications",
            "Reference signal data to support internal business decisions",
          ]} />
        </Section>

        {/* 4. Prohibited use */}
        <Section title="4. Prohibited use">
          <p>You may not:</p>
          <Ul items={[
            "Scrape, harvest, or bulk-download data from the terminal via automated means",
            "Redistribute, resell, republish, or share FragranceIndex.ai data or outputs with third parties without explicit written permission",
            "Use the terminal or its outputs to build a competing database, product, or service",
            "Reverse-engineer, decompile, or attempt to extract source data, algorithms, or methodologies from the terminal or API",
            "Share access credentials or facilitate unauthorized access by third parties",
            "Use terminal outputs to identify, contact, profile, harass, or surveil any individual",
            "Use terminal outputs for spam, unsolicited commercial outreach, or any purpose targeting individuals",
            "Use the terminal in any manner that violates applicable law, platform terms, or third-party rights",
          ]} />
        </Section>

        {/* 5. Intellectual property */}
        <Section title="5. Intellectual property">
          <p>
            All signals, scoring methodologies, aggregated data, UI components, software,
            and content created by FragranceIndex.ai powering FTI Market Terminal are the
            intellectual property of FragranceIndex.ai and its licensors. You may not copy,
            modify, or create derivative works from our proprietary content without written
            permission.
          </p>
        </Section>

        {/* 6. Third-party source content */}
        <Section title="6. Third-party source content">
          <p>
            FragranceIndex.ai does not claim ownership of third-party source content from
            YouTube, Reddit, or other platforms. We use limited source information for
            analytical, transformative, and attribution purposes, subject to applicable law
            and platform terms.
          </p>
          <p>
            Source references and limited excerpts displayed in the terminal are for context
            and attribution only. Users should visit the original platform to view original
            content in full. See our{" "}
            <a href="/data-sources" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Data Sources &amp; Platform Compliance Notice
            </a>{" "}
            and{" "}
            <a href="/copyright" className="text-amber-500/70 hover:text-amber-400 transition-colors">
              Copyright / DMCA Notice
            </a>.
          </p>
        </Section>

        {/* 7. Accuracy disclaimer */}
        <Section title="7. Accuracy disclaimer">
          <p>
            Trend signals, market scores, and analytics displayed in FTI Market Terminal are
            derived from automated processing of public content signals. FragranceIndex.ai
            makes no representations or warranties about the accuracy, completeness,
            timeliness, or fitness for any particular purpose of any data displayed.
          </p>
        </Section>

        {/* 8. No professional advice */}
        <Section title="8. No professional advice">
          <p>
            Nothing in FTI Market Terminal constitutes legal, regulatory, compliance, or
            professional advice of any kind. Consult qualified professionals for advice
            specific to your situation.
          </p>
        </Section>

        {/* 9. No financial advice */}
        <Section title="9. No financial or investment advice">
          <p>
            Data, signals, and scores displayed in FTI Market Terminal are for informational
            purposes only. Nothing in this terminal constitutes commercial, financial,
            investment, or business advice. Use of FragranceIndex.ai data for commercial
            decisions is at your sole discretion and risk.
          </p>
        </Section>

        {/* 10. Beta / soft launch */}
        <Section title="10. Beta and soft launch disclaimer">
          <p>
            FTI Market Terminal is currently in invite-only soft launch. Features, data
            coverage, and performance may change without notice. We reserve the right to
            modify, suspend, or discontinue any part of the service at any time during
            this phase.
          </p>
        </Section>

        {/* 11. Account suspension */}
        <Section title="11. Account suspension and termination">
          <p>
            FragranceIndex.ai reserves the right to suspend or revoke access at any time,
            with or without notice, for any violation of these terms or at our sole discretion
            during the soft launch period. No compensation or refund will be owed for access
            revocation during the invite-only phase.
          </p>
        </Section>

        {/* 12. Limitation of liability */}
        <Section title="12. Limitation of liability">
          <p>
            To the maximum extent permitted by applicable law, FTI Market Terminal is
            provided &ldquo;as is&rdquo; and &ldquo;as available&rdquo; without warranty of
            any kind, express or implied. FragranceIndex.ai shall not be liable for any
            direct, indirect, incidental, consequential, or special damages arising from
            the use or inability to use the terminal, including but not limited to loss of
            data, lost profits, or business interruption.
          </p>
        </Section>

        {/* 13. Indemnity */}
        <Section title="13. Indemnification">
          <p>
            You agree to indemnify and hold harmless FragranceIndex.ai and its operators,
            officers, and affiliates from any claims, damages, losses, or costs (including
            reasonable legal fees) arising from your use of the terminal in violation of
            these terms or applicable law.
          </p>
        </Section>

        {/* 14. Changes to terms */}
        <Section title="14. Changes to these terms">
          <p>
            We may update these terms at any time. We will update the &ldquo;Last
            updated&rdquo; date when we do. Continued use of the terminal after changes are
            posted constitutes acceptance of the updated terms.
          </p>
        </Section>

        {/* 15. Governing law */}
        <Section title="15. Governing law">
          <p>
            These terms are governed by the laws of the State of Florida, United States,
            without regard to its conflict of law provisions. <em className="text-zinc-600">
            [Attorney review recommended before paid launch — confirm operating entity
            and jurisdiction.]</em>
          </p>
        </Section>

        {/* 16. Contact */}
        <Section title="16. Contact">
          <p>
            For questions about these terms:{" "}
            <a
              href="mailto:legal@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              legal@fragranceindex.ai
            </a>
          </p>
        </Section>
      </div>
    </div>
  );
}
