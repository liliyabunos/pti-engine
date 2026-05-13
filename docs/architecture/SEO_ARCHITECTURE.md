# SEO Architecture — FragranceIndex.ai

**Version:** 1.0 — SEO0 Foundation
**Date:** 2026-05-13
**Phase:** SEO0 — SEO Infrastructure Foundation

---

## 1. Purpose

SEO is product and acquisition architecture, not later marketing polish.

FragranceIndex.ai currently has zero public acquisition surface: all entity pages are behind authentication, no sitemap existed, no robots policy existed, no dynamic metadata existed, and no public entity URLs were indexed. Every month without a public layer is compounding opportunity cost on SEO and organic acquisition.

SEO0 establishes the technical crawl and sitemap foundation so that PUB1 can implement public entity pages into a ready infrastructure — not require a simultaneous infrastructure rebuild.

The strategic principle from the approved roadmap: **public SEO pages are core product, not "marketing later."**

---

## 2. SEO0 Decisions Implemented

### 2.1 robots.ts

**File:** `frontend/src/app/robots.ts`

**Policy:**

| Route family | Directive | Reason |
|---|---|---|
| `/` | Allow | Public landing page — primary acquisition surface |
| `/glossary` | Allow | Public content page |
| `/privacy`, `/terms`, `/data-sources`, `/cookies`, `/copyright`, `/data-deletion` | Allow | Legal pages — trust signals for crawlers |
| `/login` | Allow | Auth gateway — allows crawlers to understand auth boundary; not submitted in sitemap |
| `/perfumes/`, `/brands/`, `/notes/`, `/accords/` | Allow | M0-locked public entity route families — pre-authorised for PUB1 even though pages are not yet live |
| `/dashboard`, `/screener`, `/entities/` | Disallow | Authenticated terminal surfaces |
| `/creators`, `/creator/` | Disallow | Authenticated terminal surfaces |
| `/watchlists`, `/alerts`, `/account` | Disallow | Authenticated user surfaces |
| `/admin/` | Disallow | Operator admin area |
| `/auth/` | Disallow | OAuth callback — no content |
| `/submit-source` | Disallow | Terminal auth-required form |
| `/api/` | Disallow | API routes — not content |

**Sitemap declared at:** `https://fragranceindex.ai/sitemap.xml`

### 2.2 sitemap.ts

**File:** `frontend/src/app/sitemap.ts`

**Current content:** static public pages only.

| URL | Priority | changeFrequency |
|---|---|---|
| `https://fragranceindex.ai` | 1.0 | daily |
| `/glossary` | 0.6 | monthly |
| `/data-sources` | 0.4 | monthly |
| `/privacy` | 0.3 | yearly |
| `/terms` | 0.3 | yearly |
| `/cookies` | 0.2 | yearly |
| `/copyright` | 0.2 | yearly |
| `/data-deletion` | 0.2 | yearly |

**Intentionally excluded:** `/login` (functional auth page, not content), all `/perfumes/*`, `/brands/*`, `/notes/*`, `/accords/*` (not yet live — dead URLs harm crawl budget).

### 2.3 Noindex for Private/Terminal Routes

**Approach:** metadata export in the `(terminal)` group layout — cascades to all pages in the group without per-page work.

**File modified:** `frontend/src/app/(terminal)/layout.tsx`

```typescript
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};
```

**Coverage:** all routes under `(terminal)/`:
- `/dashboard`
- `/screener`
- `/entities/*` (perfume/[id], brand/[id], note/[name], accord/[name])
- `/creators`, `/creator/*`
- `/watchlists`, `/alerts`
- `/account`
- `/admin/*`
- `/submit-source`

**Auth callback:** `frontend/src/app/auth/callback/page.tsx` also receives explicit noindex (lives outside the terminal group).

### 2.4 metadataBase / Domain

**Root layout:** `frontend/src/app/layout.tsx`

`metadataBase: new URL("https://fragranceindex.ai")` — confirmed correct. No stale Railway or pti-frontend domain references in public-facing metadata.

OpenGraph and Twitter card site-level defaults added in SEO0:

```typescript
openGraph: {
  type: "website",
  siteName: "FragranceIndex.ai",
  title: "FTI Market Terminal",
  description: "...",
},
twitter: {
  card: "summary",
  title: "FTI Market Terminal",
  description: "...",
},
```

Homepage (`frontend/src/app/page.tsx`) now has specific metadata overriding these defaults with a more descriptive acquisition-oriented title and description.

### 2.5 OG Image / Social Preview

**Current state:** No branded image assets exist in `frontend/public/`. The OG image field is intentionally absent from SEO0 metadata.

**Follow-up (PUB1):** Create a branded `og-image.png` (1200×630px) and place in `frontend/public/`. Reference via:

```typescript
openGraph: {
  images: [{ url: "/og-image.png", width: 1200, height: 630 }],
}
```

Per-entity OG images for PUB1 public pages can be implemented later via Next.js `opengraph-image.tsx` route convention.

---

## 3. Public Canonical URL Strategy

M0 locked the public canonical route families:

| Entity type | Public canonical route |
|---|---|
| Perfume | `/perfumes/[slug]` |
| Brand | `/brands/[slug]` |
| Note | `/notes/[slug]` |
| Accord | `/accords/[slug]` |

**Terminal entity routes are NOT canonical public SEO routes:**

- `/entities/perfume/[id]` — authenticated terminal; noindex; will receive `rel=canonical` pointing to `/perfumes/[slug]` in PUB1
- `/entities/brand/[id]` — same
- `/entities/note/[name]` — same
- `/entities/accord/[name]` — same

**Why terminal routes are not canonical:** they are behind authentication, use internal UUIDs (not human-readable slugs), and are not intended as the public acquisition surface. Canonicalising them now to non-existent public slugs would create broken canonical chains.

**SEO0 action:** noindex terminal entity routes now. Canonical links added in PUB1 once public target routes exist and are verified live.

**Slug generation rule (PUB1 task):** Slugs must be derived from `entity_market.canonical_name` — URL-safe, lowercased, hyphenated. Slug → entity_id mapping must be stable (no slug changes after initial assignment without proper redirects). The resolver alias seed already provides the canonical name source of truth.

---

## 4. Future Entity Sitemap Strategy

When PUB1 public entity pages are live, the sitemap must scale to cover ~55,000+ perfume pages, brands, notes, and accords. A single sitemap.ts returning all URLs will exceed the 50,000 URL limit per sitemap file (per sitemaps.org spec and Google recommendation).

### 4.1 Architecture: Sitemap Index via generateSitemaps

Use Next.js `generateSitemaps()` to emit a sitemap index at `/sitemap.xml` with child sitemaps at `/sitemap/[id].xml`:

```typescript
// app/sitemap.ts — converted to dynamic index

export async function generateSitemaps() {
  return [
    { id: "static" },
    { id: "perfumes-0" },  // up to 50k perfumes per shard
    { id: "perfumes-1" },
    { id: "brands" },
    { id: "notes" },
    { id: "accords" },
  ];
}

export default async function sitemap({ id }: { id: string }): Promise<MetadataRoute.Sitemap> {
  if (id === "static") return staticPages;
  if (id.startsWith("perfumes")) return perfumePagesBatch(id);
  // etc.
}
```

### 4.2 Priority Ordering

1. **Active tracked perfumes** (entity_market entities with timeseries data) — highest priority, daily change frequency
2. **Full catalog perfumes** (resolver catalog entries with entity pages) — medium priority, weekly
3. **Active tracked brands** — medium priority, daily
4. **Notes** — low priority, monthly (PUB2)
5. **Accords** — low priority, monthly (PUB2)

### 4.3 Dead URL Prevention

- Only emit URLs for entities where the public page route exists AND the entity is in `entity_market` (has data)
- Do NOT emit slugs for entities with no `entity_timeseries_daily` history if page would be content-thin
- Anti-thin-content rule: each public entity page must have at least one data-driven signal before being indexed (score, direction, at least one mention) — see section 6

### 4.4 Slug Stability

Once a slug is emitted in the sitemap, it must remain stable. Slug changes require:
1. A 301 redirect from the old slug to the new slug
2. Sitemap updated to emit new slug only
3. Old slug disallowed in robots after redirect is in place (or left as redirect target)

---

## 5. Metadata Requirements for PUB1/PUB2

### 5.1 Perfume Pages (`/perfumes/[slug]`)

```typescript
export async function generateMetadata({ params }): Promise<Metadata> {
  const perfume = await getPerfumeBySlug(params.slug);
  return {
    title: `${perfume.canonical_name} by ${perfume.brand} — Market Intelligence · FragranceIndex.ai`,
    description: `Track ${perfume.canonical_name} fragrance trends. Market score, momentum, and signal data from YouTube and Reddit. Updated daily.`,
    openGraph: {
      title: `${perfume.canonical_name} — Fragrance Trend Data`,
      description: `...(same as above or shorter)...`,
      url: `https://fragranceindex.ai/perfumes/${params.slug}`,
      type: "article",
    },
    alternates: {
      canonical: `https://fragranceindex.ai/perfumes/${params.slug}`,
    },
  };
}
```

**Canonical:** `/perfumes/[slug]` — always self-referential canonical on the public page.

### 5.2 Brand Pages (`/brands/[slug]`)

Similar pattern. Title: `[Brand Name] Perfume Brand — Market Intelligence · FragranceIndex.ai`.

### 5.3 Note/Accord Pages (`/notes/[slug]`, `/accords/[slug]`)

PUB2 scope. Title: `[Note Name] Note — Trending Fragrances · FragranceIndex.ai`.

### 5.4 JSON-LD Recommendations

Evaluate in PUB1 implementation:

| Page type | Recommended JSON-LD type |
|---|---|
| Perfume entity page | `ItemPage` or `Product` |
| Brand page | `Organization` or `Brand` |
| Note/accord page | `DefinedTerm` |
| Homepage | `WebSite` with `SearchAction` (future) |

JSON-LD implementation is not required in SEO0 — evaluate concrete schema markup in PUB1.

---

## 6. Anti-Thin / Anti-Duplicate Guidance

### 6.1 Anti-Thin Content Rule

Do not index a public entity page if the page has only:
- Entity name + brand name
- No market score history (entity never appeared in `entity_timeseries_daily`)
- No mentions, no signals

Gate sitemap inclusion on: `total_mentions > 0 AND has_timeseries_data = true`. Pages below this threshold should be `noindex` via `generateMetadata` returning `robots: { index: false }` until data accumulates.

### 6.2 Anti-Duplicate Content for Flankers/Variants

Concentration variants (`Dior Sauvage EDP`, `Dior Sauvage EDT`) are collapsed to the same market entity by the resolver. Public entity pages must not create separate indexable pages for variants resolved to the same entity. One canonical URL per `entity_market.id`.

### 6.3 Title Uniqueness

Every public entity page must have a unique title tag. Use the combination of `canonical_name + brand` — this is unique within entity_market by design.

Do not create titles like "Perfume Market Score" on every page without differentiating entity data. Google will treat these as near-duplicates and devalue the entire set.

---

## 7. Change Log

| Date | Version | Change |
|---|---|---|
| 2026-05-13 | 1.0 | Initial SEO0 foundation — robots, sitemap, noindex policy, OG defaults, canonical URL strategy |

---

*End of SEO_ARCHITECTURE.md*
*Phase: SEO0 — SEO Infrastructure Foundation*
*Next phase: PUB1 — Public Perfume & Brand Pages*
