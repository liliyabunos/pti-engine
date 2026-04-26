"use client";

/**
 * Plain Supabase client for magic-link / OTP dispatch ONLY.
 *
 * @supabase/ssr hardcodes flowType:"pkce" in createBrowserClient after
 * spreading user options — it cannot be overridden via options.
 * This client uses @supabase/supabase-js directly so that flowType:"implicit"
 * is respected, causing Supabase to send #access_token= links instead of
 * pkce_-prefixed tokens.
 *
 * Session management (cookie storage, middleware) still uses the @supabase/ssr
 * client. When the implicit-flow link is clicked, the callback page's
 * @supabase/ssr browser client reads the hash via detectSessionInUrl:true
 * and stores the session in cookies — exactly as before.
 *
 * Both supabaseUrl and anonKey are passed as explicit params from the Server
 * Component (LoginPage) — the client never reads process.env in the browser.
 *
 * Use ONLY for signInWithOtp. Do not use for getSession / signOut / user checks.
 */

import { createClient } from "@supabase/supabase-js";

export function createOtpClient(supabaseUrl: string, anonKey: string) {
  return createClient(supabaseUrl, anonKey, {
    auth: {
      flowType: "implicit",
      persistSession: false, // OTP client has no session to persist
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  });
}
