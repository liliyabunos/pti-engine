import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Supabase server client — use in Server Components, Route Handlers,
 * and middleware (via a separate cookies adapter — see middleware.ts).
 *
 * This variant reads/writes cookies via the Next.js `cookies()` API,
 * which requires a request context (Server Components and Route Handlers).
 * Do NOT call this in Client Components.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => {
              cookieStore.set(name, value, options);
            });
          } catch {
            // setAll can throw in Server Components (read-only context).
            // Safe to ignore — the session will be set by the Route Handler
            // that processes the Supabase callback.
          }
        },
      },
    }
  );
}
