/**
 * SOURCE-INTAKE-V1A — Admin Source Intake Batch List.
 *
 * Server Component: reads Supabase session server-side.
 * - Unauthenticated → redirect to /login
 * - Authenticated non-admin → 403 page
 * - Admin → renders <SourceIntakeConsole />
 */

import { redirect } from "next/navigation";
import { createClient } from "@/lib/auth/server";
import { isAdminUser } from "@/lib/auth/guards.server";
import { SourceIntakeConsole } from "./SourceIntakeConsole";

export default async function AdminSourceIntakePage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/admin/source-intake");
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

  return <SourceIntakeConsole adminEmail={user.email ?? user.id} />;
}
