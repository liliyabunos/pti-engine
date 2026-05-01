import Link from "next/link";

export function PublicFooter() {
  return (
    <footer className="border-t border-zinc-800 bg-zinc-950 py-8">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-4 px-6 sm:flex-row sm:justify-between">
        <span className="font-mono text-xs font-bold tracking-widest text-amber-400/70 uppercase">
          FTI
        </span>
        <nav className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-zinc-600">
          <Link href="/glossary" className="hover:text-zinc-400 transition-colors">
            Signal Glossary
          </Link>
          <Link href="/privacy" className="hover:text-zinc-400 transition-colors">
            Privacy Policy
          </Link>
          <Link href="/terms" className="hover:text-zinc-400 transition-colors">
            Terms of Use
          </Link>
          <Link href="/login" className="hover:text-zinc-400 transition-colors">
            Sign In
          </Link>
        </nav>
        <p className="text-[11px] text-zinc-700">
          Invite-only soft launch &middot; {new Date().getFullYear()}
        </p>
      </div>
    </footer>
  );
}
