import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_API_BASE_URL:
      process.env.NEXT_PUBLIC_API_BASE_URL ??
      "https://generous-prosperity-production-25cc.up.railway.app",
  },
};

export default nextConfig;
