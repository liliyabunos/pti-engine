import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Cookie Notice · FragranceIndex.ai",
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

export default function CookiesPage() {
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
          Cookie Notice
        </h1>
        <p className="text-xs text-zinc-600">Last updated: {LAST_UPDATED}</p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed">
        <Section title="What we use cookies and local storage for">
          <p>
            FragranceIndex.ai currently uses only essential cookies and browser localStorage
            to operate the invite-only access system and maintain your session.
          </p>
          <Ul items={[
            "Access code storage: your invite access code is stored in localStorage to maintain your authenticated session across page loads",
            "Session cookie: a browser cookie may be set to support session continuity with our authentication provider (Supabase)",
            "No preferences, tracking, advertising, or analytics cookies are set at this stage",
          ]} />
        </Section>

        <Section title="No third-party advertising or analytics cookies">
          <p>
            FragranceIndex.ai does not currently use:
          </p>
          <Ul items={[
            "Third-party advertising cookies",
            "Third-party analytics or behavioral tracking cookies",
            "Session recording tools",
            "Social media pixel trackers",
          ]} />
        </Section>

        <Section title="Essential cookies only">
          <p>
            Because we currently use only essential cookies necessary to operate the service,
            cookie consent banners are not required under most frameworks at this time.
            If we add non-essential cookies or analytics tools in the future, we will update
            this notice and implement appropriate consent mechanisms where required by law.
          </p>
        </Section>

        <Section title="How to manage cookies">
          <p>
            You can clear cookies and localStorage at any time through your browser settings.
            Doing so will sign you out of the terminal and require you to re-enter your
            access code.
          </p>
        </Section>

        <Section title="Changes to this notice">
          <p>
            If we add non-essential cookies, analytics, or advertising technologies,
            we will update this notice with details on what is set, why, and how to
            opt out. We will implement consent mechanisms where required by applicable law
            (e.g. ePrivacy Directive / PECR for EEA/UK visitors).
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Cookie or privacy questions:{" "}
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
