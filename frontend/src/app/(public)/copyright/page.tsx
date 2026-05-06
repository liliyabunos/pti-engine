import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Copyright & DMCA Notice · FragranceIndex.ai",
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

export default function CopyrightPage() {
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
          Copyright &amp; DMCA Notice
        </h1>
        <p className="text-xs text-zinc-600">Last updated: {LAST_UPDATED}</p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed">
        <Section title="Intellectual property policy">
          <p>
            FragranceIndex.ai respects intellectual property rights. We do not claim
            ownership over third-party platform content, including videos, posts, or other
            media from YouTube, Reddit, or other sources.
          </p>
          <p>
            Where source references, limited title excerpts, or links appear in FTI Market
            Terminal, they are used for analytical, transformative, and attribution purposes,
            subject to applicable law and platform terms. Users should visit original
            platforms to view content in full.
          </p>
        </Section>

        <Section title="DMCA takedown notice">
          <p>
            If you are a copyright owner or authorized agent and believe that material
            accessible through FragranceIndex.ai infringes your copyright, you may submit
            a takedown notice to:
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
            Your notice must include the following, as required by 17 U.S.C. § 512(c)(3):
          </p>
          <Ul items={[
            "Identification of the copyrighted work you claim has been infringed (or a representative list if multiple)",
            "Identification of the material you claim is infringing and its location (e.g. URL within FragranceIndex.ai)",
            "Your contact information: name, address, telephone number, and email address",
            "A statement that you have a good-faith belief that the use is not authorized by the copyright owner, its agent, or the law",
            "A statement, made under penalty of perjury, that the information in your notice is accurate and that you are the copyright owner or authorized to act on the owner's behalf",
            "Your physical or electronic signature",
          ]} />
          <p>
            We will review valid DMCA notices and respond in accordance with applicable law.
            Submitting a false DMCA notice may result in liability under 17 U.S.C. § 512(f).
          </p>
        </Section>

        <Section title="Counter-notice">
          <p>
            If you believe that material was removed in error or misidentification, you may
            submit a counter-notice to{" "}
            <a
              href="mailto:legal@fragranceindex.ai"
              className="text-amber-500/70 hover:text-amber-400 transition-colors"
            >
              legal@fragranceindex.ai
            </a>{" "}
            including:
          </p>
          <Ul items={[
            "Identification of the material that was removed and where it appeared",
            "A statement under penalty of perjury that you have a good-faith belief the material was removed by mistake or misidentification",
            "Your name, address, telephone number, and email",
            "A statement that you consent to the jurisdiction of the federal court in your district (or, if outside the US, any judicial district in which we may be found), and that you will accept service of process from the complainant",
            "Your physical or electronic signature",
          ]} />
        </Section>

        <Section title="Our intellectual property">
          <p>
            The signals, scoring methodologies, aggregated analytics, software, UI design,
            and content created by FragranceIndex.ai are our intellectual property and are
            protected by applicable copyright, trade secret, and other laws.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Copyright and IP inquiries:{" "}
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
