import { redirect } from "next/navigation";
import { Sidebar } from "@/components/shell/Sidebar";
import { StatusBar } from "@/components/shell/StatusBar";
import { getApprovedSessionUser } from "@/lib/auth/guards.server";

/**
 * Terminal shell layout — Server Component.
 *
 * Visual structure (desktop):
 * ┌──────────────────────────────────────────────────────┐  ← h-screen
 * │  StatusBar  (global top bar, 28px, full width)       │
 * ├────────────┬─────────────────────────────────────────┤
 * │            │                                         │
 * │  Sidebar   │  [Page content]                         │
 * │  192px     │  flex-1, overflow-y-auto inside pages   │
 * │            │                                         │
 * └────────────┴─────────────────────────────────────────┘
 *
 * Two-layer auth model:
 *   Layer 1 — middleware.ts: redirects unauthenticated/unapproved requests
 *             before the page is rendered (early redirect, low cost)
 *   Layer 2 — this layout: server-side re-check before rendering any content.
 *             Catches edge cases where middleware was bypassed or the approval
 *             status changed between the middleware check and the render.
 *
 * This layout is a Server Component so it can call getApprovedSessionUser()
 * directly. No client-side useEffect needed.
 */
export default async function TerminalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Server-side auth guard — second layer of protection
  const user = await getApprovedSessionUser();
  if (!user) {
    redirect("/login");
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-zinc-950">
      {/* Global top status bar */}
      <StatusBar />

      {/* Sidebar + page content side-by-side */}
      <div className="flex min-h-0 flex-1">
        <Sidebar />

        {/* Main region — pages own their internal scroll */}
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  );
}
