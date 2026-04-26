import { Suspense } from "react";
import LoginForm from "./LoginForm";

export default function LoginPage() {
  // Read server-side: Railway runtime env always has this var even when the
  // Nixpacks build can't inline it into the client bundle at build time.
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
  return (
    <Suspense>
      <LoginForm supabaseAnonKey={supabaseAnonKey} />
    </Suspense>
  );
}
