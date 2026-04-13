import Link from "next/link";

export function PublicHeader() {
  return (
    <header className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        {/* Wordmark */}
        <Link href="/" className="flex items-center gap-2.5 text-zinc-100 hover:text-amber-400 transition-colors">
          <span className="font-mono text-xs font-bold tracking-widest text-amber-400 uppercase">
            PTI
          </span>
          <span className="text-sm font-semibold tracking-tight">
            Market Terminal
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-6 text-xs text-zinc-500">
          <Link href="/glossary" className="hover:text-zinc-300 transition-colors">
            Glossary
          </Link>
          <Link href="/privacy" className="hover:text-zinc-300 transition-colors">
            Privacy
          </Link>
          <Link href="/terms" className="hover:text-zinc-300 transition-colors">
            Terms
          </Link>
          <Link
            href="/login"
            className="rounded border border-zinc-700 px-3 py-1.5 text-zinc-300 hover:border-amber-500 hover:text-amber-400 transition-colors"
          >
            Sign in
          </Link>
        </nav>
      </div>
    </header>
  );
}
