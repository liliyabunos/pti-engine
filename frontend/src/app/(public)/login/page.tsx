import { Suspense } from "react";
import LoginForm from "./LoginForm";

export default function LoginPage() {
  // Both vars are read server-side at Railway runtime — NOT from the Next.js env block.
  // NEXT_PUBLIC_SUPABASE_ANON_KEY is deliberately excluded from next.config.ts env block
  // to prevent build-time baking of undefined. Server Components always get the real
  // Railway runtime value when the var is NOT in the env block.
  const supabaseUrl =
    process.env.NEXT_PUBLIC_SUPABASE_URL ??
    "https://ewdwufoovhzbhaeiqjmw.supabase.co";
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Safe diagnostic — booleans only, no secrets logged
  console.log("[PTI LOGIN PAGE] env diagnostics", {
    hasSupabaseUrl: !!supabaseUrl,
    hasAnonKey: !!supabaseAnonKey,
    anonKeyLength: supabaseAnonKey?.length ?? 0,
  });

  return (
    <Suspense>
      <LoginForm
        supabaseUrl={supabaseUrl}
        supabaseAnonKey={supabaseAnonKey ?? ""}
      />
    </Suspense>
  );
}
