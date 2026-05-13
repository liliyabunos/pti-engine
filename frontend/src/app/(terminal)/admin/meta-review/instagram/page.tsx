/**
 * IG1-R — Admin Meta App Review Demo Page.
 *
 * Server Component: reads Supabase session server-side.
 * - Unauthenticated → redirect to /login
 * - Authenticated non-admin → 403 page
 * - Admin → renders <MetaReviewConsole />
 *
 * Route: /admin/meta-review/instagram
 * Access: admin-only (ADMIN_EMAILS / ADMIN_USER_IDS env vars)
 * Purpose: Meta App Review screencast demo for Instagram Public Content Access
 */

import { redirect } from "next/navigation";
import { createClient } from "@/lib/auth/server";
import { isAdminUser } from "@/lib/auth/guards.server";
import { MetaReviewConsole } from "./MetaReviewConsole";

export const metadata = {
  title: "Instagram App Review Demo — Admin · FragranceIndex.ai",
  robots: { index: false, follow: false },
};

export default async function AdminMetaReviewInstagramPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/admin/meta-review/instagram");
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

  return <MetaReviewConsole />;
}
