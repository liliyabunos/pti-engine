import { redirect } from "next/navigation";
import { Sidebar } from "@/components/shell/Sidebar";
import { StatusBar } from "@/components/shell/StatusBar";
import { createClient } from "@/lib/auth/server";

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
 * Auth: session check only (soft launch).
 * No approval gate — access gating via payment layer later.
 */
export default async function TerminalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
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
