import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_API_BASE_URL:
      process.env.NEXT_PUBLIC_API_BASE_URL ??
      "https://generous-prosperity-production-25cc.up.railway.app",
    // Supabase public vars — embedded at build time.
    // URL has a hardcoded fallback (non-secret, project ref).
    // Anon key is injected by Railway at build time (set in service env vars).
    // Without these in the env block, NEXT_PUBLIC_ vars missing from Railway
    // at build time will be undefined client-side → createBrowserClient crashes.
    NEXT_PUBLIC_SUPABASE_URL:
      process.env.NEXT_PUBLIC_SUPABASE_URL ??
      "https://ewdwufoovhzbhaeiqjmw.supabase.co",
    NEXT_PUBLIC_SUPABASE_ANON_KEY:
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    NEXT_PUBLIC_SITE_URL:
      process.env.NEXT_PUBLIC_SITE_URL ??
      "https://pti-frontend-production.up.railway.app",
  },
};

export default nextConfig;
