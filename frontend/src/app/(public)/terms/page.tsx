import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Use · PTI Market Terminal",
};

const LAST_UPDATED = "April 2026";

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
      </div>

      <div className="space-y-8 text-sm leading-relaxed text-zinc-400">
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Invite-only access
          </h2>
          <p>
            PTI Market Terminal is currently available only to users who have
            received an explicit invitation from the PTI team. Access codes are
            personal and non-transferable. Sharing your access code with
            unauthorized parties is a violation of these terms and may result in
            immediate access revocation.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Acceptable use
          </h2>
          <p className="mb-2">You may use the PTI terminal to:</p>
          <ul className="ml-4 list-disc space-y-1 text-zinc-500">
            <li>View fragrance trend data, signals, and market scores</li>
            <li>Use insights for internal research, brand strategy, or editorial purposes</li>
            <li>Monitor watchlists and receive in-app signal alerts</li>
          </ul>
          <p className="mt-3 mb-2">You may not:</p>
          <ul className="ml-4 list-disc space-y-1 text-zinc-500">
            <li>Scrape, harvest, or bulk-download data from the terminal via automated means</li>
            <li>Redistribute, resell, or republish PTI data without explicit written permission</li>
            <li>Use the terminal to build competing products without a separate licensing agreement</li>
            <li>Reverse-engineer, decompile, or attempt to extract source data from the API</li>
            <li>Share access credentials or facilitate unauthorized access</li>
          </ul>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Intellectual property
          </h2>
          <p>
            All signals, scoring methodologies, aggregated data, UI components,
            and software powering PTI are the intellectual property of PTI and
            its creators. The underlying source content (social media posts,
            videos) belongs to its respective creators and platforms. PTI holds
            no claim over source content and processes it only for analytical
            purposes under fair use principles.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            No commercial or financial advice
          </h2>
          <p>
            Data, signals, and scores displayed in PTI are for informational
            purposes only. Nothing in this terminal constitutes commercial,
            financial, investment, or business advice. PTI makes no
            representations or warranties about the accuracy, timeliness, or
            completeness of any information provided. Use of PTI data for
            commercial decisions is at your sole discretion and risk.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Account suspension and termination
          </h2>
          <p>
            PTI reserves the right to suspend or revoke access at any time,
            without notice, for any violation of these terms or at our discretion
            during the soft launch period. No compensation or refund will be owed
            for access revocation during the invite-only phase.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Limitation of liability
          </h2>
          <p>
            PTI is provided &ldquo;as is&rdquo; during the soft launch period, without warranty of any kind,
            express or implied. PTI shall not be liable for any damages arising
            from the use or inability to use the terminal, including but not
            limited to loss of data, commercial losses, or indirect damages.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Changes to these terms
          </h2>
          <p>
            We may update these terms at any time. Continued use of the terminal
            after changes are posted constitutes acceptance of the updated terms.
          </p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Contact
          </h2>
          <p>
            Questions about these terms:{" "}
            <a
              href="mailto:legal@pti.market"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              legal@pti.market
            </a>
          </p>
        </section>
      </div>
    </div>
  );
}
