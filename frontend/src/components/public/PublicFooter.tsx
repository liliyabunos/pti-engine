import Link from "next/link";

const LEGAL_LINKS = [
  { href: "/glossary", label: "Signal Glossary" },
  { href: "/privacy", label: "Privacy Policy" },
  { href: "/terms", label: "Terms of Use" },
  { href: "/data-sources", label: "Data Sources" },
  { href: "/privacy/california", label: "California Privacy" },
  { href: "/cookies", label: "Cookies" },
  { href: "/copyright", label: "Copyright / DMCA" },
  { href: "/privacy/request", label: "Data Rights Request" },
  { href: "/login", label: "Sign In" },
];

export function PublicFooter() {
  return (
    <footer className="border-t border-zinc-800 bg-zinc-950 py-8">
      <div className="mx-auto max-w-5xl px-6">
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between">
          <span className="font-mono text-xs font-bold tracking-widest text-amber-400/70 uppercase shrink-0">
            FTI
          </span>
          <nav className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-zinc-600">
            {LEGAL_LINKS.map(({ href, label }) => (
              <Link key={href} href={href} className="hover:text-zinc-400 transition-colors">
                {label}
              </Link>
            ))}
          </nav>
          <p className="text-[11px] text-zinc-700 shrink-0">
            Invite-only soft launch &middot; {new Date().getFullYear()}
          </p>
        </div>
        <p className="mt-4 text-center text-[10px] text-zinc-800">
          FragranceIndex.ai provides aggregated fragrance market intelligence, not personal data brokerage.
          We do not sell personal profiles, follower lists, subscriber lists, or raw platform datasets.
        </p>
      </div>
    </footer>
  );
}
