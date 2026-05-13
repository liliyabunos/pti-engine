import type { MetadataRoute } from "next";

/**
 * SEO0 — static sitemap for currently public pages.
 *
 * PUB1 expansion strategy (do not implement here):
 *   When public entity pages (/perfumes/[slug], /brands/[slug], etc.) are live,
 *   convert this file to a sitemap index by using generateSitemaps() and splitting
 *   into sub-sitemaps per entity type:
 *
 *     /sitemap/0  — static pages (this file's content)
 *     /sitemap/1  — perfumes batch 1 (≤50k URLs per sitemap per spec)
 *     /sitemap/2  — brands
 *     /sitemap/3  — notes
 *     /sitemap/4  — accords
 *
 *   Priority ordering: tracked active perfumes first, full catalog second,
 *   brands, then notes/accords. Do not emit slugs for entities with no public
 *   page yet — dead URLs harm crawl budget.
 *
 * Intentionally excluded from this sitemap:
 *   /login        — functional auth page, not content
 *   /perfumes/*   — not yet live (PUB1)
 *   /brands/*     — not yet live (PUB1)
 *   /notes/*      — not yet live (PUB2)
 *   /accords/*    — not yet live (PUB2)
 */

const BASE_URL = "https://fragranceindex.ai";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: BASE_URL,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1.0,
    },
    {
      url: `${BASE_URL}/glossary`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${BASE_URL}/data-sources`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.4,
    },
    {
      url: `${BASE_URL}/privacy`,
      lastModified: new Date(),
      changeFrequency: "yearly",
      priority: 0.3,
    },
    {
      url: `${BASE_URL}/terms`,
      lastModified: new Date(),
      changeFrequency: "yearly",
      priority: 0.3,
    },
    {
      url: `${BASE_URL}/cookies`,
      lastModified: new Date(),
      changeFrequency: "yearly",
      priority: 0.2,
    },
    {
      url: `${BASE_URL}/copyright`,
      lastModified: new Date(),
      changeFrequency: "yearly",
      priority: 0.2,
    },
    {
      url: `${BASE_URL}/data-deletion`,
      lastModified: new Date(),
      changeFrequency: "yearly",
      priority: 0.2,
    },
  ];
}
