import type { MetadataRoute } from "next";

/**
 * SEO0 — robots.txt route
 *
 * Allow: current public marketing/legal routes + future public entity route families
 *        locked by M0 (/perfumes/, /brands/, /notes/, /accords/)
 * Disallow: all authenticated terminal surfaces, admin, API, auth callbacks
 *
 * /login is allowed so crawlers can understand the auth boundary, but it is
 * intentionally omitted from sitemap.xml (functional page, not content).
 *
 * Canonical host: fragranceindex.ai
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: [
          "/",
          "/glossary",
          "/privacy",
          "/terms",
          "/data-sources",
          "/cookies",
          "/copyright",
          "/data-deletion",
          "/login",
          // M0 public entity route families — pages don't exist yet (PUB1)
          // but pre-authorising them here avoids a robots update in PUB1.
          "/perfumes/",
          "/brands/",
          "/notes/",
          "/accords/",
        ],
        disallow: [
          "/dashboard",
          "/screener",
          "/entities/",
          "/creators",
          "/creator/",
          "/watchlists",
          "/alerts",
          "/account",
          "/admin/",
          "/auth/",
          "/submit-source",
          "/api/",
        ],
      },
    ],
    sitemap: "https://fragranceindex.ai/sitemap.xml",
  };
}
