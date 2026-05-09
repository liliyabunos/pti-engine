import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Data Deletion Instructions · FragranceIndex.ai",
};

function EmailLink({ email, subject }: { email: string; subject?: string }) {
  const href = subject
    ? `mailto:${email}?subject=${encodeURIComponent(subject)}`
    : `mailto:${email}`;
  return (
    <a
      href={href}
      className="text-amber-500/70 hover:text-amber-400 transition-colors"
    >
      {email}
    </a>
  );
}

export default function DataDeletionPage() {
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
          Data Deletion Instructions
        </h1>
        <p className="text-xs text-zinc-600">Last updated: May 2026</p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed text-zinc-400">
        <p>
          FragranceIndex.ai respects your privacy and your right to request
          deletion of your data.
        </p>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            How to Request Deletion
          </h2>
          <div className="space-y-3">
            <p>
              If you used Facebook Login, Instagram Login, or connected a Meta
              business asset to FragranceIndex.ai, you may request deletion of
              your data by contacting us at:
            </p>
            <p>
              <EmailLink
                email="privacy@fragranceindex.ai"
                subject="Data Deletion Request"
              />
            </p>
            <p>
              Please use the subject line:{" "}
              <span className="font-mono text-zinc-300">
                Data Deletion Request
              </span>
            </p>
            <p>
              In your email, please include the email address, Meta account,
              Facebook Page, Instagram account, or business asset associated
              with your request so we can verify and process it.
            </p>
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            What Happens Next
          </h2>
          <div className="space-y-3">
            <p>
              Once we receive a verified request, we will delete or anonymize
              applicable personal data associated with your account or connected
              Meta business asset, unless we are required to retain certain
              information for legal, security, fraud prevention, or compliance
              purposes.
            </p>
            <p>
              We will process verified deletion requests in accordance with
              applicable privacy laws and Meta Platform requirements.
            </p>
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Contact
          </h2>
          <p>
            If you have questions about data deletion or privacy, contact us at:{" "}
            <EmailLink email="privacy@fragranceindex.ai" />
          </p>
        </section>
      </div>
    </div>
  );
}
