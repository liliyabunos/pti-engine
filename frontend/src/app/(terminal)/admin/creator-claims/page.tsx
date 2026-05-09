/**
 * C2.1 — Admin Creator Claims Console.
 *
 * Server Component: reads Supabase session server-side.
 * - Unauthenticated → redirect to /login
 * - Authenticated non-admin → 403 page
 * - Admin → renders <ClaimsConsole /> (client component)
 *
 * Admin check: user email vs ADMIN_EMAILS env var,
 *              user ID vs ADMIN_USER_IDS env var.
 * Both are comma-separated. This is a temporary C2.1 allowlist gate.
 * Future hardening option: app_admins table or Supabase custom claims.
 *
 * No OAuth. No pipeline changes. No private data.
 */

import { redirect } from "next/navigation";
import { createClient } from "@/lib/auth/server";
import { ClaimsConsole } from "./ClaimsConsole";

function isAdminUser(email: string | undefined, userId: string): boolean {
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

export default async function AdminCreatorClaimsPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/admin/creator-claims");
  }

  if (!isAdminUser(user.email, user.id)) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm font-semibold text-red-400">403 — Access Denied</p>
        <p className="text-[12px] text-zinc-500">
          You do not have permission to access the operator console.
        </p>
      </div>
    );
  }

  return <ClaimsConsole adminEmail={user.email ?? user.id} />;
}
