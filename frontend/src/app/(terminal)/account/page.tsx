/**
 * C2.2 — User Account & My Claims page (server component).
 *
 * Auth: protected by (terminal) layout + middleware.
 * Unauthenticated users are redirected to /login?next=/account.
 *
 * Reads Supabase session server-side to get the user email.
 * Renders <AccountConsole /> (client component) which fetches claims
 * from the existing /api/creator-claims Next.js server route.
 *
 * No backend changes. No migration. No OAuth. No platform API.
 * verification_code_hash is never returned by /api/creator-claims.
 */

import { redirect } from "next/navigation";
import { createClient } from "@/lib/auth/server";
import { AccountConsole } from "./AccountConsole";

export default async function AccountPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/account");
  }

  return <AccountConsole userEmail={user.email ?? user.id} />;
}
