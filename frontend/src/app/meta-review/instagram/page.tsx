/**
 * IG1-R — Meta App Review public demo page.
 *
 * Accessible without authentication. Intended for Meta App Review reviewers
 * to verify Instagram Public Content Access usage without a FragranceIndex account.
 *
 * Uses the same MetaReviewConsole component as the admin route, but routes
 * API calls through /api/review/instagram-review (no Supabase auth required).
 *
 * No sidebar. No admin navigation. No terminal shell.
 * Reviewer sees only the Instagram Public Content demo UI.
 */

import type { Metadata } from "next";
import { MetaReviewConsole } from "@/app/(terminal)/admin/meta-review/instagram/MetaReviewConsole";

export const metadata: Metadata = {
  title: "Instagram Public Content Demo — FragranceIndex.ai App Review",
  robots: { index: false, follow: false },
};

export default function MetaReviewInstagramPage() {
  return (
    <MetaReviewConsole apiBase="/api/review/instagram-review" />
  );
}
