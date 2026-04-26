import { Suspense } from "react";
import LoginForm from "./LoginForm";

export default function LoginPage() {
  // Why two different env var names:
  //
  // NEXT_PUBLIC_* variables are statically inlined at BUILD TIME by Next.js, even
  // in Server Components. Railway's Nixpacks build does not expose service variables
  // to the `next build` step, so process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY evaluates
  // to undefined at build time → gets baked in as undefined → LoginForm receives "".
  //
  // SUPABASE_ANON_KEY (no NEXT_PUBLIC_ prefix) is NOT processed by Next.js static
  // analysis. It is read from Node.js process.env at request time — always runtime,
  // always the real Railway value.
  //
  // NEXT_PUBLIC_SUPABASE_URL works because next.config.ts gives it a hardcoded fallback.

  const supabaseUrl =
    process.env.NEXT_PUBLIC_SUPABASE_URL ??
    "https://ewdwufoovhzbhaeiqjmw.supabase.co";

  // Read from server-side-only var (runtime). Falls back to NEXT_PUBLIC_ in case
  // both are set (e.g. local dev with .env file). Never reads empty string as a key.
  const supabaseAnonKey =
    process.env.SUPABASE_ANON_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  console.log("[PTI LOGIN PAGE] env diagnostics", {
    hasSupabaseUrl: !!supabaseUrl,
    supabaseUrlLength: supabaseUrl?.length ?? 0,
    hasAnonKey: !!supabaseAnonKey,
    anonKeyLength: supabaseAnonKey?.length ?? 0,
    startsWithEyJ: supabaseAnonKey?.startsWith("eyJ") ?? false,
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
