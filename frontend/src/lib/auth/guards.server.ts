/**
 * Server-only auth guard — never import this from client components or pages
 * that share the client bundle (e.g. login, public routes).
 *
 * This file uses next/headers (via ./server) and must remain in the
 * Server Component build graph only.
 */

import { createClient } from "./server";
import { getAppUser, type AppUser } from "./guards";

/**
 * Returns true if the given email/userId is an admin.
 * Source of truth: ADMIN_EMAILS and ADMIN_USER_IDS Railway env vars.
 * Used by admin page guards AND the Sidebar to conditionally show admin nav.
 */
export function isAdminUser(email: string | undefined, userId: string): boolean {
  const adminEmails = (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  const adminUserIds = (process.env.ADMIN_USER_IDS ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const normalizedEmail = email?.toLowerCase() ?? "";
  return (
    (normalizedEmail !== "" && adminEmails.includes(normalizedEmail)) ||
    adminUserIds.includes(userId)
  );
}

/**
 * Get the current Supabase session's email and verify approval.
 * Use in Server Components and Route Handlers only.
 *
 * Returns null if:
 *   - no active session
 *   - env vars missing
 *   - email not found in app_users
 *   - access_status !== 'approved'
 *   - API unreachable or timed out
 */
export async function getApprovedSessionUser(): Promise<AppUser | null> {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user?.email) return null;

  const appUser = await getAppUser(user.email);
  return appUser?.access_status === "approved" ? appUser : null;
}
