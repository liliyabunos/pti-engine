# Monetization Architecture — FragranceIndex.ai / FTI Market Terminal

**Version:** 1.0 — M0 Foundation
**Date:** 2026-05-12
**Phase:** M0 — Monetization Architecture Foundation
**Status:** ARCHITECTURE DEFINED — awaiting downstream implementation phases

---

## 1. Executive Purpose

FragranceIndex.ai is **not launching monetization now.**

This document defines the commercial and product architecture so that future monetization — public SEO pages, Pro access, premium reports, Enterprise data access — can be implemented without rearchitecting data models, API contracts, or routing conventions.

M0 is a documentation phase. Its job is to make four downstream decisions now that are painful to change later:

1. **What is public vs gated** — the field-level tier access matrix
2. **What the future commercial layers are** — the four-layer model
3. **What the Opportunity Object is** — the data contract IL1 will implement
4. **What the public URL/routing convention is** — what SEO0 and PUB1 will build

M0 has no code output. It unlocks:

| Phase | M0 Output Consumed |
|-------|-------------------|
| DATA0 | Methodology versioning decisions (section 10) |
| SEO0 | Public routing and metadata policy (sections 6, 11) |
| PUB1 | Public field exposure policy (section 5, 6.1–6.2) |
| PUB2 | Content/linking strategy (section 6.3) |
| IG1 | Public boundary rules for new data source (sections 5, 6) |
| IL1 | Opportunity Object schema (section 9) |
| REPORT1 | Report section/data requirements (section 8) |
| PRO1 | Gating/tier assumptions (sections 5, 7, 10) |

---

## 2. Commercial Layer Model

### 2.1 Public / SEO Layer

**Purpose:** Organic acquisition. Indexable intelligence pages that attract brands, marketers, agencies, fragrance sellers, journalists, and creators through organic search — before they have accounts. Public pages are the only acquisition funnel; without them the platform is invisible to search.

**Principle:** Public exposure provokes curiosity. It must offer enough intelligence to be valuable to a casual visitor, while clearly leaving the most actionable depth gated behind sign-up.

**Target queries this layer should rank for:**
- Perfume-specific: "[perfume name] trending", "[perfume name] popular", "[perfume name] reviews"
- Brand: "[brand name] popular fragrances", "[brand] fragrance market"
- Category/ingredient: "vanilla fragrances trending", "oud trending perfumes"

### 2.2 Pro Layer

**Purpose:** Paid intelligence workspace for serious fragrance buyers, sellers, advisors, and consultants. Deeper history, richer attribution, cross-entity comparison, watchlist management, alerts, and CSV exports.

**Target user:** Fragrance retailer buyer, brand marketing manager, niche perfume advisor, collector/enthusiast at research depth.

**Price point:** Not defined in M0 — deferred to PRO1. Expected monthly subscription.

### 2.3 Premium Report Layer

**Purpose:** High-margin research artifacts for brands, investors, agencies, and M&A teams. Perfume Deep Dive is the first product. Later: Competitor Map, Brand Health Report, Competitive Landscape, M&A Due Diligence Pack. Reports are data-backed, methodology-annotated documents, not live dashboards.

**Target user:** Brand strategy team, private equity fragrance deal team, fragrance house R&D, specialty retailer category manager.

**Price point:** Per-report or annual subscription. Expected significantly higher than Pro.

### 2.4 Enterprise / Data Access Layer

**Purpose:** API access, BI integration, custom dashboards, portfolio-level alerts, and custom entity definitions for large fragrance houses, distributors, and research firms. SLA-backed.

**Target user:** Large fragrance house (Givaudan, Firmenich, L'Oréal, IFF), distributor, retail chain, luxury group.

**Price point:** Annual contract. Custom pricing.

---

## 3. Entity Monetization Role Map

| Entity Type | Public Layer Role | Pro Layer Role | Report Role | Enterprise Role | Notes |
|-------------|------------------|----------------|-------------|-----------------|-------|
| **Perfume** | Primary SEO object. Name, brand, score, trend direction, top note/accord identity, limited creator names, 1 opportunity tag. Internal links to brand/notes/accords. CTA to terminal. | Full chart, all drivers, all creators, full signal timeline, all opportunity evidence, watchlists, alerts, comparison, CSV. | Core report subject. All sections of Deep Dive. Historical methodology-annotated data. | API + custom entity pools + portfolio tracking + custom score formula options. | Primary monetizable entity. Highest search intent. |
| **Brand** | SEO acquisition. Brand name, aggregate score, top 5 perfumes, momentum status, top notes/accords. CTA to terminal. | Full portfolio performance, brand chart history, competitor brand comparison, portfolio alerts, export. | Brand Health Report subject. Portfolio trend analysis, creator concentration, market positioning. | Brand-level API endpoints, custom competitor sets, portfolio-wide alerts and exports. | Secondary monetizable object. Powers brand intelligence track. |
| **Creator** | NOT a primary public object in current model. Creator names may appear on perfume pages (top 3) as attribution context only — without deep attribution data. Creator verification badge may be publicly visible. | Full creator attribution, creator influence scores, full portfolio association, full mention timeline. Leaderboard access. | Section 4 (Driver Attribution) and Section 5 (Creator Concentration) in Deep Dive. | Creator API access, custom creator pools, verified creator analytics. | Creator is attribution/provenance, not a primary paid product. May become primary object in future C3 Multi-Platform Creator Intelligence track. |
| **Note** | SEO acquisition object (PUB2). Note identity page with linked perfumes by note. Trending context if available. Internal linking. | Full note-level analytics: trend over time, top perfumes by note, intent distribution by note. | Notes & Accords Context section in Deep Dive. Note/accord momentum analysis in Competitive Landscape. | Note-level API for formulation teams and ingredient-focused queries. | Key SEO long-tail surface. Each note page can rank for "[note] fragrances", "[note] trending". |
| **Accord** | SEO acquisition object (PUB2). Accord identity with linked perfumes. | Full accord analytics, historical trend. | Same as Notes in reports. | Same as Notes in enterprise. | Similar role to Notes in public/SEO layer. |
| **Opportunity Object** | NOT public directly. Only the opportunity type label (e.g. "Gifting Demand") may appear on public perfume pages — no evidence, no confidence score, no evidence refs. | Confidence-scored opportunity objects with evidence refs, time windows, strength grades. Opportunity Feed. | Full Opportunity Analysis section in Deep Dive (section 8). Ranked by confidence × recency. | Opportunity Object API. Custom opportunity type filtering. Alert on new opportunities. | The most important future intelligence unit. Currently implemented as 11 string flags with no scoring. IL1 will formalize. |

---

## 4. Current Capability Audit by Surface

### 4.1 Perfume Entity

**Source:** `GET /api/v1/entities/perfume/{id}` → `PerfumeEntityDetail` schema in `routes/entities.py:466–517`

**Identity:** `canonical_name`, `brand_name`, `ticker`, `entity_id` (stable string slug), `resolver_id` (integer, Fragrantica resolver). Entity role: `entity_role` (designer_original, niche_original, dupe_alternative, designer_alternative, celebrity_alternative, unknown). Reference original and dupe family for Phase 5 dupe entities. **Status: COMPLETE.**

**Market score:** `latest_score` (composite_market_score from `entity_timeseries_daily`). **Status: COMPLETE.**

**Trend state:** `trend_state` (rising/stable/declining/accelerating, from Phase I3 detection). **Status: COMPLETE.**

**Timeseries:** `timeseries: List[SnapshotRow]` — daily rows. API defaults to 30 days (`history_days=30`) but accepts `?history_days=1..365`. No tier enforcement — all auth'd users get same depth. **Status: COMPLETE, but no tier depth enforcement yet.**

**Signals:** `recent_signals: List[SignalRow]` — breakout/acceleration/sustained events detected by `detect_breakout_signals.py`. Ordered by detected_at DESC. **Status: COMPLETE.**

**Drivers:** `top_drivers: List[DriverRow]` (Phase I4) — top content items by source_score × views, with source platform, URL, source name, engagement metrics, source_score, date. Deduped by source_url. **Status: COMPLETE.**

**Mentions:** `recent_mentions: List[RecentMentionRow]` — latest entity_mentions rows enriched with mention_sources engagement data. **Status: COMPLETE.**

**Creator attribution:** via `GET /api/v1/entities/perfume/{id}/creators` (separate endpoint, Phase C1). Returns top creators by influence with tier, portfolio data, first/last mention, early signal badge. **Status: COMPLETE.**

**Notes / Accords:** `notes_top`, `notes_middle`, `notes_base`, `accords`, `notes_source` — sourced from Fragrantica/Parfumo resolver data. `similar_perfumes` by shared notes. **Status: COMPLETE for entities in Fragrantica catalog. PARTIAL for entities that are tracked but not in Fragrantica catalog.**

**Topics / Intents:** `top_topics`, `top_queries`, `top_subreddits` (Phase I5); `differentiators`, `positioning`, `intents` (Phase I7 semantic classification). **Status: COMPLETE.**

**Opportunity flags:** `opportunities: List[str]` — 11 rule-based string flags (alternative_demand, clone_market, affordable_alt, high_intent, competitive_comparison, gifting, viral_momentum, launch_window, social_validation, performance_leader, alternative_search_interest). **Status: COMPLETE as string flags. MISSING: confidence scores, evidence refs, time windows, scoring — these are IL1 scope.**

**Narrative:** `narrative: Optional[str]` — template-based plain-language explanation. **Status: COMPLETE.**

**Compared-against / Competitors:** `competitors: List[str]` — entity-resolved competitor names from VS-pattern query analysis. Unresolved query phrases silently dropped. **Status: COMPLETE, limited by VS pattern coverage.**

**Semantic/Dupe layer:** `reference_original`, `dupe_family` for known dupe entities (Phase 5, curated `_DUPE_RAW` dict in `entity_role.py`). **Status: COMPLETE for seeded dupe map. PARTIAL: curated list, not computed.**

---

### 4.2 Brand Entity

**Source:** `GET /api/v1/entities/brand/{id}` → `BrandEntityDetail` schema in `routes/entities.py:519–558`

**Portfolio summary:** `perfume_count`, `active_perfume_count`, `catalog_perfumes` (up to 100 perfumes with score, mention_count, has_activity_today). **Status: COMPLETE.**

**Top perfumes:** `top_perfumes` (alias for `catalog_perfumes` — same list). **No server-side top-N by score sort explicitly enforced in brand page.** **Status: PARTIAL.**

**Market score / aggregate score:** `latest_score` — aggregated via daily metrics job from perfume entity signals under the brand. `trend_state`. **Status: COMPLETE.**

**Brand chart:** `timeseries: List[SnapshotRow]` — same history depth policy as perfume (default 30, up to 365). **Status: COMPLETE.**

**Brand-level intelligence:** `top_topics`, `top_queries`, `top_subreddits`, `differentiators`, `positioning`, `intents` — aggregated across all brand perfume entities via `_get_brand_topics()`. `narrative`, `opportunities`, `competitors`. **Status: COMPLETE.**

**Portfolio notes / accords:** `top_notes`, `top_accords` — aggregated across all brand perfumes. **Status: COMPLETE.**

**Brand competitor comparison:** Detected via VS-pattern queries same as perfume level. No explicit brand-vs-brand comparison chart. **Status: PARTIAL — detected from query patterns, no formal brand comparison tool.**

**Long history / brand historical analysis:** Same `history_days` parameter, no tier enforcement. **Status: PARTIAL — data exists, no tier enforcement.**

---

### 4.3 Creator Surface

**Leaderboard:** `GET /api/v1/creators` — 757 creators, paginated, filtered by quality_tier, category, sort by influence score / avg_views / mention_count. Platform-aware (YouTube only currently). Display name from `youtube_channels.title`. **Status: COMPLETE.**

**Creator portfolio:** `GET /api/v1/creators/{id}` — profile, entity portfolio, recent content. **Status: COMPLETE.**

**Tier / influence score:** v1 formula (6 components: reach, signal_quality, entity_breadth, volume, early_signal, engagement). Tier labels (tier_1 through tier_4). **Status: COMPLETE.**

**Claims workflow:** `creator_profile_claims` table — bio_code, screenshot, manual_review methods. Admin review console. `verified_status` returned on creator profile. **Status: COMPLETE (C2/C2.1).**

**Cross-platform attribution:** YouTube only. TikTok watchlist exists as `creator_platform_accounts` but no TikTok signals. No Instagram. **Status: PARTIAL — YouTube complete; cross-platform = future IG1/C3.**

**Creator Intelligence as monetizable product:** NOT currently a paid object. Leaderboard is in the authenticated terminal (all auth'd users see it equally). **Status: MISSING — no tier enforcement on creator data.**

---

### 4.4 Screener / Alerts / Watchlists

**Screener:** Full screener page at `/screener` — market mode (active entities, catalog_perfumes, catalog_brands), composition mode (notes, accords). Server-side filters: sort by score/growth/mentions, quality tier, trend state, entity type, text search, note/accord filter, range selector. **Status: COMPLETE. Currently terminal-only (auth required).**

**Watchlists:** Full CRUD API at `/api/v1/watchlists` — create, list, get detail (enriched market data per item), add/remove. Frontend at `/watchlists`. **Auth: DEV_OWNER_KEY placeholder — no real per-user auth.** **Status: PARTIAL — API complete, per-user auth missing.**

**Alerts:** Full CRUD API at `/api/v1/alerts` — create, list, patch (pause/resume/rename), history. `delivery_type` hardcoded to `"in_app"`. No email, no webhook, no actual delivery mechanism. Alert event logging exists via `AlertEvent` table. **Frontend at `/alerts`. Auth: DEV_OWNER_KEY placeholder.** **Status: PARTIAL — API/schema complete, real delivery missing, per-user auth missing.**

**Comparison chart:** NOT implemented. No multi-entity chart overlay. **Status: MISSING.**

**CSV export:** NOT implemented. **Status: MISSING.**

**History depth enforcement:** NOT implemented. All authenticated users can request up to 365 days via `?history_days=365`. **Status: MISSING — tier enforcement is PRO1 scope.**

---

## 5. Field-Level Tier Access Matrix

> Legend: ✅ = exists today | ⚠️ = exists but partial | ❌ = not yet implemented

### 5.1 Perfume Fields

| Field / Block | Exists Today? | Source | Public | Pro | Report | Enterprise | Rationale |
|---------------|---------------|--------|--------|-----|--------|------------|-----------|
| Canonical name | ✅ | `entity_market.canonical_name` | ✅ | ✅ | ✅ | ✅ | Core identity — always public |
| Brand name | ✅ | `entity_market.brand_name` | ✅ | ✅ | ✅ | ✅ | Core identity — always public |
| Entity role badge (niche/designer/dupe) | ✅ | `entity_role.py` | ✅ | ✅ | ✅ | ✅ | Product context — helps SEO and discoverability |
| Reference original (for dupe entities) | ✅ | `entity_role.py` `_DUPE_RAW` | ✅ | ✅ | ✅ | ✅ | Public context adds SEO value ("alternative to Creed Aventus") |
| Notes / accords | ✅ | Fragrantica resolver | ✅ | ✅ | ✅ | ✅ | Ingredient-level identity — core SEO content |
| Current market score (single number) | ✅ | `entity_timeseries_daily.composite_market_score` | ✅ | ✅ | ✅ | ✅ | Provokes curiosity; drives sign-up without giving away depth |
| Trend direction (rising/stable/declining) | ✅ | `entity_market.trend_state` | ✅ | ✅ | ✅ | ✅ | Simple directional signal — enough for public discovery |
| Top 1 opportunity tag (label only) | ✅ | `market_intelligence.py` string flags | ✅ | ✅ | ✅ | ✅ | "Why trending" hook for SEO/public curiosity |
| Top 3 creator names (no attribution data) | ✅ | `creator_scores` via creators endpoint | ✅ | ✅ | ✅ | ✅ | Social proof for public — no deep attribution |
| All creator attribution (tier, engagement, early signal, timeline) | ✅ | `creator_entity_relationships` + `creator_scores` | ❌ | ✅ | ✅ | ✅ | Deep attribution is Pro intelligence |
| 30-day trend chart | ✅ | `entity_timeseries_daily` | ❌ | ✅ | ✅ | ✅ | Chart is Pro — public gets direction only |
| Extended history (90-day) | ✅ (data exists, no enforcement) | `entity_timeseries_daily` | ❌ | ✅ | ✅ | ✅ | Depth is Pro |
| Extended history (up to 24 months where available) | ⚠️ (data exists since tracking began; API allows 365d) | `entity_timeseries_daily` | ❌ | ❌ | ✅ | ✅ | Report-depth historical analysis |
| Mention count (single number) | ✅ | `entity_timeseries_daily.mention_count` | ⚠️ | ✅ | ✅ | ✅ | Could expose as public context; see section 13.2 for deferral |
| Source-platform split (YouTube vs Reddit vs Instagram) | ✅ (YouTube+Reddit now; IG1 future) | `entity_mentions.source_platform` | ❌ | ✅ | ✅ | ✅ | Source attribution is Pro |
| Full signal timeline | ✅ | `signals` table | ❌ | ✅ | ✅ | ✅ | Full signal history is Pro/Report depth |
| Signals summary (count, latest) | ✅ | `signals` table | ❌ | ✅ | ✅ | ✅ | Signals are Pro — surface only direction for public |
| Top drivers (content items with views/engagement) | ✅ | `mention_sources` + `entity_mentions` | ❌ | ✅ | ✅ | ✅ | Full driver attribution is Pro |
| All opportunity flags (all 11) | ✅ (as string labels) | `market_intelligence.py` | ❌ | ✅ | ✅ | ✅ | All opportunity detail is Pro+ |
| Opportunity evidence (content item refs, time windows) | ❌ (IL1 scope) | Future `entity_opportunities` table | ❌ | ✅ | ✅ | ✅ | Requires IL1 |
| Opportunity confidence score | ❌ (IL1 scope) | Future `entity_opportunities` table | ❌ | ✅ | ✅ | ✅ | Requires IL1 |
| Differentiators (e.g. "compliment getter") | ✅ | `entity_topic_links` + semantic classifier | ❌ | ✅ | ✅ | ✅ | Top 2 differentiators may be partially public (see 6.1) |
| Top 2 differentiators (label only) | ✅ | `entity_topic_links` + semantic classifier | ⚠️ | ✅ | ✅ | ✅ | Roadmap says public; confirm in PUB1 implementation |
| Positioning tags | ✅ | `entity_topic_links` + semantic classifier | ❌ | ✅ | ✅ | ✅ | Positioning detail is Pro |
| Intent breakdown | ✅ (topic-level) | `entity_topic_links` | ❌ | ✅ | ✅ | ✅ | Full intent distribution is Pro; mention-level intent is IL1 scope |
| Narrative (plain-language trend explanation) | ✅ | `market_intelligence.py` template | ❌ | ✅ | ✅ | ✅ | Narrative is Pro workspace |
| Compared-against / competitors | ✅ | VS-pattern from `entity_topic_links` | ❌ | ✅ | ✅ | ✅ | Competitive intelligence is Pro |
| Dupe / alternative landscape (full family) | ✅ (curated map) | `entity_role.py` `_DUPE_RAW` | ❌ | ✅ | ✅ | ✅ | "Alternative to X" label is public; full landscape is Pro |
| Similar perfumes by notes | ✅ | Fragrantica resolver notes join | ✅ | ✅ | ✅ | ✅ | Discovery linking — adds SEO internal link value |
| Watchlist add / alert | ⚠️ (API exists, no user auth) | `watchlists` + `alerts` tables | ❌ | ✅ | ✅ | ✅ | Pro workspace features |
| CSV export | ❌ | Not implemented | ❌ | ✅ | ✅ | ✅ | Pro utility |

### 5.2 Brand Fields

| Field / Block | Exists Today? | Source | Public | Pro | Report | Enterprise | Rationale |
|---------------|---------------|--------|--------|-----|--------|------------|-----------|
| Brand name | ✅ | `entity_market.canonical_name` | ✅ | ✅ | ✅ | ✅ | Core identity |
| Perfume count | ✅ | `entity_market.perfume_count` | ✅ | ✅ | ✅ | ✅ | Useful public context |
| Top 5 perfumes (names + state) | ✅ | `catalog_perfumes` sorted | ✅ | ✅ | ✅ | ✅ | Drives internal links; public discovery |
| Aggregate score + momentum summary | ✅ | `entity_timeseries_daily` | ✅ | ✅ | ✅ | ✅ | Single number for public; drives curiosity |
| Top notes / accords | ✅ | `top_notes` + `top_accords` | ✅ | ✅ | ✅ | ✅ | Useful for composition-aware public visitors |
| Full portfolio (all perfumes, all scores) | ✅ | `catalog_perfumes` list | ❌ | ✅ | ✅ | ✅ | Full portfolio is Pro |
| Brand chart / history | ✅ (no enforcement) | `entity_timeseries_daily` | ❌ | ✅ | ✅ | ✅ | Chart is Pro |
| Brand competitors | ✅ (VS-pattern) | `entity_topic_links` | ❌ | ✅ | ✅ | ✅ | Competitive intelligence is Pro |
| Full brand intelligence (topics, intents, narrative) | ✅ | `entity_topic_links` + semantic | ❌ | ✅ | ✅ | ✅ | Pro workspace |
| Portfolio alerts / watchlist | ⚠️ (API exists, no user auth) | `watchlists` + `alerts` | ❌ | ✅ | ✅ | ✅ | Pro feature |
| Portfolio export | ❌ | Not implemented | ❌ | ✅ | ✅ | ✅ | Pro utility |

### 5.3 Creator Fields

| Field / Block | Exists Today? | Source | Public | Pro | Report | Enterprise | Rationale |
|---------------|---------------|--------|--------|-----|--------|------------|-----------|
| Creator name / title | ✅ | `youtube_channels.title` | ✅ (on perfume pages only) | ✅ | ✅ | ✅ | Attribution context for public perfume pages |
| Platform badge (YT) | ✅ | `creator_scores.platform` | ✅ (on perfume pages only) | ✅ | ✅ | ✅ | Platform identity context |
| Verified creator badge | ✅ | `creator_profile_claims.claim_status` | ✅ | ✅ | ✅ | ✅ | Trust signal — publicly useful |
| Creator profile page (full leaderboard) | ✅ | `/creators` route (terminal) | ❌ | ✅ | ✅ | ✅ | Leaderboard is Pro workspace; names appear on public perfume pages only |
| Influence tier + score | ✅ | `creator_scores.quality_tier` + `influence_score` | ❌ | ✅ | ✅ | ✅ | Pro attribution depth |
| Creator portfolio (entities covered) | ✅ | `creator_entity_relationships` | ❌ | ✅ | ✅ | ✅ | Pro intelligence |
| Full attribution (views, engagement, early signal) | ✅ | `creator_entity_relationships` + `mention_sources` | ❌ | ✅ | ✅ | ✅ | Pro intelligence |

### 5.4 Product / Feature Access

| Feature | Exists Today? | Public | Pro | Report | Enterprise | Rationale |
|---------|---------------|--------|-----|--------|------------|-----------|
| Screener (market + composition) | ✅ (auth required) | ❌ | ✅ | N/A | ✅ | Research tool — Pro workspace |
| Watchlists (create/manage) | ⚠️ (DEV_OWNER_KEY) | ❌ | ✅ | N/A | ✅ | Pro workspace — needs user auth |
| Alerts (create/pause/history) | ⚠️ (DEV_OWNER_KEY, in_app only) | ❌ | ✅ | N/A | ✅ | Pro workspace — needs delivery |
| Alert delivery (email/webhook) | ❌ | ❌ | ✅ | N/A | ✅ | Requires PRO1 implementation |
| Comparison chart (multi-entity) | ❌ | ❌ | ✅ | ✅ | ✅ | PRO1 scope |
| CSV export | ❌ | ❌ | ✅ | ✅ | ✅ | PRO1 scope |
| 30-day chart | ✅ (no enforcement) | ❌ | ✅ | ✅ | ✅ | Chart gating via API tier enforcement in PRO1 |
| 90-day chart | ✅ (no enforcement) | ❌ | ✅ | ✅ | ✅ | Same |
| 24-month history (where available) | ⚠️ (data may exist, API allows 365d) | ❌ | ❌ | ✅ | ✅ | Report depth — requires DATA0 versioning |
| Opportunity Feed | ❌ | ❌ | ✅ | ✅ | ✅ | Requires IL1 |
| Premium reports (PDF/structured artifacts) | ❌ | ❌ | ❌ | ✅ | ✅ | Requires REPORT1 |
| Enterprise API | ❌ | ❌ | ❌ | ❌ | ✅ | Custom implementation post-PRO1 |

---

## 6. Public Layer Specification

### 6.1 Public Perfume Page — Architecture Contract

The following defines what PUB1 should expose at `/perfumes/[slug]` (see section 11 for slug format).

**Publicly exposed (M0 recommendation — validated against data reality):**

| Field | Data source | Notes |
|-------|-------------|-------|
| Perfume name | `entity_market.canonical_name` | Always available for tracked + catalog entities |
| Brand name (linked) | `entity_market.brand_name` | Links to `/brands/[slug]` public page |
| Entity role badge | `entity_role.py` | Designer Original / Niche Original / Dupe Alternative — useful public context |
| Reference original ("Alternative to: Creed Aventus") | `entity_role.py _DUPE_RAW` | Only for known dupe entities |
| Notes top/middle/base + accords (linked) | Fragrantica resolver | Available for ~90% of catalog; internal links to `/notes/[name]` and `/accords/[name]` |
| Similar perfumes by notes (3–5, linked) | Fragrantica notes join | Internal link graph value for SEO |
| Current market score (single number) | `entity_timeseries_daily.composite_market_score` | Only for tracked entities with timeseries. Catalog-only entities: "Not yet tracked" |
| Trend direction label (Rising / Stable / Declining) | `entity_market.trend_state` | Only for tracked entities |
| Top 1 opportunity tag (label only, no evidence) | `market_intelligence.py` first flag | "Gifting Demand", "Social Validation", etc. — provokes curiosity |
| Top 2 differentiators (label only) | `entity_topic_links` → semantic | "Compliment getter", "Longevity / projection" — "Why people talk about it" preview |
| Top 3 creator names (no engagement data, no tier) | `creator_entity_relationships` + `youtube_channels.title` | Attribution context only; links to terminal creator page behind sign-up CTA |
| Internal links to brand, notes, accords | navigation | Core SEO internal link graph |
| Sign-up CTA | — | "See full market intelligence — join FTI Terminal" |

**Gated / not public:**

| Field | Reason |
|-------|--------|
| Full historical chart | Pro depth — provokes sign-up |
| Extended history (any period) | Pro/Report |
| All creators with attribution data | Pro intelligence |
| Full signal timeline | Pro depth |
| All opportunity flags with labels | Pro — expose only top 1 |
| Opportunity evidence / confidence scores | Pro/Report — IL1 scope |
| Full differentiators + positioning + intents | Pro workspace |
| Narrative text | Pro workspace |
| Compared-against / competitor details | Pro competitive intelligence |
| Full dupe/alternative landscape | Pro — reference only is public |
| Mention count (numeric) | Currently deferred — see section 13.2 |
| Source platform split | Pro |

**Catalog-only entities:** Entities in Fragrantica KB but not yet tracked in market engine show name, brand, notes, accords, and similar perfumes only. Score and trend: "Not yet tracked." This is valid public content — it creates SEO pages that will fill in with intelligence once tracking begins.

### 6.2 Public Brand Page — Architecture Contract

Public brand pages at `/brands/[slug]`:

**Publicly exposed:**

| Field | Data source |
|-------|-------------|
| Brand name | `entity_market.canonical_name` |
| Total perfume count | `entity_market` (count of brand perfumes) |
| Top 5 perfumes (name, current state) | `catalog_perfumes` top 5 |
| Aggregate market score | `entity_timeseries_daily` (brand entity) |
| Momentum summary (Rising / Stable / Declining) | `entity_market.trend_state` |
| Top notes / accords across portfolio | `top_notes`, `top_accords` |
| CTA to terminal | — |

**Gated:**

| Field | Reason |
|-------|--------|
| Full portfolio with scores | Pro |
| Brand history chart | Pro |
| Brand competitor comparison | Pro competitive intelligence |
| Brand-level intelligence (narrative, opportunities) | Pro |
| Portfolio alerts / export | Pro workspace |

### 6.3 Future Public Note / Accord Pages (PUB2)

Note pages at `/notes/[name]` and accord pages at `/accords/[name]` are PUB2 scope — they are not PUB1.

**Architecture role:**
- Each note/accord page lists top perfumes that feature it (cross-linked to perfume public pages)
- Provides fragrance family context and brief identity text
- Trending context: "Used in X fragrances currently rising in market interest" (simple count, no score depth)
- Internal link value: every perfume page links to its notes; every note page links back to perfumes — this creates a crawlable internal link graph for long-tail SEO

**SEO value:** Pages should rank for "[note name] fragrances", "[accord name] perfumes", "fragrances with [note]" queries. These are high-intent discovery queries for fragrance buyers and sellers.

**Data requirements for PUB2:**
- `perfume_notes` / `perfume_accords` tables from Fragrantica resolver (already exist)
- `entity_market` to flag which linked perfumes are "trending" (already exists)
- No new DB tables required for basic PUB2; enhanced analytics are Pro

---

## 7. Pro Layer Specification

The Pro layer is the authenticated intelligence workspace. It extends what the public layer surfaces with full depth.

### Perfume Pro
| Capability | Structurally Supported? | Gap |
|------------|------------------------|-----|
| Full timeseries chart (30-day, 90-day) | ✅ — data exists; API allows 30d default, 365d max | No tier enforcement; PRO1 implements gating |
| Extended history (up to 24 months where available) | ⚠️ — data exists if tracking began 24 months ago; may not for all entities | DATA0 adds formula versioning so history is report-comparable |
| All creators with full attribution | ✅ — `creator_entity_relationships` endpoint exists | Currently auth-only, no Pro-specific gating |
| Full signal timeline | ✅ — `recent_signals` in API | No tier enforcement |
| All opportunity flags (all 11) | ✅ — string flags returned | Confidence scoring requires IL1 |
| Opportunity evidence / Opportunity Feed | ❌ | Requires IL1 |
| Full differentiators + positioning + intents | ✅ — returned in API | No tier enforcement |
| Narrative | ✅ | No tier enforcement |
| Compared-against competitors | ✅ | No tier enforcement |
| Full dupe/alternative landscape | ✅ (curated) | Curated only — ML expansion future |
| Watchlists | ⚠️ — API complete, DEV_OWNER_KEY | Per-user auth + PRO1 gating needed |
| Alerts (in_app only) | ⚠️ — API schema exists, no delivery | Delivery mechanism needed in PRO1 |
| Alert delivery (email/webhook) | ❌ | PRO1 scope |
| Comparison chart (multi-entity) | ❌ | PRO1 scope |
| CSV export | ❌ | PRO1 scope |

### Brand Pro
| Capability | Structurally Supported? | Gap |
|------------|------------------------|-----|
| Full portfolio performance (all entities + scores) | ✅ — `catalog_perfumes` (up to 100) | PRO1 gating |
| Brand chart (extended history) | ✅ — same as perfume | PRO1 gating |
| Brand competitor comparison | ⚠️ — VS-pattern detection only | No formal brand-vs-brand comparison view |
| Portfolio alerts | ⚠️ | PRO1 user auth + delivery |
| Portfolio export | ❌ | PRO1 scope |

### Cross-Entity Pro Tools
| Tool | Exists? | Gap |
|------|---------|-----|
| Screener with all filters | ✅ (auth required) | PRO1 tier enforcement (currently same for all auth'd users) |
| Watchlist create/manage | ⚠️ | DEV_OWNER_KEY → PRO1 user auth |
| Alerts create/manage | ⚠️ | DEV_OWNER_KEY + no delivery → PRO1 |
| Comparison chart | ❌ | PRO1 scope |
| CSV export (any entity/list) | ❌ | PRO1 scope |

---

## 8. Premium Report Layer Specification

### 8.1 Perfume Deep Dive — Report Section Map

| # | Report Section | Business Question | Data Available? | Existing Source | Missing Prerequisite |
|---|----------------|-------------------|-----------------|-----------------|---------------------|
| 1 | **Executive Summary / Current Status** | What is the entity's current market position? Rising or declining? | ✅ | `entity_timeseries_daily.composite_market_score`, `entity_market.trend_state`, `narrative` | DATA0: formula_version needed to cite methodology |
| 2 | **Market Position & Historical Trend** | How has score evolved over 30/90/180/365 days? | ⚠️ | `entity_timeseries_daily` rows | DATA0: score_formula_version required for cross-period comparability; 24-month data may not exist for all entities |
| 3 | **Signal Timeline** | What specific events drove attention? When? How strong? | ✅ | `signals` table — breakout/acceleration/sustained events with detected_at | DATA0: signal_threshold_version needed for methodology citation |
| 4 | **Driver Attribution** | Which creators and content items drove the signal? | ✅ | `creator_entity_relationships`, `mention_sources`, `canonical_content_items` | Partial for cross-platform (YouTube only now; IG1 adds Instagram) |
| 5 | **Creator Concentration / Source Dependence** | Is growth from one creator (risky) or distributed (sustainable)? | ✅ | `creator_entity_relationships.mention_count`, `creator_scores` | Cross-platform requires IG1 |
| 6 | **Intent Breakdown** | Why are people talking about it? Gift? Review? Comparison? Blind buy? | ⚠️ | `entity_topic_links` (topic-level intent, not mention-level) | IL1: mention-level intent classification required for % breakdown by intent type |
| 7 | **Compared Against / Competitive Cluster** | Which other fragrances does it get compared to? | ⚠️ | VS-pattern from `entity_topic_links` → `_find_competitor_names()` | Limited to VS-pattern; no formal comparison graph; entity resolution only for tracked entities |
| 8 | **Dupe / Alternative Landscape** | Is it a dupe target? A clone? What family does it sit in? | ⚠️ | `entity_role.py _DUPE_RAW` (curated), `reference_original`, `dupe_family` | Curated map only; not computed at scale |
| 9 | **Opportunity Analysis** | What market opportunities are active? How confident? | ⚠️ | 11 string flags in `market_intelligence.py` | IL1: formal `entity_opportunities` table with confidence scores, evidence refs, time windows required |
| 10 | **Note / Accord Momentum Context** | Are the notes in this fragrance trending? | ✅ | `entity_topic_links`, notes from Fragrantica, `top_notes` / `top_accords` on dashboard | PUB2 note/accord trend analytics would enrich this |
| 11 | **Risk Signals** | Is growth creator-dependent? Is velocity decelerating? | ⚠️ | `momentum`, `acceleration`, `volatility` in timeseries; creator concentration derivable | Not yet explicitly computed as a "risk score" object |
| 12 | **Methodology / Confidence** | How were scores computed? What data was used? | ❌ | Nothing — no formula version, no source annotation on scores | DATA0: `score_formula_version` on `entity_timeseries_daily` + `signal_threshold_version` on `signals` required |

**Summary:** Sections 1, 3, 4, 5, 10 are largely buildable from current data. Sections 2, 6, 7, 9, 11, 12 require DATA0 and/or IL1 to be credible report products.

### 8.2 Other Future Report Families

These report families are not defined in detail in M0 but are placed correctly in the commercial model:

| Report | Primary Use Case | Key Data Requirements |
|--------|-----------------|----------------------|
| **Competitor Map** | Map a fragrance's competitive ecosystem: dupes, alternatives, adjacent positioned scents | Formal dupe/alternative graph (currently curated, not computed); IL1 Opportunity Objects |
| **Launch Playbook** | Should a brand launch a new fragrance in a niche? What creators and occasions matter? | IL1 intent distribution; creator tier data; IG1 cross-platform data |
| **Brand Health Report** | Full brand portfolio momentum, top performers, risky entries, creator concentration | Brand-level aggregation (current) + IL1 + DATA0 versioning |
| **Competitive Landscape** | Category-level view: who is winning in "fresh masculine" or "oud dark" | Note/accord-level trend analytics (PUB2 level) + IL1 |
| **M&A Due Diligence Pack** | Fragrance brand acquisition target assessment | Full history (DATA0 + 24-month window) + creator concentration + competitor map |

---

## 9. Opportunity Object Model — Data Contract

This section defines the formal schema that IL1 will implement as the `entity_opportunities` table. It is a data contract only — no code is written in M0.

### 9.1 Current State

The current implementation in `market_intelligence.py` returns `opportunities: List[str]` — a list of up to 11 string labels per entity. These are computed at API request time from topic/intent signals. They have no confidence score, no evidence references, no time windows, no formula version, and no persistence.

**Current flags (11):** alternative_demand, clone_market, alternative_search_interest, affordable_alt, high_intent, competitive_comparison, gifting, viral_momentum, launch_window, social_validation, performance_leader

This is sufficient for the Pro workspace today but is inadequate for premium reports, Pro sorting, or Opportunity Feed — all of which require scored, evidenced, time-bounded objects.

### 9.2 Formal Opportunity Object Schema (IL1 target)

```
entity_opportunities
--------------------
id                    UUID    — primary key; stable identifier for evidence links
opportunity_type      VARCHAR — one of defined types (see below)
entity_type           VARCHAR — 'perfume' | 'brand' | 'note' | 'accord'
entity_id             UUID    — FK → entity_market.id
confidence_score      FLOAT   — 0.0–1.0; computed by rule/model; citable in reports
strength              VARCHAR — 'low' | 'medium' | 'high' — human-readable grade
evidence_refs         JSONB   — array of canonical_content_items.id or entity_mentions.id
evidence_summary      TEXT    — human-readable justification (template-generated)
time_window_start     DATE    — start of the evidence window
time_window_end       DATE    — end of the evidence window (usually today)
is_active             BOOL    — False when evidence fades or contradicted
generated_at          TIMESTAMPTZ — when this object was computed
formula_version       VARCHAR — e.g. "opp_v1" — must be set from DATA0 versioning policy
recommended_action    TEXT    — optional brief action hint ("prioritize in gifting assortment", etc.)
```

**Field rationale:**

| Field | Why It Exists | Required | Unlocks |
|-------|--------------|----------|---------|
| `id` | Stable reference for reports and API evidence links | YES | Report evidence citation, Opportunity Feed deduplication |
| `opportunity_type` | Structured label replacing ad-hoc string flags | YES | Filtering, sorting, Opportunity Feed |
| `confidence_score` | Makes opportunities ranked and comparable | YES | Pro sorting, Report credibility, Opportunity Feed ranking |
| `strength` | Human-readable grade for non-numeric display | YES | Report display, Pro UI |
| `evidence_refs` | Links to actual content items that support the flag | YES | Report section 9, Pro "show me why" UX |
| `evidence_summary` | Template-generated explanation | YES | Pro UX, Report narrative, LLM-ready |
| `time_window_start/end` | Makes opportunities temporal, not timeless | YES | Report methodology, trend recency |
| `is_active` | Allows opportunities to expire | YES | Feed cleanup, report snapshot accuracy |
| `generated_at` | Audit trail | YES | Report timestamp, methodology citation |
| `formula_version` | Ties to DATA0 versioning policy | YES | Report comparability across time |
| `recommended_action` | Bridges intelligence to decision | NO | Future Enterprise / brand guidance product |

**Opportunity types (IL1 to define exhaustive list; initial set from current flags):**

| Type | Replaces Current Flag | Meaning |
|------|-----------------------|---------|
| `gifting_demand` | `gifting` | Gift-intent signals detected across multiple sources |
| `high_purchase_intent` | `high_intent` | Multiple buy/discovery signals active simultaneously |
| `social_validation` | `social_validation` | Compliment-getter reputation driving word of mouth |
| `viral_momentum` | `viral_momentum` | Rapid velocity increase detected |
| `launch_window` | `launch_window` | New release / flanker activity detected |
| `competitive_comparison` | `competitive_comparison` | Active comparison queries; comparison-driven awareness |
| `alternative_demand` | `alternative_demand` | Reference scent with strong dupe-search demand |
| `clone_market` | `clone_market` | Clone/inspired entity with active dupe demand |
| `affordable_positioning` | `affordable_alt` | Price-value positioning actively discussed |
| `performance_leader` | `performance_leader` | Longevity/projection differentiator standing out |
| `alternative_search_interest` | `alternative_search_interest` | Dupe-adjacent activity for entity with unknown role |

### 9.3 Future Uses

| Consumer | How Opportunity Objects Are Used |
|----------|----------------------------------|
| **Opportunity Feed** | Active objects ranked by `confidence_score × recency_decay`; surfaced as the Pro "what's new in intelligence" stream |
| **Pro workspace** | Per-entity opportunity cards with evidence_summary; "show me why" evidence drilldown |
| **Premium reports (REPORT1)** | Report section 9 cites confidence scores, evidence_refs, time_window; methodology_version enables comparability |
| **Alert triggers** | Alert fires when `opportunity_type = 'gifting_demand' AND confidence_score > 0.7 AND is_active = true` |
| **Screener filter** | "Show me entities with active high_purchase_intent opportunities" |
| **Enterprise API** | Queryable opportunity stream for brand/retail intelligence tools |

---

## 10. History Depth / Access Tier Policy

### 10.1 Current Reality

- `entity_timeseries_daily` has rows since each entity began being tracked. Older tracked entities may have 12–18+ months of data. Newer additions have less.
- The API currently accepts `?history_days=1..365` with no tier enforcement — all authenticated users receive the same depth.
- No `score_formula_version` exists on timeseries rows — historical periods are technically uncomparable if the aggregation formula changes.
- DATA0 must add formula versioning before report-grade history can be cited.

### 10.2 Recommended Tier History Policy

| Tier | History Depth | Chart Access | Rationale |
|------|--------------|--------------|-----------|
| **Public** | Current score + trend direction only. No chart. | ❌ No chart | Chart is the key Pro conversion lever. Public direction (↑/↓) is enough to provoke curiosity. |
| **Pro** | 90-day chart + 6-month data on request | ✅ 90-day default | 90 days shows meaningful trend cycles; 6-month view available on demand. Sufficient for portfolio monitoring. |
| **Report** | Up to 24 months where data exists, with methodology versioning | ✅ Full window | Report analysis requires sufficient history to comment on seasonal patterns, launch trajectories, and long-term trajectory. "Where data exists" is an honest qualification. |
| **Enterprise** | Full available history + export | ✅ Full window + export | Custom contracts; full data access for BI integration. |

### 10.3 Chart Gating — Specific Recommendation

**The roadmap said "30-day public chart" as a candidate.** This M0 document does NOT recommend exposing a chart on public pages.

**Rationale:** The trend chart is the single strongest conversion lever from public visitor to Pro subscriber. Showing a direction label ("Rising ↑") and a single score is sufficient to create curiosity without giving away depth. A visible chart reduces conversion urgency. The public page should be compelling enough to explain the platform, not so complete that there is no reason to sign up.

**This is a lock recommendation, not a deferral.** If the founder disagrees, this is the only major public-vs-Pro boundary question that should be re-evaluated in section 13.

### 10.4 What is Locked vs Revisitable

| Decision | Status | Revisit Window |
|----------|--------|---------------|
| No chart on public pages | LOCKED by M0 | Can revisit at PRO1 if A/B test data suggests otherwise |
| 90-day Pro default chart | RECOMMENDED — not locked | Can revisit at PRO1 |
| 6-month Pro on-demand history | RECOMMENDED — not locked | Can revisit at PRO1 |
| 24-month Report window | LOCKED as upper bound | Subject to DATA0 data availability reality |
| Formula versioning required before report-grade history cited | LOCKED — DATA0 dependency | Cannot skip |

---

## 11. Public URL / Routing / Canonical Strategy

### 11.1 Problem Statement

Current terminal routes use internal entity IDs or entity type paths that are not SEO-friendly:
- `/entities/perfume/{entity_id}` — entity_id is a string like `creed-aventus` or a UUID depending on entity type
- `/entities/brand/{id}`
- `/entities/note/{name}`
- `/entities/accord/{name}`

These routes are under the `(terminal)` Next.js route group which is behind auth middleware. They are not indexable.

Public pages must be a separate route family, outside the `(terminal)` group, with clean slug-based URLs.

### 11.2 Recommended Public Route Structure

| Entity Type | Public URL | Example |
|-------------|-----------|---------|
| Perfume | `/perfumes/[slug]` | `/perfumes/creed-aventus` |
| Brand | `/brands/[slug]` | `/brands/creed` |
| Note | `/notes/[slug]` | `/notes/vanilla` |
| Accord | `/accords/[slug]` | `/accords/woody` |

**Slug format:** lowercase, hyphen-separated, derived from `canonical_name`. Accent characters NFD-normalized and stripped. Special characters removed. Consecutive hyphens collapsed.

Examples:
- `Creed Aventus` → `creed-aventus`
- `Maison Francis Kurkdjian Baccarat Rouge 540` → `maison-francis-kurkdjian-baccarat-rouge-540`
- `Dior Sauvage EDP` → `dior-sauvage-edp`
- `Vanilla` → `vanilla`

### 11.3 Slug Collision Risk

Slug collision can occur when two entities have the same canonical_name after normalization (e.g., two brands with the same name but different spellings). Mitigation:

- Slug uniqueness must be enforced per entity type (perfume slugs are unique among perfumes; brand slugs among brands — no cross-type collision is possible with separate URL namespaces).
- In the rare case of a within-type collision, append a stable numeric disambiguator: `creed-aventus-2`.
- Slugs should be stored in `entity_market` or a dedicated `entity_slugs` table (SEO0 scope) for stability — a slug assigned to an entity should never change once indexed.

### 11.4 Slug Stability Requirement

A slug once indexed by search engines must never change without a 301 redirect. Stability is the primary SEO concern. **Slugs must not be recomputed dynamically on each page render.** They must be persisted.

**SEO0 scope:** Create the `entity_slugs` mechanism (table or column) and persist slugs on entity creation/update.

### 11.5 Relationship Between Terminal and Public Routes

| Route Type | URL Pattern | Auth Required | Indexable | Canonical |
|------------|-------------|---------------|-----------|-----------|
| Public entity page | `/perfumes/[slug]` | ❌ No | ✅ Yes | `/perfumes/[slug]` |
| Terminal entity page | `/entities/perfume/[id]` | ✅ Yes | ❌ No (noindex) | `/perfumes/[slug]` |

**Terminal pages must add `<meta name="robots" content="noindex">` and `<link rel="canonical" href="/perfumes/[slug]">`.** This prevents duplicate content penalties. SEO0 implements this.

### 11.6 Concentration / Flanker Naming Concerns

Fragrances often have concentration variants: Creed Aventus, Creed Aventus EDP, Creed Aventus for Her. The aggregation pipeline collapses concentration suffixes — "Dior Sauvage EDP" and "Dior Sauvage" resolve to the same market entity. However, the Fragrantica catalog may have them as separate resolver entries.

**Policy:** One canonical public page per `entity_market` entity. If concentration variants exist as separate catalog entries but resolve to the same market entity, the canonical page is for the market entity's `canonical_name`. Fragrantica variant names may be listed as aliases without separate pages.

**PUB1 to decide:** whether to create stub redirect pages for aliases. Not a blocking M0 decision.

### 11.7 Slug + Stable ID Pattern (Recommended)

For maximum URL stability, use slug-primary with UUID fallback at the DB level:

- Primary access: `/perfumes/[slug]` (canonical URL)
- Internal lookup: slug resolves to `entity_market.id` (UUID)
- If slug is unknown/deleted: 404 or redirect

This is preferable to slug-only (collision risk) and to UUID-only (not SEO-friendly).

---

## 12. Phase Interfaces

### M0 → DATA0
DATA0 receives these specific decisions from M0:
- `entity_timeseries_daily` must have `score_formula_version VARCHAR` column — reports cannot cite history without it
- `signals` must have `signal_threshold_version VARCHAR` — methodology citation for Section 3 of Deep Dive
- `entity_topic_links` overwrite-on-rebuild is a data integrity risk — DATA0 decides option A (snapshot table) or option B (append-with-date)
- Retention policy anchor: raw content items, mentions, timeseries rows must be kept indefinitely; topic links and opportunity objects need defined retention

### M0 → SEO0
SEO0 receives:
- Public URL structure: `/perfumes/[slug]`, `/brands/[slug]`, `/notes/[slug]`, `/accords/[slug]`
- Slug format: lowercase hyphen-separated from canonical_name
- Slug stability requirement: must be persisted, not recomputed
- Terminal routes must be noindex + canonical to public route
- `robots.ts`: allow `/perfumes/*`, `/brands/*`, `/notes/*`, `/accords/*`; noindex all `/(terminal)/*` routes
- `metadataBase`: confirmed `https://fragranceindex.ai`
- `generateMetadata()` conventions: title = `{canonical_name} — FragranceIndex.ai`, description includes trend direction and top note
- JSON-LD schema selection: `ItemPage` for perfume, `Organization` for brand, `DefinedTerm` for notes/accords

### M0 → PUB1
PUB1 receives:
- Full public field exposure policy: section 6.1 (perfume) and 6.2 (brand)
- No chart on public pages (locked in section 10.3)
- Top 1 opportunity tag (label only)
- Top 2 differentiators (labels only)
- Top 3 creator names (no attribution data)
- Similar perfumes by notes — internal links
- CTA framing: "See full market intelligence — join FTI Terminal"
- Catalog-only entities: show name, brand, notes, accords; no score

### M0 → PUB2
PUB2 receives:
- Note and accord pages at `/notes/[slug]` and `/accords/[slug]`
- Each page: note/accord identity + linked perfumes + trending context (count)
- Anti-thin-content rule: each page must carry at least one unique data-driven signal
- No duplicate content across concentration variants

### M0 → IG1
IG1 receives:
- Public boundary rules: Instagram content items follow the same field-level tier access as YouTube — source platform split is Pro, not public
- Public pages show top 3 creator names regardless of platform — no platform-specific counts publicly
- `source_platform='instagram'` in `canonical_content_items` is structurally defined by migration 034 (`tiktok_layer` extension)
- Platform weight initial recommendation: 0.8× (same as TikTok Layer 3); calibrate upward after quality verified
- Creator identity rule from C2.2A applies: Instagram creator names must not be auto-merged with YouTube/Reddit creators by display name

### M0 → IL1
IL1 receives the formal Opportunity Object schema from section 9.2:
- Table: `entity_opportunities`
- Required fields: id, opportunity_type, entity_type, entity_id, confidence_score, strength, evidence_refs, evidence_summary, time_window_start, time_window_end, is_active, generated_at, formula_version
- Optional field: recommended_action
- Opportunity types: defined in section 9.2 (11 initial types mapping from current string flags)
- `formula_version` must respect DATA0 versioning policy from day one

### M0 → REPORT1
REPORT1 receives:
- Full report section map: section 8.1 (12 sections)
- DATA0 and IL1 as prerequisites for sections 2, 6, 9, 12
- IG1 as additive for sections 4, 5 (cross-platform data strengthens)
- Internal prototype targets: Creed Aventus · Baccarat Rouge 540 · Armaf Club de Nuit Intense Man

### M0 → PRO1
PRO1 receives:
- Pro tier: 90-day chart default, 6-month on-demand history
- Pro features: full attribution, all opportunity flags, Opportunity Feed (IL1 required), watchlists (user auth needed), alerts (user auth + delivery needed), comparison chart, CSV export
- Alert architecture: `delivery_type` currently `in_app` only — email/webhook delivery is PRO1 scope
- Watchlist/alert auth: DEV_OWNER_KEY must be replaced with real per-user auth in PRO1

---

## 13. Decisions Locked vs Deferred

### 13.1 Decisions Locked by M0

These decisions are binding for downstream phases. Changing them later requires explicit founder override and architectural rework.

| Decision | Section | Why Locked |
|----------|---------|------------|
| Four commercial layers (Public, Pro, Report, Enterprise) | 2 | Foundation of all gating logic |
| Perfume and Brand are primary monetizable entity objects | 3 | Creator is attribution, not primary product |
| No chart on public pages | 10.3 | Conversion lever; exposing chart removes urgency |
| Public URL structure: `/perfumes/[slug]`, `/brands/[slug]`, `/notes/[slug]`, `/accords/[slug]` | 11.2 | SEO0 and PUB1 will build against this; changing post-SEO0 requires 301 redirects |
| Slug stability: must be persisted, not recomputed | 11.4 | Changing indexed URLs causes SEO rank loss |
| Terminal routes must be noindex + canonical to public routes | 11.5 | Duplicate content penalty prevention |
| Opportunity Object formal schema (section 9.2) | 9 | IL1 implements this contract; changing post-IL1 requires migration |
| `formula_version` required on `entity_opportunities` from day one | 9.2 | DATA0 policy must apply to all new scored objects |
| Report section map for Deep Dive (12 sections) | 8.1 | REPORT1 builds to this spec |
| IL1 and DATA0 are prerequisites before report-grade history can be cited | 8.1 | Methodology integrity |
| Top 3 creator names (label only) on public pages | 6.1 | Balance: attribution context without deep data |

### 13.2 Decisions Intentionally Deferred

These are open policy questions that do not block SEO0, DATA0, or PUB1, and are resolved later.

| Decision | Deferred To | Current Recommendation |
|----------|-------------|----------------------|
| Pricing and subscription packaging | PRO1 | Not defined in M0 |
| Checkout provider (Stripe or equivalent) | PRO1 | Not defined in M0 |
| Final paywall UX and conversion flow | PRO1 | Not defined in M0 |
| Enterprise contract format and SLA | Post-PRO1 | Not defined in M0 |
| Exact report pricing | REPORT1 | Not defined in M0 |
| Alert delivery vendor (email provider, webhook format) | PRO1 | Architecture defined; implementation deferred |
| Whether to expose mention count as public context | PUB1 | Currently excluded. Could be reconsidered at PUB1 implementation if it improves conversion signal without cannibalizing Pro depth. Rationale for exclusion: mention count is a raw number without context; trend direction communicates intent better. |
| Alias stub redirect pages for concentration variants | PUB1 | Not blocking; decide during PUB1 implementation |
| Final 6-month vs 90-day Pro history default | PRO1 | M0 recommends 90-day default; revisit with usage data |
| IG1 platform weight calibration (0.8× vs higher) | IG1 | Start at 0.8×; calibrate after 30-day signal quality review |
| Mention-level intent classification method | IL1 | Deterministic rules recommended; detail is IL1 scope |
| TikTok Research API eligibility for commercial platforms | TT2 | Deferred pending formal investigation |

---

## 14. Founder Decision Checklist

Based on the audit above, the following items genuinely require founder input before DATA0 or SEO0 can begin:

| # | Question | Context | Default if No Response |
|---|----------|---------|----------------------|
| 1 | **Confirm: no chart on public pages.** M0 recommends gating the chart entirely (public pages show trend direction label only). The roadmap previously listed "30-day public chart" as a candidate. This document recommends against it. Do you agree? | Section 10.3. The chart is the single strongest conversion lever from public to Pro. Exposing it on public pages is giving away depth that drives sign-up motivation. | Proceed with NO chart on public pages. |
| 2 | **Confirm: creator names appear on public pages, but the creator profile and leaderboard are Pro-only.** Top 3 creator names (no tier, no engagement data) visible on public perfume pages. The full `/creators` leaderboard and `/creators/[id]` profile are behind auth. | Section 6.1, section 3. This positions creator attribution as trust-building public context without making the leaderboard a free product. | Proceed as specified. |

**No other blocking founder decisions remain before DATA0 or SEO0 can begin.** The two questions above are recommended confirmations, not blockers — defaults are stated. DATA0 can proceed immediately based on the versioning decisions in section 12.

---

*End of MONETIZATION_ARCHITECTURE.md — M0 Foundation*
*Next phase: DATA0 — Historical Integrity & Metric Versioning*
