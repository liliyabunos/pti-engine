import { PublicFooter } from "@/components/public/PublicFooter";
import { PublicHeader } from "@/components/public/PublicHeader";

/**
 * Public shell layout — wraps landing, glossary, legal, and login pages.
 *
 * Structure:
 *   PublicHeader (fixed nav)
 *   <main>        (page content)
 *   PublicFooter
 *
 * No Sidebar, no StatusBar — this is the outer public shell only.
 */
export default function PublicLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-950">
      <PublicHeader />
      <main className="flex-1">{children}</main>
      <PublicFooter />
    </div>
  );
}
