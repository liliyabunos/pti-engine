import { Suspense } from "react";
import CallbackClient from "./CallbackClient";

// Must be dynamic — reads runtime env vars that are not available at Nixpacks build time.
// Same pattern as /login/page.tsx.
export const dynamic = "force-dynamic";

export default function AuthCallbackPage() {
  const supabaseUrl =
    process.env.NEXT_PUBLIC_SUPABASE_URL ??
    "https://ewdwufoovhzbhaeiqjmw.supabase.co";

  const supabaseAnonKey =
    process.env.SUPABASE_ANON_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  console.log("[PTI CALLBACK PAGE] env diagnostics", {
    hasSupabaseUrl: !!supabaseUrl,
    hasAnonKey: !!supabaseAnonKey,
    anonKeyLength: supabaseAnonKey?.length ?? 0,
  });

  return (
    <Suspense>
      <CallbackClient
        supabaseUrl={supabaseUrl}
        supabaseAnonKey={supabaseAnonKey ?? ""}
      />
    </Suspense>
  );
}
