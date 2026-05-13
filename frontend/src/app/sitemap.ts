import type { MetadataRoute } from "next";

/**
 * PUB1 — sitemap including public entity pages.
 *
 * Revalidates every hour (same cadence as public entity pages).
 * Entity slugs are fetched from the backend sitemap endpoints, which apply
 * the anti-thin-content filter (only entities with mention_count > 0).
 *
 * Future scaling (PUB2, when entity count exceeds ~50k):
 *   Convert to generateSitemaps() pattern to split into partitioned sub-sitemaps:
 *     /sitemap/static, /sitemap/perfumes-0, /sitemap/perfumes-1, /sitemap/brands, ...
 *   See docs/architecture/SEO_ARCHITECTURE.md §4 for the full architecture.
 */

export const revalidate = 3600;

const BASE_URL = "https://fragranceindex.ai";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface SitemapPerfumeEntry {
  slug: string;
  canonical_name: string;
}

interface SitemapBrandEntry {
  slug: string;
  canonical_name: string;
}

async function fetchEntitySlugs<T>(path: string): Promise<T[]> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

const STATIC_PAGES: MetadataRoute.Sitemap = [
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

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Fetch entity slugs from backend — silently returns [] if backend unreachable
  const [perfumes, brands] = await Promise.all([
    fetchEntitySlugs<SitemapPerfumeEntry>("/api/v1/public/sitemap/perfumes"),
    fetchEntitySlugs<SitemapBrandEntry>("/api/v1/public/sitemap/brands"),
  ]);

  const perfumeUrls: MetadataRoute.Sitemap = perfumes.map((p) => ({
    url: `${BASE_URL}/perfumes/${p.slug}`,
    lastModified: new Date(),
    changeFrequency: "daily",
    priority: 0.8,
  }));

  const brandUrls: MetadataRoute.Sitemap = brands.map((b) => ({
    url: `${BASE_URL}/brands/${b.slug}`,
    lastModified: new Date(),
    changeFrequency: "daily",
    priority: 0.7,
  }));

  return [...STATIC_PAGES, ...perfumeUrls, ...brandUrls];
}
