# CLAUDE.md — Perfume Trend Intelligence SDK

## Phase I — Intelligence Layer

### Purpose
Transform the system from data tracking into market intelligence.

This layer does NOT modify ingestion (D) or UI (E/U).
It enriches signals with meaning, influence, and prediction.

---

### I1 — Source Intelligence (COMPLETED — 2026-04-24)

Add source-level data:
- who created content
- channel size
- engagement

Result:
System knows WHO drives trends.

STATUS: COMPLETE

DEPLOYMENT:
- Migration 018: `source_profiles` + `mention_sources` tables — applied to production
- Migration 019: UNIQUE(mention_id) on mention_sources — applied to production
- Aggregator: writes MentionSource rows alongside every EntityMention (live pipeline)
- Backfill: `scripts/backfill_source_intelligence.py --days 30` run successfully
- API: `recent_mentions` enriched with views/likes/comments_count/engagement_rate
- API: new endpoint `GET /api/v1/entities/{id}/sources` (top sources by view volume)
- Frontend: `RecentMentionRow` type extended with source intelligence fields

VERIFICATION:
- mention_sources: 2,444 rows (one per entity_mention, UNIQUE enforced)
- source_profiles: 313 unique channel/author profiles
- 337 rows with real view counts from YouTube engagement data
- Top source: Scentlegacy 71,330 total views / 6 mentions
- Correct handling: one video → multiple entity_mentions → separate mention_sources rows (expected)

NOTES:
- Backfill join uses OR: `cci.id = em.source_url OR cci.source_url = em.source_url`
  (old entity_mentions use short video ID; new ones use full URL)
- source_profiles.subscribers not populated — requires separate YouTube Channel API call
- Reddit mention_sources created with NULL views (Reddit API returns score, not views)
- Pipeline-daily migration 019 runs automatically via `alembic upgrade head` on next deploy

---

### I2 — Signal Weighting (COMPLETED — 2026-04-24)

Replace equal mentions with weighted signals.

Result:
Noise vs real movement separation.

STATUS: COMPLETE

DEPLOYMENT:
- Migration 020: `weighted_signal_score` column on `entity_timeseries_daily` — applied to production
- Migration 020: `mention_sources.source_score` backfilled for all existing rows
- Migration 020: `weighted_signal_score` backfilled for all existing timeseries rows
- Aggregator: computes `source_score` per mention + `weighted_signal_score` per entity/day after each run
- API: `weighted_signal_score` exposed in `TopMoverRow`, `SnapshotRow` (entity timeseries)
- Frontend types: `weighted_signal_score: number | null` added to `TopMoverRow` and `SnapshotRow`

FORMULA:
```
# Per mention (stored in mention_sources.source_score):
YouTube:  source_score = 0.70 × min(log10(views+1)/log10(100_000), 1.0)
                       + 0.30 × min(engagement_rate × 10, 1.0)
Reddit:   source_score = 0.60 × min(log10(upvotes+1)/log10(1_000), 1.0)
                       + 0.40 × min(log10(comments+1)/log10(100), 1.0)
Other:    source_score = None (no boost, no penalty)

# Per entity per day (stored in entity_timeseries_daily.weighted_signal_score):
quality = COALESCE(AVG(source_score) for entity's mentions on date, 0.0)
weighted_signal_score = MIN(100, composite_market_score × (1.0 + quality))
```

NON-DESTRUCTIVE ROLLOUT:
- `composite_market_score` is unchanged — raw score preserved
- `weighted_signal_score` is a new field alongside it
- Range: [composite_market_score, min(100, 2.0 × composite_market_score)]
- Entities with no source data: quality=0.0 → weighted_score = raw score (×1.0)
- High-quality YouTube mentions (viral videos): quality≈0.8 → weighted_score ≈ 1.8 × raw

VERIFICATION:
- Checked: production PostgreSQL + /api/v1/dashboard (2026-04-24)
- migration 020 applied: `weighted_signal_score` column added, backfill complete
- mention_sources.source_score: 1,455 / 2,444 rows populated (59% — YouTube rows with views)
- entity_timeseries_daily.weighted_signal_score: 628 / 628 rows (100% of mention_count>0 rows)
- API `/api/v1/dashboard` TopMoverRow now has 21 keys (was 20); `weighted_signal_score` present
- Top production boosts: Creed Aventus +55.6%, Juliette Has a Gun Anyway +79.4%, Creed Aventus +44%

NOTES:
- Reddit mentions with NULL views: source_score=None → no boost (intended)
- Carry-forward rows (mention_count=0): weighted_signal_score=NULL (correct — no mentions to weight)
- Deployment required two fixes: (1) CollapsedRow dataclass field order violation (default field before
  non-default), (2) stale 018 row in alembic_version causing double-head; both fixed in production.
- Future: `weighted_signal_score` can replace `composite_market_score` as the ranking signal in I3+

---

### I3 — Trend State (COMPLETED — 2026-04-24)

Add directional understanding:
- emerging
- rising
- breakout
- peak
- declining

Result:
System knows WHERE trend is going.

STATUS: COMPLETE

DEPLOYMENT:
- Migration 021: `trend_state VARCHAR(20) NULLABLE` column on `entity_timeseries_daily` — applied to production
- `perfume_trend_sdk/analysis/market_signals/trend_state.py`: pure `compute_trend_state()` function with 6 states + None (carry-forward)
- Aggregator: computes trend_state per entity/day using current score, prev score, growth_rate, momentum, mention_count
- Brand rollup: prev brand score looked up via ORM query; brand trend_state computed and stored
- Carry-forward rows: always trend_state=None (no activity, no trend state)
- Variant collapser: picks best state across concentration variants via numeric priority dict (breakout=6 > rising=5 > peak=4 > stable=3 > declining=2 > emerging=1)
- API: `trend_state` exposed in `TopMoverRow`, `EntitySummary` (screener), `SnapshotRow` (timeseries), `PerfumeEntityDetail`, `BrandEntityDetail`
- Frontend: `TrendStateBadge` primitive with 6 semantic colors (emerald=breakout, green=rising, amber=peak, sky=stable, rose=declining, violet=emerging); 3 variants (pill, dot, label)
- Frontend: Trend column added to TopMoversTable and ScreenerTable
- Frontend: TrendStateBadge on perfume and brand entity page headers

CLASSIFICATION THRESHOLDS:
```
breakout:  score ≥ 15 AND growth ≥ 35% AND mentions ≥ 2
           OR signal in (breakout, acceleration_spike) AND score ≥ 10
declining: prev_score ≥ 10 AND score < 50% of prev
           OR growth < -30% AND prev_score ≥ 5
rising:    growth ≥ 15% AND score ≥ 5 AND mentions ≥ 1
           OR momentum ≥ 0.3 AND score ≥ 5
peak:      score ≥ 20 AND -5% ≤ growth ≤ +10%
emerging:  prev_score == 0 AND score > 0 AND mentions ≥ 1
           OR score < 10 AND growth > 0 AND mentions ≥ 1
stable:    score > 0 (fallback)
None:      mention_count == 0 (carry-forward row)
```

VERIFICATION:
- Checked: production PostgreSQL + /api/v1/screener + browser UI (2026-04-24)
- Backfill ran via `scripts/backfill_trend_state.py` on `generous-prosperity` service
- 1,610 rows updated; 0 active rows remain NULL
- DB distribution: rising=436, breakout=153, declining=36, peak=2, stable=1, NULL(carry-forward)=982
- API: /api/v1/screener returns 258 active rows, all with non-null trend_state
- Browser: Dashboard TREND column shows colored pills
- Browser: Screener TREND column shows colored pills (no more "—")
- Browser: Active rows show mix of states — breakout, rising, declining, peak, stable confirmed
- Perfume and brand entity page headers show trend badge
- Version: 1.0.3

NOTES:
- trend_state is additive — existing signals, scores, and timeseries are unchanged
- Pure function in trend_state.py allows easy threshold tuning
- Non-finite growth_rate values (inf/-inf) handled safely via is_finite guard
- Brand trend states aggregated from brand's own timeseries (not from constituent perfumes)
- Backfill required after deploy: existing rows were NULL until `backfill_trend_state.py` ran
- Future aggregation runs populate trend_state automatically — no manual backfill needed

---

### I4 — Driver Analysis (COMPLETED — 2026-04-24)

Identify:
- top videos
- top posts
- top creators

Result:
System knows WHAT caused the trend.

STATUS: COMPLETE

DEPLOYMENT:
- New `DriverRow` Pydantic schema: source_platform, source_url, source_name, views, likes,
  comments_count, engagement_rate, source_score, occurred_at
- New `_get_top_drivers(db, entity_uuid, limit=10)`: DISTINCT ON source_url query joining
  entity_mentions + mention_sources, ordered by source_score DESC then views DESC; up to 10
  deduplicated content items per entity
- New `_get_top_drivers_for_brand(db, brand_name, limit=10)`: brand-specific variant that
  aggregates across all perfume entity_market rows matching brand_name (brands have no direct
  entity_mentions — those live on perfume entities)
- `top_drivers: List[DriverRow] = []` added to `PerfumeEntityDetail` and `BrandEntityDetail`
- Wired into `get_perfume_entity()` (tracked path) and `get_brand_entity()` (tracked path)
- `DriverRow` interface + `top_drivers: DriverRow[]` added to `frontend/src/lib/api/types.ts`
- `TopDrivers` component added to perfume entity page (between Notes and Signals sections)
- `TopDrivers` component added to brand entity page (before Signal Timeline)

ORDERING LOGIC:
```
# Per entity: deduplicate by source_url (DISTINCT ON), then outer sort by:
priority_1: source_score DESC   (quality signal — YouTube or Reddit engagement formula)
priority_2: views DESC          (reach — YouTube views; NULL for Reddit)

# Only rows with ms.source_score IS NOT NULL returned (unscored items excluded from drivers)
```

VERIFICATION:
- Checked: /api/v1/entities/perfume/Creed%20Aventus — top_drivers=10, YouTube creators ranked
  by quality score. Top driver: "Fragrance Therapy" score=0.757 views=1828
- Checked: /api/v1/entities/perfume/Yves%20Saint%20Laurent%20Libre — top_drivers=10, top
  driver: "Купить Парфюм Недорого" score=0.678 views=27119
- Checked: /api/v1/entities/brand/brand-creed — top_drivers=10 (aggregated across Creed perfumes)
- Checked: /api/v1/entities/brand/brand-yves-saint-laurent — top_drivers=10
- Checked: /api/v1/entities/brand/brand-xerjoff---join-the-club — top_drivers=10 (Reddit drivers,
  no views — score derived from comments/upvotes formula)
- Frontend: Top Drivers block renders on perfume and brand pages when data present
- Version: 1.0.2

NOTES:
- Brand entity_market rows carry no direct entity_mentions — perfume entities carry those.
  Solution: `_get_top_drivers_for_brand` joins through `entity_market.brand_name` instead of UUID.
- Reddit sources have NULL views but non-null source_score — appear in drivers ordered by score,
  views column shows "—" in UI. This is correct behavior.
- Catalog-only entities (no entity_market row) never get top_drivers (returns empty list).
- title field reserved in DriverRow schema but always null for now — video title not stored in
  entity_mentions; source_url is the identifier. Future I5 may populate title from content text.

---

### I5 — Topic / Query Intelligence (COMPLETED — 2026-04-24)

Track:
- queries
- topics
- keywords

Result:
System knows WHY the trend exists.

STATUS: COMPLETE

DEPLOYMENT:
- Migration 022: `content_topics` + `entity_topic_links` tables — applied to production
- Extractor: `perfume_trend_sdk/analysis/topic_intelligence/extractor.py` — 40 deterministic regex-based TOPIC_RULES, no AI
- Extraction job: `perfume_trend_sdk/jobs/extract_entity_topics.py` — processes `canonical_content_items`, links topics to entities via `entity_mentions.source_url`
- API: `PerfumeEntityDetail` + `BrandEntityDetail` extended with `top_topics`, `top_queries`, `top_subreddits`
- Brand aggregation: `_get_brand_topics()` aggregates across brand portfolio via `entity_market.brand_name`
- Frontend: `WhyTrending` component — chip-based, color-coded by type (sky=topic, violet=query, orange=subreddit)
- Frontend: Added to perfume entity page (after Top Drivers) and brand entity page
- Fix: `RETURNING id` used for PostgreSQL compatibility (`lastrowid=0` for pg+SQLAlchemy text())

TOPIC TYPES:
- `query` — YouTube search query that surfaced the content (e.g. "creed aventus review")
- `subreddit` — Reddit community (e.g. "fragrance", "Colognes", "FemFragLab")
- `topic` — deterministic regex match from ~40 TOPIC_RULES vocabulary:
  - Usage: compliment getter, office scent, date night, signature scent, gym/sport, beach/vacation
  - Discovery: blind buy, gift idea, sample/decant, review, ranking/best of, comparison, dupe/alternative
  - Trends: trending/viral, new release, flanker, reformulation
  - Scent: vanilla, oud, fresh/citrus, floral, woody, musk, sweet/gourmand, spicy, smoky/leather, green/earthy
  - Market: niche fragrance, designer fragrance, affordable, luxury
  - Gender: men's fragrance, women's fragrance, unisex
  - Performance: longevity/projection
  - Season: summer, winter, fall/autumn, spring
  - Geographic: arab/oriental, french fragrance, italian fragrance

VERIFICATION:
- Checked: production PostgreSQL + /api/v1/entities/perfume/Yves%20Saint%20Laurent%20Libre (2026-04-24)
- content_topics: 2,983 rows (1,698 topic + 731 query + 554 subreddit)
- entity_topic_links: 26 rows
- YSL Libre: topics=['review', "women's fragrance", 'floral', 'vanilla', 'sample/decant', 'fresh/citrus', 'new release'], queries=['ysl libre perfume', 'ysl libre perfume review']
- MFK Baccarat Rouge 540: topics=['trending/viral'], queries=['baccarat rouge 540']
- Brand endpoint /api/v1/entities/brand/brand-creed: top_topics/top_queries/top_subreddits fields present
- WhyTrending block renders on entity pages when data is present

NOTES:
- 26 entity_topic_links due to entity_mentions join requiring source_url=canonical_content_items.id match; coverage grows automatically as pipeline accumulates more linked content
- Brand entities aggregate topics from portfolio perfumes (not direct brand entity_mentions)
- _safe() wrapping ensures graceful degradation if content_topics table is unavailable in SQLite dev
- RETURNING id required for PostgreSQL; SQLite uses lastrowid which is 0 for pg+SQLAlchemy text()

---

### I6 — Topic Coverage Expansion (COMPLETED — 2026-04-25)

Increase entity_topic_links coverage from ~1% to ≥70% of active entities.

STATUS: COMPLETE

ROOT CAUSE:
`entity_mentions.source_url` = full URL (`https://youtube.com/watch?v=VIDEO_ID`)
`canonical_content_items.id` = bare video ID (`PLfRPNG_ij0`)
Old join: `em.source_url = cci.id` — matched only 11 of 2,457 entity_mentions.

FIX:
New join: `cci.id = em.source_url OR cci.source_url = em.source_url`
Maps entity_mentions to canonical_content_items via full URL match.
mention_map key = `cci.id` (same as content_topics.content_item_id).

JOIN COVERAGE (production):
- Old match (em.source_url = cci.id): 11 rows
- New match (em.source_url = cci.source_url): 2,447 rows
- YouTube video ID extracted: 841 rows
- Reddit post ID extracted: 1,605 rows
- Total covered: 2,447 unique entity_mention rows

DEPLOYMENT:
- `extract_entity_topics.py`: new DISTINCT ON join via `OR cci.source_url = em.source_url`
- `--rebuild-links` flag: clears entity_topic_links, rebuilds from existing content_topics without re-extracting
- `WhyTrending` component: shows "Low signal" placeholder for entities with no data (not hidden)
- Pipeline integration: `--rebuild-links` added to `start_pipeline.sh` Step 4b and `start_pipeline_evening.sh` Step 3b
- `scripts/diagnose_topic_coverage.py`: coverage diagnostic script

RESULTS (before → after):
- entity_topic_links: 26 → 2,912
- entity coverage: 9 perfume entities → 177/182 perfume entities
- Coverage: 1.4% → 97.3%

EXAMPLES:
- Creed Aventus (was empty): topics=['review','luxury','woody','fresh/citrus',"men's fragrance",'dupe/alternative'], queries=['creed aventus perfume','creed aventus review'], subs=['colognes','fragrance']
- Yves Saint Laurent Libre: topics=['review',"women's fragrance",'floral','vanilla','new release'], queries=['ysl libre perfume','ysl libre perfume review']
- brand-creed: topics=['review','luxury','woody','fresh/citrus'], queries=['creed aventus perfume','creed aventus review'], subs=['colognes','fragrance']

ONGOING:
- Pipeline now runs extract_entity_topics --rebuild-links after every ingest cycle
- Coverage will grow as more content is ingested and linked

---

### I7 — Topic Quality Layer: Semantic Intelligence (COMPLETED — 2026-04-25)

Transform raw Topic/Query Intelligence (I5–I6) into high-quality semantic insights by ranking,
filtering generic topics, and classifying into three structured categories.

STATUS: COMPLETE

DEPLOYMENT:
- New module: `perfume_trend_sdk/analysis/topic_intelligence/semantic.py` — pure deterministic classifier
- `_get_entity_topics()` and `_get_brand_topics()` in `entities.py` extended to return 6-tuple
  (top_topics, top_queries, top_subreddits, differentiators, positioning, intents)
- `PerfumeEntityDetail` and `BrandEntityDetail` Pydantic models extended with `differentiators[]`, `positioning[]`, `intents[]`
- `frontend/src/lib/api/types.ts` extended with same 3 fields on both detail interfaces
- `WhyTrending.tsx` rewritten: 3 semantic sections (Differentiators / Positioning / Why People Search)
  + optional Communities row for subreddits
- Entity pages updated to pass new semantic props to `<WhyTrending />`

CLASSIFICATION:
- Scoring formula: `score = occ × (1.0 + avg_quality_score)`
- Differentiators (emerald chips): "dupe / alternative", "compliment getter", "longevity / projection",
  "reformulation", "affordable", "blind buy"
- Positioning (sky chips): niche/designer/luxury, vanilla/oud/floral/woody/musk/fresh/spicy/smoky/green,
  men's/women's/unisex, summer/winter/fall/spring, arab/french/italian, office/date night/signature/gym/beach
- Intent (violet chips): all raw search queries + "review", "ranking / best of", "comparison",
  "gift idea", "trending / viral", "new release", "flanker", "sample / decant", "blind buy"
- Stoplist (excluded from Diff/Pos, kept in Intent only): "review", "comparison", "trending / viral",
  "ranking / best of"
- Subreddits (orange chips): Communities section when top_subreddits present

VERIFICATION:
- No backfill required — transformation layer reads existing entity_topic_links
- API returns differentiators/positioning/intents on all perfume and brand entity endpoints
- UI sections collapse if empty; "Low signal" shown only if ALL sections empty
- Checked: Creed Aventus entity — top_queries map to intents, topic labels route to diff/pos correctly
- Non-destructive: existing top_topics/top_queries/top_subreddits fields preserved in API

NOTES:
- Subreddits are not classified into semantic sections — shown as Communities footer row
- Unmapped topic labels are silently skipped (not surfaced to UI)
- No AI. Pure frozenset membership checks — O(1) per topic row
- Brand entities use same classification via _get_brand_topics() → aggregate across portfolio

---

### I8 — Market Intelligence (COMPLETED — 2026-04-25)

Transform semantic profiles (I7) into actionable decision intelligence:
  - `narrative`: plain-language reason why an entity is trending (template-based, no AI)
  - `opportunities[]`: rule-based market flags (dupe_market, high_intent, gifting, …)
  - `competitors[]`: detected competing entities from comparison query analysis

This is NOT analytics. It is decision intelligence.

STATUS: COMPLETE

DEPLOYMENT:
- New module: `perfume_trend_sdk/analysis/topic_intelligence/market_intelligence.py`
  - `generate_market_intelligence()` — main entry point, pure deterministic function
  - `_build_opportunity_flags()` — 9 flag types evaluated from differentiators/intents
  - `_build_narrative()` — template-based sentence construction from semantic profile
  - `extract_vs_competitors()` — VS-pattern regex + orphan-query extraction
- `entities.py` updated:
  - `_find_competitor_names(db, entity_id, top_queries, canonical)` — ILIKE match against entity_market
  - `PerfumeEntityDetail` and `BrandEntityDetail` extended with `narrative`, `opportunities[]`, `competitors[]`
  - Both tracked perfume and brand paths call `generate_market_intelligence()` after I7 classification
- `frontend/src/lib/api/types.ts` extended with same 3 fields on both detail interfaces
- `frontend/src/components/entity/MarketInsight.tsx` created:
  - `OPPORTUNITY_LABELS` map: 9 flags → label + semantic color + tooltip description
  - `OpportunityBadge` with hover tooltip; `CompetitorChip` in rose color
  - Renders null when no data — no empty placeholder
- `MarketInsight` block added to perfume entity page (after WhyTrending)
- `MarketInsight` block added to brand entity page (after WhyTrending)

OPPORTUNITY FLAGS:
```
dupe_market          — "dupe / alternative" in differentiators
affordable_alt       — "affordable" in differentiators
high_intent          — ≥2 high-intent intent labels OR ≥1 intent label + ≥2 raw queries
competitive_comparison — "comparison" in intents
gifting              — "gift idea" in intents
viral_momentum       — "trending / viral" in intents
launch_window        — "new release" or "flanker" in intents
social_validation    — "compliment getter" in differentiators
performance_leader   — "longevity / projection" in differentiators
```

COMPETITOR EXTRACTION:
- VS pattern: "Creed Aventus vs Baccarat Rouge 540" → "Baccarat Rouge 540"
- Orphan queries: query not mentioning current entity → candidate competitor
- ILIKE validation against entity_market.canonical_name (case-insensitive substring)
- Up to 5 competitors returned, deduped, order-preserving

VERIFICATION:
- Checked: `/api/v1/entities/perfume/Creed%20Aventus` — narrative, opportunities, competitors present
- Checked: frontend perfume and brand entity pages render MarketInsight block when data present

NOTES:
- No AI. Template-based narrative + deterministic rule evaluation
- Brand entities use same opportunity/narrative generation (no competitor detection)
- MarketInsight block returns null when all fields empty — no wasted space
- Competitors list validated against DB — raw VS-pattern strings not exposed directly

---

## Phase Prefix Registry

| Prefix | Domain | Description |
|--------|--------|-------------|
| D | Data Pipeline | Ingestion, aggregation, signal detection, scheduling |
| E | Entity / UI | Entity hygiene, linking, brand surface, catalog |
| U | UI Layer | Frontend pages, screener, dashboard, navigation |
| I | Intelligence Layer | Source weighting, trend drivers, prediction, signal quality |
| O | Operations | Deployment, infrastructure, runtime, backup |
| R | Recovery / Migration | DB migrations, schema fixes, data recovery |

**Rule:** Every new phase must declare its prefix based on this registry. If the work spans multiple domains, pick the primary domain. Do not create new prefixes without adding them here first.

**Next available:**
- I2 — next Intelligence Layer phase (Signal Weighting)
- E4 — next Entity/UI phase
- U3 — next UI Layer phase

---

## Phase Completion Format (MANDATORY)

Every completed phase MUST end with the following block. Do not mark a phase complete without it.

```
STATUS: COMPLETE

DEPLOYMENT:
- Status: SUCCESS
- Active: YES
- Time: <timestamp>

VERIFICATION:
- Checked: <endpoint / UI page>
- Result: <what is working>

NOTES:
- Any limitations or follow-ups
```

**Rules:**
- `Status: SUCCESS` means Railway deployment completed without errors
- `Active: YES` means the feature is live and serving real traffic
- `Checked` must name a specific URL, endpoint, or UI page — not "tested locally"
- `Result` must describe what was observed, not what was expected
- If deployment failed or is pending, use `Status: FAILED` or `Status: PENDING` — never write SUCCESS without verifying
- If there are no limitations, write `None`

---

## Frontend Production Verification Rule

Healthcheck success is NOT sufficient production proof.

A frontend task is BLOCKED if the shell loads but real dashboard/screener data fetch fails.

**Production verification requires ALL of the following:**
- Dashboard loads real data (entity rows visible, not empty/error state)
- Screener loads real data (rows visible, not empty/error state)
- "API down" indicator disappears from StatusBar
- No "TypeError: Failed to fetch" or "Failed to load" errors in browser

`/api/health → {"ok":true}` and `/ → 200` do NOT prove the product works.

**Common cause**: `NEXT_PUBLIC_API_BASE_URL` not embedded at build time → browser uses `http://localhost:8000` fallback → mixed-content failure from HTTPS page. Fix: set in `next.config.ts` env block as a hardcoded build-time fallback.

---

## Dashboard Interaction Rules (CRITICAL)

### Principle
Dashboard is not a static table. It is a navigation layer into the system.

Every entity row must be an entry point into deeper analysis.

---

### Row Click Behavior

All rows in Dashboard (Top Movers, Signals, etc.) MUST be clickable.

Clicking a row must navigate to the correct entity page:

- perfume → /entities/perfume/{id}
- brand → /entities/brand/{id}

---

### Clickable Elements

The following elements must trigger navigation:

- entire row
- entity name
- ticker

Do NOT require precise clicking — interaction must be forgiving.

---

### Hover State

Rows must have a hover state:
- subtle background highlight
- cursor: pointer

This signals interactivity.

---

### Entity Type Awareness

Navigation MUST respect entity_type:

- If entity_type == "brand" → route to brand page
- If entity_type == "perfume" → route to perfume page

Hardcoding routes is prohibited.

---

### Event Handling

Future interactive elements (e.g. watchlist icon, bookmark, actions) must:

- use stopPropagation()
- NOT break row navigation

---

### Anti-Pattern (Forbidden)

❌ Static tables with no navigation  
❌ Clickable only on small elements  
❌ Client confusion about where to click  
❌ Rows that display data but do not lead anywhere  

---

### Completion Criteria

Feature is considered COMPLETE only if:

- Clicking any row opens correct entity page
- Works for both brand and perfume
- Verified in production UI (not assumed)

---

## Screener Search Rules

Search in the screener must be **server-side** for all modes. Client-side filtering of a loaded page is not sufficient.

**Mode-specific search scope:**

| Mode | Search endpoint | What is searched |
|------|----------------|-----------------|
| Active Today | `GET /api/v1/screener?q=` | All ~200–300 active entities (not just the current page) |
| All Perfumes | `GET /api/v1/catalog/perfumes?q=` | Full 56k resolver catalog |
| All Brands | `GET /api/v1/catalog/brands?q=` | Full 1,600+ resolver catalog |

**Rules:**
- `q` param must be sent to the backend, not used to filter `rows` in the browser
- Active Today: search is a substring match on `canonical_name`, `ticker`, and `brand_name`
- Catalog modes: search is already server-side via catalog API
- Debounce: 300ms before sending — avoids excessive API calls during typing
- Empty state on Active Today + non-empty search: show clear message + "Search full catalog" button
- "Search full catalog" button must preserve the current search term and switch to catalog mode

**Anti-pattern (forbidden):**
```typescript
// WRONG — only searches the 50 loaded rows
const filteredRows = useMemo(() => rows.filter(r => r.canonical_name.includes(search)), [rows, search]);
```

**Correct pattern:**
```typescript
// Debounce → send as q param → backend filters all entities → receive correct total + page
queryFn: () => fetchScreener({ ...params, q: debouncedSearch || undefined })
```

---

## 🔒 Core Constraint

This system is a distributed multi-service architecture.

→ All shared state MUST be stored in Postgres.

Local filesystem is NOT a valid persistence layer.

---

This project must optimize for correctness, recomputability, and low API cost over maximum automation.

## Perfume Trend Intelligence SDK — architecture guardrails

### Core principles
- Prioritize low-cost, deterministic pipelines over frequent LLM calls.
- Do not use OpenAI/Gemini for every mention or every text item.
- LLMs are optional arbiters for ambiguous entity resolution, not the default parser for the whole dataset.
- Always prefer: exact match -> fuzzy match -> optional AI validation.
- Preserve raw inputs and resolution metadata so history can be recomputed later.

### Environment and secrets
- API keys must be loaded from environment variables first.
- Priority for secrets: `.env` / environment variables -> config yaml fallback.
- Never hardcode API keys in source files.
- `YOUTUBE_API_KEY` must come from environment first.
- `OPENAI_API_KEY` must come from environment first.

### Budget safety rules
- AI validation must be behind a feature flag.
- Default config should keep AI validation off unless explicitly enabled.
- Limit AI calls per run with a hard cap, for example:
  - `ai_enabled: false`
  - `ai_max_items_per_run: 5`
- Before sending text to an LLM:
  - deduplicate
  - remove short/noisy texts
  - prioritize by source weight / influence / freshness
- Cache AI results by content hash to avoid repeated API spend.
- Prefer batch analysis over one-request-per-item when possible.

### Resolver architecture
Entity resolution must use the following order:
1. Pre-normalization
2. Exact alias match
3. Fuzzy match
4. Optional AI arbitration
5. Unresolved queue

### Pre-normalization rules
Before matching entities:
- lowercase text
- trim whitespace
- normalize unicode
- collapse repeated spaces
- strip punctuation where safe
- normalize common perfume abbreviations
- separate concentration terms from perfume name:
  - EDP
  - Body Spray (Body Mist)
  - EDT
  - Extrait
  - Parfum
- "Body Spray" and "Body Mist" are the same canonical product-form entity for matching and analytics:
  - map both to one canonical value: `body_spray`
  - remove both from perfume-name candidate text before resolver matching
  - return `body_spray` in the metadata concentration field
  - do not treat them as separate analytics entities

Example:
- `Baccarat Rouge 540 Extrait` -> base name: `baccarat rouge 540`, concentration: `extrait`
- `BR540` -> normalized alias candidate for `Baccarat Rouge 540`

## Knowledge Base Layer (Fragrance Master Data)

The system must maintain a **static fragrance knowledge base** as the primary source of truth for entity resolution.

### Source
- Fragrance Database (Kaggle / GitHub datasets)
- Loaded as initial seed dataset

### Purpose
- Provide canonical perfume and brand names
- Enable high-accuracy entity resolution (target: 90–95% coverage)
- Reduce dependency on AI for entity matching
- Standardize aliases across all pipelines

### Data Model Extension

#### fragrance_master (seed table)
- `fragrance_id`
- `brand_name`
- `perfume_name`
- `canonical_name`
- `normalized_name`
- `release_year` (optional)
- `gender` (optional)
- `source` (e.g. kaggle)
- `created_at`

### Rules
- This dataset is **read-mostly**
- Must be loaded before any extraction/resolution pipeline runs
- Must not be overwritten by dynamic pipeline data
- Can be extended but not replaced by runtime signals

---

## Alias Generation System

Aliases must be generated automatically from fragrance_master to support high recall in entity resolution.

### Alias Sources
For each perfume:
- Full canonical name
- Brand + perfume
- Short perfume name
- Common abbreviations (when possible)

### Example
Canonical: `parfums de marly delina`

Generated aliases:
- `delina`
- `pdm delina`
- `delina perfume`
- `parfums marly delina`

### Rules
- All aliases must be normalized (lowercase, cleaned)
- Aliases must be stored in `aliases` table with `match_type = exact`, `confidence = 1.0`
- Auto-generated aliases must be distinguishable from manual, fuzzy, and AI-confirmed aliases

---

## Discovery Layer (Emerging Entities)

The system must detect and track **new or unknown perfumes** not present in fragrance_master.

### When triggered
If resolver fails exact match, fuzzy match, and AI validation → entity is not discarded.

### Storage

#### fragrance_candidates
- `id`
- `raw_name`
- `normalized_name`
- `source`
- `first_seen_at`
- `mention_count`
- `status` (`unverified` | `promoted` | `rejected`)

### Promotion Logic
- Consistent mentions over time + increasing engagement → can be promoted into `fragrance_master`

### Rejection Logic
- Low frequency or noise/spam patterns

### Rules
- Never drop unknown entities
- Discovery is required for identifying early trends

---

## Phase 3 — Growth Engine (Self-Learning System)

The system must evolve from a static knowledge base into a **self-improving intelligence engine**.

### Goal

Continuously increase entity resolution coverage by:
- discovering new perfumes and brands from real data
- validating them
- promoting them into the knowledge base

---

## Growth Loop (MANDATORY)

The system must implement the following loop:

```
Ingest → Resolve → Unresolved Queue → Candidate Extraction → Validation → Promotion → Knowledge Base
```

### Step 1 — Ingest
Fetch raw content from sources (YouTube, TikTok, Instagram).

### Step 2 — Resolve
Run `PerfumeResolver` against `fragrance_master` aliases.
- Exact match → resolved → stored in `resolved_signals`
- No match → goes to unresolved queue

### Step 3 — Unresolved Queue
Store all unresolved mentions in `fragrance_candidates` with:
- `raw_name` — original candidate text
- `normalized_name` — cleaned version
- `source` — where it came from
- `first_seen_at` — timestamp
- `mention_count` — incremented on repeat
- `status = unverified`

### Step 4 — Candidate Validation
Periodically review top candidates by `mention_count`:
- **Rule-based check**: does it look like a real perfume name?
- **Optional AI check**: confirm via LLM if ambiguous
- **Manual review**: human approves high-value candidates

### Step 5 — Promotion
Approved candidates are written into `fragrance_master` + `aliases`.
Status updated to `promoted`.

### Step 6 — Re-resolution
Historical unresolved mentions can be re-resolved after promotion.
This is why raw text must always be preserved.

---

## Growth Loop — Full Cycle

```
Unresolved Mentions → Candidate Aggregation → Validation → Seed Update → Resolver Improvement
```

This loop is the primary driver of system intelligence growth.

---

## Step 1 — Candidate Aggregation

Unresolved mentions must be aggregated into structured candidates.

### Source
- unresolved_mentions (from Resolver)
- fragrance_candidates table

### Aggregation rules
- group by normalized_name
- track:
  - mention_count
  - distinct_sources_count
  - first_seen_at
  - last_seen_at

### Output file (required)

`outputs/top_unresolved_candidates.json`

### Example structure
```json
[
  {
    "text": "lattafa khamrah",
    "count": 5,
    "sources": 3,
    "first_seen_at": "...",
    "last_seen_at": "..."
  }
]
```

---

## Step 2 — Candidate Filtering

Not all candidates should be promoted.

### Promotion thresholds (initial defaults)
- `mention_count >= 2`
- OR `distinct_sources_count >= 2`

### Rejection rules
- extremely short tokens (<= 3 chars)
- generic words (e.g. "perfume", "best scent")
- spam patterns

Filtering must be deterministic and configurable.

---

## Step 3 — Candidate Structuring

Candidates must be converted into structured entities.

### Basic parsing
- split into brand + perfume when possible
- fallback: store as unresolved structured entity

### Example
- `"lattafa khamrah"` → brand: Lattafa, perfume: Khamrah
- `"arabians tonka"` → brand unknown → perfume candidate

### Rules
- Do NOT assume perfect parsing
- Store raw + parsed versions

---

## Step 4 — Promotion Pipeline

New entities must NOT directly enter `fragrance_master`.

### Required step: Promotion Workflow

New workflow: `workflows/promote_candidates.py`

### Promotion logic
- read filtered candidates
- convert into seed rows
- append to: `perfume_trend_sdk/data/fragrance_master/seed_master.csv`

### Required fields
- `brand_name`
- `perfume_name`
- `source = "discovery"`

---

## Step 5 — Knowledge Base Reload

After promotion:

```
load_fragrance_master → rebuild aliases → resolver updated
```

This step must be explicit and logged.

---

## Step 6 — Resolver Feedback Loop

After reload:
- rerun ingestion pipeline
- measure:
  - resolved rate increase
  - unresolved reduction

### Required metrics
- `resolution_rate`
- `unresolved_rate`
- `new_entities_added`

---

## Auto-Learning Modes

| Mode | Description |
|------|-------------|
| Mode 1 — Manual (default, safe) | human reviews candidates, approves before promotion |
| Mode 2 — Semi-Automatic (recommended) | auto-promote high-confidence candidates, log all changes |
| Mode 3 — Fully Automatic (future) | promote based on statistical thresholds only |

---

## Discovery Layer Upgrade (REQUIRED)

Extend `fragrance_candidates` with:
- `distinct_sources_count`
- `confidence_score`
- `promotion_status` (`pending` | `approved` | `rejected`)
- `last_promoted_at`

---

## Alias Expansion from Discovery

When a new entity is promoted:
- generate aliases immediately
- mark:
  - `match_type = discovery_generated`
  - `confidence = 0.7–0.9`

---

## System-Level Requirement

The system must improve over time WITHOUT increasing AI usage.

Priority order:
1. Knowledge base expansion
2. Alias coverage increase
3. Fuzzy matching tuning
4. AI usage (last resort)

---

## Success Criteria for Phase 3

- Resolver coverage improves run-over-run
- Unresolved mentions decrease over time
- Niche / TikTok / emerging brands begin to resolve correctly
- New entities appear in trend reports within 1–2 pipeline cycles

---

## Critical Constraint

The system must NEVER:
- overwrite canonical entities without explicit promotion
- create entities directly inside resolver
- mix runtime signals with knowledge base data

---

## Future Extensions (Phase 3.5+)

- Fragrantica integration (new releases, reviews)
- TikTok caption ingestion (high-priority signal source)
- Reddit ingestion (early trend detection)
- AI-assisted entity validation (only for high-value candidates)

---

## Phase 4A — Fragrantica Integration (Discovery + Enrichment Source)

The system must integrate Fragrantica as a **secondary intelligence source** for:

1. Enrichment of known perfume entities
2. Discovery of new perfumes and brands

Fragrantica is NOT a canonical source of truth.

---

## Role of Fragrantica

Fragrantica operates as:

- Discovery Layer Extension
- Metadata Enrichment Source

It must NOT:
- override canonical entities
- create entities directly inside resolver
- redefine brand or perfume naming in fragrance_master

---

## Integration Modes

### Mode 1 — Enrichment (Primary)

Used for already resolved perfumes.

#### Input
- `fragrance_id`
- `canonical_name`

#### Output
Additional metadata:
- accords
- top / middle / base notes
- rating_value
- rating_count
- release_year (optional)
- perfumer (optional)
- gender (optional)
- similar_perfumes (optional)

#### Rules
- Enrichment must NOT overwrite canonical_name
- Enrichment must be additive only
- Missing fields must not break pipeline

---

### Mode 2 — Discovery

Used to identify new perfumes not present in fragrance_master.

#### Sources
- Fragrantica perfume pages
- discovery lists (e.g. new / popular perfumes)

#### Output
- unresolved candidates must be routed to:
  - `fragrance_candidates`
  - Phase 3 Growth Loop

---

## Fragrantica Connector Rules

### Connector responsibilities
- fetch raw HTML only
- respect retry/backoff rules
- configurable user-agent
- configurable timeout

### Strict rule
Connector MUST NOT:
- parse business logic
- perform extraction or analytics

---

## Raw Storage Requirement

All fetched pages must be stored BEFORE parsing.

Required fields:
- `source_name = "fragrantica"`
- `source_url`
- `fetched_at`
- `raw_html`

This ensures:
- replayability
- parser improvements without re-fetch

---

## Parser Requirements

Parser must be:
- deterministic
- tolerant to missing fields
- independent from pipeline logic

### Required fields (v1)
- brand_name
- perfume_name
- accords
- notes_top
- notes_middle
- notes_base
- rating_value
- rating_count

### Optional fields
- release_year
- perfumer
- gender
- similar_perfumes

---

## Normalization Rules

Parsed Fragrantica data must be mapped into a structured internal record: `FragranticaPerfumeRecord`

### Rules
- normalization must preserve source_url
- normalization must NOT resolve entities
- normalization must NOT mutate canonical data

---

## Enrichment Pipeline

New workflow: `workflows/enrich_from_fragrantica.py`

### Flow
Resolved perfumes → Fragrantica fetch → parse → normalize → enrich entity metadata

### Rules
- enrichment is applied AFTER resolution
- enrichment must not block pipeline if fails
- enrichment must be idempotent

---

## Discovery Pipeline

New workflow: `workflows/ingest_fragrantica_discovery.py`

### Flow
Fragrantica pages → parse → normalize → unresolved → fragrance_candidates

### Rules
- discovered perfumes must go through Phase 3 Growth Engine
- direct insertion into fragrance_master is forbidden

---

## Alias Expansion from Fragrantica

When Fragrantica provides alternative names or similar perfumes, these may be used to:
- generate alias candidates
- improve resolver recall

### Rules
- store as alias candidates
- do NOT auto-promote to exact aliases without validation
- mark:
  - `match_type = external_source`
  - `confidence < 1.0`

---

## Data Separation Rules

Fragrantica data must be stored separately from canonical data.

| Layer | Tables |
|-------|--------|
| Canonical | `fragrance_master`, `aliases` |
| External Source | `fragrantica_records`, enrichment metadata |

**Rule:** External data must NEVER redefine canonical identity directly.

---

## Failure Handling

| Stage | Behavior |
|-------|----------|
| fetch failure | retry |
| parse failure | log + skip |
| enrichment failure | must not stop pipeline |

---

## Logging Requirements

Each stage must log:
- `fetch_count`
- `parse_success` / `parse_fail`
- `enriched_entities_count`
- `discovered_entities_count`

---

## Success Criteria
- Known perfumes enriched with accords and notes
- Reports include note-level intelligence
- Discovery pipeline produces new candidates
- Resolver coverage improves via Phase 3 loop

---

## Critical Constraint

Fragrantica must enhance intelligence without increasing system fragility.

---

## Future Extensions (Phase 4A+)
- review sentiment aggregation
- rating trend tracking
- note popularity modeling
- similarity graph between perfumes

---

## Phase 4B — Reddit Ingestion v1 (Community Intelligence Source)

The system adds Reddit as a **community intelligence source** focused on authentic consumer discussion, recommendation language, objections, and early niche discovery.

Reddit is valuable because it captures:
- real user opinions
- comparison language
- buyer objections
- niche and dupe discovery
- recommendation phrasing not always present in creator-led content

Reddit must be treated as a **social/community signal source**, not as a canonical source of truth.

**Reddit v1 uses public JSON endpoints — no OAuth, no API credentials required.**
Data is fetched from subreddit feeds (e.g. `/r/fragrance/new.json`).
Ingestion is read-only public data access. Reddit data is treated as a **real data source** equivalent to YouTube in the serving layer.

---

### Role of Reddit

Reddit operates as:

- Community Intelligence Source
- Discovery Layer Input
- Insight Layer Support

It should help answer:
- what real users like or dislike
- which perfumes are compared against each other
- which notes are being praised or criticized
- which niche or clone fragrances are rising in conversation

---

## Reddit v1 Implementation Notes

- **Access method:** public JSON endpoints (`/r/<subreddit>/new.json`, `/.json` suffix on any listing URL)
- **No credentials required:** no Reddit API key, no OAuth, no app registration for v1
- **Subreddit watchlist:** config-driven list of subreddits to poll
- **Rate-limited polite fetching:** respect Reddit's public rate limits (1 req/sec, `User-Agent` header required)
- **Raw payload storage required** before normalization — same architecture rule as all sources
- **Normalization:** into `CanonicalContentItem` via `normalize_reddit_item()` in `SocialContentNormalizer`
- **`source_platform = "reddit"`** — Reddit is a named first-class platform in the serving layer

Run order:
```bash
python3 scripts/ingest_reddit.py --lookback-days 3
python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date YYYY-MM-DD
```

---

## Reddit API (Future Integration — TODO)

> **TODO / FUTURE WORK — do not implement yet.**

The current v1 Reddit connector uses public JSON endpoints.
A future version may migrate to the **official Reddit API** when higher reliability or richer data is needed.

### Potential benefits of official Reddit API

- Higher rate limits (authenticated requests get significantly more headroom)
- Richer metadata: full comment trees, user karma, subreddit subscriber counts, crosspost data
- Reliability guarantees (no breakage risk from HTML/JSON format changes)
- Access to private or age-gated subreddits if approved

### Requirements for official Reddit API

- Reddit developer application registration
- OAuth 2.0 app credentials (`client_id`, `client_secret`)
- Compliance with Reddit API terms of service (usage limits, attribution)
- Possible partnership / review process for data products

### Migration path (when needed)

1. Replace `client.py` fetch logic with `praw` or direct OAuth requests
2. Add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` to `.env`
3. Keep connector interface (`connector.py`, `parser.py`) unchanged — only the client layer changes
4. No changes to normalizer, resolver, or pipeline contracts

This migration is not required for v1. Public JSON ingestion is sufficient for initial serving.

---

### Scope for v1

Reddit v1 is intentionally limited.

**In scope:**
- subreddit watchlist ingestion via public JSON endpoints
- post title ingestion
- selftext/body ingestion
- basic engagement metadata (score, num_comments)
- extraction/resolution through existing pipeline
- unresolved routing into discovery flow

**Out of scope for v1:**
- official Reddit API / OAuth authentication
- full-platform Reddit scan
- full comment ingestion
- sentiment AI analysis by default
- quote mining from large comment trees
- real-time monitoring

---

### Source Targets (Initial)

Recommended initial subreddit watchlist:
- `r/fragrance`
- `r/FemFragLab`
- `r/Colognes`
- `r/Perfumes` (optional)

The watchlist must remain config-driven.

---

### Reddit Connector Rules

Create source package:

```text
connectors/reddit_watchlist/
  connector.py
  client.py
  parser.py
  config.py
```

**Connector responsibilities:**
- fetch raw Reddit post payloads only
- support subreddit-based watchlist
- support bounded fetch windows / limits
- configurable retry/backoff and timeout
- no extraction, analytics, scoring, or entity resolution inside connector

**Strict rule:** Connector MUST NOT compute trend scores, resolve perfumes, classify notes, or enrich entities.

---

### Raw Storage Requirement

All Reddit raw payloads must be stored before normalization.

Required fields to preserve:
- `source_name = "reddit"`
- `subreddit`
- `post_id`
- `permalink` / `url`
- `fetched_at`
- raw payload

This guarantees replayability, parser upgrades without re-fetch, and traceability.

---

### Required Reddit Fields (v1)

The parser must extract, when available:

- `external_content_id`
- `subreddit`
- `source_url`
- `source_account_handle` (author if available)
- `title`
- `selftext`
- `published_at`
- `score`
- `num_comments`
- `link_flair_text` (optional)

**Rules:**
- parser must be deterministic
- parser must tolerate missing body/selftext
- parser must preserve raw metadata where useful

---

### Normalization Rules

Reddit content must reuse the canonical social content path where possible.

Normalized Reddit item should map into:
- `source_platform = "reddit"`
- `content_type = "post"`
- `title`
- `text_content = title + " " + selftext`
- `engagement`: `likes` mapped from Reddit `score`, `comments` mapped from `num_comments`

**Rules:**
- normalization must preserve subreddit in `media_metadata`
- normalization must preserve `source_url`
- normalization must not perform entity resolution

---

### Reddit Workflow Integration

Reddit must flow through the same core path as existing sources:

```
fetch → raw storage → normalize → extract → resolve → store
```

**Rules:**
- existing extractors should operate on Reddit normalized text
- unresolved mentions must route into Discovery / Growth Engine
- Reddit must not require a separate analytics model for v1

---

### Discovery Value from Reddit

Reddit is especially valuable for:
- niche perfume discovery
- clone / dupe discovery
- comparison language
- consumer objections
- recommendation phrases

Examples of useful patterns:
- "better than baccarat rouge"
- "smells expensive"
- "too synthetic"
- "long lasting vanilla"
- "blind buy worthy"

These patterns must remain preserved in raw and normalized text for future insight work.

---

### Source Intelligence Rules for Reddit

Source intelligence should support Reddit items where possible.

Attach or derive:
- `source_type = "community"`
- influence / weight from engagement signals
- subreddit metadata for context

**Rules:**
- Reddit influence must not be treated the same as influencer reach
- `score` and discussion depth should matter more than follower logic

---

### Logging Requirements

Structured logs must include:
- `fetch_started`, `fetch_succeeded`, `fetch_failed`
- `normalized_count`, `extracted_count`, `resolved_count`, `unresolved_count`
- `subreddit`

---

### Tests for Reddit v1

Required:
- raw Reddit post fixture
- parser unit test
- normalization integration test
- end-to-end ingestion test for Reddit source

---

### Success Criteria for Reddit v1

- subreddit posts ingest successfully
- normalized Reddit records are created
- perfume/note mentions are extracted from titles and selftext
- resolved entities flow into analytics
- unresolved entities flow into discovery
- Reddit becomes available as an input to client-facing reports

---

## Phase 4C — Multi-Source Client Report v1

The system must produce a richer client-facing report that combines TikTok, YouTube, Reddit, and Notes / accords intelligence.

The goal is to move from source-specific outputs to a **cross-source market narrative**.

---

### Purpose of Multi-Source Report

The report should answer:
- which perfumes are trending
- which notes are rising or declining
- which platforms are driving the trend
- whether the signal is creator-driven, community-driven, or mixed
- what this means commercially

This report is intended for: perfume brands, retail buyers, content strategists, internal market research.

---

### Required Sections (v1)

**1. Executive Summary**
High-level market summary for the reporting window.

**2. Top Trending Perfumes**
Cross-source ranking with trend direction.

**3. Top Notes This Period**
- note, score, direction, brief drivers if available

**4. Source Breakdown**
Relative contribution from TikTok, YouTube, Reddit.

**5. Community vs Creator Signal**
Differentiate: creator-led hype, community-led validation, mixed signals.

**6. Emerging Entities**
Unresolved/promoted candidates that may become important.

**7. Opportunity / Risk Summary**
Commercial interpretation: launch opportunities, oversaturation risks, declining profiles.

---

### Multi-Source Aggregation Rules

The report must not simply concatenate source outputs — it must aggregate signals across sources by canonical entity.

**Rules:**
- perfume-level aggregation must use resolved canonical entity IDs
- note-level aggregation must combine extracted note mentions with enrichment notes
- source attribution must remain visible
- report should distinguish: high-volume signal, high-engagement signal, high-credibility/community signal

---

### Report Output Formats

Required output formats:
- **Markdown** — source-of-truth report format
- **PDF** — client-facing presentation format
- **CSV** — analyst workflow export

---

### Report Design Principle

The report must be useful to a client without requiring access to the raw system.

This means: concise executive narrative, visible trend direction, source-aware interpretation, commercial implications.

---

### Success Criteria for Multi-Source Report

- one report combines TikTok + YouTube + Reddit + Notes
- trend direction is visible
- source contribution is visible
- note momentum is visible
- report reads like market intelligence, not raw logs

---

## Infrastructure Decision Gate — PostgreSQL + docker-compose

After Reddit v1 and the multi-source client report are complete, the project must explicitly evaluate whether it should move beyond the current local + lightweight setup.

**This is a decision gate, not an automatic migration.**

---

### Decision Criteria

Move toward PostgreSQL and optionally docker-compose if at least several of these conditions are true:

**PostgreSQL criteria:**
- multiple scheduled jobs run regularly
- concurrent reads/writes begin to matter
- history volume grows significantly
- analyst UI or client UI needs stable query performance
- SQLite becomes operationally fragile

**docker-compose criteria:**
- local and VPS environments need reproducible parity
- project now includes multiple services
- PostgreSQL is introduced
- report/UI/API stack needs one-command startup
- environment setup is becoming error-prone

**Rules:**
- PostgreSQL is not mandatory before it is operationally needed
- docker-compose is not mandatory before multi-service complexity exists
- avoid premature infrastructure complexity
- infrastructure changes must follow product and operational needs, not precede them

---

### Preferred Transition Order

1. Complete Reddit v1 locally
2. Generate multi-source client report
3. Review operational pain points
4. Decide on PostgreSQL
5. Decide on docker-compose
6. Then prepare VPS production contour accordingly

---

### Evaluation Output

When this decision gate is reached, the system/project should produce a brief architecture review covering:
- current bottlenecks
- current storage limitations
- current deployment pain points
- recommendation: stay on SQLite + venv / move to PostgreSQL only / move to PostgreSQL + docker-compose

---

## Resolver Extension — Knowledge Base Integration

Resolver must prioritize fragrance_master before any dynamic logic.

### Resolution Order (UPDATED)
1. Pre-normalization
2. Exact alias match (from fragrance_master)
3. Fuzzy match (against fragrance_master)
4. Optional AI arbitration
5. Unresolved → Discovery Layer

### Rules
- Resolver must NOT create new canonical entities directly
- All new entities must go through Discovery Layer
- fragrance_master remains the only source of canonical truth

---

## Signal Attribution Rule

All signals (mentions, engagement, trends) must be attached to resolved canonical entities.

### Rules
- Do NOT score raw text mentions directly
- All analytics must operate on `fragrance_id` and `brand_id`

### Example
Input: `"best delina perfume 2025"` → fragrance_id → Parfums de Marly Delina

### Impact
- Prevents duplication
- Ensures accurate aggregation
- Enables reliable trend scoring

---

## Static vs Dynamic Data Separation

The system must strictly separate:

### Static Layer
- `fragrance_master`
- `aliases`

### Dynamic Layer
- `mentions`
- `signals`
- `trends`
- engagement data

### Rules
- Static data must not be mutated by runtime signals
- Dynamic signals must not redefine canonical entities
- Updates to static layer must be explicit and controlled

---

### Canonical data model
The project should maintain canonical entity tables:
- `brands`
- `perfumes`
- `aliases`

Recommended minimum fields:

#### brands
- `id`
- `canonical_name`
- `normalized_name`

#### perfumes
- `id`
- `brand_id`
- `canonical_name`
- `normalized_name`
- `default_concentration` (optional)

#### aliases
- `id`
- `alias_text`
- `normalized_alias_text`
- `entity_type` (`brand`, `perfume`)
- `entity_id`
- `match_type` (`manual`, `exact`, `fuzzy`, `ai_confirmed`)
- `confidence`
- `created_at`
- `updated_at`

### Mention and resolution storage
Never store only the final canonical ID.
Each resolved mention must preserve:
- raw text
- normalized text
- extracted candidate
- resolved entity id
- resolved entity type
- resolution method
- resolution confidence
- source
- timestamp
- weight / score if available

This is required so the system can re-resolve history later if matching logic improves.

### Unknown / unresolved handling
If no reliable match is found:
- do not discard the mention
- store it in an unresolved queue for later review

Suggested unresolved fields:
- `id`
- `raw_text`
- `normalized_text`
- `candidate_text`
- `source`
- `mention_id`
- `reason`
- `created_at`

### Fuzzy matching policy
- Use RapidFuzz for fuzzy matching.
- Do not run fuzzy search blindly across everything if candidate narrowing is available.
- Initial thresholds:
  - `>= 92`: auto-accept
  - `80-91`: review or optional AI validation
  - `< 80`: unresolved

Thresholds can be tuned later using real data.

### LLM usage policy
Use LLMs only when:
- exact match failed
- fuzzy score is in the ambiguous middle range
- the mention is high-value enough to justify cost
- the alias is not already known

LLM outputs must be structured JSON when used for validation.

Example shape:
```json
{
  "is_match": true,
  "canonical_name": "Baccarat Rouge 540",
  "entity_type": "perfume",
  "confidence": 0.88,
  "reason": "BR540 is a common shorthand for Baccarat Rouge 540"
}
```

---

## Project Identity

**Working title:** Perfume Trend Intelligence SDK (PTI SDK)
**Internal aliases:** PTI SDK, Perfume Signals Engine, Fragrance Trend OS

**Mission:** Build a modular platform for collecting, normalizing, analyzing, and packaging perfume trend signals from the US market (social platforms, retail sources, commercial data) — reusable across media, app, B2B analytics, affiliate models, and future data APIs.

---

## Technology Stack

| Concern | Choice |
|---------|--------|
| Language | Python 3.11+ |
| Data validation | Pydantic v2 |
| HTTP client | requests / httpx |
| Browser automation | Playwright (when needed) |
| Storage (dev) | SQLite with PostgreSQL-ready abstractions |
| File formats | JSONL, CSV, Markdown |
| Scheduling | cron / GitHub Actions / lightweight task runner |
| Testing | pytest |
| Logging | Structured JSON logs |

---

## AI Layer Rules (NEVER VIOLATE)

- AI extractors must be model-agnostic — logic lives in engine, not pipeline
- All AI engines must return the same unified output schema
- AI is an optional layer — pipeline must work without it
- Rule-based extractor remains the fallback
- Always route through `get_extractor(provider)` — never instantiate engines directly in pipeline
- Source intelligence is a first-class signal — not metadata decoration

---

## Architecture Principles (NEVER VIOLATE)

1. **Interfaces first, then implementation** — define contracts before writing logic
2. **No source dictates the data model** — connectors adapt to canonical schema, not the other way around
3. **No analytics inside connectors** — connectors return raw data only
4. **Each layer stores its own result separately** — raw ≠ normalized ≠ signals ≠ enriched
5. **Every block must have a clear replacement point** — weak coupling everywhere
6. **Historical data must be reprocessable** — never overwrite raw with interpreted data
7. **Loose coupling** — connector knows nothing about scoring; scoring doesn't depend on collection method

---

## Architecture Layers

| Layer | Name | Responsibility |
|-------|------|----------------|
| 1 | Core | Config loading, module registry, pipeline routing, error handling, logging, versioning |
| 2 | Connectors | Fetch raw data from external sources, maintain cursors, return raw payload |
| 3 | Normalization | Convert raw source into canonical CanonicalContentItem |
| 4 | Extraction | Extract perfume/brand/note/price/retailer mentions, classify signal type |
| 5 | Resolution | Deduplicate entities, build alias mapping, identity layer |
| 6 | Enrichment | Add official notes, prices, retailer list, discount signals |
| 7 | Scoring & Analytics | Compute trend score, creator influence, note momentum, rising perfumes |
| 8 | Output / Delivery | Publish to CSV, JSON, Google Sheets, markdown report, API |
| 9 | SDK Layer | Module interfaces, developer docs, config templates, test fixtures |

---

## Project Structure

```
perfume_trend_sdk/
  pyproject.toml
  README.md
  .env.example
  configs/
    app.yaml
    sources/
      youtube.yaml
      tiktok_watchlist.yaml
      instagram_watchlist.yaml
      retail_prices.yaml
    watchlists/
      creators_us.yaml
      brands_us.yaml
      retailers_us.yaml
    scoring/
      trend_score.yaml
  core/
    config/
    registry/
    pipeline/
    logging/
    errors/
    models/
    types/
    utils/
  connectors/
    youtube/
    tiktok_watchlist/
    instagram_watchlist/
    retail_prices/
    brand_sites/
  normalizers/
    social_content/
    commerce_snapshot/
  extractors/
    perfume_mentions/
    brand_mentions/
    note_mentions/
    price_mentions/
    retailer_mentions/
    recommendation_signals/
  resolvers/
    perfume_identity/
    brand_identity/
  enrichers/
    perfume_metadata/
    pricing/
    discounts/
  scorers/
    trend_score/
    creator_weight/
    note_momentum/
  storage/
    interfaces/
    raw/
    normalized/
    signals/
    entities/
    analytics/
  publishers/
    json/
    csv/
    markdown/
    sheets/
  workflows/
    ingest_social_content.py
    enrich_market_data.py
    build_weekly_report.py
  tests/
    unit/
    integration/
    fixtures/
  docs/
    schemas/
    module_contracts/
```

---

## Base Types (Core)

```python
class PipelineContext(BaseModel):
    run_id: str
    workflow_name: str
    started_at: datetime
    environment: str
    schema_version: str
    extractor_version: str | None = None
    scoring_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class FetchCursor(BaseModel):
    source_name: str
    cursor_type: str
    cursor_value: str | None = None
    updated_at: datetime

class FetchSessionResult(BaseModel):
    source_name: str
    fetched_count: int
    success_count: int
    failed_count: int
    next_cursor: FetchCursor | None = None
    raw_items: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

---

## SDK Module Contracts (Python Protocols)

```python
class SourceConnector(Protocol):
    name: str
    version: str
    def validate_config(self, config: dict[str, Any]) -> None: ...
    def healthcheck(self) -> bool: ...
    def get_cursor(self) -> FetchCursor | None: ...
    def set_cursor(self, cursor: FetchCursor) -> None: ...
    def fetch(self, context: PipelineContext, limit: int | None = None) -> FetchSessionResult: ...

class Normalizer(Protocol):
    name: str
    version: str
    def normalize(self, raw_item: dict[str, Any], context: PipelineContext) -> CanonicalContentItem: ...

class Extractor(Protocol):
    name: str
    version: str
    def extract(self, content_item: CanonicalContentItem, context: PipelineContext) -> ExtractedSignals: ...

class Resolver(Protocol):
    name: str
    version: str
    def resolve(self, signals: ExtractedSignals, context: PipelineContext) -> ResolvedSignals: ...

class Enricher(Protocol):
    name: str
    version: str
    def enrich(self, entity: dict[str, Any], context: PipelineContext) -> dict[str, Any]: ...

class Scorer(Protocol):
    name: str
    version: str
    def score(self, entity: dict[str, Any], context: PipelineContext) -> dict[str, Any]: ...

class Publisher(Protocol):
    name: str
    version: str
    def publish(self, payload: dict[str, Any], destination: dict[str, Any], context: PipelineContext) -> None: ...

class ModuleRegistry(Protocol):
    def register_connector(self, connector: SourceConnector) -> None: ...
    def register_normalizer(self, normalizer: Normalizer) -> None: ...
    def register_extractor(self, extractor: Extractor) -> None: ...
    def register_resolver(self, resolver: Resolver) -> None: ...
    def register_enricher(self, enricher: Enricher) -> None: ...
    def register_scorer(self, scorer: Scorer) -> None: ...
    def register_publisher(self, publisher: Publisher) -> None: ...
    def get_connector(self, name: str) -> SourceConnector: ...
    def get_normalizer(self, name: str) -> Normalizer: ...
    def get_extractor(self, name: str) -> Extractor: ...
    def get_resolver(self, name: str) -> Resolver: ...
    def get_enricher(self, name: str) -> Enricher: ...
    def get_scorer(self, name: str) -> Scorer: ...
    def get_publisher(self, name: str) -> Publisher: ...
```

**Contract rules:**
- `fetch()` returns raw records only — no analytics, no alias resolution
- `normalize()` must not discard reference to raw payload; must be deterministic
- `extract()` must record confidence where applicable; must not call publishers
- Extractor/Scorer/Publisher output must be versioned

---

## Canonical Schemas (Pydantic v2)

```python
class EngagementMetrics(BaseModel):
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None

class CanonicalContentItem(BaseModel):
    id: str
    schema_version: str
    source_platform: Literal["youtube", "tiktok", "instagram", "other"]
    source_account_id: str | None = None
    source_account_handle: str | None = None
    source_account_type: Literal["creator", "brand", "retailer", "other"] | None = None
    source_url: str
    external_content_id: str | None = None
    published_at: datetime
    collected_at: datetime
    content_type: Literal["video", "short", "reel", "post", "other"]
    title: str | None = None
    caption: str | None = None
    text_content: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions_raw: list[str] = Field(default_factory=list)
    media_metadata: dict[str, Any] = Field(default_factory=dict)
    engagement: EngagementMetrics = Field(default_factory=EngagementMetrics)
    language: str | None = None
    region: str = "US"
    raw_payload_ref: str
    normalizer_version: str

class EntityMention(BaseModel):
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = None
    start_char: int | None = None
    end_char: int | None = None

class PriceMention(BaseModel):
    raw_text: str
    currency: str | None = None
    amount: float | None = None
    confidence: float | None = None

class ExtractedSignals(BaseModel):
    content_item_id: str
    schema_version: str
    extractor_version: str
    perfume_mentions: list[EntityMention] = Field(default_factory=list)
    brand_mentions: list[EntityMention] = Field(default_factory=list)
    note_mentions: list[EntityMention] = Field(default_factory=list)
    retailer_mentions: list[EntityMention] = Field(default_factory=list)
    price_mentions: list[PriceMention] = Field(default_factory=list)
    discount_mentions: list[EntityMention] = Field(default_factory=list)
    recommendation_tags: list[str] = Field(default_factory=list)
    sentiment_hints: list[str] = Field(default_factory=list)
    usage_context_tags: list[str] = Field(default_factory=list)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)

class ResolvedEntityLink(BaseModel):
    entity_type: Literal["perfume", "brand", "retailer", "note"]
    entity_id: str
    canonical_name: str
    matched_from: str
    confidence: float | None = None

class ResolvedSignals(BaseModel):
    content_item_id: str
    resolver_version: str
    resolved_entities: list[ResolvedEntityLink] = Field(default_factory=list)
    unresolved_mentions: list[str] = Field(default_factory=list)
    alias_candidates: list[dict[str, Any]] = Field(default_factory=list)

class PerfumeEntity(BaseModel):
    perfume_id: str
    brand_id: str | None = None
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    concentration: str | None = None
    official_notes: list[str] = Field(default_factory=list)
    family: str | None = None
    status: Literal["active", "discontinued", "unknown"] = "unknown"
    metadata_sources: list[str] = Field(default_factory=list)
    entity_version: str

class PriceSnapshot(BaseModel):
    id: str
    perfume_id: str
    retailer_id: str
    captured_at: datetime
    currency: str = "USD"
    price: float | None = None
    list_price: float | None = None
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    product_url: str
    source_name: str

class DiscountSnapshot(BaseModel):
    id: str
    perfume_id: str
    retailer_id: str
    captured_at: datetime
    discount_type: str | None = None
    discount_value: float | None = None
    promo_text: str | None = None
    product_url: str
    source_name: str

class TrendSignal(BaseModel):
    perfume_id: str
    window: Literal["7d", "30d"]
    mention_count: int
    engagement_weighted_mentions: float
    creator_weighted_mentions: float
    recency_score: float
    novelty_score: float
    trend_score: float
    top_context_tags: list[str] = Field(default_factory=list)
    top_note_mentions: list[str] = Field(default_factory=list)
    scoring_version: str
```

---

## Storage Interfaces

```python
class RawStorage(Protocol):
    def save_raw_batch(self, source_name: str, run_id: str, items: list[dict[str, Any]]) -> list[str]: ...

class NormalizedStorage(Protocol):
    def save_content_items(self, items: list[CanonicalContentItem]) -> None: ...
    def get_content_items(self, ids: list[str]) -> list[CanonicalContentItem]: ...

class SignalStorage(Protocol):
    def save_extracted_signals(self, items: list[ExtractedSignals]) -> None: ...
    def save_resolved_signals(self, items: list[ResolvedSignals]) -> None: ...

class EntityStorage(Protocol):
    def upsert_perfumes(self, items: list[PerfumeEntity]) -> None: ...
    def get_perfume_by_alias(self, alias: str) -> PerfumeEntity | None: ...

class AnalyticsStorage(Protocol):
    def save_trend_signals(self, items: list[TrendSignal]) -> None: ...
    def get_trend_signals(self, window: str) -> list[TrendSignal]: ...
```

**Storage rules:**
- Raw payloads must be persisted **before** normalization results are committed
- Normalized items must reference raw payload location (`raw_payload_ref`)
- Storage must support replay workflows
- Failed items must be traceable to source and run_id

---

## Configuration Structure

### configs/app.yaml
```yaml
app_name: perfume_trend_sdk
environment: dev
schema_version: "1.0"
default_region: US
logging:
  level: INFO
  format: json
storage:
  raw_backend: filesystem
  normalized_backend: sqlite
  signals_backend: sqlite
  entities_backend: sqlite
  analytics_backend: sqlite
workflows:
  ingest_social_content:
    enabled: true
  enrich_market_data:
    enabled: true
  build_weekly_report:
    enabled: true
```

### configs/sources/youtube.yaml (example)
```yaml
name: youtube_watchlist
enabled: true
connector: youtube_connector
normalizer: social_content_normalizer
cursor_strategy: published_after
fetch_limit: 50
watchlist_file: configs/watchlists/creators_us.yaml
rate_limits:
  requests_per_minute: 30
retry:
  max_attempts: 3
  backoff_seconds: 5
```

### configs/watchlists/creators_us.yaml (example)
```yaml
accounts:
  - platform: youtube
    account_handle: "example_creator"
    account_type: creator
    priority: high
    region: US
    active: true
```

### configs/scoring/trend_score.yaml (example)
```yaml
trend_score:
  mention_weight: 1.0
  engagement_weight: 0.5
  creator_weight: 0.8
  recency_weight: 0.7
  novelty_weight: 0.3
creator_weights:
  high: 1.5
  medium: 1.0
  low: 0.7
```

**Lives in config:** active sources, watchlists, fetch params, schedules, scoring weights, output routes, feature flags, account priorities

**Does NOT live in config:** business-critical computations requiring code, complex entity matching algorithms

---

## Workflows

### Workflow A: ingest_social_content
1. Load pipeline context
2. For each enabled social connector:
   - validate config → healthcheck → fetch raw batch → persist raw
   - normalize items → persist canonical content
   - run extractors → persist extracted signals
   - run resolvers → persist resolved signals
   - update cursor
3. Emit workflow summary

### Workflow B: enrich_market_data
1. Load recently resolved perfume entities
2. For each entity: run metadata enricher → price enricher → discount enricher
3. Persist entity updates, price snapshots, discount snapshots
4. Emit enrichment summary

### Workflow C: build_weekly_report
1. Load last 7 days of resolved and enriched data
2. Run scoring modules
3. Aggregate: top perfumes, notes, creators, retailers, discount signals
4. Persist trend signals
5. Publish: JSON + CSV + markdown report + optional Sheets sync

---

## First End-to-End Path (required before multi-source)

```
YouTube watchlist → normalization → extraction → resolution → storage → weekly markdown export
```

Acceptance conditions:
- Source fetch succeeds with cursor support
- Canonical content records are created
- Perfume mentions are extracted from normalized items
- Resolved entities are stored
- Weekly markdown output is generated from stored results

---

## Logging Specification

All runtime logs must be structured JSON with these fields:

```json
{
  "timestamp": "ISO8601",
  "level": "INFO|WARNING|ERROR",
  "run_id": "string",
  "workflow_name": "string",
  "module_type": "connector|normalizer|extractor|...",
  "module_name": "string",
  "event_name": "string",
  "source_name": "string",
  "entity_id": "string (if applicable)",
  "message": "string",
  "error_type": "string (if applicable)"
}
```

---

## Error Handling

### Error Classes
```
ConfigValidationError
ConnectorHealthcheckError
FetchError
NormalizationError
ExtractionError
ResolutionError
EnrichmentError
PublishError
StorageError
```

### Rules
- Connector failure must NOT crash unrelated source workflows
- Item-level normalization errors: log and skip when safe
- Extraction errors: preserve failed content item identifiers
- Publisher failures: must NOT delete analytics results
- Retry only where idempotence is acceptable

### Retry Policy
| Operation | Retry |
|-----------|-------|
| Network fetch | Yes |
| Storage write (idempotent) | Yes |
| Normalization logic bug | No — fail and log |
| Extraction parsing error | No — log for inspection |

---

## Scoring Formula

```
trend_score =
  (mention_count × mention_weight) +
  (engagement_weighted_mentions × engagement_weight) +
  (creator_weighted_mentions × creator_weight) +
  (recency_score × recency_weight) +
  (novelty_score × novelty_weight)
```

- All weights loaded from `configs/scoring/trend_score.yaml`
- Creator tier comes from watchlist metadata (`priority: high/medium/low`)
- Formula must be isolated in scorer module
- Report must display which `scoring_version` was used

---

## Versioning

Required version fields:
- `schema_version` — canonical schema
- `normalizer_version` — normalizer logic
- `extractor_version` — extraction logic
- `resolver_version` — resolution logic
- `scoring_version` — scoring formulas
- `entity_version` — entity shape

**Rule:** Whenever output shape or logic materially changes, the corresponding version must change.
**Replay requirement:** Historical raw data must be replayable through newer versions of normalization, extraction, or scoring.

---

## Security Rules

- Secrets must NOT be hardcoded anywhere in the codebase
- Credentials must come from environment variables or secret manager
- Source configs may reference secret keys by name only
- Logs must NOT expose tokens or session secrets
- Browser automation settings must remain source-isolated

---

## Testing Requirements

### Unit tests (required)
- Config loading
- Connector validation
- Normalizer mapping behavior
- Extractor output shape
- Resolver alias matching
- Scorer formula behavior
- Publisher payload formatting

### Integration tests (required)
- One connector end-to-end through normalization and extraction
- Replay from raw storage
- Weekly report generation from stored data
- Module replacement without breaking registry

### Fixtures (required)
- Raw YouTube-like content item
- Raw Instagram-like content item
- Raw TikTok-like content item
- Ambiguous perfume alias examples
- Price and discount page samples

---

## Module Development Workflow

For every new module, follow this sequence:
1. Define the contract (interface)
2. Create skeleton implementation
3. Create example config
4. Create test cases
5. Register module in registry
6. Run integration
7. Document the interface

---

## Implementation Milestones

| Milestone | Scope |
|-----------|-------|
| 1 | Core skeleton + config loader + registry + logging |
| 2 | YouTube connector + social normalizer + raw/normalized storage |
| 3 | Perfume mention extractor + brand extractor + basic resolver |
| 4 | Weekly markdown report |
| 5 | TikTok and Instagram watchlist connectors |
| 6 | Market enrichment for price and discount signals |
| 7 | Trend scoring + CSV/JSON outputs |
| 8 | SDK cleanup + examples + fixture set |

---

## Implementation Roadmap (Stages)

| Stage | Goal | Status |
|-------|------|--------|
| 0 | Project Charter | Done |
| 1 | Domain Modeling | Done |
| 2 | Core Framework Skeleton | Next → Milestone 1 |
| 3 | First end-to-end pipeline (YouTube) | Milestones 2–4 |
| 4 | Social Source Expansion (TikTok, Instagram) | Milestone 5 |
| 5 | Extraction Engine v1 | Milestone 3 |
| 6 | Identity Resolution Layer | Milestone 3 |
| 7 | Market Enrichment Layer | Milestone 6 |
| 8 | Trend Scoring Engine | Milestone 7 |
| 9 | Reporting & Delivery | Milestones 4, 7 |
| 10 | SDK Packaging | Milestone 8 |
| 11 | Monetization Adapters | Post-v1 |

---

## Definition of Done — v1

- [ ] Minimum 3 sources running
- [ ] Single canonical schema for all v1 sources
- [ ] Perfume mentions extracted and aggregated
- [ ] Notes, prices, and retailers added for at least a subset of entities
- [ ] Weekly report assembled automatically
- [ ] One module can be disabled without breaking the core
- [ ] New connector can be added via template

---

## Scope — v1

**In scope:**
- US market, perfume category
- Watchlist monitoring of known US players
- Level 1: TikTok, Instagram, YouTube watchlists
- Level 2: brand sites, retail pages, price/availability/discount pages
- Normalization, extraction, basic enrichment, trend score, weekly report

**Out of scope for v1:**
- Full TikTok/Instagram/YouTube scan
- Real-time tracking
- Full comment analysis
- Multi-language / multi-region
- Complex recommendation models
- Public SDK for third-party developers

---

## Key Business Questions System Must Answer

1. Which perfumes are currently being promoted in the US by key accounts?
2. Who exactly is promoting them?
3. What exactly are they saying about them?
4. Which notes repeat most often?
5. What price range is being discussed?
6. Where are they sold?
7. Are there signs of discounts, promotions, or commercial pressure?

---

## Implementation Plan v1 — Sprint Breakdown

### Build Philosophy

Build as a sequence of thin, testable vertical slices. Each slice must:
- implement one clear responsibility
- fit the contracts defined in Tech Spec v1
- remain replaceable
- be usable in the next sprint

For each module: define interface → skeleton → minimum logic → tests → integration → document.

---

### Sprint Overview

| Sprint | Goal | Status |
|--------|------|--------|
| 0 | Project bootstrap — repo skeleton, package structure, configs | Done |
| 1 | Core framework — config, registry, logging, models, storage interfaces | Done |
| 2 | First end-to-end source — YouTube → raw → normalize → extract → resolve → markdown | Done |
| 3 | Hybrid AI Intelligence — pre-filter, multi-engine AI extractor, router | Next |
| 3.5 | Source Intelligence — who drives trends, influence scoring, UnifiedSignal extension | Pending |
| 4 | Social expansion — TikTok + Instagram connectors under same contracts | Pending |
| 5 | Intelligence layer — full extraction, resolution, enrichment, scoring | Pending |
| 6 | Output + SDK packaging — CSV/JSON/Sheets publishers, replay, docs, fixtures | Pending |
| 7 | Stabilization — modular review, contract freeze, v1 readiness check | Pending |

---

### Sprint 0 — Project Bootstrap

Exit criteria:
- package structure exists and imports work
- configs load from filesystem path
- pytest runs (even with placeholders)

Files:
```
pyproject.toml, README.md, .env.example
configs/app.yaml, configs/sources/, configs/watchlists/, configs/scoring/
perfume_trend_sdk/__init__.py + all top-level package dirs
tests/ + fixtures/ structure
```

---

### Sprint 1 — Core Framework

Exit criteria:
- foundation modules compile
- config + registry operational
- all core schemas exist
- storage interfaces defined
- core unit tests pass

Modules: `core/config`, `core/registry`, `core/logging`, `core/errors`, `core/models`, `storage/interfaces`

Key files:
```
core/config/models.py          ← AppConfig, LoggingConfig, StorageConfig
core/config/loader.py          ← load_yaml, load_app_config
core/errors/base.py + typed errors
core/logging/logger.py         ← log_event (structured JSON)
core/models/context.py         ← PipelineContext
core/models/fetch.py           ← FetchCursor, FetchSessionResult
core/models/content.py         ← CanonicalContentItem
core/models/signals.py         ← ExtractedSignals, ResolvedSignals
core/models/entities.py        ← PerfumeEntity, PriceSnapshot, DiscountSnapshot
core/models/analytics.py       ← TrendSignal
core/types/contracts.py        ← Protocol interfaces for all module types
core/registry/module_registry.py
storage/interfaces/raw.py + normalized.py + signals.py + entities.py + analytics.py
```

---

### Sprint 2 — First End-to-End Source (YouTube)

Required path before multi-source expansion:
```
YouTube watchlist → raw storage → normalization → extraction → resolution → markdown output
```

Exit criteria:
- fetch returns FetchSessionResult with cursor support
- raw, normalized, extracted, resolved layers all exist in storage
- markdown weekly report generated
- replay from raw manually possible

Key files:
```
connectors/youtube/connector.py + client.py + mappers.py
storage/raw/filesystem.py
normalizers/social_content/normalizer.py
storage/normalized/sqlite_store.py
extractors/perfume_mentions/extractor.py
extractors/brand_mentions/extractor.py
storage/signals/sqlite_store.py
resolvers/perfume_identity/resolver.py + alias_store.py
publishers/markdown/weekly_report.py
workflows/ingest_social_content.py
workflows/build_weekly_report.py
```

---

### Sprint 3 — Hybrid AI Intelligence Layer

**Goal:** Upgrade extraction from rule-based to hybrid AI + multi-engine + source intelligence.

**Architecture:**
```
Fetch → Pre-filter → AI Extractor (via router) → Resolver → Unified Signals → Scoring → Reports
```

**Pipeline rules:**
- Rule-based extractor = fallback (always works without AI)
- AI layer = optional, plugged via router only
- Pipeline must work without AI
- Do NOT hardcode AI logic in pipeline
- All AI engines must return same unified output schema

**Phase A — Pre-filter**
```
extractors/pre_filter/filter.py
```
- Skip non-perfume content before AI call
- Reduce API cost and noise

**Phase B — Multi-Engine AI Extraction**
```
extractors/ai_engines/
    base.py          ← AIExtractor Protocol
    router.py        ← get_extractor(provider: str) -> AIExtractor
    openai_extractor.py
    claude_extractor.py   (placeholder)
    gemini_extractor.py   (placeholder)
```

AI interface:
```python
class AIExtractor(Protocol):
    def extract(self, text: str) -> dict: ...
```

Required unified output schema (ALL engines must return this):
```json
{
  "perfumes": [
    {"brand": "Dior", "product": "Sauvage Elixir", "confidence": 0.95, "sentiment": "positive"}
  ],
  "brands": ["Dior"],
  "notes": ["vanilla", "oud"],
  "sentiment": "positive",
  "confidence": 0.92
}
```

**Phase C — AI Config**
```yaml
ai:
  provider: "openai"
  model: "gpt-4o-mini"
  temperature: 0
  enabled: true
```

**Phase D — Pipeline Integration**
Update: `workflows/test_pipeline.py`, `workflows/ingest_social_content.py`

**Phase E — Cost & Control**
- `max_tokens` config
- Fallback to rule-based extractor on AI failure

**Exit criteria:**
- Pre-filter implemented
- AIExtractor interface defined
- OpenAI extractor working
- Router routes by config provider
- Pipeline works with AI disabled
- Fallback to rule-based confirmed

---

### Sprint 3.5 — Source Intelligence Layer

**Goal:** Identify WHO drives trends and weight their influence.

**Modules:**
```
analysis/source_intelligence/
    analyzer.py
    scoring.py
```

**Output schema:**
```json
{
  "source_type": "influencer | brand | user | bot",
  "influence_score": 0,
  "credibility_score": 0.0,
  "engagement_level": "low | medium | high"
}
```

**UnifiedSignal extension** (`core/models/unified_signal.py`):
- `source_type: str | None`
- `influence_score: float | None`
- `credibility_score: float | None`

**Business value:** System sells influence-weighted intelligence, not raw mention counts.
Example: "80% of Dior hype driven by 3 influencers with >500k audience"

**Exit criteria:**
- Source analyzer classifies source type
- Influence scoring works from metadata
- UnifiedSignal extended with source fields

---

### Sprint 4 — Social Expansion (previously Sprint 3)

Exit criteria:
- TikTok + Instagram connectors conform to same SourceConnector contract
- registry activates source modules by config
- core contracts unchanged

Key files:
```
connectors/tiktok_watchlist/connector.py + client.py + config.py
connectors/instagram_watchlist/connector.py + client.py + config.py
core/config/watchlist_loader.py
configs/watchlists/creators_us.yaml (finalized schema)
```

---

### Sprint 4 — Intelligence Layer

Exit criteria:
- notes, prices, retailers, discounts enter the data model
- brand and perfume aliases resolve from fixtures
- trend scores generated and stored

Key files:
```
extractors/note_mentions/extractor.py
extractors/price_mentions/extractor.py
extractors/retailer_mentions/extractor.py
extractors/recommendation_signals/extractor.py
resolvers/brand_identity/resolver.py
storage/entities/sqlite_store.py
enrichers/perfume_metadata/enricher.py
enrichers/pricing/enricher.py
enrichers/discounts/enricher.py
storage/analytics/sqlite_store.py
scorers/trend_score/scorer.py
scorers/creator_weight/scorer.py
scorers/note_momentum/scorer.py
workflows/enrich_market_data.py
```

---

### Sprint 5 — Output + SDK Packaging

Exit criteria:
- JSON, CSV, optional Sheets outputs available
- replay workflow works
- module template docs exist
- project resembles SDK-ready constructor

Key files:
```
publishers/json/publisher.py
publishers/csv/publisher.py
publishers/sheets/publisher.py (optional)
workflows/replay_from_raw.py
docs/module_contracts/source_connector.md + normalizer.md + extractor.md
sdk/examples/sample_connector.py + sample_extractor.py + sample_publisher.py
tests/fixtures/ (hardened: social, commerce, entities, edge cases)
```

---

### Sprint 6 — Stabilization

Required review checklist:
- YouTube connector swappable without changing extractor logic?
- TikTok connector disableable while report still builds from other sources?
- Raw payloads replayable through newer normalizer versions?
- Scoring weights entirely config-driven?
- Outputs decoupled from internal storage shape?
- New publisher addable without editing connector code?

Exit criteria: all critical integration tests pass, contracts frozen, known limitations documented.

---

### File Build Order Summary

| Phase | Files |
|-------|-------|
| A — Foundation | pyproject.toml, core/config/*, core/errors/*, core/logging/*, core/models/*, core/types/contracts.py, core/registry/module_registry.py, storage/interfaces/* |
| B — First vertical slice | connectors/youtube/*, storage/raw/filesystem.py, normalizers/social_content/normalizer.py, storage/normalized/sqlite_store.py, extractors/perfume_mentions/*, extractors/brand_mentions/*, storage/signals/sqlite_store.py, resolvers/perfume_identity/*, workflows/ingest_social_content.py, publishers/markdown/weekly_report.py, workflows/build_weekly_report.py |
| C — Source expansion | connectors/tiktok_watchlist/*, connectors/instagram_watchlist/*, core/config/watchlist_loader.py |
| D — Intelligence | extractors/note_mentions→recommendation_signals/*, resolvers/brand_identity/*, storage/entities/*, enrichers/*/*, storage/analytics/*, scorers/*/*, workflows/enrich_market_data.py |
| E — Packaging | publishers/json→sheets/*, workflows/replay_from_raw.py, docs/module_contracts/*, sdk/examples/*, tests/fixtures/* |

---

## Perfume Trend Intelligence Engine v1

### 1. Product Definition

Perfume Trend Intelligence Engine is a market terminal for fragrance trends.

**This is NOT:**
- a static dashboard
- a reporting tool
- a simple analytics panel

**This IS:**
- a real-time trend intelligence system
- a decision engine
- a market-like environment, where perfumes, brands, notes, and accords behave like tradable entities (similar to stocks/assets)

The system must allow users to:
- detect rising trends early
- monitor momentum
- compare entities
- identify breakouts and reversals
- understand WHY something is moving

---

### 2. Core Product Metaphor

All tracked entities behave like market instruments.

Each entity has:
- score (like price)
- momentum
- volume
- volatility
- signals

UI and backend must follow this model strictly.

---

### 3. Core Entities

**Primary**
- Brand
- Perfume
- Note
- Accord

**Secondary**
- Creator (TikTok / YouTube / etc.)
- Channel (TikTok, YouTube, Google Trends, etc.)
- Retailer (Amazon, etc.)
- Signal Event

---

### 4. Existing Data (DO NOT REMOVE)

The system already includes:
- `mention_count` (weighted float)
- `influence_score` weighting
- sentiment multiplier: positive → ×1.2, negative → ×0.5
- `ai_confidence` multiplier
- `trend_score`
- `mentions_last_24h`
- `mentions_prev_24h`
- `growth`

These must remain intact. All new layers must build on top of this, not replace it.

---

### 5. Required Backend Architecture (Market Engine)

**Layer A — Ingestion**

Collect data from:
- YouTube (metadata)
- Google Trends
- Reddit
- News / blogs
- Fragrance datasets (GitHub / Kaggle)
- Keepa API (Amazon proxy)

**Layer B — Entity Resolution**
- detect brands, perfumes, notes, accords
- resolve aliases and misspellings
- map mentions → entities

**Layer C — Enrichment**
- sentiment
- confidence
- influence score
- engagement normalization
- channel attribution
- region attribution

**Layer D — Aggregation**

Store time-bucketed data:
- hourly (short-term)
- daily (core)
- weekly/monthly (long-term)

**Layer E — Derived Metrics**

Compute:
- `composite_market_score`
- momentum
- acceleration
- volatility
- source_diversity
- creator_velocity
- saturation_risk
- forecast_score

**Layer F — Signal Engine**

Detect:
- breakout
- acceleration spike
- reversal
- divergence
- creator-driven spike
- cross-channel confirmation
- note fatigue

**Layer G — Serving Layer**

Expose API endpoints for UI:
- dashboard
- screener
- entity page
- charts
- signals
- watchlists
- alerts

---

### 6. Data Model Requirements

**Required new fields**

Each entity must have:
- `entity_id`
- `entity_type`
- `ticker` (short symbol)

Time series must include:
- `timestamp`
- `mention_count`
- `unique_authors`
- `engagement_sum`
- `sentiment_avg`
- `search_index`
- `retailer_score`
- `composite_market_score`
- `acceleration`
- `volatility`
- `forecast_score`

---

### 7. UI Principles (MANDATORY)

UI must follow financial terminal logic, not ecommerce.

**Required characteristics:**
- dark theme
- data-dense layout
- real-time feel
- chart-first design
- comparison-friendly
- sortable tables
- filters everywhere

**Avoid:**
- "beauty brand" UI
- decorative layouts
- large empty spaces
- marketing-style pages

The UI must feel like TradingView or a simplified Bloomberg terminal.

---

### 8. API Design Principles

APIs must return:
- precomputed data
- chart-ready time series
- screener-ready rows

Frontend must NOT:
- compute metrics from raw mentions
- aggregate heavy datasets

All heavy computation belongs to backend.

---

### 9. Data Source Policy

**Allowed sources:**
- Google Trends
- YouTube metadata
- Reddit
- News / blogs
- Fragrance datasets (GitHub / Kaggle)
- Keepa API (Amazon data proxy)

**Amazon Policy:**
- Use Keepa API for: price history, rank proxy, stock proxy
- DO NOT use Amazon Seller / SP-API
- DO NOT require seller account authentication

---

### 10. Development Rules

- DO NOT delete existing pipeline
- ALWAYS extend current system
- EACH feature must map to: entity, metric, signal, workflow

**Prefer:**
- precomputation
- normalized data
- reusable metrics

**Avoid:**
- one-off scripts
- UI-specific logic in backend
- raw data exposure

---

### 11. V1 Scope (STRICT PRIORITY)

Build in this order:
1. Entity master tables (brands, perfumes, notes, accords)
2. Time-series storage
3. Composite market score
4. Dashboard API
5. Top movers table
6. Screener API
7. Entity page (summary + chart)
8. Signal detection v1
9. Watchlists

---

### 12. V2 Scope

After V1:
- Notes & accords rotation engine
- Relationship graph
- Channel attribution layer
- Creator influence system
- Saturation detection
- Forecast engine

---

### 13. Product Goal

The system must allow users to feel:
- they are watching a live market
- they can discover trends early
- data is actionable
- movement is visible and explainable

This is NOT about data display. This is about decision advantage.

---

### 14. Golden Rule

If a feature does not:
- improve trend detection
- improve decision speed
- improve signal clarity

→ it should NOT be implemented.

---

## 15. Frontend Terminal Architecture (V1)

The frontend for Perfume Trend Intelligence Engine must be implemented as a **desktop-first market terminal**, not as a marketing site or ecommerce storefront.

### Frontend goals

The frontend must:

* render dense market intelligence clearly
* support fast scanning of movers, signals, and entities
* prioritize dashboard, screener, and entity workflows
* remain compatible with future watchlists, alerts, and compare features

### Core frontend stack

Preferred stack:

* Next.js
* React
* TypeScript
* Tailwind CSS
* TanStack Query
* Zustand
* TanStack Table
* Recharts for V1 charts

The stack may be adapted to the existing repo if needed, but the architecture and interaction model must remain consistent.

### Frontend page structure

Required V1 routes:

* `/dashboard`
* `/screener`
* `/entities/[entityId]`
* `/watchlists` (placeholder allowed in V1)
* `/alerts` (placeholder allowed in V1)

The root route may redirect to `/dashboard`.

### App shell rules

The app must use a shared terminal shell with:

* left sidebar
* top navigation/header
* main content region

Sidebar items:

* Dashboard
* Screener
* Watchlists
* Alerts

The shell must be:

* dark-first
* compact
* desktop-first
* route-aware with active state highlighting

### Primary UI pages

#### Dashboard

The dashboard must include:

* top control bar
* KPI strip
* top movers table
* main chart panel
* signal feed panel

The dashboard is the market overview screen and should answer:

* what is moving?
* how strongly is it moving?
* what just triggered?

#### Entity page

The entity page must include:

* entity header
* main chart
* metrics rail
* signal timeline
* recent mentions

The entity page should answer:

* what is happening?
* how strong is it?
* why is it happening?
* what should the user watch next?

#### Screener

The screener must include:

* quick controls
* advanced filters
* sortable results table
* pagination footer

The screener is the discovery workflow and should allow users to hunt for opportunities quickly.

### Watchlists and alerts

In V1:

* watchlists and alerts may exist as scaffold or placeholder routes
* do not build full workflow unless explicitly requested
* preserve route structure so the product can expand cleanly later

### Shared design system requirements

All frontend work must use a consistent terminal-style design system.

Required shared primitives:

* TerminalPanel
* SectionHeader
* KpiCard
* MetricBadge
* DeltaBadge
* SignalBadge
* EmptyState
* ErrorState
* LoadingSkeleton
* ControlBar
* SearchInput
* FilterChip
* ChartContainer

Design principles:

* information first
* dense but readable
* semantic color only
* consistent formatting across all pages

### Table rules

Tables are core UI infrastructure.

Use a reusable table system for:

* top movers
* screener
* watchlists later
* alerts later

Tables must support:

* compact density
* sortable headers
* row click
* loading state
* empty state

### Chart rules

Charts must be used as analytical tools, not decoration.

V1 charts should:

* use line charts
* support time range switching where practical
* use real backend timeseries
* prioritize clarity over animation

### API integration rules

Frontend must consume real backend APIs where available.

Do:

* centralize API calls in a dedicated API layer
* use typed response models
* use TanStack Query for server-state
* keep server data out of local UI stores

Do not:

* fetch directly in deeply nested presentational components
* scatter formatting logic across pages
* hardcode fake market data when real endpoints exist

### State management rules

Use:

* TanStack Query for server state
* Zustand only for local UI state

Examples of local UI state:

* selected dashboard entity
* modal open/close
* screener panel open/close
* active watchlist id later
* chart mode toggle

Do not use a large global store for backend responses.

### URL and filter behavior

Screener filters should be URL-friendly where practical.

Examples:

* entity type
* signal type
* min score
* min confidence
* min mentions
* sort_by
* order
* offset

This ensures shareable and reproducible views.

### Formatting rules

Use a shared adapter/formatter layer for:

* score formatting
* growth formatting
* confidence formatting
* signal labels
* timestamps

Do not duplicate formatting logic across components.

### Frontend build order

When implementing the frontend, build in this order:

1. app shell
2. shared primitives
3. dashboard page
4. entity page
5. screener page
6. watchlists placeholder
7. alerts placeholder

### Frontend non-goals for V1

Do not prioritize:

* landing page
* auth system
* ecommerce-style branding
* animation-heavy UI
* full compare mode
* full watchlist workflow
* full alerts workflow

### Golden frontend rule

If a frontend change does not improve:

* market readability
* decision speed
* signal clarity
* workflow efficiency

then it should not be prioritized.

---

## 16. Frontend/Backend Contract Rules

The frontend must treat the backend as the source of truth for:

* market scores
* growth rates
* confidence
* signals
* timeseries
* screener filtering results

### Rules

* do not recompute backend market metrics in the frontend
* do not derive alternative signal logic in the frontend
* only format and present backend values
* keep frontend adapters lightweight and presentation-focused

### Page-to-endpoint mapping

* Dashboard → `/api/v1/dashboard`
* Screener → `/api/v1/screener`
* Entity Page → `/api/v1/entities/{id}`
* Signals feed → `/api/v1/signals`

### Contract principle

If payload shape mismatches UI needs:

* prefer lightweight frontend adapters first
* only change backend when the mismatch is structural or repeated

---

## 17. Current Product Stage

The project is currently in the transition from backend foundation to frontend terminal implementation.

This means:

* backend market engine is already functional
* API payloads are terminal-ready for V1
* frontend work should now focus on dashboard, entity page, and screener
* watchlists and alerts remain secondary in the first frontend build pass

---

## 18. Watchlists and Alerts (V1)

The next product layer after the core terminal is a personal monitoring workflow built around watchlists and alerts.

### Watchlists goals

Watchlists allow users to:

* save important entities
* group them into named lists
* return quickly to a curated set of perfumes and brands
* monitor signal activity without re-running searches

### Alerts goals

Alerts allow users to:

* be notified when meaningful entity changes happen
* react to breakouts, acceleration, and threshold changes
* reduce the need to manually check the terminal repeatedly

### V1 watchlists scope

Implement only:

* manual watchlists
* add/remove entities
* watchlist detail view with enriched market fields
* watchlist activity based on signals affecting watched entities

Do not implement yet:

* team/shared watchlists
* dynamic screener-based watchlists
* folders/tags
* complex notes system

### V1 alerts scope

Implement only:

* entity-based alerts
* in-app delivery only
* active/paused state
* trigger history
* cooldown support
* simple condition types

Do not implement yet:

* email/slack delivery
* team notification routing
* screener-wide alerts
* boolean rule builders
* AI-generated alert conditions

### V1 alert condition types

Allowed V1 conditions:

* breakout_detected
* acceleration_detected
* any_new_signal
* score_above
* growth_above
* confidence_below

### Watchlist and alert principle

This layer must transform the terminal from a place users visit occasionally into a place they can rely on continuously.

---

## 19. Alerting Rules

Alerts must be low-noise and meaningful.

### Rules

* the backend is the source of truth for alert evaluation
* the frontend must never independently evaluate alert conditions
* alerts should only trigger on explicit backend-supported conditions
* every alert type must map to clear stored logic
* repeated alerts require cooldown protection

### Cooldown

Every alert must support a cooldown window.
Default V1 behavior should use a 24-hour cooldown unless explicitly configured otherwise.

If a condition remains true during the cooldown period:

* do not generate a fresh active alert event
* optionally record a suppressed event for diagnostics later

### Alert quality principle

It is better to deliver fewer, more meaningful alerts than many repetitive alerts.
A noisy alert system reduces trust in the product.

---

## 20. Current Product Direction

The project has now moved from:

* backend market engine foundation
* terminal frontend foundation
  into:
* monitoring and retention workflow

Current product priority:

1. core terminal stability
2. watchlists
3. alerts
4. later deployment and live ingestion hardening

The next implementation work should focus on turning analytics into persistent user workflows.

---

## D1. Real Data Ingestion (V1)

The product must now evolve from dev/demo data into a real ingestion-driven market terminal.

### Initial real data source priority

Implement real ingestion in this order:

1. YouTube — primary validated source (API-based)
2. Reddit — secondary source (public JSON endpoints, no credentials required)
3. TikTok — deferred until Research API access is approved

YouTube is the first required real source for V1 live data.
Reddit JSON ingestion is active and treated as real data equivalent to YouTube.
TikTok ingestion is implemented but deferred from serving until production API approval.

### YouTube ingestion — V1 status

**Implemented.** `scripts/ingest_youtube.py` is the market-aware entry point for YouTube metadata ingestion. It writes into the same market pipeline:

```
ingestion → normalization → resolution → entity_mentions → aggregation
```

Key details:
* reads queries from `configs/watchlists/perfume_queries.yaml` (14 queries, all 8 tracked entities covered)
* writes `canonical_content_items` and `resolved_signals` to `PTI_DB_PATH` (market_dev.db)
* uses `outputs/pti.db` (resolver DB) for `PerfumeResolver` — the two DBs are kept separate
* idempotent: `ON CONFLICT DO UPDATE` on `(platform, external_content_id)`
* `channel_title` and `channel_id` are captured in `media_metadata`

Run order:
```bash
python3 scripts/ingest_youtube.py --max-results 10 --lookback-days 30
python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date YYYY-MM-DD
```

### YouTube ingestion goals

The YouTube pipeline must:

* query videos using tracked perfume/brand search terms
* fetch metadata for recent videos
* normalize results into canonical content items
* preserve source identity and timestamps
* support downstream entity resolution and aggregation
* allow repeated runs without duplicating the same content items

### Minimum YouTube fields to capture

At minimum store:

* platform = youtube
* external_content_id
* source_url
* title
* description
* channel_id
* channel_title
* published_at
* view_count if available
* like_count if available
* comment_count if available
* search query used
* ingestion timestamp

### Real ingestion principle

Real source data should flow through the same downstream market engine path:

* ingestion
* normalization
* entity resolution
* entity_mentions
* aggregation
* signals
* API
* frontend terminal

Do not create a separate analytics path for real sources.

### Aggregation job rules

* The aggregation job (`perfume_trend_sdk/jobs/aggregate_daily_market_metrics.py`) must always be run after new `resolved_signals` are written.
* The job must be run with `--date` matching the publication date of the new content, not the current wall-clock date.
* The job reads `PTI_DB_PATH` from `.env` automatically (via `load_dotenv()` in `main()`). No manual env var prefix is required.
* Re-running the aggregation for a date that already has snapshots is safe — rows are upserted, not duplicated.

### Brand name resolution

`entity_market.brand_name` is denormalized at aggregation time via a `perfumes → brands` catalog JOIN on slug.

* New entities get `brand_name` set on first insert.
* Existing rows with `brand_name IS NULL` are back-filled automatically on the next aggregation run.
* The API reads `entity.brand_name` directly — no cross-table lookup at request time.

### Duplication rules

Real ingestion must be idempotent where possible.
Use platform + external_content_id as the stable identity key for YouTube content.

### Real data sources vs. synthetic data

**Real data sources (count toward serving verification):**
- YouTube — fetched via YouTube Data API v3
- Reddit — fetched from public subreddit JSON endpoints (`/r/<subreddit>/new.json`)

**Synthetic / demo data (never allowed in serving DB):**
- seed backfill data generated for UI development
- test fixtures in `tests/fixtures/`
- sandbox data produced by dev scripts
- any item with `id LIKE 'dev_%'` or inserted without a real `source_url`

The serving database (`market_dev.db`) must contain only real-source items.
Verification (`verify_market_state`) rejects any synthetic items found in the serving DB.

### Demo data

The local demo build initially used `outputs/market_dev.db` populated with synthetic backfill
data for 2026-04-07 through 2026-04-10. That synthetic data has been removed.
The serving DB now contains only real YouTube items. Reddit items will be added as ingestion runs.

### V1 YouTube non-goals

Do not require in V1:

* transcript ingestion
* comment-level ingestion
* creator scoring completeness
* full channel analytics
* multi-source orchestration in the same step

---

## D2. Source Priority and Freshness

### Source freshness principle

The market terminal should prefer fresh source data while preserving a usable historical trail.

### Source hierarchy for V1

| Priority | Source | Access method | Signal value |
|----------|--------|---------------|--------------|
| 1 | YouTube | YouTube Data API v3 | Primary validated source — creator coverage, metadata-rich |
| 2 | Reddit | Public JSON endpoints (no credentials) | Community validation, niche discovery, authentic consumer voice |
| 3 | TikTok | Research API (deferred — pending approval) | Highest velocity, real-time trend signal |
| 4 | Google Trends | Public API | Search intent proxy, macro confirmation |

**TikTok note:** client and ingest script are implemented and tested. Ingestion into serving DB is deferred until Research API production credentials are approved.

### Freshness rules

* ingestion jobs should be rerunnable
* recent content should be prioritized
* source timestamps must be preserved exactly
* downstream aggregation must use source publish/occurred timestamps, not only ingestion time
* daily aggregation must run once per calendar day per target date
* signal detection window is 24 hours by default — signals older than the window do not contribute to the current day's signal feed

### Content date vs. run date

* Always aggregate using `--date` set to the content's `published_at` date, not the job's execution date.
* A job run on 2026-04-12 for content published on 2026-04-10 must use `--date 2026-04-10`.
* Running with today's date when content is from prior days produces zero-entity results.

### Search scope for V1

Initial real ingestion should focus on tracked watchlists / query lists rather than open-ended full-platform crawling.

Allowed V1 query drivers:

* tracked perfume queries
* tracked brand queries
* curated watchlist YAML files
* manually seeded entity query sets

### Data quality principle

It is better to ingest a smaller, cleaner, more explainable set of real YouTube items than a large noisy stream.

---

## D3. Signal Tuning and Source-Weighted Scoring

Real-source data must not be evaluated with thresholds designed only for synthetic/dev backfill.

### Signal tuning principles

* reversal signals must suppress obvious single-day noise
* breakout signals should be achievable from real-source early momentum, not only synthetic high-volume spikes
* single low-volume events must not dominate the market layer
* source transitions (synthetic history → real source) must not be misread as true market reversals

### Reversal rules

* suppress reversal when mention_count_today is below the minimum noise threshold
* require sufficient prior data stability before emitting strong reversal signals
* large single-day score collapses caused by source transitions should be suppressed

### Breakout rules

* breakout thresholds may be lower for real-source early detection than for synthetic backfill
* breakout must still require a minimum mention floor
* recent source activity should meaningfully influence breakout eligibility

### Composite scoring rules

* momentum is part of ranking, not only signal generation
* source-aware weighting is allowed in the market layer
* YouTube may be weighted above legacy/dev data as an early signal source
* future multi-source weighting should remain extensible for TikTok and Reddit

### Principle

The market engine should respond to real-world source momentum without becoming overly sensitive to low-volume noise.

### V1 implementation

Implemented in `perfume_trend_sdk/analysis/market_signals/detector.py` and `aggregator.py`.

Current thresholds (`DEFAULT_THRESHOLDS`):

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `breakout_min_score` | 15.0 | Lowered from 20 for real-source early detection |
| `breakout_min_mentions` | 2.0 | Suppress single-video breakouts |
| `breakout_growth_pct` | 0.35 | 35% growth qualifies (was 50%) |
| `reversal_min_mentions` | 2.0 | Suppress single-mention reversals |
| `reversal_max_score_ratio` | 4.0 | Suppress if prev_score > 4× current (source transition) |
| `acceleration_spike_threshold` | 1.5 | Momentum ratio ≥ 1.5 (unchanged) |

Composite score weights (v2):

| Component | Weight | Notes |
|-----------|--------|-------|
| mention_count | 35% | Was 40% |
| engagement | 25% | Was 30% |
| growth | 20% | Unchanged |
| momentum | 10% | New — acceleration affects ranking |
| source_diversity | 10% | Unchanged |

Source platform weights applied to mention count:

| Platform | Weight |
|----------|--------|
| TikTok | 1.3× (reserved) |
| YouTube | 1.2× |
| Reddit | 1.0× |
| Legacy/other | 0.8× |

Signal detection is idempotent: stale signals for a target date are cleared before re-detection. Re-running the job after threshold changes or re-aggregation produces a clean signal set.

---

## D4. Market Reality Verification (CRITICAL)

### Core Objective (ENFORCED)

The system must prove that it reflects the real market.

A working market terminal is NOT a system that:
- ingests data
- runs aggregation
- shows numbers

A working market terminal IS a system that:
- shows numbers that match what real humans are saying about real perfumes right now

### Definition of "Reflecting the Real Market"

The market terminal reflects reality when:

1. Perfumes that are actually trending on YouTube appear in the top movers
2. The mention counts match real video volume (not inflated synthetic backfill)
3. Signal types (breakout, reversal, new_entry) correspond to real observable events
4. The relative ranking of perfumes matches external reference points (e.g. Dior Sauvage is consistently top-searched, Creed Aventus has stable premium positioning)

### Verification Workflow

After each ingestion run, verify in this order:

**Step 1 — Check entity_timeseries_daily**
```sql
SELECT entity_id, date, mention_count, composite_market_score
FROM entity_timeseries_daily
WHERE date = 'YYYY-MM-DD'
ORDER BY composite_market_score DESC
LIMIT 10;
```
Expected: top entities should match known popular perfumes, not random low-signal items.

**Step 2 — Check signals**
```sql
SELECT s.signal_type, e.canonical_name, s.strength, s.detected_at
FROM signals s
JOIN entity_market e ON s.entity_id = e.id
ORDER BY s.detected_at DESC
LIMIT 20;
```
Expected: signal_type and strength should be explainable from the timeseries data above.

**Step 3 — Cross-reference with external source**
Manually search YouTube for the top 3–5 entities returned.
Confirm that video volume and recency are consistent with the system's composite_market_score.

**Step 4 — Check for noise artifacts**
- Are there entities with 1 mention and a high composite score? → tune thresholds
- Are there synthetic backfill entities dominating over real-source entities? → fix date targeting
- Are reversals firing for entities that just switched from synthetic to real data? → check reversal_max_score_ratio

### Pagination Rule

**CRITICAL: Do not use page numbers.**

All pagination in ingestion scripts, API endpoints, and database queries must use:
- cursor-based pagination (nextPageToken for YouTube)
- offset-based pagination where cursor is unavailable

**Never pass `page=N` to any ingestion loop.**

YouTube Data API v3 uses `pageToken` (a string token). Passing a page number is not supported and produces incorrect results.

Correct pattern:
```python
next_page_token = None
while True:
    results = fetch_page(query, page_token=next_page_token, max_results=50)
    process(results)
    next_page_token = results.get("nextPageToken")
    if not next_page_token:
        break
```

### Verification Targets

Run verification against at least 3–5 well-known entities after each ingestion batch:

| Entity | Why it's a reference point |
|--------|---------------------------|
| Dior Sauvage | Consistently top-searched men's fragrance globally |
| Creed Aventus | Premium halo, consistent YouTube presence |
| MFK Baccarat Rouge 540 | Viral social proof, high engagement per video |
| Parfums de Marly Delina | Female equivalent of BR540 in creator content |
| YSL Libre | Major brand ad spend + creator coverage |

If these entities do not appear in the top 10 composite_market_score after a real ingestion run, treat it as a verification failure.

### Signal Validation Rules

**new_entry signals** must correspond to entities genuinely appearing for the first time with real content.
- If a new_entry fires for a synthetic backfill entity, it means the backfill data predated the real ingestion — that is expected behavior, not a bug, but must be noted.

**breakout signals** must correspond to a visible spike in video volume or engagement.
- Verify by checking `mention_count` and `engagement_sum` increased meaningfully from the prior day.

**reversal signals** must correspond to a genuine drop in attention, not a data-source transition.
- If a reversal fires on the first real ingestion day after backfill: check `reversal_max_score_ratio`. If the score ratio exceeds 4.0, the noise suppression should have blocked it. If it still fires, tighten the ratio.

### Noise Suppression Requirements

The following categories of false signals must be actively suppressed:

| Noise type | Suppression mechanism |
|------------|----------------------|
| Single-video breakout | `breakout_min_mentions >= 2` |
| Synthetic→real transition reversal | `reversal_max_score_ratio <= 4.0` |
| Low-volume reversal | `reversal_min_mentions >= 2` |
| Zero-history new entity with 1 mention | `new_entry` allowed but not breakout |

If any of these noise types appear in production signals, the thresholds must be tightened before new sources are added.

### Business Validity Rule

Every signal that reaches the frontend must pass a simple sanity check:

> "Would a fragrance market analyst agree this signal is meaningful?"

If the answer is "no" or "probably not", the signal should not appear in the terminal.

This does not require a human in the loop for every run. It requires:
- correct thresholds calibrated against real source behavior
- verified alignment between signal output and externally observable market events
- regular spot-checks as new sources are added

### Success Criteria

The system passes market reality verification when:

- [ ] Top 5 composite_market_score entities after real ingestion match known popular perfumes
- [ ] Breakout signals fire only for entities with >= 2 real mentions and >= 35% score growth
- [ ] Reversal signals do not fire for source-transition artifacts
- [ ] new_entry signals correspond to entities genuinely not seen before in the timeseries
- [ ] External YouTube search for top entities confirms video volume is consistent with system scores
- [ ] No entity with 1 mention appears in the top 5 composite_market_score ranking

### Accepted real source platforms for verification

Verification (`verify_market_state`) accepts the following as real data:

```
source_platform IN ("youtube", "reddit")
```

- `youtube` — API-fetched, always real
- `reddit` — public JSON endpoint fetched, counts as real
- `tiktok` — excluded from serving verification until Research API production approval
- `other` — treated as synthetic / legacy unless explicitly documented as real

### Critical Development Rule

**YouTube verification is complete and passing.**
**Reddit JSON ingestion is active and counts as a second verified real source.**
**TikTok ingestion into the serving DB is deferred until Research API credentials are approved.**

Serving DB must contain only items where `source_platform IN ("youtube", "reddit")` until TikTok is verified.

Rationale: one clean, verified source is more valuable than three unverified sources. Each new source must pass strict verification before being added to the serving layer.

### Principle

The product is not a data pipeline.

The product is:

👉 a market mirror

If the mirror is distorted, adding more data only amplifies the distortion.

---

## O1. Runtime and Database Selection

### Local runtime rule

For local review and terminal demo runs, the backend must point to the populated market engine database, not the legacy resolver database.

### Database files

| File | Purpose | Market rows |
|------|---------|-------------|
| `outputs/pti.db` | Legacy resolver DB (integer PKs, old schema) | None — do not use for API |
| `outputs/market_dev.db` | Market engine DB (UUID schema, V1 tables) | Populated demo data |

### Default DB selection

The FastAPI app and CLI jobs resolve the database in this order:

1. `DATABASE_URL` env var — PostgreSQL in production
2. `PTI_DB_PATH` env var — SQLite file path for dev/test
3. Hard default: `outputs/pti.db` (legacy — has no market data)

**The `.env` file sets `PTI_DB_PATH=outputs/market_dev.db` for the local demo build.**
This means the plain `uvicorn` startup command is sufficient — no manual env var prefix needed.

### Rule

If multiple databases exist:

* resolver DB (`pti.db`) is for identity resolution and bridge support
* market DB (`market_dev.db`) is for API serving and terminal frontend

The API serving layer must read from the populated market-serving database.

### Starting the backend locally

```bash
cd /Users/liliyabunos/Claude_projects/Perfume_Trend_Intelligence_SDK
python3 -m uvicorn perfume_trend_sdk.api.main:app --reload --port 8000
```

No `PTI_DB_PATH=...` prefix required. The `.env` file handles it.

### Running aggregation locally

```bash
cd /Users/liliyabunos/Claude_projects/Perfume_Trend_Intelligence_SDK
python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date YYYY-MM-DD
```

The job calls `load_dotenv()` at startup, so `.env` is respected automatically.

### Rules

* Never manually edit `outputs/market_dev.db` outside of the defined pipeline scripts.
* `outputs/pti.db` must not be passed to the FastAPI app — it has no `entity_market` rows.
* If `brand_name` is null for existing rows, re-run aggregation for the dates with data. The back-fill path in `_upsert_entity_market` will populate it.
* Future new sections in CLAUDE.md must follow the same letter+topic format (`D3.`, `O2.`, etc.) introduced here. Do not renumber existing sections 1–20.

---

## O2. Server Deployment & Soft Launch Layer (CRITICAL)

### Deployment Principle

The goal of this layer is to make the product accessible from an external server without local machine dependency.

This means:
- ingestion jobs run on a server (not on a developer's laptop)
- the API serves real data to real users
- the frontend is accessible from a public URL
- at least one external user can complete the full product workflow

### Database Strategy

**SQLite is for local development only.**

For production server deployment:
- Use PostgreSQL as the production database
- All storage interfaces must support both SQLite (dev) and PostgreSQL (prod) — no SQLite-specific SQL in production paths
- Connection string is set via `DATABASE_URL` environment variable
- SQLAlchemy ORM must handle dialect differences transparently

**Environment variable precedence (unchanged):**
1. `DATABASE_URL` — PostgreSQL in production (e.g. `postgresql://user:pass@host:5432/pti`)
2. `PTI_DB_PATH` — SQLite file path for dev/test
3. Hard default: `outputs/pti.db` (legacy — do not use for serving)

### Required Environment Variables (Production)

```
DATABASE_URL=postgresql://user:pass@host:5432/pti
YOUTUBE_API_KEY=...
OPENAI_API_KEY=...          # only if AI validation is enabled
SECRET_KEY=...              # for session tokens / magic link signing
```

Optional (override defaults):
```
PTI_ENV=production
LOG_LEVEL=INFO
```

### Scheduled Jobs

Production deployment requires the following scheduled jobs (cron or equivalent):

| Job | Schedule | Command |
|-----|----------|---------|
| Ingest YouTube | Every 2–6 hours | `python3 scripts/ingest_youtube.py --max-results 50 --lookback-days 2` |
| Ingest Reddit | Every 2–6 hours | `python3 scripts/ingest_reddit.py --lookback-days 1` |
| Aggregate metrics | Daily (after ingestion) | `python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date $(date +%Y-%m-%d)` |
| Detect signals | Daily (after aggregation) | `python3 -m perfume_trend_sdk.jobs.detect_signals --date $(date +%Y-%m-%d)` |
| Verify state | Daily | `python3 scripts/verify_market_state.py` |

**Rules:**
- Detect signals must run after aggregate — never before
- Verify state must run after detect — used to confirm no synthetic data leaked
- All jobs must be idempotent — re-running for the same date must not produce duplicates
- Job failures must be logged with enough detail to diagnose without SSH access

### API Serving

Serve the FastAPI backend via uvicorn behind a reverse proxy (nginx or Caddy recommended):

```bash
python3 -m uvicorn perfume_trend_sdk.api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Rules:
- Do not expose port 8000 directly — proxy through 443 (TLS)
- `--workers 2` is sufficient for soft launch volume
- Restart policy: always restart on crash (systemd or supervisor)

### Soft Launch Access Model

**Status: CONFIRMED WORKING in production (2026-04-17)**

V1 soft launch uses **frictionless magic link access** — no approval gate anywhere in the auth flow.

#### Canonical auth flow (verified end-to-end)

```
user enters email
→ LoginForm calls signInWithOtp via createOtpClient (plain @supabase/supabase-js, flowType:implicit)
→ Supabase sends magic link email
→ user clicks link
→ Supabase verifies token → redirects to /auth/callback#access_token=...&refresh_token=...
→ AuthCallbackPage (client component) manually parses window.location.hash
→ supabase.auth.setSession({ access_token, refresh_token })
→ @supabase/ssr stores session in httpOnly cookie
→ router.replace("/dashboard")
→ middleware: session present → pass
→ terminal layout: session present → render
```

#### Why manual hash parsing is required

`@supabase/ssr createBrowserClient` hardcodes `flowType:"pkce"` after spreading user options — the user-provided value is always overridden. A PKCE-wired client does not process `#access_token=` hash tokens. `getSession()` returns null and `onAuthStateChange` never fires → 8s timeout → `auth_failed`.

Fix: manually parse `window.location.hash` and call `setSession()` directly on the `@supabase/ssr` client. This bypasses the PKCE-only `detectSessionInUrl` behavior while keeping cookie storage intact.

#### Access gate state

- login page: no pre-check, `signInWithOtp` always fires
- `/auth/callback`: no approval check, session → `/dashboard`
- middleware: Supabase session check only, no `app_users` lookup
- terminal layout: Supabase session check only, no `app_users` lookup
- `app_users` table and `isApprovedUser` guard remain in codebase, inactive
- future gating: payment/subscription layer (Stripe), not manual approval

#### Auth implementation notes

- OTP sending: `createOtpClient()` (`@supabase/supabase-js` direct, `flowType:implicit`, no session persistence)
- Session management: `createClient()` (`@supabase/ssr createBrowserClient`, httpOnly cookie storage)
- Callback route: `/auth/callback` — the only route that finalizes auth
- Root `/` is a Server Component and cannot process `#access_token=` hash — never use as redirect target
- `redirect_to` must be at the top level of the Supabase Admin `generate_link` payload — nested inside `options` is silently ignored

#### Lessons learned

- Do not use pre-approval as a login gate — it adds friction with no security benefit (Supabase controls identity)
- Do not rely on implicit hash parsing "by default" with `@supabase/ssr` — verify in production with a real magic link
- Test every auth flow in a clean browser window with a fresh email
- `redirect_to` in `generate_link` API goes at top level, not inside `options`
- Always verify the `redirect_to` value in the generated link URL before testing

### Minimal Product Shell (Required Before External Access)

Before any external user accesses the product, the following must exist:

| Page | Purpose | Required content |
|------|---------|-----------------|
| Landing page | First impression | 2–3 sentences about what PTI does, access request or invite flow |
| Privacy policy | Legal baseline | Data collection, retention, contact |
| Terms of use | Legal baseline | Acceptable use, no warranty |
| Login page | Access gate | Email input for magic link, or token field |

These pages do not need to be polished. They need to exist.

### Deployment Readiness Criteria

The product is ready for soft launch when ALL of the following are true:

- [ ] Ingestion runs without the developer's local machine
- [ ] PostgreSQL is the active production database
- [ ] API is accessible via a public HTTPS URL
- [ ] At least one scheduled job runs automatically on the server
- [ ] At least 1 external user can log in and view the dashboard with real data
- [ ] Landing page, privacy policy, and terms of use exist (minimal is acceptable)
- [ ] Verify state passes with no synthetic data in the serving DB

### Non-Goals for Soft Launch

Do not build before first external user has accessed the product:

- email notification delivery for alerts (in-app delivery is sufficient)
- team/multi-user watchlists
- complex RBAC or role system
- public marketing site
- full onboarding flow
- mobile-responsive layout (desktop terminal is acceptable for soft launch)
- uptime SLA or monitoring beyond basic process restart

### Principle

The soft launch goal is: **one real external user sees real fragrance market data on a server that runs without the developer present.**

Everything else is secondary to that milestone.

---

## O3. Railway Production Service Map & Runtime Guards

### Confirmed Railway production contour

The production Railway environment is split into these services:

| Role | Service | Runtime model |
|------|---------|---------------|
| Frontend | `pti-frontend` | always-on |
| FastAPI backend | `generous-prosperity` | always-on |
| Ingestion / scheduled jobs | `pipeline-daily` | cron / scheduled |
| PostgreSQL | `Postgres` | managed |

### Environment variable responsibilities

#### `generous-prosperity`
Required:
- `DATABASE_URL`
- `PTI_ENV=production`

Optional:
- `SECRET_KEY` only if backend-signed auth/session/token flows are enabled

Not required:
- `YOUTUBE_API_KEY`

#### `pipeline-daily`
Required:
- `DATABASE_URL`
- `PTI_ENV=production`
- `YOUTUBE_API_KEY`

Rule:
`pipeline-daily` must fail fast if `DATABASE_URL` is missing in production. It must never silently fall back to SQLite in production mode.

#### `pti-frontend`
Required:
- frontend public env vars only (e.g. API base URL, Supabase public vars as applicable)

Not required:
- `DATABASE_URL`
- `YOUTUBE_API_KEY`

### Production DB safety rule

In production, both backend and scheduled pipeline must use PostgreSQL via `DATABASE_URL`.

`PTI_ENV=production` must be set on all production compute services so missing `DATABASE_URL` fails fast instead of falling back to SQLite.

### Schema management rule

Production schema must be managed by Alembic migrations only.

Do NOT call:
- `Base.metadata.create_all(...)`

inside request-path dependency code.

Reason:
- `start.sh` already runs `alembic upgrade head`
- request-time schema creation is wasteful and can bypass migration discipline

### Auth secret rule

`SECRET_KEY` is required only if the backend directly signs:
- tokens
- sessions
- magic links
- JWT-like auth artifacts

If auth is fully delegated to Supabase frontend/server flows and the backend does not sign auth state, `SECRET_KEY` may remain unset until a backend-signed auth flow is introduced.

### Current confirmed state

- `YOUTUBE_API_KEY` belongs in `pipeline-daily`, not in backend API service
- `generous-prosperity` correctly uses production PostgreSQL
- `pipeline-daily` must explicitly set `PTI_ENV=production`
- request-time `create_all()` must be removed from API dependencies

---

## Entity Mentions Integrity Rule

`entity_mentions.entity_id` must always reference `entity_market.id`.

Do NOT write resolver perfume UUIDs or resolver IDs into `entity_mentions.entity_id`.

**Reason:** Entity pages, Recent Mentions, source intelligence, and driver analysis all join
`entity_mentions.entity_id` → `entity_market.id`. If a different UUID is stored
(e.g. `perfume_identity_map.market_perfume_uuid`), the join returns zero rows and
Recent Mentions shows empty — even when signals and timeseries are correct.

**Correct lookup in aggregator:**
```python
entity_uuid: Optional[uuid.UUID] = entity_uuid_map.get(canonical)  # entity_market.id
```

**Forbidden:**
```python
# DO NOT use — returns perfume_identity_map.market_perfume_uuid, not entity_market.id
uuid_str = identity_resolver.perfume_uuid(int(raw_eid))
```

**Historical fix:** `scripts/backfill_entity_mention_uuids.py` bridges via canonical_name:
`entity_mentions.entity_id` → `perfume_identity_map` (market_perfume_uuid → canonical_name)
→ `entity_market` (canonical_name → id). Run as a one-time backfill; idempotent.

**Applied:** 2026-04-24. Fixed 2,171 historical entity_mentions rows (791 exact canonical match,
1,380 concentration-suffix bridge). Result: 2,202/2,444 correctly linked; 98 signaling entities
now expose Recent Mentions in the UI.

---

## D5. Aggregation Layer Rules (Entity Consolidation + Chart Continuity)

### Core rules (MANDATORY)

1. **Market aggregation must collapse concentration suffixes into base perfume entities.**
   `"Dior Sauvage Eau de Parfum"` and `"Dior Sauvage"` are the same market entity.
   Concentration variants must not create separate market streams.

2. **Carry-forward rows are allowed only as zero-mention continuity rows.**
   They provide chart line continuity on quiet days. They must never carry forward
   non-zero mention counts, scores, or engagement values.

3. **Carry-forward must be bounded by a 7-day lookback.**
   An entity silent for 7+ consecutive real days stops receiving carry-forward rows
   automatically. The lookback window counts only `mention_count > 0` rows.

4. **Carry-forward rows must never inflate mentions, scores, growth, or signal logic.**
   Score=0, mentions=0. All signal detection thresholds (breakout_min_score=15,
   breakout_min_mentions=2) are above carry-forward values by design.

5. **Stale fragment entities must be cleaned if they predate consolidation fixes.**
   Pre-fix backfill may have written data to concentration-variant entities.
   Those rows pollute top movers rankings and must be deleted.

6. **Signal re-detection is required after fragment cleanup for affected historical dates.**
   Signal detection is idempotent — it clears stale signals before re-detecting.
   Always re-run `detect_breakout_signals --date <date>` for each affected date
   after running a fragment cleanup.

---

### Entity key normalisation (concentration suffix stripping)

The daily aggregator (`perfume_trend_sdk/analysis/market_signals/aggregator.py`)
normalises the resolver's `canonical_name` before using it as the market entity key.
Concentration suffixes are stripped from the END of the name using `_base_name()`.

Suffixes stripped (longest-first, iterative):
- `Extrait de Parfum` → `Eau de Parfum` → `Eau de Toilette` → `Eau de Cologne` → `Eau Fraiche` → `Extrait` → `Parfum`

The loop iterates until stable — handles double-suffixed names:
`"Baccarat Rouge 540 Extrait Extrait de Parfum"` → two passes → `"Baccarat Rouge 540"`.

Guard: if stripping would return an empty string (e.g. a single-word name like `"Parfum"`),
the original name is kept unchanged.

**Rule:** Resolver tables (`resolved_signals`, `perfume_identity_map`) are unchanged.
Normalisation is aggregation-layer only. The original `canonical_name` is preserved
in resolver storage for replay/debugging.

---

### Carry-forward rows

After the main snapshot write pass, the aggregator inserts zero-mention rows for
entities that were active in the past 7 days but produced no content on `target_date`.
This is implemented in `_carry_forward_quiet_entities()` in
`perfume_trend_sdk/jobs/aggregate_daily_market_metrics.py`.

**Row values:** `mention_count=0`, `engagement_sum=0`, `composite_market_score=0.0`,
`growth_rate=-1.0`, `momentum=acceleration=volatility=0.0`.

**Critical safeguard — perpetuation prevention:**
The 7-day activity window query must filter `AND mention_count > 0`.
Without this, carry-forward rows themselves count as activity, causing fragment
entities to receive carry-forward indefinitely even after all real data is gone.

**Three guarantees:**
1. Real rows for `target_date` are never overwritten (NOT IN guard).
2. Carry-forward rows do NOT extend the window — only real `mention_count > 0` rows count.
3. Re-running aggregation for the same date is idempotent.

---

### Fragment entity cleanup

If concentration-variant entity_market rows exist from a pre-normalisation backfill,
they must be deleted in FK order before they pollute top movers rankings.

**Deletion order (respect FK constraints):**
1. `entity_timeseries_daily` WHERE entity_id IN (fragment IDs)
2. `signals` WHERE entity_id IN (fragment IDs)
3. `entity_mentions` WHERE entity_id IN (fragment IDs)
4. `entity_market` WHERE canonical_name matches suffix pattern

**Fragment identification pattern (PostgreSQL):**
```sql
WHERE canonical_name ~* ' (Extrait de Parfum|Eau de Parfum|Eau de Toilette|Eau de Cologne|Eau Fraiche|Extrait|Parfum)$'
```

Use `~*` (case-insensitive) to catch mixed-case variants from the resolver.

**Always run a DRY-RUN SELECT first** to confirm the candidate list before executing DELETE.

**After cleanup — required signal re-detection:**
```bash
railway ssh --service generous-prosperity python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date <YYYY-MM-DD>
```
Run for each date that had fragment signals. Signal detection clears stale signals
for the target date before re-detecting — safe to run repeatedly.

---

### Signal metadata JSON safety

Signal metadata (stored in `signals.metadata_json`) must never contain non-finite
float values (`float("inf")`, `float("-inf")`, `float("nan")`). PostgreSQL JSON
rejects these as invalid tokens.

**Two-layer protection implemented:**
1. Detector (`detector.py`): caps `growth_pct` at `9999.9` when `prev_score == 0`.
2. Storage (`detect_breakout_signals.py`): `_sanitize_metadata()` replaces any
   remaining `inf`/`-inf` with `±9999.9` and `nan` with `None` before ORM flush.

---

### Verification queries after any aggregation or cleanup run

```sql
-- Fragments must be zero
SELECT COUNT(*) FROM entity_market
WHERE canonical_name ~* ' (Extrait de Parfum|Eau de Parfum|Eau de Toilette|Eau de Cologne|Eau Fraiche|Extrait|Parfum)$';

-- Top movers must be base entities only
SELECT e.canonical_name, t.composite_market_score, t.mention_count, t.date
FROM entity_timeseries_daily t
JOIN entity_market e ON e.id = t.entity_id
WHERE t.date = (SELECT MAX(date) FROM entity_timeseries_daily WHERE mention_count > 0)
  AND t.mention_count > 0
ORDER BY t.composite_market_score DESC
LIMIT 10;

-- Reference entity continuity check (Dior Sauvage, Creed Aventus, MFK BR540)
SELECT t.date, t.mention_count, t.composite_market_score
FROM entity_timeseries_daily t
JOIN entity_market e ON e.id = t.entity_id
WHERE e.canonical_name = 'Dior Sauvage'
ORDER BY t.date;
```

---

## D6. Production Schedule & Execution Model — COMPLETED 2026-04-17

### Implementation status

| Component | Status |
|-----------|--------|
| `pipeline-daily` (morning) | ACTIVE — cron `0 11 * * *` |
| `pipeline-evening` | ACTIVE — cron `0 23 * * *` |
| `pipeline-email` | CREATED — cron disabled, pending `send_daily_digest` implementation |
| Email digest job | NOT YET IMPLEMENTED |

All three Railway services are configured. Two cycles run fully automatically.
Email slot is reserved but inactive until `send_daily_digest.py` is built.

---

### Timezone

All scheduled times are defined in **UTC**.

| UTC | ET (standard) | ET (daylight) |
|-----|--------------|---------------|
| 11:00 | 06:00 EST | 07:00 EDT |
| 23:00 | 18:00 EST | 19:00 EDT |
| 00:00 | 19:00 EST | 20:00 EDT |

---

### Production schedule

| UTC | Railway service | cron | Script | Cycle |
|-----|----------------|------|--------|-------|
| 11:00 | `pipeline-daily` | `0 11 * * *` | `sh start_pipeline.sh` | Morning |
| 23:00 | `pipeline-evening` | `0 23 * * *` | `sh start_pipeline_evening.sh` | Evening |
| 00:00 | `pipeline-email` | *(disabled)* | `send_daily_digest` *(stub)* | — |

Steps within each cycle run sequentially inside the shell script (not separate cron entries):

**Morning cycle** (`start_pipeline.sh`): reset sequence → YouTube ingest → Reddit ingest → aggregate → detect signals → verify state

**Evening cycle** (`start_pipeline_evening.sh`): reset sequence → YouTube ingest → Reddit ingest → aggregate → detect signals *(no verify)*

---

### Service configuration

| Service | Config file | Start command | `DATABASE_URL` | `PTI_ENV` | `YOUTUBE_API_KEY` |
|---------|-------------|--------------|----------------|-----------|-------------------|
| `pipeline-daily` | `railway.pipeline.toml` | `sh start_pipeline.sh` | ✓ | `production` | ✓ |
| `pipeline-evening` | `railway.pipeline-evening.toml` | `sh start_pipeline_evening.sh` | ✓ | `production` | ✓ |
| `pipeline-email` | `railway.pipeline-email.toml` | echo placeholder | ✓ | `production` | — |
| `generous-prosperity` | `railway.toml` | `sh start.sh` | ✓ | `production` | — |
| `pti-frontend` | — | Next.js | — | — | — |

---

### Execution order rules

- Jobs must run in strict order within each cycle.
- Aggregation must run **after** both ingest jobs complete.
- Signal detection must run **after** aggregation completes.
- `verify_market_state` runs **once daily**, after the morning cycle only.
- The email report runs **once daily**, after the evening cycle is complete.
- No job in a cycle may start before the preceding job finishes.

---

### Safety guarantees

- All production jobs connect via `DATABASE_URL` (Railway PostgreSQL). No SQLite fallback.
- `PTI_ENV=production` enforced on all compute services — missing `DATABASE_URL` fails fast.
- All jobs are **idempotent** — re-running for the same date produces no duplicates.
- Scheduled jobs derive the target date from wall-clock UTC automatically.
  `--date` overrides are for manual backfill only.
- Schema managed exclusively by Alembic (`start.sh` runs `alembic upgrade head`).
  No `Base.metadata.create_all()` in any request path or job CLI.

---

### Failure handling

- If an ingest job fails, aggregation still runs on existing data. Ingestion is additive — a missed cycle is not fatal.
- If aggregation fails, signal detection must not run for that cycle.
- If signal detection fails, `verify_market_state` may still run (read-only).
- A failed evening cycle must not block the next morning cycle.
- All failures are logged with enough detail to diagnose without SSH access.

---

### Email reporting rules (for future implementation)

- Exactly **one report per calendar day** (UTC midnight boundary).
- Report content based on the latest completed evening cycle data.
- Deduplication check required before send — skip if report for the date already dispatched.
- Report must not send if the evening cycle has not completed successfully.
- Implementation requires: `RESEND_API_KEY`, `DIGEST_FROM_EMAIL`, `DIGEST_TO_EMAIL` env vars.
- Activate by: implementing `send_daily_digest.py` → uncommenting `cronSchedule` in
  `railway.pipeline-email.toml` → push → Railway picks up automatically.

---

## Phase U1 — Catalog Exposure in UI

### Target Type: PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `resolver_*` tables (migration 014 — already live)
- `entity_market` table (already live)

### Requires Commit / Push / Deploy: YES

### Expected UI Change: YES — screener gets mode tabs, entity page gets quiet state

### Goal

Expose the full resolver/catalog (56k perfumes, 1,600+ brands) to the UI.

Before Phase U1, the screener only showed entities with timeseries data from ingestion.
After Phase U1, users can browse, search, and discover all known entities regardless of ingestion activity.

### What was implemented

**Backend — `perfume_trend_sdk/api/routes/catalog.py`**
- `GET /api/v1/catalog/perfumes` — search resolver_perfumes, cross-ref entity_market
- `GET /api/v1/catalog/brands` — search resolver_brands, cross-ref entity_market
- `GET /api/v1/catalog/counts` — headline counts: known_perfumes, known_brands, active_today
- All endpoints gracefully return empty results for SQLite dev environments (resolver_* tables are Postgres-only)
- `entity_id` (market slug) is returned when entity has been resolved from content — null for catalog-only entries

**Registered in `main.py`**: `prefix="/api/v1/catalog"`, tag `catalog`

**Frontend — new types in `types.ts`**: `CatalogPerfumeRow`, `CatalogBrandRow`, `CatalogPerfumesResponse`, `CatalogBrandsResponse`, `CatalogCounts`, `CatalogParams`

**Frontend — `frontend/src/lib/api/catalog.ts`**: `fetchCatalogPerfumes`, `fetchCatalogBrands`, `fetchCatalogCounts`

**Frontend — screener page (`screener/page.tsx`)**:
- Mode tabs: "Active today" | "All Perfumes" | "All Brands"
- Active today: existing screener behavior (entity_market + timeseries)
- All Perfumes: server-side text search via `GET /api/v1/catalog/perfumes?q=`
- All Brands: server-side text search via `GET /api/v1/catalog/brands?q=`
- Catalog table rows: "Tracked" badge (green) if entity_id present, "In Catalog" badge (grey) if not
- Tracked rows navigate to entity page; catalog-only rows are non-clickable
- Header subtitle shows catalog totals from `/api/v1/catalog/counts`

**Frontend — entity page quiet state**:
- If `summary.last_score == null && summary.mention_count == null`, show a gray banner:
  "This entity is known to the catalog but has not appeared in any ingested content yet."

### Completion Criteria

- [ ] `GET /api/v1/catalog/perfumes` returns results from resolver_perfumes in production
- [ ] `GET /api/v1/catalog/brands` returns results from resolver_brands in production
- [ ] `GET /api/v1/catalog/counts` returns 56k+ known_perfumes, 1,600+ known_brands
- [ ] Screener mode tabs visible in frontend
- [ ] "All Perfumes" tab shows catalog rows with server-side search
- [ ] Tracked entities navigate to entity page; catalog-only rows show "In Catalog" badge
- [ ] Entity page shows quiet state banner for entities with no market data

---

## Phase D1.0 — Auth Stabilization Before Domain Migration

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- `frontend/next.config.ts` (build-time env embedding)
- `frontend/src/app/(public)/login/page.tsx` (Server Component — runtime key pass)
- `frontend/src/app/(public)/login/LoginForm.tsx` (Client Component — prop receiver)
- `frontend/src/lib/auth/otp-client.ts` (OTP dispatch — accepts key param)

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES — login page becomes fully functional; OTP dispatch works

### Status
COMPLETED — 2026-04-26

---

### Root Cause Sequence

**Problem 1 — "This page couldn't load" on login (critical)**

`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` were not embedded
in the Turbopack client bundle. Root cause: Nixpacks ran the Next.js build before
these vars were available in Railway service env. Turbopack (unlike Webpack) does not
statically replace `process.env.NEXT_PUBLIC_*` at build time — it uses a runtime
`e.default.env.NEXT_PUBLIC_*` accessor which resolves through module 47167 →
module 35451 (browser `process` polyfill with empty `env: {}`) → `undefined`.

Effect: `createBrowserClient(undefined!, undefined!)` → client JS crash on load →
"This page couldn't load".

**Problem 2 — HTTP 500 after first fix attempt**

Added `NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ""`
to `next.config.ts` env block. Turbopack inlined `""` as a literal string. Supabase
SSR client (`createServerClient`) validates the anon key is non-empty — throws during
SSR → Railway edge returns 500 for all routes. Service was down ~15 minutes (12:47–13:09 UTC).

**Problem 3 — Anon key still undefined in browser after second fix**

Removed `?? ""` fallback — service returned 200. But Turbopack still emits a dynamic
accessor for `NEXT_PUBLIC_SUPABASE_ANON_KEY` (it cannot inline `undefined`). Login
page renders but OTP submission fails: Supabase rejects an undefined anon key.

---

### Fix Architecture

Three commits applied in sequence:

**Commit a84e180** — Added `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ""`,
`NEXT_PUBLIC_SITE_URL` to `next.config.ts` env block. Fixed URL embedding; caused 500 on anon key.

**Commit 41f0559** — Removed `?? ""` fallback from `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Stopped
500; URL embedded correctly; anon key still undefined in browser.

**Commit 169f415** — Server-prop pattern: `LoginPage` (Server Component) reads
`process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY` from Railway runtime env (always available
to Server Components regardless of build-time embedding), passes it as `supabaseAnonKey`
prop to `LoginForm`. `createOtpClient(anonKey: string)` accepts key as parameter.

No hardcoded secrets. Works regardless of whether Nixpacks embeds the var at build time.

---

### Files Changed

| File | Change |
|------|--------|
| `frontend/next.config.ts` | Added `env` block: URL (hardcoded fallback), ANON_KEY (no fallback), SITE_URL (hardcoded fallback) |
| `frontend/src/app/(public)/login/page.tsx` | Reads anon key server-side, passes to LoginForm |
| `frontend/src/app/(public)/login/LoginForm.tsx` | Accepts `supabaseAnonKey` prop, passes to createOtpClient |
| `frontend/src/lib/auth/otp-client.ts` | `createOtpClient(anonKey: string)` — key as param |

---

### Key Architectural Insights (do not repeat these mistakes)

1. **Turbopack does not statically replace process.env like Webpack.** It generates a
   dynamic accessor. Only vars with hardcoded literal fallbacks in `next.config.ts` env
   block get inlined as strings.

2. **`?? ""` empty-string fallback for Supabase credentials causes SSR 500.** Supabase
   validates that both URL and anon key are non-empty strings during server client creation.

3. **Server Components always have Railway runtime env.** For secrets that must not be
   hardcoded, pass from Server Component → Client Component as props instead of relying on
   `NEXT_PUBLIC_*` build-time embedding.

4. **`healthcheckPath` in `frontend/railway.toml` causes failures.** Supabase middleware
   intercepts health check requests. Use Railway TCP health check (no `healthcheckPath`).
   (See feedback_railway_healthcheck.md memory.)

5. **Login page renders even with undefined anon key.** `createOtpClient()` is called on
   submit, not on render. Missing key causes OTP failure, not page load failure.

---

### Completion Criteria — Status

> ⚠️ Prior D1.0 report (commit 169f415) incorrectly claimed login page renders.
> Browser DevTools showed `<html id="__next_error__">` — the form was NOT rendering.
> HTTP 200 does NOT prove SSR succeeded. Root cause was a 4th problem (see below).

**Problem 4 — Middleware crashes for all public routes (actual root cause of __next_error__)**

`refreshSessionAndContinue()` was calling `buildSupabaseClient()` even for public
routes like `/login`. `buildSupabaseClient` calls `createServerClient(url, anon_key, ...)`.
If `NEXT_PUBLIC_SUPABASE_ANON_KEY` is undefined at build time, `createServerClient`
throws `"supabaseKey is required"` synchronously inside middleware. A synchronous
throw in Next.js middleware causes the framework to render `<html id="__next_error__">`
for every affected request — including `/login` — even with HTTP 200 status.

**Fix — commit 679c319:**
- `refreshSessionAndContinue` now just returns `NextResponse.next()` — no Supabase call.
  Public routes need no session refreshing.
- `guardProtectedRoute` now guards against missing credentials (fails safe → redirect to login
  instead of crashing) before calling `buildSupabaseClient`.

**Lesson learned:** HTTP 200 + `__next_error__` in HTML is a valid combination in Next.js.
Always check the rendered HTML in DevTools Elements, not just the network status code.

---

### Verification Required After Railway Deploy (commit 679c319)

- [ ] `/login` renders the email form in browser (no `__next_error__`, no console crash)
- [ ] DevTools Elements no longer shows `<html id="__next_error__">`
- [ ] Browser Console tab shows no fatal errors (supabaseKey, process, undefined)
- [ ] Submit email → OTP request fires → Supabase dispatches magic link
- [ ] Magic link email received
- [ ] `/auth/callback` sets session → redirects to `/dashboard`
- [ ] Dashboard loads with real data

---

### All commits in D1.0

| Commit | Effect |
|--------|--------|
| `a84e180` | Added Supabase vars to `next.config.ts` env block; `?? ""` fallback caused HTTP 500 |
| `41f0559` | Removed `?? ""` fallback — 500 gone; URL embedded; anon key still undefined in browser |
| `169f415` | Server-prop: LoginPage passes anon key to LoginForm; `createOtpClient(anonKey)` param |
| `687e44c` | Docs: added D1.0 section (SUPERSEDED by this correction) |
| `679c319` | **Real fix**: middleware no longer calls createServerClient for public routes |

---

## Current System Status

**As of 2026-04-17**

| Component | Status |
|-----------|--------|
| Production pipeline | ACTIVE |
| Scheduling | FULLY AUTOMATED — 2× daily (11:00 UTC + 23:00 UTC) |
| Data source: YouTube | ACTIVE |
| Data source: Reddit | ACTIVE |
| Data source: TikTok | DEFERRED — pending Research API approval |
| Timeseries continuity | VERIFIED — continuous lines, carry-forward working |
| Fragment entity consolidation | COMPLETE — 53 concentration-variant rows cleaned |
| Signal detection | VERIFIED — no duplicate signals, Infinity JSON bug fixed |
| Email reporting | NOT YET IMPLEMENTED |
| Frontend terminal | ACTIVE — live data, real signals |
| Auth (login + magic link) | FIXED — commit 169f415, 2026-04-26 |

---

## D7. Coverage Expansion Strategy

PTI must not rely on live ingestion alone to build market coverage.

Live ingestion (YouTube, Reddit) is optimized for **detecting fresh market movement**, not for constructing a complete perfume universe.

### Core Rule

Do NOT attempt to reach full perfume coverage through YouTube or Reddit queries alone.

### Coverage Expansion Must Combine

1. Seed / Knowledge Base imports (Kaggle, curated datasets)
2. External metadata enrichment (Fragrantica)
3. Discovery loop (candidate → validation → promotion)
4. Historical backfill (pre-project data)

### Coverage Objective

The system must continuously expand:
- number of known perfumes
- number of known brands
- metadata completeness (notes, accords, brand info)

Coverage growth is a **first-class objective**, separate from signal detection.

---

## D8. Knowledge Base Operational Status

A first-generation Knowledge Base (KB) is already implemented.

### Current KB (v1)

Primary resolver database: `pti.db`

Contains:
- fragrance_master (~2,240 rows)
- aliases (~12,770 rows)
- brands
- perfumes

Market-serving database: `market_dev.db` / PostgreSQL production

Contains:
- brands (UUID schema)
- perfumes (UUID schema)
- identity maps (resolver → market)

### Important Distinction

This KB is **already operational**, not theoretical.

The goal is NOT to rebuild it, but to:

- stabilize production-safe seeding
- expand metadata completeness
- integrate enrichment layers
- improve linkage with market entities

### Rule

All ingestion and resolution must use the KB as the **source of truth for entity identity**.

---

## D9. Historical Backfill Layer

Historical data must be collected through a dedicated backfill layer.

### Purpose

- Populate pre-project history
- Increase entity coverage
- Improve chart continuity
- Reduce "cold start" effect

### Sources

- YouTube historical queries
- Reddit historical fetch
- Fragrantica catalog/discovery
- (Optional future) Google Trends

### Rules

- Backfill is NOT part of daily/evening pipelines
- Backfill runs as separate jobs
- Backfill must be idempotent
- Backfill must write through canonical storage (same schema as live ingestion)

### Implementation Model

Backfill jobs may be chunked by:
- brand
- perfume
- date range
- source platform

Backfill must not interfere with real-time ingestion performance.

---

## D10. Fragrantica Enrichment Activation

Fragrantica integration is implemented at the code level but not operationally active.

### Current State

| Component | Status |
|-----------|--------|
| connector | implemented |
| parser | implemented |
| normalizer | implemented |
| enricher | implemented |
| workflow | manual CLI only |
| DB persistence | MISSING |
| pipeline integration | MISSING |
| raw data storage | MISSING |

### Required Behavior

Fragrantica enrichment must:

1. Fetch raw HTML
2. Store raw payloads
3. Parse structured fields
4. Normalize records
5. Persist to DB-backed tables
6. Merge into product metadata layer

### Required Data

- notes (top / middle / base)
- accords
- rating (value + count)
- release year
- perfumer
- gender
- similar perfumes

### Critical Rule

Enrichment must write to structured database tables, not only JSON files.

---

## D11. Notes & Accords Intelligence Layer

Notes and accords are first-class analytical entities.

### Required Tables

- `notes`
- `accords`
- `perfume_notes` (many-to-many)
- `perfume_accords` (many-to-many)

### Required Capabilities

- perfume entity page must expose notes and accords
- dashboard must support:
  - rising notes
  - note spikes
  - accord spikes
- note-level scoring must be possible

### Data Sources

- Fragrantica (primary)
- curated mappings
- future extraction from content text

### Rule

A perfume entity is considered metadata-incomplete if notes or accords are missing and external sources can provide them.

### Strategic Value

Notes and accords enable:
- cross-perfume trend analysis
- ingredient-level intelligence
- early detection of emerging scent trends

---

## D12. Brand Intelligence Layer

Brands are first-class entities and must be fully represented.

### Required Brand Metadata

- canonical name
- website
- description
- country of origin
- founding year (optional)
- perfume count
- tracked perfume count

### Required Capabilities

- brand entity page must exist
- brand page must show:
  - linked perfumes
  - trend contribution
  - top notes / accords across brand portfolio
- brand must be linkable to external website

### Rule

Brand data must not remain implicit via perfume rows alone.
Brand identity must be explicit and queryable.

---

## D13. Discovery & Self-Improving Knowledge Loop

The system must continuously learn new entities from unresolved content.

### Core Concept

Unknown entities must NOT be discarded.

### Required Table: fragrance_candidates

| Field | Type | Notes |
|-------|------|-------|
| raw_text | text | original unresolved mention |
| normalized_text | text | cleaned version |
| source | text | platform origin |
| occurrences | int | mention count |
| first_seen | timestamp | |
| last_seen | timestamp | |
| confidence | float | rule-based or AI score |
| status | enum | `new` / `validated` / `rejected` |

### Flow

```
ingestion → unresolved mention
→ fragrance_candidates table
→ aggregate by frequency
→ validate via:
    deterministic rules
    KB matching
    recurrence threshold
    optional AI arbitration
→ promote to:
    fragrance_master
    aliases
    brands / notes
```

### Rule

Discovery must be deterministic-first, AI-last.

### Goal

Transform unknown ingestion data into structured KB knowledge automatically.

---

## D14. Entity Coverage Maintenance Service

A dedicated service must maintain completeness of known entities.

### Purpose

- ensure data freshness
- repair missing metadata
- prevent broken or sparse entities

### Responsibilities

- detect stale entities (no recent mentions)
- detect metadata gaps (missing notes, accords, brand info)
- detect fragmented entities (concentration-suffix duplicates)
- schedule targeted refresh jobs

### Example Maintenance Queues

- `stale_entity_queue` — entities with no recent timeseries rows
- `metadata_gap_queue` — entities with NULL notes_summary or accords
- `fragment_merge_queue` — concentration-variant duplicates
- `missing_brand_info_queue` — entities with brand_name IS NULL
- `missing_note_info_queue` — perfumes with no note associations

### Rule

This service maintains known entities.
It is NOT responsible for discovering new trends.

---

## O5. Resolver DB Path Rule

Production resolver state must be updated in the production-path resolver database.

### Rule

For any KB-changing phase (Phase 4b, 4c, and future promotion phases):

- do NOT assume `outputs/pti.db` is the production resolver source
- the authoritative production-path resolver DB is `data/resolver/pti.db`

### Requirement

All promotion runs that mutate KB state must target the resolver DB actually used by deployment/runtime.

Run promotion jobs as:
```bash
RESOLVER_DB_PATH=data/resolver/pti.db PTI_DB_PATH=outputs/market_dev.db \
  python3 -m perfume_trend_sdk.jobs.<phase_job> ...
```

Or copy after a local run:
```bash
cp outputs/pti.db data/resolver/pti.db
```

### Verification

After any KB mutation phase, always verify both DBs:

```bash
sqlite3 data/resolver/pti.db "SELECT COUNT(*) FROM perfumes; SELECT COUNT(*) FROM aliases; SELECT COUNT(*) FROM fragrance_master;"
sqlite3 outputs/pti.db         "SELECT COUNT(*) FROM perfumes; SELECT COUNT(*) FROM aliases; SELECT COUNT(*) FROM fragrance_master;"
```

Counts must match. New entities and aliases must appear in `data/resolver/pti.db` before committing and pushing.

### Why this matters

`data/resolver/pti.db` is the file checked into git and deployed to Railway. `outputs/pti.db` is a local working copy only — it is gitignored in effect (large binary, not pushed routinely). A KB change applied only to `outputs/pti.db` is invisible to the production pipeline until `data/resolver/pti.db` is updated and pushed.

**Incident reference:** Phase 4b+4c (2026-04-21) — all KB changes were applied only to `outputs/pti.db`. Production resolver was stale for 5 days (April 16–21). Fixed by commit 3de63d1.

---

## O6. Deployment Target Rule

Every phase must explicitly declare its execution target before implementation.

### Allowed target types

1. `LOCAL_ONLY`
2. `PRODUCTION_TARGETED`
3. `BUNDLED_LATER`

### Definitions

#### LOCAL_ONLY

Used for:
- experiments
- partial code work
- local DB exploration
- prototype logic

Rules:
- do not mark as production-complete
- do not assume UI/API will change
- do not treat local DB mutations as deployed state

#### PRODUCTION_TARGETED

Used for:
- schema migrations
- pipeline changes
- KB mutations intended for live resolver
- serving-layer changes
- anything expected to affect API/UI

Rules:
- must identify the authoritative production DB/file path
- must commit and push
- must deploy to Railway
- must verify production state after deploy
- phase is not complete until production verification passes

#### BUNDLED_LATER

Used when a phase is intentionally developed in parts and released later as one combined deploy.

Rules:
- must explicitly say:
  - "do not commit as final phase"
  - "bundle with Phase X"
- must not be described as done in production
- must be marked as deferred for deploy

### Required declaration in every phase prompt

Before implementation, each phase prompt must state:

- `target_type`: LOCAL_ONLY / PRODUCTION_TARGETED / BUNDLED_LATER
- authoritative DB/file targets
- whether commit/push/deploy is required
- whether UI/API changes are expected immediately

### Critical KB rule

For any KB-changing phase (promotion, alias creation, new entities):
- do not write only to working-copy DBs such as `outputs/pti.db`
- write to the authoritative resolver DB used by runtime/deploy
- verify resolver row counts and new aliases/entities in the production-path DB

### Completion rule

A phase may be marked fully complete only if its declared target has been satisfied.

| Target type | Completion criteria |
|-------------|-------------------|
| LOCAL_ONLY | locally verified only |
| PRODUCTION_TARGETED | deployed and production-verified |
| BUNDLED_LATER | implemented but not yet released |

**Incident references:**
- Phase 4b+4c (2026-04-21) — KB changes written only to `outputs/pti.db` (working copy), not to `data/resolver/pti.db` (production path) → resolver stale for 5 days. Covered by O5.
- Phase 3 (2026-04-21) — `aggregate_candidates` and `validate_candidates` implemented but not added to production pipeline scripts → Phase 3B inactive in production until explicit activation check.

---

## O4. Backup & Recovery Policy

Backups are mandatory for all production data layers.

### Required Backup Types

**1. Database snapshots**
- daily automated snapshot
- weekly retained
- monthly archived

**2. Raw data archives**
- YouTube payloads (JSONL per run)
- Reddit payloads (JSONL per run)
- Fragrantica HTML (when enrichment is active)

**3. Knowledge Base exports**
- fragrance_master
- aliases
- brands
- perfumes
- notes (when populated)
- accords (when populated)
- identity maps (brand_identity_map, perfume_identity_map)

### Rules

- backups must be automated
- backups must be versioned with timestamp
- restore must be tested before a backup is considered valid

### Critical Rule

A backup is not valid until a restore has been verified against a test environment.

---

## Current Data Layer Status (v1)

**As of 2026-04-22**

| Layer | Status |
|-------|--------|
| Knowledge Base (seed) | OPERATIONAL — Kaggle + curated, ~2,240 perfumes |
| Live ingestion | OPERATIONAL — YouTube + Reddit, 2× daily |
| Fragrantica enrichment | OPERATIONAL via local bridge · 35 records · Railway IPs still blocked |
| Notes / accords layer (Fragrantica) | OPERATIONAL — 137 notes, 324 perfume_notes in production |
| Notes / accords layer (dataset bulk) | OPERATIONAL — 272,622 notes · 132,954 accords · 26,799 perfumes covered (Phase 1B, 2026-04-22) |
| Notes / accords UI layer | OPERATIONAL — Phase 2R deployed 2026-04-22 |
| Discovery loop | OPERATIONAL — fragrance_candidates, aggregate_candidates, validate_candidates |
| Coverage maintenance service | OPERATIONAL — Phase 5 |
| Historical backfill layer | NOT IMPLEMENTED |
| Backup policy | NOT YET IMPLEMENTED |

### Current Priority Order

1. ~~Stabilize KB production seeding~~ — **DONE (Phase 0)**
2. ~~Activate Fragrantica enrichment (DB tables + pipeline integration)~~ — **DONE (Phase 1R)**
3. ~~Add notes / accords tables + populate from Fragrantica~~ — **DONE — 137 notes, 324 perfume_notes**
4. ~~Bulk notes backfill from Parfumo dataset (Phase 1B)~~ — **DONE (2026-04-22) — 272,622 notes, 132,954 accords, 26,799 perfumes covered**
5. ~~Notes & accords UI rollout (Phase 2R)~~ — **DONE (2026-04-22)**
6. Build historical backfill layer
7. Implement backup policy

---

## Phase 1 — Fragrantica Enrichment Activation

### Status
- Code complete
- Deploy complete
- Production DB path verified
- Production blocked by Fragrantica HTTP 403

### Verified in production
- Alembic migration 008 applied successfully
- Production PostgreSQL contains:
  - fragrantica_records
  - notes
  - accords
  - perfume_notes
  - perfume_accords
- identity map lookup works
- DB persistence path works
- notes_summary update path works

### External blocker
Live Fragrantica fetch from Railway IPs returns HTTP 403.
This is an external access constraint, not a schema or persistence bug.

### Rule
Phase 1 is not considered fully source-operational until the fetch layer is upgraded
to a Playwright-based or cookie-backed client and a real enrichment batch succeeds.

---

## Phase 1b — Fragrantica Access Layer (COMPLETED)

### Status

- Code complete
- Fetch layer operational (via CDP client)
- End-to-end enrichment pipeline verified
- Production automation pending (infra constraint)

### What was achieved

Cloudflare 403 protection was bypassed using a Chrome DevTools Protocol (CDP) client.

Instead of direct HTTP requests, the system:
- connects to a real Chrome session
- reuses an authenticated browser context
- fetches HTML through the browser

### Results (validated)

- HTTP 403 errors: eliminated
- successful fetch rate: ~90%+
- real HTML parsed from Fragrantica SPA
- notes / accords extracted correctly
- DB persistence verified:
  - fragrantica_records
  - notes
  - perfume_notes
  - perfume_accords
- notes_summary successfully updated

### Parser updates

- Fragrantica migrated to Vue.js SPA
- parser updated to support:
  - span.pyramid-note-label
  - dynamic content containers

### URL resolution

- slug-only URLs may return 404
- system now resolves canonical URLs via search before fetch

### Current limitation

CDP client requires a locally running Chrome instance.

Production (Railway) cannot yet run:
- browser session
- CAPTCHA / Cloudflare bypass

### Classification

Fragrantica integration is now:

- fully operational (data layer)
- partially operational (production automation)

### Rule

All enrichment logic is considered complete.

Remaining work is strictly infrastructure:
- remote browser execution
- proxy / CAPTCHA bypass
- or hybrid local enrichment pipeline

No further changes to parser / enrichment / DB schema are required.

---

## Phase 1R — Fragrantica Enrichment Recovery (COMPLETED)

### Status
- Code complete
- Local enrichment bridge operational
- Production PostgreSQL populated with real notes data
- Railway production fetch still blocked by Cloudflare IP restriction

### What was achieved

Phase 1R unblocked the Fragrantica enrichment pipeline end-to-end.

Root cause (fixed): `FragranticaClient` used `User-Agent: PTI-SDK/1.0` which Fragrantica's bot
detection immediately blocked. Fixed to realistic Chrome User-Agent.

Larger blocker: Cloudflare blocks all requests from Railway datacenter IPs with HTTP 403.
This applies regardless of User-Agent or TLS fingerprint (including `curl_cffi chrome120`).

Resolution: **Local enrichment bridge** — run `enrich_from_queue.py` on the local machine
(not blocked by Cloudflare) with `DATABASE_URL` pointing to production PostgreSQL.
Fetch happens locally; persist goes directly to production DB.

### Key implementations

**`perfume_trend_sdk/jobs/enrich_from_queue.py`** (new job):
- Queue loader with `resolver_fragrance_master` JOIN filter (only loads resolvable entities)
- Identity resolution via `entity_market.id → canonical_name → resolver_fragrance_master`
  (NOT via `perfume_identity_map` which has stale UUIDs from old seeding)
- Multi-strategy fetch: curl_cffi → Playwright → plain requests
- Search-based URL resolution: Fragrantica requires numeric ID in URL
  (`/perfume/Brand/Name-12345.html`). Slug-only URLs return 404.
  - Strategy A: Fragrantica search redirect detection (works for popular perfumes)
  - Strategy B: DuckDuckGo HTML search for canonical URLs with numeric IDs
  - Rate limiting: DDG shows CAPTCHA after ~2 rapid requests; add delays between searches

### Production verification

6 perfumes enriched in production (2026-04-22):

| Perfume | Notes extracted |
|---------|----------------|
| Parfums de Marly Layton | Top: Apple, Lavender, Bergamot; Mid: Geranium, Violet, Jasmine; Base: Vanilla, Cardamom, Sandalwood |
| Parfums de Marly Pegasus | Top: Heliotrope, Cumin, Bergamot; Mid: Bitter Almond, Lavender, Jasmine; Base: Vanilla, Sandalwood, Amber |
| Dior Sauvage | Top: Calabrian bergamot, Pepper; Mid: Sichuan Pepper, Lavender; Base: Ambroxan, Cedar |
| Creed Aventus | Top: Geranium, Cumin, Bergamot; Mid: Oakmoss, Oud; Base: Sandalwood, Musk |
| Chanel Bleu de Chanel | Record created, Vue.js notes rendering required for extraction |
| Tom Ford Black Orchid | Record created, Vue.js notes rendering required for extraction |

Production counts: `fragrantica_records=35`, `notes=137`, `perfume_notes=324`

### Local enrichment run command

```bash
DATABASE_URL="<production-public-url>" \
python3 -m perfume_trend_sdk.jobs.enrich_from_queue --limit 10
```

For items where DDG search fails (rate-limited), use the direct-URL approach with known
Fragrantica numeric IDs. The queue sets `fragrance_id` when a real Fragrantica ID is available;
`_build_url` uses that directly if present.

### Rule

Phase 1R local bridge is the operational path until Railway IPs are unblocked.
Phase 1c (full production automation) remains deferred — see that section for details.

---

## Phase 1B — Bulk Notes Backfill (Dataset-Based)

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `resolver_perfume_notes` (migration 017)
- `resolver_perfume_accords` (migration 017)
- entity API (`/api/v1/entities/perfume/{id}`)

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES — notes appear at scale in entity pages for both tracked and catalog-only perfumes

---

### Problem

Fragrantica enrichment covers only 35 perfumes (blocked from Railway by Cloudflare).
The full 56k catalog has no notes/accords data in production.

The Parfumo dataset (TidyTuesday 2024-12-10, `parfumo_data_clean.csv`) which was used
to seed `resolver_perfumes` in Phase 5 also contains structured notes and accords columns:
- `Top_Notes`, `Middle_Notes`, `Base_Notes` — comma-separated ingredient lists
- `Main_Accords` — comma-separated accord names

Importing this dataset's notes covers the full 56k catalog at zero cost — no scraping,
no AI, no external service calls.

---

### What was implemented

**Alembic migration 017** — `resolver_perfume_notes` + `resolver_perfume_accords` tables:
- Integer FK to `resolver_perfumes.id` (not entity_market UUIDs)
- Covers all 56k resolver catalog entries regardless of ingestion activity
- UNIQUE on `(resolver_perfume_id, normalized_name, position)` — idempotent inserts
- `source` column: `parfumo_v1` for imported rows, `fragrantica_v1` for scrape future

**`scripts/import_dataset_notes.py`** — production import script:
- Downloads Parfumo CSV from TidyTuesday (cached in `/tmp/`)
- Builds resolver lookup: 2 key strategies (brand+perfume, full canonical)
- Auto-detects table names: `resolver_perfumes` (Postgres) or `perfumes` (SQLite legacy)
- ON CONFLICT DO NOTHING — fully idempotent, safe to re-run
- Batch commits (500 rows), progress logging
- `--dry-run` mode for safe preview
- `--verify-only` for post-run checks
- Source tagging for rollback: `DELETE FROM resolver_perfume_notes WHERE source='parfumo_v1'`

**Entity API** (`entities.py`) — two-layer fallback:
1. `_fragrantica_notes()` — reads from `fragrantica_records` (scrape quality, highest priority)
2. `_resolver_notes()` — reads from `resolver_perfume_notes` (dataset quality, fallback)
3. Combined in `_get_perfume_notes()` — prefer fragrantica, fall back to dataset
4. Catalog-only entities (no entity_market row) now also get notes from `_resolver_notes()`

---

### Production run command

```bash
# Step 1 — apply migration (run automatically via alembic upgrade head on deploy)
# Or manually: railway run --service generous-prosperity alembic upgrade head

# Step 2 — dry-run preview
railway run --service pipeline-daily \
  python3 scripts/import_dataset_notes.py --dry-run

# Step 3 — bounded first run (500 rows to validate)
railway run --service pipeline-daily \
  python3 scripts/import_dataset_notes.py --limit 500

# Step 4 — full run
railway run --service pipeline-daily \
  python3 scripts/import_dataset_notes.py

# Step 5 — verify
railway run --service pipeline-daily \
  python3 scripts/import_dataset_notes.py --verify-only
```

---

### Expected results (after full production run)

| Metric | Expected |
|--------|----------|
| Matched resolver_perfumes | ~45,000–50,000 (80-90% of 56k) |
| resolver_perfume_notes rows | ~150,000–300,000 |
| resolver_perfume_accords rows | ~100,000–200,000 |
| Perfumes with any notes | ~40,000+ |
| Entity API notes for catalog-only | ALL matched catalog perfumes |
| Fragrantica notes priority | Unchanged — still preferred |

---

### Rollback

```sql
DELETE FROM resolver_perfume_notes WHERE source = 'parfumo_v1';
DELETE FROM resolver_perfume_accords WHERE source = 'parfumo_v1';
```

---

### Status
- Code complete ✅
- Migration 017 written ✅
- Entity API updated ✅
- Committed and pushed ✅
- Production run: COMPLETED ✅ (2026-04-22)

### Production Results (verified 2026-04-22)

| Metric | Value |
|--------|-------|
| Dataset rows processed | 59,325 |
| Matched to resolver | 52,748 (88.9%) |
| resolver_perfume_notes rows | 272,622 |
| resolver_perfume_accords rows | 132,954 |
| Perfumes with notes | 26,799 |
| Perfumes with accords | 27,880 |
| Idempotency | ✅ verified — second run: counts unchanged |
| Catalog-only entity API | ✅ notes returned for resolver_id-based lookups |
| Fragrantica priority | ✅ confirmed — Fragrantica notes returned when present |
| Dataset fallback | ✅ confirmed — resolver_perfume_notes used when no Fragrantica record |

---

## Phase 2R — Notes & Accords UI Rollout (COMPLETED)

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `resolver_perfume_notes`, `resolver_perfume_accords` (migration 017)
- `fragrantica_records`, `notes`, `perfume_notes` (migration 008)
- Backend entity + dashboard + notes APIs
- Frontend entity pages + screener

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES — notes visible on all entity pages, note filter in screener, note chips in screener table

### Status
COMPLETED — 2026-04-22

---

### What was implemented

**Backend — `entities.py`**
- `_get_perfume_notes()` returns 5-tuple `(top, mid, base, accords, source)` where source is `"fragrantica"` | `"parfumo"` | `None`
- `_similar_by_notes(db, resolver_id, limit=8)` — self-JOIN on `resolver_perfume_notes.normalized_name` to find perfumes sharing the most notes with a target
- `_brand_top_notes(db, brand_canonical_name, limit=15)` — aggregated top notes across brand portfolio via resolver tables
- `_brand_top_accords(db, brand_canonical_name, limit=10)` — same for accords
- `PerfumeEntityDetail` extended: `notes_source: Optional[str]`, `similar_perfumes: List[SimilarPerfumeRow]`
- `BrandEntityDetail` extended: `top_notes: List[str]`, `top_accords: List[str]`
- New `SimilarPerfumeRow` Pydantic model

**Backend — `notes.py`** (new route module)
- `GET /api/v1/notes/top?limit=` — top notes by perfume_count across resolver tables
- `GET /api/v1/accords/top?limit=` — top accords by perfume_count
- `GET /api/v1/notes/search?q=&limit=` — ILIKE search over normalized note names
- All queries wrapped in `_safe_query` for graceful Postgres-only table failures

**Backend — `dashboard.py`** (screener extension)
- `note: Optional[str]` query param added to screener endpoint
- Pre-computation of `entity_uuids_with_note` via 3-table JOIN (entity_market → resolver_perfumes → resolver_perfume_notes)
- Batch top_notes fetch after pagination using `ANY(:ids)` with try/except SQLite fallback
- Screener rows enriched with `top_notes` via `model_copy(update={"top_notes": ...})`

**Frontend — `types.ts`**
- `EntitySummary.top_notes: string[]`
- `SimilarPerfumeRow` interface
- `PerfumeEntityDetail.notes_source: string | null`, `.similar_perfumes: SimilarPerfumeRow[]`
- `BrandEntityDetail.top_notes: string[]`, `.top_accords: string[]`
- `NoteRow`, `AccordRow` interfaces
- `ScreenerParams.note?: string`

**Frontend — `notes.ts`** (new)
- `fetchTopNotes`, `fetchTopAccords`, `fetchNotesSearch` using `NEXT_PUBLIC_API_BASE_URL`

**Frontend — perfume entity page**
- `SourceBadge` component (Fragrantica = violet, Parfumo Dataset = gray)
- `NotesSection` shows source badge in header
- `SimilarByNotes` section — shows up to 8 perfumes ordered by shared note count, navigable

**Frontend — brand entity page**
- "Notes & Accords" section aggregated across brand portfolio (accords first, then notes)
- Rendered before signal timeline

**Frontend — screener**
- "Contains Note" text filter in `ScreenerFilters`
- Note filter serialized to/from URL params
- `top_notes` column in `ScreenerTable` showing up to 3 chips per row

---

### Completion Criteria — Verified

- [x] `GET /api/v1/notes/top` returns top notes from resolver tables
- [x] Perfume entity pages show notes with source badge
- [x] "Similar by notes" section on perfume pages
- [x] Brand entity pages show aggregated top notes/accords
- [x] Screener note filter (`?note=Vanilla`) works end-to-end
- [x] Screener rows show note chips in "Notes" column
- [x] All resolver-table queries wrapped in try/except (SQLite dev compatibility)
- [x] `NEXT_PUBLIC_API_BASE_URL` env var aligned across all API modules

---

## Phase 1c — Fragrantica Production Automation (DEFERRED)

### Status

Deferred by design.

### Context

Fragrantica enrichment is fully operational via CDP-based local execution.

All core system layers are verified:
- fetch
- parse
- normalize
- persist

The only missing capability is fully automated execution in production (Railway).

### Problem

Railway environment cannot:
- run persistent browser sessions
- pass Cloudflare bot protection
- maintain authenticated browser context

### Possible Solutions (not implemented)

- remote headless browser (Playwright service)
- proxy + CAPTCHA solving infrastructure
- external scraping provider
- hybrid local enrichment scheduler

### Decision

This phase is intentionally deferred.

Reason:
Product data layers (notes, brands, discovery, analytics) provide higher immediate value than production automation.

### Rule

Do NOT block product development waiting for full production automation.

Local/CDP-based enrichment is considered sufficient for:

- development
- data expansion
- feature building

### Future Trigger

Phase 1c should be revisited when:

- system requires continuous automated enrichment
- manual/local runs become a bottleneck
- production scaling becomes necessary

---

## Phase 2b — Production Enrichment Data Bridge (COMPLETED)

### Status

- Code complete
- Deploy complete
- Production verified

### What was achieved

Local enrichment data successfully synchronized to production PostgreSQL.

Tables populated:
- fragrantica_records
- notes
- accords
- perfume_notes
- perfume_accords

### Result

Phase 2 intelligence layer is now fully operational in production:

- notes_canonical populated
- note_stats populated
- accord_stats populated
- note_brand_stats populated

Production now returns real analytical outputs.

### Important Note

This bridge uses locally generated enrichment data.

It is a temporary solution until Phase 1c (automated production enrichment) is implemented.

### Known Technical Insight

Multiple PostgreSQL JOIN issues required explicit UUID/text casting.

Rule:
All cross-table joins involving UUID/text must use explicit CAST.

---

## Phase 3 — Discovery / Self-Improving System

### Status

- Phase 3A (collection layer): COMPLETE and ACTIVE in production
- Phase 3B (validation/filtering): COMPLETE and ACTIVE in production

### Production evidence (as of 2026-04-21)
- fragrance_candidates: 2,300 rows in production PostgreSQL (youtube source)
- all rows classified: 312 accepted_rule_based / 1758 review / 230 rejected_noise
- confidence_score computed (status='aggregated')
- both jobs run in every pipeline cycle: Steps 1b + 1c (added 2026-04-21, commit 0d76907)

### Gap fixed (2026-04-21)
aggregate_candidates and validate_candidates existed but were not added to pipeline scripts.
Candidates were collected (Phase 3A) but never aggregated or classified (Phase 3B).
Fixed by adding Steps 1b and 1c to start_pipeline.sh and start_pipeline_evening.sh.

### What is implemented

- fragrance_candidates table
- resolver integration (unresolved → candidates)
- aggregation job
- confidence scoring

### Current behavior

The system collects ALL unresolved phrases, including:
- natural language fragments
- partial perfume names
- full perfume names
- brand references

This is intentional.

### Observation

Majority of candidates are noise (common phrases).

This is expected at this stage.

### Rule

Phase 3A must NOT attempt to filter or validate candidates.

Filtering is deferred to Phase 3B.

### Next step

Implement promotion pipeline (Phase 3C).

---

## Phase 3B — Candidate Validation & Noise Filtering (COMPLETED)

### Status
- Code complete
- Deterministic validation complete
- Discovery layer operational

### What was added
- rule-based classification of fragrance_candidates
- candidate_type classification
- validation_status classification
- rejection_reason support
- deterministic noise filtering

### Classification outcomes
Candidates are now separated into:
- accepted_rule_based
- rejected_noise
- review

### Current behavior
The system now:
- preserves all unresolved candidates
- rejects obvious natural-language noise
- surfaces perfume/brand/note-like candidates
- keeps ambiguous entities in review

### Rule
Phase 3B does NOT promote candidates into the KB.

Promotion remains a separate phase.

### Result
PTI now has a usable discovery pipeline:
unresolved → candidate collection → validation → review-ready queue

---

## Phase 4 — Promotion Pipeline (Controlled Knowledge Expansion)

### Status

Planned.

### Purpose

Convert validated candidates into structured knowledge base entities without introducing noise or breaking resolver integrity.

### Design Principle

Promotion must be controlled, explicit, and reversible.

Discovery (Phase 3) produces candidates.  
Phase 4 determines which candidates become part of the Knowledge Base.

---

## Phase 4a — CSV Review & Approval Pipeline (COMPLETED)

### Status
- Code complete
- Review workflow complete
- CSV-first human review interface implemented
- System ready for Phase 4b with safeguards

### What was added
Review fields were added to `fragrance_candidates`:

- `review_status`
- `normalized_candidate_text`
- `reviewed_at`
- `review_notes`
- `approved_entity_type`

### Review model

Phase 4a introduces a human-in-the-loop review layer without writing to the Knowledge Base.

Primary interface:
- CSV export for review
- CSV import for review decisions

### Review states

Human review decisions are persisted through `review_status`, including:
- `pending_review`
- `approved_for_promotion`
- `rejected_final`
- `needs_normalization`

### Important distinction

`validation_status` and `review_status` are separate dimensions:

- `validation_status` = system decision
- `review_status` = human/promotion decision

Noise classified in Phase 3B may still remain `pending_review` until explicitly rejected or excluded from review exports.

### Current result

A first approved-for-promotion queue now exists.

Examples:
- `baccarat rouge 540`
- `xerjoff`
- `dior homme`
- `dior homme parfum`
- `ysl myself`

Normalization examples:
- `review the baccarat rouge` → `baccarat rouge`

### Rule for Phase 4b

Phase 4b must NOT promote candidates blindly from `approved_for_promotion`.

Before KB insertion, Phase 4b must apply final safeguards:
- deduplication against existing KB
- language detection / non-English filtering
- context-fragment stripping validation
- conflict checks against existing aliases and canonical entities

---

## Phase 4b — Safe Promotion to Knowledge Base (COMPLETED)

### Status
- Code complete
- Conservative promotion verified
- KB integrity preserved

### What was achieved
Phase 4b introduced a controlled promotion pipeline with four explicit outcomes:

- `exact_existing_entity`
- `merge_into_existing`
- `create_new_entity`
- `reject_promotion`

### Current result
The first bounded run proved that promotion can operate safely without corrupting the Knowledge Base.

Verified outcomes:
- exact KB matches detected and recorded
- safe alias merges performed
- unsafe candidates rejected by safeguard rules
- create bucket gated for manual follow-up

### Important result
Phase 4b did NOT perform blind KB expansion.

In the first bounded production-safe run:
- no new fragrance_master rows were inserted
- no new brands were inserted
- no new perfumes were inserted
- only safe aliases were added

### Rule
Phase 4b is conservative by design.

`--allow-create` must remain gated until create candidates pass additional review and cleanup.

### Relationship to next phase
The create_new_entity bucket is deferred to Phase 4c, which will handle:
- manual review of gated create candidates
- safe creation of new KB entities
- missing-brand seed expansion before allowing creation

---

## Phase 4c — Create Bucket Review & Controlled New Entity Creation (COMPLETED)

### Status
- Code complete / 5 new KB entities created / KB integrity verified

### What was achieved
- Enhanced classifier (`enhanced_classify_4c`) — stricter than Phase 4b:
  - pyramid position words rejected from perfume part (notes, bottom, top, middle, base, heart)
  - single-note-word perfume parts rejected
  - perfume-part alias lookup for convert_to_merge
  - in-batch partial-name deduplication (prevents creating "Xerjoff Jazz" and "Xerjoff Jazz Club" as separate entities)
- Brand alias seed: "jovoy" → Jovoy Paris added; 5 Jovoy candidates resolved as exact_now_in_kb
- 5 new perfume entities created: Xerjoff Jazz Club, Xerjoff Pt 2 Deified, Initio Musk Therapy, Tom Ford Grey Vetiver, Dior Homme Parfum
- 3 merge aliases for existing entities: Tom Ford Tobacco Oud, Tom Ford Uno, Tom Ford Uno De
- 6 partial-name aliases auto-created post-entity-creation in second pass: Tom Ford Grey, Xerjoff Jazz, Dior Homme
- KB integrity check: PASS — zero duplicates, zero orphan aliases

### Rule
Phase 4c create runs are bounded and conservative by design.
Do NOT increase `--allow-create --limit` without re-running `--analyze` to inspect the current bucket state.

### Scope

Phase 4c is responsible for:

1. reviewing and cleaning the create bucket
2. expanding missing brand coverage in KB
3. re-validating candidates after cleanup
4. enabling controlled `create_new_entity` promotion

---

## Step 1 — Create Bucket Review

### Objective

Filter out invalid candidates before allowing entity creation.

### Tasks

- review `create_new_entity` candidates
- identify and reject:
  - partial product fragments (e.g. "rouge", "540")
  - over-stripped tokens (e.g. "different")
  - contextual phrases (e.g. "inspired by baccarat")
  - foreign-language fragments (e.g. "en el baccarat")
- retain only candidates that:
  - resemble full perfume names
  - or clearly represent real brands

### Rule

Rejected create candidates must remain in DB with explicit rejection reason.

---

## Step 2 — Brand Coverage Expansion

### Objective

Resolve the largest rejection class: `brand_not_resolvable`.

### Tasks

- identify frequently occurring unknown brands from candidates
- manually or via seed import add known brands into KB

Examples:
- Yodeyma
- Lattafa
- Kayali
- other high-frequency unresolved brands

### Rule

Brand expansion must be done via controlled seed process, not implicit promotion.

---

## Step 3 — Re-Validation

### Objective

Re-run promotion pre-check after cleanup and brand expansion.

Expected effects:
- some candidates move from `reject_promotion` → `merge_into_existing`
- some candidates move from `create_new_entity` → valid create candidates
- reduction of noise in create bucket

---

## Step 4 — Controlled Create Promotion

### Objective

Enable safe creation of new KB entities.

### Rules

- creation allowed only with explicit flag (`--allow-create`)
- bounded batch only (e.g. 10–25 entities)
- only high-confidence candidates
- only after passing all safeguards

### Required Safeguards

Before creating new entity:
- dedup against existing perfumes and brands
- normalized text must be clean and stable
- language check (no fragments, no mixed context)
- entity type must be confident (perfume or brand)

---

## Step 5 — Post-Creation Validation

### Objective

Ensure KB integrity after new entity insertion.

### Must verify

- no duplicate canonical entities created
- resolver correctly maps new entities
- aliases correctly linked
- ingestion pipeline remains stable
- new entities appear in discovery and intelligence layers

---

## Out of Scope

Phase 4c does NOT:
- introduce AI classification
- perform bulk auto-creation
- modify enrichment layer
- modify signal engine

---

## Completion Criteria

Phase 4c is complete when:

1. create bucket is cleaned and reduced to valid candidates
2. missing brands are added to KB via seed expansion
3. controlled entity creation is successfully executed
4. new entities are integrated without duplication
5. resolver accuracy is preserved or improved

---

## Relationship to Previous Phases

- Phase 3A: collects all candidates
- Phase 3B: filters and classifies candidates
- Phase 4a: validates candidates for promotion
- Phase 4b: inserts validated candidates into KB

---

## Completion Criteria

Phase 4 is complete when:

1. candidates can be reviewed and approved
2. approved candidates can be safely promoted
3. KB grows without introducing duplicates or noise
4. resolver accuracy is maintained or improved

---

## Phase 2 — Notes & Brand Intelligence Layer

### Status

COMPLETED — 2026-04-21

- Code complete
- Deploy complete
- Production verified (all 9 validation checks PASS)

### What is verified

- Alembic migration 009 applied successfully
- All intelligence tables exist in production:
  - notes_canonical
  - note_canonical_map
  - note_stats
  - accord_stats
  - note_brand_stats
- Intelligence job executes successfully in production environment
- PostgreSQL compatibility issues resolved (UUID/text casting)

### Current limitation

Production database contains no enrichment data:

- notes = 0
- accords = 0
- perfume_notes = 0
- perfume_accords = 0

As a result:
- intelligence job produces 0 rows

### Root cause

Fragrantica enrichment runs only in local environment via CDP client.

Railway production cannot execute enrichment due to Cloudflare protection.

This is the same constraint described in Phase 1c.

### Classification

Phase 2 is:

- fully implemented
- fully deployable
- data-dependent in production

### Rule

Do NOT modify Phase 2 logic.

Phase 2 will become fully production-verified automatically once
enrichment data is present in production database.

---

## Phase 0 — KB Stabilization (COMPLETED)

### Status

Phase 0 (Knowledge Base stabilization and seeding) is complete.

### Achievements

- Restored Postgres-compatible fragrance master store (`pg_fragrance_master_store.py`, SQLAlchemy-based)
- Unified seeding entrypoint (`scripts/seed_kb.py`)
- Verified repeatable seed load for:
  - fragrance_master
  - aliases
  - brands
  - perfumes
- Identity mapping between resolver (`data/resolver/pti.db`) and market DB is stable
- brands: 260/260 linked, perfumes: 2246/2247 linked

### Known Behaviors (NOT bugs)

#### Alias Count Variance

Alias count differences across environments are expected.

Cause:
- Different CSV load order (seed_master vs seed_placeholder)
- ID assignment differences in resolver DB

Impact:
- No duplicate entities created
- Resolver behavior remains correct
- Some aliases intentionally map to multiple entities (e.g. base vs concentration variants)

This behavior is accepted and should NOT be "fixed".

#### Alias Collisions

Examples like:
- `"aventus"` → base entity (`Creed Aventus`, pid=27) + EDP variant (`Creed Aventus Eau de Parfum`)

Are expected and beneficial.

Resolver prioritizes:
- base entity (lower ID)

This is consistent with concentration-stripping aggregation logic.

### Known Edge Case

**"Les Bains Guerbois Eau de Cologne"**

Issue:
- Name contains `"Eau de Cologne"` as part of the actual product name (not a concentration qualifier)
- `seed_market_catalog.py` strips standalone `Cologne` → produces malformed entry `name='Eau de'`, `slug='les-bains-guerbois-eau-de'`
- `sync_identity_map.py` strips full `"Eau de Cologne"` → expects slug `'les-bains-guerbois'` → no match → 1 unlinked perfume

Status:
- Known issue, documented
- Low impact — brand is not in tracked watchlist, has not appeared in any ingestion data
- Deferred fix — do not modify normalization rules globally for this case

### Rule

Do NOT rework seeding logic unless:
- data integrity is broken
- resolver produces incorrect matches

---

## Execution Rule — Phase Completion

A phase is NOT considered complete when code is only implemented locally.

Each phase must pass 3 gates:

**1. Code Complete**
- implementation finished
- local tests pass
- local DB state verified

**2. Deploy Complete**
- changes pushed to main
- Railway deployment completed
- Alembic migrations applied successfully

**3. Production Verified**
- target workflow executed in Railway
- expected DB/state changes confirmed
- smoke-check passed

### Rule

CLAUDE.md may record a phase as fully complete only after all 3 gates pass.

If code is complete but production is blocked by an external constraint
(e.g. third-party 403, missing credentials, infra limitation),
the phase must be marked as:

- **code-complete**
- **production-blocked**

not fully complete.

---

## Phase Execution & Deployment Discipline

### Core Rule

Every phase MUST explicitly declare its execution target and deployment expectations before implementation.

No phase is considered complete without satisfying its declared target.

---

## Phase Target Types

Each phase must start with:

- `target_type`
- `authoritative_targets`
- `requires_commit_push_deploy`
- `expected_ui_visibility`

### 1. LOCAL_ONLY

Used for:
- experiments
- partial implementations
- data exploration
- prototype logic

Rules:
- changes may exist only in local DB (e.g. `outputs/*.db`)
- must NOT be marked as production-complete
- must NOT be assumed visible in API/UI
- no deploy required

---

### 2. PRODUCTION_TARGETED

Used for:
- schema changes (alembic)
- pipeline changes
- resolver / KB mutations
- ingestion / aggregation changes
- anything expected to affect API or UI

Rules:
- must define authoritative production targets (DB/files)
- must commit + push
- must deploy (Railway)
- must run production verification
- NOT complete until production is verified

---

### 3. BUNDLED_LATER

Used when:
- phase is intentionally split
- final deploy happens later as a group

Rules:
- must explicitly say: "deploy deferred"
- must NOT be marked as production-complete
- must reference which phase it will be bundled with

---

## Required Phase Header

Every Claude Code task MUST begin with:

```
TARGET TYPE: [LOCAL_ONLY / PRODUCTION_TARGETED / BUNDLED_LATER]

AUTHORITATIVE TARGETS:
  [e.g. production PostgreSQL]
  [e.g. data/resolver/pti.db]

REQUIRES COMMIT/PUSH/DEPLOY: [YES/NO]

EXPECTED UI CHANGE: [YES/NO/DELAYED]
```

---

## Resolver / KB Rule

For any phase that mutates Knowledge Base:

- DO NOT write only to working DBs (e.g. `outputs/pti.db`)
- MUST write to authoritative resolver DB used in production
- MUST verify:
  - row counts
  - new entities
  - new aliases
  - resolver correctness

---

## UI Visibility Rule

Knowledge Base changes do NOT guarantee immediate UI visibility.

For an entity to appear in UI:

1. entity exists in KB/resolver
2. ingestion encounters matching content
3. resolver maps content
4. aggregation creates market rows
5. API returns entity
6. UI filters allow it

Therefore:
- KB update ≠ UI update
- absence in UI ≠ failure

---

## Phase Completion Definition

A phase is COMPLETE only if:

| Target type | Completion criteria |
|-------------|-------------------|
| LOCAL_ONLY | verified locally |
| PRODUCTION_TARGETED | deployed + verified in production |
| BUNDLED_LATER | implemented and explicitly deferred |

---

## Phase 4P — Promotion Pipeline: Postgres KB Writes (COMPLETED)

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `resolver_*` tables (migration 014)
- `fragrance_candidates` (market Postgres DB)

### Requires Commit / Push / Deploy
YES

### Expected UI Change
NO (resolver-layer change only)

---

### Problem

All Phase 4 promotion jobs (`promote_candidates.py`, `review_create_bucket.py`)
wrote KB changes via `sqlite3.connect(RESOLVER_DB_PATH)`.

Since Phase R1, the production resolver reads exclusively from Postgres `resolver_*` tables.

Result: promoted entities never reached the production resolver. Phase 4b + 4c
were effectively no-ops in production.

---

### What was implemented

**New file — `perfume_trend_sdk/analysis/candidate_validation/pg_promoter.py`**

Postgres-aware promotion execution layer:
- `load_kb_snapshot_pg(store)` — reads `resolver_*` Postgres tables into memory
- `execute_merge_pg(check, store)` — writes to `resolver_aliases` (ON CONFLICT DO NOTHING)
- `execute_create_perfume_pg(check, store, candidate_id)` — atomic write to
  `resolver_perfumes` + `resolver_fragrance_master` + `resolver_aliases`
- `execute_create_brand_pg(check, store)` — writes to `resolver_brands` + `resolver_aliases`
- `record_promotion_outcome_pg(db, ...)` — updates `fragrance_candidates` via SQLAlchemy Session
- Re-exports all pure (no-DB) logic from `promoter.py` unchanged:
  `safeguard_check`, `check_exact`, `check_merge`, `resolve_brand`, `run_prechecks`, etc.

**Rewritten — `perfume_trend_sdk/jobs/promote_candidates.py`**
- Removed `sqlite3` + `RESOLVER_DB_PATH`
- Uses `PgResolverStore()` for KB reads/writes
- Uses `session_scope()` for market DB (fragrance_candidates)
- Added `_assert_postgres_available()` production guard

**Rewritten — `perfume_trend_sdk/jobs/review_create_bucket.py`**
- Removed `sqlite3` + `RESOLVER_DB_PATH`
- All KB writes route through `pg_promoter` functions
- All market DB ops use SQLAlchemy Session
- Added `_assert_postgres_available()` production guard

---

### Production guard

```python
def _assert_postgres_available() -> None:
    pti_env = os.environ.get("PTI_ENV", "dev").strip().lower()
    if pti_env == "production" and not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "promote_candidates: DATABASE_URL is required when PTI_ENV=production. "
            "This job writes to Postgres resolver_* tables and does not support SQLite."
        )
```

Both jobs raise `RuntimeError` on startup if `PTI_ENV=production` and `DATABASE_URL` is unset.
This prevents any accidental SQLite fallback in production.

---

### Usage (after deploy)

```bash
# Dry-run preview (safe — no DB writes)
railway run --service pipeline-daily \
  python3 -m perfume_trend_sdk.jobs.promote_candidates --dry-run

# Bounded real run — merge aliases only
railway run --service pipeline-daily \
  python3 -m perfume_trend_sdk.jobs.promote_candidates --no-dry-run --limit 25 --type perfume

# Bounded real run — with new entity creation enabled
railway run --service pipeline-daily \
  python3 -m perfume_trend_sdk.jobs.promote_candidates --no-dry-run --limit 25 --allow-create
```

---

## Phase 4P.1 — Bounded Alias Expansion (Stability Phase)

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- production PostgreSQL (`resolver_*` tables)
- fragrance_candidates
- promotion pipeline

### Requires Commit / Push / Deploy
NO (execution phase)

### Expected UI Change
INDIRECT (better resolution coverage)

---

### Goal

Expand resolver alias coverage safely after Phase 4P by running bounded promotion batches using only safe decisions:

- exact_existing_entity
- merge_into_existing

This phase builds confidence in production promotion behavior before enabling create_new_entity.

---

### Rules

- Only approve small batches (10–20 max)
- Only exact/merge candidates
- Never bulk approve entire candidate set
- Always run dry-run before real run
- Always verify resolver behavior after promotion

---

### Batches executed

**Batch 1 (2026-04-22):** 9 candidates — 7 exact + 2 merge
- Approved: id=316 (baccarat rouge 540), 815 (xerjoff erba bura), 3803 (creed silver mountain water), 440 (maison francis kurkdjian), 813 (xerjoff), 1578 (louis vuitton), 394 (royal crown), 3814 (silver mountain water), 3813 (creed silver mountain)
- Result: resolver_aliases 12,884 → 12,886 (+2 merge aliases)

**Batch 2 (2026-04-22):** 7 candidates — 5 exact + 2 merge
- Approved: id=330 (baccarat rouge), 1334 (creed aventus), 814 (xerjoff erba), 1064 (yves saint laurent), 3824 (creed silver), 677 (baccarat rouge 540 extrait), 905 (erba pura)
- Result: resolver_aliases 12,886 → 12,888 (+2 merge aliases)

### Cumulative count delta
- resolver_aliases: 12,884 → 12,888 (+4 total)
- resolver_perfumes / resolver_brands / resolver_fragrance_master: unchanged
- discovery_generated aliases: 15 → 19 (+4)

---

### Out of Scope

- No create_new_entity execution
- No schema changes
- No promotion logic changes

---

### Completion Criteria

- Multiple bounded batches executed successfully ✅
- resolver_aliases steadily increases ✅
- new aliases resolve correctly in production ✅
- no incorrect merges observed ✅

---

### Next Phase

→ Phase 4P.2 — Controlled New Entity Creation

---

## Phase 4P.2 — First Controlled New Entity Creation

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `resolver_*` tables (migration 014)
- `fragrance_candidates` (market Postgres DB)

### Requires Commit / Push / Deploy
NO (no code changes — execution only)

### Expected UI Change
INDIRECT (new entity visible once ingestion encounters matching content)

---

### Goal

Execute the first controlled `create_new_entity` promotion in production using a single low-risk candidate.

Candidate scope: **id=373, text="royal crown un", type=perfume**

---

### Pre-Checks Passed (all 9)

1. `safeguard_check("royal crown un")` → None (PASS)
2. No exact match in `resolver_aliases` for "royal crown un"
3. No merge match via `check_merge` (hence CREATE, not merge)
4. `resolve_brand("royal crown un", kb)` → brand_id=1143, brand_name="Royal Crown"
5. normalized_name="royal crown un" — no duplicate in `resolver_perfumes`
6. No duplicate in `resolver_fragrance_master`
7. No existing alias for this normalized text
8. "Un" not already under brand_id=1143 in `resolver_perfumes`
9. Brand id=1143 confirmed in `resolver_brands`

### Why create_new_entity (not merge)

`check_merge` scans `alias_lookup` for "royal crown un" and finds no entry.
No FM row with normalized_name="royal crown un" exists. No fuzzy match above
threshold for this text. Brand is resolvable → entity is new, not a variant.

### Result

New entity created in one atomic transaction:
- `resolver_perfumes`: id=113590, canonical="Royal Crown Un", normalized="royal crown un", brand_id=1143
- `resolver_fragrance_master`: fid=disc_000373, brand_name="Royal Crown", perfume_name="Un", canonical="Royal Crown Un", source=discovery, perfume_id=113590
- `resolver_aliases`: alias="Royal Crown Un", norm="royal crown un", type=discovery_generated, confidence=0.80

### Count Deltas (production, 2026-04-22)

| Table | Before | After | Delta |
|-------|--------|-------|-------|
| resolver_perfumes | 56,067 | 56,068 | +1 |
| resolver_fragrance_master | 56,067 | 56,068 | +1 |
| resolver_aliases | 12,888 | 12,889 | +1 |
| resolver_brands | 1,608 | 1,608 | 0 |
| discovery FM rows | 5 | 6 | +1 |
| discovery_generated aliases | 19 | 20 | +1 |

### Naming Convention Note

Discovery entities store the FULL canonical name (brand + perfume) in
`resolver_perfumes.canonical_name` — e.g., "Royal Crown Un".
This differs from Kaggle-seed entities which store only the perfume part
(e.g., "Aeternum"). Both are correct for their respective sources.

### Bounded-Run Discipline

- Single candidate only for first create run
- Dry-run verified before real run
- All 9 pre-checks passed before approval
- Post-create verification ran immediately after

### Status
COMPLETED — 2026-04-22

---

## Phase 5 — Coverage Maintenance Service

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- production PostgreSQL
- maintenance queue tables (`stale_entity_queue`, `metadata_gap_queue`)
- maintenance jobs / runner
- production pipeline integration (`start_pipeline.sh`)

### Requires Commit / Push / Deploy
YES

### Expected UI Change
INDIRECT

---

### Goal

Keep entity coverage healthy over time.

After Phase 4 completed the production self-learning loop, the system now has a
maintenance layer that detects stale entities and metadata gaps, then queues
safe follow-up work for future remediation.

---

### Core Principle

Discovery grows the universe. Maintenance keeps the universe usable.

Phase 5 prevents:
- stale entities with no recent refresh path going unnoticed
- metadata-incomplete perfumes silently degrading entity pages
- growing UI/catalog surface with empty or degraded entity pages

---

### Alembic Migration

Migration 016 (`alembic/versions/016_add_maintenance_queues.py`) adds:

**`stale_entity_queue`**
- `entity_id` (UNIQUE) — entity_market.id UUID
- `entity_type`, `canonical_name`, `reason`, `priority`
- `status`: pending / detected_only / done / failed
- `last_seen_date`, `days_inactive`
- `created_at`, `updated_at`, `last_attempted_at`, `notes_json`

**`metadata_gap_queue`**
- `entity_id + gap_type` (UNIQUE) — one entry per entity per gap type
- `gap_type`: missing_fragrantica | missing_notes | missing_accords
- `entity_type`, `canonical_name`, `reason`, `priority`
- `status`: pending / pending_enrichment / done / failed
- `fragrance_id` (resolver reference for enrichment path lookup)
- `created_at`, `updated_at`, `last_attempted_at`, `notes_json`

---

### Jobs Added

| Job | Module | Purpose |
|-----|--------|---------|
| detect_stale_entities | `perfume_trend_sdk.jobs.detect_stale_entities` | Find entities inactive > N days |
| detect_metadata_gaps | `perfume_trend_sdk.jobs.detect_metadata_gaps` | Find perfumes with missing notes/accords/fragrantica |
| run_maintenance | `perfume_trend_sdk.jobs.run_maintenance` | Process bounded pending queue items |

**Stale detection rule**: entity has no timeseries row with mention_count > 0
in the last `--stale-days` (default: 14). Or has zero timeseries rows at all.

**Metadata gap types detected**:
- `missing_fragrantica`: perfume in entity_market with no fragrantica_records row
- `missing_notes`: fragrantica_records exists but all note lists are empty
- `missing_accords`: fragrantica_records exists but accords_json is empty

**Runner behavior (Phase 5 conservative)**:
- stale_entity_queue: no automated refresh path exists yet → mark `detected_only`
- metadata_gap_queue: Fragrantica enrichment requires CDP browser (not automated in prod) → mark `pending_enrichment`
- Bounded: `--limit 20` per queue per run
- Both outcomes are explicit states — no silent failures

---

### Pipeline Integration

Added to `start_pipeline.sh` Step 5 (morning cycle only, non-blocking):

```sh
timeout 300 python3 -m perfume_trend_sdk.jobs.detect_stale_entities --stale-days 14 || ...
timeout 300 python3 -m perfume_trend_sdk.jobs.detect_metadata_gaps || ...
timeout 300 python3 -m perfume_trend_sdk.jobs.run_maintenance --limit 20 || ...
```

Evening pipeline (`start_pipeline_evening.sh`) is not modified — maintenance runs once daily.

---

### Production Verification

After deploy, run in Railway:

```bash
railway ssh --service generous-prosperity "cd /app && python3 -m perfume_trend_sdk.jobs.detect_stale_entities --dry-run"
railway ssh --service generous-prosperity "cd /app && python3 -m perfume_trend_sdk.jobs.detect_metadata_gaps --dry-run"
```

Then real run:
```bash
railway ssh --service generous-prosperity "cd /app && python3 -m perfume_trend_sdk.jobs.detect_stale_entities"
railway ssh --service generous-prosperity "cd /app && python3 -m perfume_trend_sdk.jobs.detect_metadata_gaps"
railway ssh --service generous-prosperity "cd /app && python3 -m perfume_trend_sdk.jobs.run_maintenance --limit 20"
```

Verify queue state:
```sql
SELECT status, COUNT(*) FROM stale_entity_queue GROUP BY status;
SELECT gap_type, status, COUNT(*) FROM metadata_gap_queue GROUP BY gap_type, status;
```

---

### Completion Criteria

- migration 016 applied in production ✓
- stale entities detected and queued automatically ✓
- metadata gaps detected and queued automatically ✓
- bounded maintenance runner executes without error ✓
- no regression in pipeline-daily / pipeline-evening ✓
- coverage health is now an active system concern ✓

---

## Phase 5 — Catalog Expansion Discipline

Phase 5 is NOT part of the live ingestion pipeline.

Principle:

- Live pipeline → signals (YouTube/Reddit)
- Catalog pipeline → universe (perfumes/brands)

Rules:

- bulk import must be controlled and batched
- must not rely on live ingestion for coverage growth
- must use structured sources (Fragrantica/Kaggle/etc.)
- must merge safely into existing KB (no duplicates)

---

## Phase 5 — Step 1: Catalog Source

### Selected Source

**Parfumo via TidyTuesday (2024-12-10)**

| Property | Value |
|----------|-------|
| Dataset | `parfumo_data_clean.csv` |
| Origin | Parfumo.com community dataset, published via R4DS TidyTuesday |
| Direct URL | `https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2024/2024-12-10/parfumo_data_clean.csv` |
| Total rows | 59,325 |
| Valid rows (after filtering) | 59,273 |
| Columns used | `Brand` → brand_name, `Name` → perfume_name |
| Columns deferred | Release_Year, Concentration, Rating_Value, Rating_Count, Main_Accords, Top/Middle/Base Notes |
| source tag | `kaggle_v1` |

### Why Parfumo

- Direct download, no authentication required
- 59k+ rows — materially expands current 2,245-perfume KB
- Community-verified perfume names from a dedicated fragrance platform
- Clean brand/name structure compatible with existing KB schema

### What it is NOT

- Not the original Fragrantica/Kaggle source discussed in early Phase 5 planning
- Not a canonical authority (Parfumo is community data)
- Deferred columns (notes, accords, ratings) require separate enrichment phase

### Rule

All Phase 5 import activity uses this dataset and `source='kaggle_v1'` tag for traceability and rollback.

---

## Phase 5 — Step 2: Data Schema Definition

### Status
Planned.

### Target
TARGET TYPE: PRODUCTION_TARGETED

### Purpose

Define a minimal, safe, and scalable schema for importing catalog data (Kaggle / Fragrantica datasets) into the Knowledge Base.

This step determines:
- what data is stored
- where it is stored
- what is intentionally excluded

---

### Design Principle

Catalog expansion must be:

- minimal-first (only required fields)
- merge-safe (no duplication of entities)
- compatible with existing KB structure
- independent from ingestion / candidates / review pipeline

---

### Scope

#### 1. Mandatory Fields

Required for all imports:

**Perfume**
- brand_name
- perfume_name

**Brand**
- brand_name

These fields must be sufficient to:
- create or match entities
- support resolver logic
- allow alias generation

---

#### 2. Optional Fields (Deferred / Secondary)

May be imported later, but NOT required in initial Phase 5:

- notes (top/middle/base)
- accords
- gender
- release_year
- rating
- url

Rule: Optional fields must NOT block import.

---

#### 3. Mapping to Existing Tables

Data must be mapped into current schema:

| Table | What is written |
|-------|----------------|
| `brands` | canonical brand_name |
| `perfumes` | canonical perfume_name + brand link |
| `fragrance_master` | combined brand + perfume identity + normalized representation |
| `aliases` | generated name variants — must not duplicate existing aliases |

---

#### 4. Explicit Exclusions

The following must NOT be imported in Step 2:

- duplicate perfume rows
- noisy or malformed names
- incomplete fragments (e.g. "rouge", "540")
- rating-based logic
- popularity metrics
- any data requiring inference or AI

---

### Completion Criteria

Step 2 is complete when:

1. required fields are clearly defined
2. optional fields are explicitly deferred
3. mapping to existing KB tables is defined
4. exclusions are clearly listed
5. schema is simple enough for safe bulk import

---

### Dedup Rule (Critical)

Deduplication must NOT rely on slug only.

Rules:

- slug is used for indexing and ON CONFLICT safety
- `normalized_name` is the canonical dedup key

Before insert:
1. normalize perfume name
2. check existence via `normalized_name`
3. only insert if not found

Reason: to prevent near-duplicate entities caused by formatting differences.

---

### Alias Rule (Critical)

Phase 5 must NOT perform bulk or aggressive alias generation.

Only allowed:
- minimal normalization-based aliases (safe, deterministic)
- or defer alias creation to existing promotion/alias pipeline

Reason: to avoid duplication, noise, and conflict with Phase 4 resolver logic.

---

---

## Phase 5 — Step 3: Import Strategy

### Execution Target

PRODUCTION_TARGETED

### Import Order

Execute in strict order to satisfy foreign key constraints:

1. brands — insert canonical brand rows first
2. perfumes — insert perfume rows with brand_id foreign key
3. fragrance_master — insert combined identity rows linking perfume + brand
4. aliases — deferred (not part of Phase 5 core import)

### Deduplication Strategy

**Step 1 — Brand dedup (before insert):**
- normalize brand_name (lowercase, strip whitespace)
- check existence in `brands` table via normalized_name
- skip if found; insert if not

**Step 2 — Perfume dedup (before insert):**
- strip concentration suffixes from perfume_name
- normalize result (lowercase, strip whitespace)
- check existence in `perfumes` table via normalized_name + brand_id
- skip if found; insert if not

**Step 3 — fragrance_master dedup:**
- check existence via normalized_name (combined brand + perfume)
- skip if found; insert if not

**Rule:** ON CONFLICT DO NOTHING is the final safety net, not the primary dedup mechanism. Normalized_name check must run first.

### Batch Size

- 500 rows per commit
- allows rollback of partial failures without losing all progress
- progress logged after each batch

### Insert Mode

`INSERT ... ON CONFLICT DO NOTHING`

Applied to all three tables. Safe for repeated runs — import is fully idempotent.

### Error Handling

- row-level errors are logged and skipped
- batch continues after single-row failure
- final summary reports: inserted, skipped, failed counts per table

### Validation After Import

After each import run, verify:
- brands count increased by expected delta
- perfumes count increased by expected delta
- fragrance_master count consistent with perfumes
- spot-check 5 known perfumes from the dataset resolve correctly via resolver

### Risks

| Risk | Mitigation |
|------|-----------|
| Slug collisions between similar names | slug is secondary — normalized_name check runs first |
| Brand name variants (e.g. "Tom Ford" vs "TomFord") | normalization must be consistent with existing KB normalization |
| Partial imports on crash | ON CONFLICT DO NOTHING + batch commits make re-run safe |
| Concentration suffix in perfume_name | strip suffixes before normalization and before dedup |

---

---

## Phase 5 — Step 4: Import Execution Strategy

### Execution Target

PRODUCTION_TARGETED

### Execution Flow

**Stage 1 — Prepare dataset locally**

1. Download Kaggle dataset CSV locally
2. Inspect raw data: count rows, check field availability (brand_name, perfume_name), identify encoding issues, identify obvious noise (nulls, fragments, single-word entries)
3. Run a manual spot-check against existing KB: pick 10 well-known perfumes from the dataset, verify they already exist in `data/resolver/pti.db` — this calibrates expected skip rate

**Stage 2 — Dry-run locally against `data/resolver/pti.db`**

Run import script in dry-run mode (no writes). Output:
- total rows in dataset
- expected brands: new / already-exist
- expected perfumes: new / already-exist / skipped-noise
- expected fragrance_master: new / already-exist
- estimated alias rows (deferred — should be 0)
- sample of 10 new entities that would be inserted
- sample of 10 entities that would be skipped and why

Dry-run must complete without errors before any real run proceeds.

**Stage 3 — Bounded real run locally against `data/resolver/pti.db`**

First real run: **500 rows only** (brands + perfumes from the first 500 dataset rows).

Why 500:
- validates the full insert path end-to-end
- dedup logic proven on real data
- any normalization bugs surface early at low cost
- rollback is trivial at this scale

After 500-row run: verify counts, run spot-checks, confirm no duplicates. Only proceed if clean.

**Stage 4 — Full real run locally**

If 500-row run is clean: run full dataset against local `data/resolver/pti.db`.

Batch size: 500 rows per commit. Each batch logs: inserted / skipped / failed counts.

Expected completion: one local run, no restarts needed (ON CONFLICT DO NOTHING makes it safe to re-run on crash).

**Stage 5 — Production import run**

After local verification:

- run the same import job against the production resolver DB
- using the same batch size and safeguards
- with `source='kaggle_v1'`

Rules:
- no DB state must be deployed via git
- all production data mutations must happen via controlled execution

**Stage 6 — Production market layer**

New entities in the production resolver DB become visible in the market layer through normal ingestion: when content mentioning new entities is ingested, `_upsert_entity_market` creates the market-layer rows automatically.

No direct PostgreSQL write to `entity_market` needed for Phase 5 — resolver is the source of truth for entity identity.

### Limits

| Run | Rows | Why |
|-----|------|-----|
| Dry-run | Full dataset | Read-only, safe at any size |
| Bounded real run | 500 | Validates dedup + insert logic at low cost |
| Full run | Full dataset | Only after 500-row run is verified clean |

**Hard stops before full run:**
- dry-run must pass with 0 errors
- 500-row run must show 0 duplicates
- spot-check must confirm at least 5 known perfumes correctly deduplicated (skipped, not re-inserted)

### Rollback Strategy

Every imported row is tagged `source='kaggle_v1'` at insert time.

If something goes wrong after any run:

```sql
DELETE FROM fragrance_master WHERE source = 'kaggle_v1';
DELETE FROM perfumes WHERE source = 'kaggle_v1';
DELETE FROM brands WHERE source = 'kaggle_v1';
```

Three targeted deletes in FK order. No migration needed. Resolver returns to pre-import state exactly.

**Production PostgreSQL:** no rollback needed — Phase 5 writes nothing directly to PostgreSQL. Market-layer rows only appear after ingestion, so the rollback window exists.

### Verification

**After 500-row run:**

1. `SELECT COUNT(*) FROM brands WHERE source='kaggle_v1'` — must be > 0, must be < total brands in first 500 rows (some already existed)
2. `SELECT COUNT(*) FROM perfumes WHERE source='kaggle_v1'` — same logic
3. Spot-check 5 known perfumes from the 500-row slice: confirm they are NOT in `kaggle_v1` rows (correctly skipped by dedup)
4. Spot-check 3 expected-new perfumes: confirm they ARE present with correct brand_id links

**After full run:**

1. Count delta: brands, perfumes, fragrance_master — compare to pre-run baseline
2. Zero duplicates check: `SELECT normalized_name, COUNT(*) FROM perfumes GROUP BY normalized_name HAVING COUNT(*) > 1` — must return 0 rows
3. Resolver lookup: 5 newly imported perfumes must resolve correctly via existing resolver logic
4. Integrity check: all `perfumes.brand_id` must reference valid `brands.id` rows
5. Confirm `aliases` table was not touched (count must be unchanged)

### Success Criteria

| Criteria | Pass condition |
|----------|---------------|
| Dry-run clean | 0 errors, expected counts look reasonable |
| 500-row run clean | Counts correct, 0 duplicates, spot-checks pass |
| Full run clean | All verification queries pass |
| Zero alias pollution | `aliases` count unchanged from pre-import |
| Zero duplicate normalized_names | Duplicate query returns 0 rows |
| Resolver integrity | 5 new + 5 existing perfumes resolve correctly |
| Rollback tag confirmed | `source='kaggle_v1'` present on all new rows |
| Production run complete | Same verification passes against production DB |

**Import is NOT considered successful if:**
- any duplicate normalized_name exists
- any perfume row has a NULL or invalid brand_id
- aliases count changed (bulk generation must be 0)
- resolver spot-check fails for any imported entity

---

## Phase 5 — Production Catalog Bootstrap Rule

Resolver catalog expansion must be deployed through an explicit guarded bootstrap command,
not through git-committed SQLite snapshots and not as a step on every pipeline start.

### Bootstrap command

```bash
python3 scripts/bootstrap_resolver_catalog.py
```

On Railway (one-time explicit trigger):
```bash
railway run --service pipeline-daily python3 scripts/bootstrap_resolver_catalog.py
```

### Behavior

- if `kaggle_v1` rows already exist at expected scale → **SKIPPED** instantly (no download, no write)
- if catalog is missing → download CSV from TidyTuesday URL, run full import → **IMPORTED**
- supports `--dry-run`
- supports `--force` for debugging only

### Rule

Catalog bootstrap is a one-time or recovery action, not a recurring pipeline step.

Do NOT add `bootstrap_resolver_catalog.py` to `start_pipeline.sh` or `start_pipeline_evening.sh`.

If the production resolver loses its catalog (e.g. after a fresh Railway deploy without the SQLite snapshot), run the bootstrap explicitly. It will detect the missing data and re-import.

### Verification after bootstrap

After running on Railway, confirm:

1. `SELECT COUNT(*) FROM fragrance_master WHERE source='kaggle_v1'` → ~53,822
2. `SELECT COUNT(*) FROM brands` → ~1,608
3. `SELECT COUNT(*) FROM perfumes` → ~56,067
4. `SELECT COUNT(*) FROM aliases` → 12,884 (must be unchanged)
5. Spot-check 5 imported perfumes resolve correctly

---

## Resolver Persistence Rule

> ⚠️ **SUPERSEDED by Phase R1 (2026-04-21).** The Railway Volume / RESOLVER_DB_PATH approach described below was rolled back. The active architecture is Phase R1: Postgres `resolver_*` tables. See `## ✅ Current Architecture` and `## 🚀 Migration Plan` below.

~~The production resolver catalog must not rely on ephemeral container filesystem state.~~

**Active rule:** Resolver catalog lives in Postgres `resolver_*` tables (migration 014). `PerfumeResolver` is constructed via `make_resolver()` which auto-selects `PgResolverStore` when `DATABASE_URL` is set, or `FragranceMasterStore(db_path)` for local SQLite fallback. No `RESOLVER_DB_PATH` env var. No Railway Volume.

---

## 🚫 Deprecated Architecture: Resolver Volume / SQLite

The project previously attempted to use a Railway volume mounted at `/app/resolver-vol`
to store a SQLite database (`pti.db`) for resolver/catalog logic.

This approach is **fully deprecated and must NOT be used**.

### ❌ Запрещено:
- Using SQLite (`pti.db`) as resolver storage
- Any filesystem-based DB under `/app/*`
- Railway volumes for KB / resolver state
- Copying seed DB files into containers
- mkdir/chmod/chown logic for resolver storage
- Any fallback to local DB

### Причина:
Railway volumes:
- cannot be shared across services reliably
- introduce permission issues (chmod/chown failures)
- break multi-service architecture
- are not needed because Postgres already exists

---

## ✅ Current Architecture: Postgres as Single Source of Truth

All resolver, catalog, and identity data MUST live in Postgres.

### Source of truth:
- `DATABASE_URL` (Postgres)

### Used by:
- `pipeline-daily`
- `pipeline-evening`
- resolver
- catalog import

### Expected tables:
- `brands`
- `perfumes`
- `aliases`
- `fragrance_master` (or equivalent KB table)

---

## 🧩 Resolver Rules

Resolver MUST:
- query Postgres directly
- NOT load any local files
- NOT depend on SQLite
- work identically across all services

---

## 🚀 Pipeline Rules

Pipelines MUST:
- read/write ONLY to Postgres
- NOT use local filesystem for state
- be stateless between runs

---

## 🧠 Resolver Architecture

Resolver and Market layers are separate systems.

Resolver uses:
- integer IDs
- `normalized_name`
- `aliases` table
- `fragrance_master` KB

Market uses:
- UUID IDs
- production entities

Resolver MUST NOT use market tables directly.

---

## 🚀 Migration Plan — Phase R1 (PRODUCTION-VERIFIED — 2026-04-21)

Resolver storage migrated from SQLite → Postgres.

### What was implemented

- **Alembic migration 014**: `resolver_brands`, `resolver_perfumes`, `resolver_aliases`, `resolver_fragrance_master` tables — INTEGER PKs, `resolver_` prefix (no collision with UUID market tables)
- **Alembic migration 015**: fixed missing SERIAL sequences for `resolver_aliases.id` and `resolver_fragrance_master.id` (migration 014 missed explicit `CREATE SEQUENCE` + `SET DEFAULT`)
- **`PgResolverStore`** (`perfume_trend_sdk/storage/entities/pg_resolver_store.py`): same interface as `FragranceMasterStore`, backed by Postgres `resolver_*` tables; includes `check_has_data()` fail-fast guard
- **`make_resolver(db_path)`** factory: auto-selects `PgResolverStore` (when `DATABASE_URL` set) or SQLite fallback; calls `check_has_data()` in production to fail fast if migration hasn't run
- **`PerfumeResolver.__init__(store=...)`**: accepts store object; `db_path` kept for backward compat
- **`scripts/migrate_resolver_to_postgres.py`**: idempotent batch migration using `psycopg2.extras.execute_values` (2,000-row batches; 56k rows in ~2 minutes)
- **`scripts/verify_resolver_shadow.py`**: shadow verification — row count parity + 16 resolver alias probes

### Production verification results (2026-04-21)

| Table | SQLite | Postgres | Match |
|-------|--------|----------|-------|
| resolver_brands | 1,608 | 1,608 | ✅ |
| resolver_perfumes | 56,067 | 56,067 | ✅ |
| resolver_aliases | 12,884 | 12,884 | ✅ |
| resolver_fragrance_master | 56,067 | 56,067 | ✅ |

Resolver output parity: 16/16 alias probes pass ✅

Shadow verification: **PASS** — "Production cutover is safe."

### Fail-fast guard (production)

If `resolver_aliases` has fewer than 5,000 rows and `PTI_ENV=production`, `make_resolver()` raises `RuntimeError` immediately. This prevents silent "no matches" when migration has not been run.

---

## Phase U2 — Entity Intelligence Pages

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- production PostgreSQL
- backend entity API layer
- frontend entity pages

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES

---

### Goal

Turn catalog entities into analyzable market objects.

After Phase U1 exposed the full known catalog to the UI, Phase U2 must make
perfume and brand pages useful as intelligence pages, not only searchable entries.

---

### Core Principle

An entity must be useful even when it is quiet.

Entity pages must support:
- active entities
- tracked but inactive entities
- catalog-only entities

---

### Requirements

#### 1. Perfume Entity Page
Must expose:
- canonical identity
- brand
- ticker
- activity state
- latest metrics
- signal state
- timeseries if available
- recent mentions
- notes / accords if available

#### 2. Brand Entity Page
Must expose:
- brand identity
- perfume count
- active perfume count
- linked perfumes
- brand-level recent activity if available

#### 3. Quiet State
Entities with no active signal:
- must still render
- must show quiet-state messaging
- must not disappear from the product

#### 4. Navigation Integrity
Screener and catalog search must open entity pages consistently.

---

### Constraints

- Postgres is the single source of truth
- frontend must present backend-computed values, not recompute them
- terminal-style UI must remain intact
- existing dashboard and screener flows must not break

---

### Completion Criteria

Phase is complete when:
- perfume pages render meaningful intelligence views
- brand pages render linked portfolio views
- catalog-only entities remain accessible
- entity pages support both active and quiet states
- production UI supports search → entity → analysis workflow

---

### What was implemented

**Backend — `perfume_trend_sdk/api/routes/entities.py`**

Two new endpoints registered BEFORE the catch-all `/{entity_id:path}`:

- `GET /api/v1/entities/perfume/{id}` — `{id}` = entity_id slug (tracked) OR resolver_id integer string (catalog-only). Returns state (active/tracked/catalog_only), aliases_count, notes/accords from `fragrantica_records`, timeseries, signals, mentions.
- `GET /api/v1/entities/brand/{id}` — Returns perfume_count (from resolver_perfumes), active_perfume_count, top_perfumes ordered by score, timeseries, signals.

**Frontend**
- New types: `PerfumeEntityDetail`, `BrandEntityDetail`, `BrandPerfumeRow`
- New fetch functions: `fetchPerfumeEntity`, `fetchBrandEntity`
- `entities/perfume/[id]/page.tsx` — state badge, chart, notes/accords section, signals, quiet state
- `entities/brand/[id]/page.tsx` — brand header, KPI row, linked perfumes table, signals
- Screener: all catalog rows now navigable (tracked → type slug URL, catalog-only → resolver_id URL)

### Navigation routing

| Entity type | Tracked | Catalog-only |
|-------------|---------|--------------|
| Perfume | `/entities/perfume/{entity_id}` | `/entities/perfume/{resolver_id}` |
| Brand | `/entities/brand/{entity_id}` | `/entities/brand/{resolver_id}` |
| Generic (backward compat) | `/entities/{entity_id}` | 404 |

---

## Phase U1 — Catalog Exposure in UI

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- production PostgreSQL (resolver/catalog tables)
- backend API layer
- frontend terminal UI (dashboard, screener, search)

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES

---

### Goal

Expose the full known perfume and brand catalog (resolver-backed, Postgres)
to the UI, not only the subset with active daily signals.

Transform PTI from:
"daily movers dashboard"

into:
"full market terminal with active + passive universe"

---

### Context

- Phase R1 completed:
  - resolver migrated to Postgres
  - ~56k perfumes available in resolver tables
- UI currently shows only active subset (~131 perfumes)
- This hides system scale and limits usability

---

### Core Principle

System must distinguish between:

1. Known universe (catalog)
2. Active market (signals today)

UI must expose both.

---

### Requirements

#### 1. Catalog API

System must provide endpoints:

- /api/v1/catalog/perfumes
- /api/v1/catalog/brands

These endpoints:

- MUST return entities even with zero activity
- MUST be backed by Postgres
- MUST NOT depend on SQLite

---

#### 2. Screener Modes

UI must support:

- Active Today
- All Perfumes
- All Brands

User must be able to explore full catalog, not only movers.

---

#### 3. Search Behavior

Search must operate on full catalog.

NOT limited to:
- movers
- today's signals

---

#### 4. Counts Separation

UI must display:

- total known perfumes
- active perfumes today

Same for brands.

---

#### 5. Quiet Entity Handling

Entities with no current activity:

- MUST remain accessible
- MUST have valid pages
- MUST show "no active signal" state

---

### Constraints

- Postgres is single source of truth
- No SQLite usage in runtime
- No silent fallback behavior
- No breaking of existing signal pipeline

---

### Completion Criteria

Phase is complete when:

- User can browse full perfume catalog in UI
- Search returns non-active entities
- Screener supports catalog exploration modes
- UI clearly separates known vs active entities
- System remains stable in production

---

### Strategic Impact

This phase converts PTI from:

signal-only system

into:

market exploration platform

and enables future layers:
- entity analytics
- historical tracking
- discovery & promotion pipelines

---

## ⚠️ Strict Architectural Constraint

If any code introduces:
- `/app/resolver-vol`
- `.db` files as resolver storage
- `sqlite3` usage in resolver or pipeline paths

→ it must be removed or rejected.

---

## Working Style Requirement

- Work step-by-step
- One phase → one goal
- No large multi-phase implementations in a single step
- Always verify before moving forward

---

## Phase E1 — Entity Hygiene for UI

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `resolver_perfumes` (catalog display filter)
- `entity_market` (screener dedup)
- catalog/screener API endpoints

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES — garbage names disappear from "All Perfumes" catalog tab; Byredo duplicate resolved in screener

### Status
COMPLETED — 2026-04-23

---

### Goal

Remove malformed and low-quality entity names from UI exposure before redesigning product screens.
UI quality comes before visual polish.

### Problem

The Parfumo/kaggle_v1 dataset (56k entries) included malformed entries:
- Fractional chars ('½'), pure numbers ('68', '88'), Cyrillic/Unicode symbols
- Names starting with punctuation (':00', ':11', '/50', ',7738')
- Generic single-word terms ('Cologne', 'Fragrance', 'Perfume', 'Scent')
- Single/double character abbreviations with no alphabetic content

The entity_market table contained 1 case-insensitive duplicate (Byredo Gypsy Water × 2).

### Audit Results (production, 2026-04-23)

| Category | Before | After | Hidden |
|----------|--------|-------|--------|
| resolver_perfumes (display) | 56,068 | 55,613 | 455 |
| resolver_brands (display) | 1,608 | 1,608 | 0 |
| entity_market duplicates | 1 | 0 | — |

Issue breakdown (perfumes):
- < 2 ASCII letters (fragments, symbols, fractions): 92
- Non-alphanumeric first character (':00', '/50', ',7738'): 387
- Pure generic terms ('Cologne', 'Fragrance', 'Perfume', 'Scent'): 4
- (categories overlap)

### What was implemented

**`perfume_trend_sdk/api/routes/catalog.py`**
- Added `_PERFUME_ELIGIBILITY_CLAUSES` — 3 SQL filter clauses always injected into WHERE:
  1. `LENGTH(REGEXP_REPLACE(rp.canonical_name, '[^a-zA-Z]', '', 'g')) >= 2` — at least 2 letters
  2. `rp.canonical_name ~ '^[a-zA-Z0-9]'` — starts with alphanumeric
  3. `LOWER(rp.canonical_name) NOT IN ('cologne','fragrance','perfume','scent','mist','spray')` — not generic
- Applied to both `catalog_perfumes` (data + count) and `_build_counts` sub-query
- Brand catalog filter: intentionally NOT applied (brands like '4711' are legitimate)

**`perfume_trend_sdk/api/routes/dashboard.py`**
- Added case-insensitive dedup step in screener after building `summaries` list
- When two rows share the same lowercase `canonical_name`, the row with higher `composite_market_score` is kept
- Eliminated 'Byredo Gypsy Water' / 'BYREDO Gypsy Water' screener duplicate

### Display Eligibility Rules Summary

Perfume must pass ALL:
1. Contains ≥ 2 ASCII alphabetic characters (anywhere in name)
2. First character is alphanumeric (a-z, A-Z, 0-9)
3. Not a bare generic term (cologne, fragrance, perfume, scent, mist, spray)

Brand: no filter applied — brand catalog is clean, and numeric brands like '4711' are legitimate.

### Non-Destructive Guarantee

Data remains in the database. The filter is applied only at the API serving layer.
No rows were deleted. Bad entries remain for potential manual cleanup or promotion decisions.

### Completion Criteria

- [x] 455 garbage perfume entries hidden from catalog UI
- [x] 1 Byredo Gypsy Water case duplicate removed from screener
- [x] `known_perfumes` count in header shows 55,613 (not 56,068)
- [x] catalog "All Perfumes" no longer shows ':00', '½', '68', '№1' etc.
- [x] Brand catalog unchanged (1,608 brands all visible, including '4711')
- [x] No DB deletes performed
- [x] Deployed to production Railway

### Known Remaining Issues (deferred to future phases)

- 'Alguien' in entity_market has brand_name='Alguien' (self-brand) — needs manual review
- Some brands have fragmented sub-brand names ('Creed Green Irish' instead of 'Creed') — systemic issue from aggregation
- 'TOM FORD Private Blend' / 'TOM FORD Signature' tracked as separate brands — correct at catalog level, confusing in UI
- case-insensitive duplicates remain in entity_market DB (not deleted, just hidden in screener)

---

## Phase E2 — Fix Brand → Perfume Linking

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `resolver_perfumes` / `resolver_brands` (source of truth for catalog)
- `entity_market` (market data overlay)
- `/api/v1/entities/brand/{id}` endpoint
- Frontend brand entity page

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES — brand pages now show full perfume list from catalog (e.g. Adidas: 114 perfumes)

### Status
COMPLETED — 2026-04-23

---

### Root Cause

`_brand_top_perfumes()` queried `entity_market` filtered by `brand_name` — only 144 tracked
entities. `_brand_perfume_count()` queried `resolver_perfumes JOIN resolver_brands` — 56k
catalog. Count and list were from different sources. For brands with zero tracked perfumes,
the list was always empty despite showing a non-zero count.

### Fix

**`perfume_trend_sdk/api/routes/entities.py`**
- Replaced `_brand_top_perfumes(db, name)` with `_brand_catalog_perfumes(db, name, limit=100)`
- New function: `resolver_perfumes JOIN resolver_brands` as source, LEFT JOIN `entity_market`
  + `entity_timeseries_daily` for market data where available
- Phase E1 eligibility filter applied (≥2 letters, alphanumeric start, not generic)
- `entity_id=None` for catalog-only perfumes (no ingested data yet)
- Returns up to 100 perfumes ordered by composite_market_score DESC, then name ASC
- `BrandEntityDetail` extended with `catalog_perfumes: List[BrandPerfumeRow]`
  (`top_perfumes` kept as alias for backward compat — same data)

**Frontend — `entities/brand/[id]/page.tsx`**
- `LinkedPerfumesTable`: "In Catalog" badge (gray) for entries with `entity_id=null`
- "Tracked" KPI: counts entries where `entity_id != null` (has market data)
- Section renamed from "Tracked Perfumes" to "Perfumes"
- "Showing N of M" footer when limit (100) < total `perfume_count`
- Empty state changed to "No perfumes in catalog"
- Catalog-only rows rendered at 50% opacity, non-clickable (no entity page yet)

**`frontend/src/lib/api/types.ts`**
- Added `catalog_perfumes: BrandPerfumeRow[]` field to `BrandEntityDetail`

### Completion Criteria

- [x] Adidas brand page shows ~114 perfumes
- [x] Tracked perfumes (with entity_id) appear first, sorted by score
- [x] Catalog-only perfumes appear below with "In Catalog" badge
- [x] KPI "Tracked" shows correct count (entity_id != null)
- [x] Phase E1 eligibility filter applied to catalog_perfumes
- [x] Deployed to production Railway

---

## Phase E3 — Brand Market Surface Fix

### Target Type
PRODUCTION_TARGETED

### Authoritative Targets
- Production PostgreSQL (`DATABASE_URL`)
- `entity_market` (brand rows with entity_type='brand')
- `entity_timeseries_daily` (brand roll-up rows)
- `signals` (brand-level signals)
- `aggregate_daily_market_metrics.py`

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES — Dashboard Brand toggle and Screener entity_type=brand filter now return brand entities

### Status
COMPLETED — 2026-04-23

---

### Root Cause

The aggregator (`aggregate_daily_market_metrics.py`) never created brand market rows:

1. **Aggregator exclusion**: `aggregator.py:251` — `if ent.get("entity_type") != "perfume": continue` — brands always excluded from snapshot writing
2. **entity_type hardcode**: `_upsert_entity_market()` always created rows with `entity_type="perfume"` regardless of actual entity type

As a result, `entity_market` contained only ~144 perfume rows and zero brand rows. The dashboard Brand toggle and screener `entity_type=brand` filter returned empty results.

---

### Fix

**`perfume_trend_sdk/jobs/aggregate_daily_market_metrics.py`**

Added `_rollup_brand_market_data(db, target_date) -> int`:
- Queries `entity_market (perfume type) JOIN entity_timeseries_daily` for the target date
- Groups by `em.brand_name`, filters `HAVING SUM(mention_count) > 0` (real activity required)
- Computes weighted-average metrics (score, growth weighted by mention_count; momentum/acceleration/volatility/confidence averaged)
- Upserts `EntityMarket` with `entity_type="brand"`, `entity_id="brand-{slugified_name}"` (e.g. `brand-creed`, `brand-parfums-de-marly`)
- Upserts `EntityTimeSeriesDaily` with brand roll-up metrics

Called in `run()` after perfume snapshots, before carry-forward. Returns count of brand rows upserted. Logged as `brand_rollup_written date=... count=...`.

---

### Data Path

```
perfume entity_market rows (existing)
→ JOIN entity_timeseries_daily for target_date
→ GROUP BY brand_name HAVING SUM(mention_count) > 0
→ _rollup_brand_market_data() aggregates metrics per brand
→ new brand entity_market rows (entity_type='brand', entity_id='brand-{slug}')
→ new brand entity_timeseries_daily rows
→ detect_breakout_signals creates brand-level signals
→ dashboard / screener Brand filter returns brand entities
```

---

### Production Verification (2026-04-23)

Backfill run across 2026-04-16 through 2026-04-23:

| Date | Brand rows written |
|------|--------------------|
| 2026-04-16 | 16 |
| 2026-04-17 | 55 |
| 2026-04-18 | 20 |
| 2026-04-19 | 38 |
| 2026-04-20 | 27 |
| 2026-04-21 | 15 |
| 2026-04-22 | 34 |
| 2026-04-23 | 33 |

Total brand entity_market rows: **79**

Key brands verified (latest date, ranked by score):

| Brand | entity_id | Score | Mentions |
|-------|-----------|-------|----------|
| Creed | brand-creed | 60.04 | 13 |
| Maison Francis Kurkdjian | brand-maison-francis-kurkdjian | 50.17 | 6 |
| Parfums de Marly | brand-parfums-de-marly | 46.56 | 6 |
| Dior | brand-dior | 41.78 | 3 |
| Yves Saint Laurent | brand-yves-saint-laurent | 39.76 | 2 |
| Chanel | brand-chanel | 37.00 | 2 |

Signal detection after backfill: 63 new signals (Apr 22) + 28 new signals (Apr 23), including brand-level breakout / new_entry / acceleration_spike signals.

---

### Completion Criteria

- [x] `_rollup_brand_market_data()` implemented and deployed
- [x] brand entity_market rows created for 79 unique brands
- [x] brand timeseries rows created across Apr 16–23
- [x] Creed, MFK, Parfums de Marly, Dior, YSL, Chanel all present with valid scores
- [x] Signal detection produces brand-level signals
- [x] Dashboard Brand toggle returns brand entities
- [x] Screener entity_type=brand filter returns brand entities
- [x] Brand entity pages navigable via `brand-{slug}` entity_id format

---

## Phase G1 — YouTube Query Expansion / Growth Diagnostics

### Target Type
CONFIG_ONLY (no schema, no migrations, no scoring changes)

### Authoritative Targets
- `configs/watchlists/perfume_queries.yaml` — only file to be changed

### Requires Commit / Push / Deploy
YES — when YAML is approved and explicitly confirmed for implementation

### Expected UI Change
INDIRECT — more entities appear in timeseries/signals as ingestion coverage widens

### Status
STATUS: COMPLETE — PRODUCTION VERIFIED (2026-04-25)

Commits:
- `d8141fa` — documented Phase G1 plan in CLAUDE.md
- `8a294dd` — expanded `configs/watchlists/perfume_queries.yaml` to 47 queries

---

### Problem

Current production YouTube ingestion uses only 14 static queries. These queries cover
a very small subset of the perfume market. The market layer, signal engine, and frontend
are all stable — growth is limited by query universe, not by entity_market, frontend,
or Railway infrastructure.

### Current Query State

- File: `configs/watchlists/perfume_queries.yaml`
- Current count: **14 queries**
- Current type: static, entity-based (specific perfume names only)
- Missing coverage:
  - brand discovery queries
  - intent/discovery queries (best of, blind buy, gift)
  - dupe/comparison queries
  - Arabic / Middle Eastern fragrance queries
  - community/content trend queries (viral, compliment getter)
  - mainstream/designer high-volume terms

---

### Quota Calculation

```
YouTube search.list = 100 units per query call
videos.list overhead = ~28 units/run (low, batch-fetched)

Current:
  14 queries × 100 units × 2 runs/day = 2,800 units/day
  + videos.list overhead ≈ 28 units/run × 2 = 56 units/day
  Total: ~2,856 units/day

Phase G1 target:
  47 queries × 100 units × 2 runs/day = 9,400 units/day
  + videos.list overhead ≈ 56 units/day (unchanged)
  Total: ~9,456 units/day

Daily quota limit: 10,000 units
Estimated headroom: ~544 units/day

Hard ceiling: do not exceed 47 total queries at 2 runs/day
unless YouTube quota is explicitly increased beyond 10,000 units.
```

---

### Approved G1 Scope

- Expand `configs/watchlists/perfume_queries.yaml` from **14 to exactly 47 total queries**
- Keep all original 14 queries unchanged at the top of the file
- Add exactly 33 new queries
- Organize YAML with commented section headers:
  1. Original core queries (14 — do not remove)
  2. Core entity expansions (broader terms for tracked perfumes/brands)
  3. Viral / mainstream high-volume queries
  4. Niche luxury queries
  5. Intent / discovery queries (blind buy, gift, best of, rankings)
  6. Dupe / affordable queries
  7. Arabic / Middle Eastern fragrance queries

---

### Required Query Strategy

- Replace any year-specific queries (e.g. "best perfume 2025") with current year (2026) versions
- Strengthen intent coverage: blind buy, gift, compliment getter, ranking
- Strengthen Arabic / Middle Eastern fragrance coverage (Lattafa, Armaf, Ajmal, Arabian Oud)
- Avoid ambiguous single-brand queries like "fragrance world lattafa khamrah" (too specific to a niche reseller)
- Avoid duplicating terms already covered by existing 14 queries

**Priority order for query slots:**
1. Original 14 (untouched)
2. Intent/discovery queries
3. Arabic / Middle Eastern fragrance queries
4. Viral mainstream queries
5. Niche luxury queries
6. Dupe / affordable queries

---

### Explicit Non-Goals

Phase G1 must NOT:
- Change any schema or database tables
- Run any Alembic migrations
- Change scoring weights or composite market score formula
- Change signal detection thresholds
- Change any frontend component or page
- Change `entity_market` rows or aggregation logic
- Enable automatic candidate promotion (`promote_candidates --allow-create`)
- Change auth, Supabase, or Railway service structure
- Add new pipeline steps to `start_pipeline.sh` or `start_pipeline_evening.sh`

---

### Verification Plan

**Step 1 — Local test before deploy:**
```bash
python3 scripts/ingest_youtube.py --max-results 5 --lookback-days 1
```
Expected: no errors, each new query fetches 5 videos, resolver attempts entity matching.

**Step 2 — Railway production verification after deploy:**
- Confirm pipeline starts normally (no import error, no YAML parse error)
- Confirm no YouTube quota exceeded error in logs
- Confirm `canonical_content_items` count increases day-over-day
- Confirm `entity_mentions` count increases day-over-day
- Confirm `fragrance_candidates` receives new unresolved entries
- Confirm `entity_timeseries_daily` active entity count holds or grows
- Confirm signals do not explode into obvious noise (spot-check top signals)

**SQL verification queries (run before and after first G1 pipeline cycle):**

```sql
-- Content items ingested per day by source
SELECT DATE(collected_at) AS day, source_platform, COUNT(*) AS items
FROM canonical_content_items
WHERE DATE(collected_at) >= CURRENT_DATE - INTERVAL '3 days'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- Entity mentions per day (total + distinct entities)
SELECT DATE(occurred_at) AS day,
       COUNT(*) AS total_mentions,
       COUNT(DISTINCT entity_id) AS distinct_entities
FROM entity_mentions
WHERE DATE(occurred_at) >= CURRENT_DATE - INTERVAL '3 days'
GROUP BY 1
ORDER BY 1 DESC;

-- Candidate queue growth per day by validation status
SELECT DATE(last_seen) AS day,
       validation_status,
       COUNT(*) AS candidates
FROM fragrance_candidates
WHERE DATE(last_seen) >= CURRENT_DATE - INTERVAL '3 days'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- Active entities in timeseries per day
SELECT date,
       COUNT(*) AS total_rows,
       SUM(CASE WHEN mention_count > 0 THEN 1 ELSE 0 END) AS active_entities
FROM entity_timeseries_daily
WHERE date >= CURRENT_DATE - INTERVAL '3 days'
GROUP BY date
ORDER BY date DESC;

-- Signals generated per day by type
SELECT DATE(detected_at) AS day, signal_type, COUNT(*) AS count
FROM signals
WHERE DATE(detected_at) >= CURRENT_DATE - INTERVAL '3 days'
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

---

### Rollback Plan

If the expanded YAML causes problems (quota error, noise spike, parse failure):

```bash
# Option A — revert entire commit
git revert HEAD --no-edit
git push origin main

# Option B — restore only the YAML file
git checkout HEAD~1 -- configs/watchlists/perfume_queries.yaml
git commit -m "revert: restore original YouTube query watchlist (14 queries)"
git push origin main
```

Railway auto-deploys on push. The next pipeline cycle uses the restored 14-query file.
No DB rollback required — ingested data from G1 queries is additive and harmless.

---

### Production Verification Results (2026-04-25)

| Metric | Apr 24 (pre-G1) | Apr 25 (G1) | Delta |
|--------|-----------------|-------------|-------|
| YouTube items | 44 | **252** | +5.7× |
| Entity mentions | 13 | **16** | +23% |
| Distinct entities | 4 | **7** | +75% |
| Fragrance candidates | 919 | **5,317** | +5.8× |
| Active entities | 16 | **23** | +44% |
| Total signals | 12 | **12** | Stable |
| new_entry signals | 1 | **3** | +200% |

Additional verification checks passed:
- No YouTube quota or auth errors
- No fatal pipeline errors
- `validate_candidates` completed — no `pending` rows remaining
- No signal noise explosion — thresholds held correctly
- `verify_market_state` passed — 100% real data, no synthetic content
- All 47 queries loaded and executed inside Railway infrastructure

### Next Bottleneck

G1 increased raw YouTube and candidate coverage significantly.

**The next growth bottleneck is resolver recall, alias sparsity, and candidate promotion** —
not the query input layer.

- More queries → more unresolved candidates → gap is now in resolution, not ingestion
- Do not lower signal thresholds
- Do not change scoring
- Do not change entity_market

### Next Phase

→ Phase G2 — Targeted Resolver Alias Seed (COMPLETED 2026-04-25)

---

## Phase G2 — Targeted Resolver Alias Seed

### Target Type
PRODUCTION_TARGETED (alias writes only — no migrations, no entity creation)

### Authoritative Targets
- Production PostgreSQL (`resolver_aliases` table)
- `scripts/seed_g2_aliases.py` (standalone, idempotent, psycopg2 only)

### Requires Commit / Push / Deploy
YES (script committed; aliases written directly via DATABASE_URL public proxy)

### Expected UI Change
INDIRECT — resolver recall improves; brand/perfume mentions in new content resolve
instead of going to fragrance_candidates

### Status
STATUS: COMPLETE — PRODUCTION APPLIED (2026-04-25)

Commit: `ddb145b` — feat: seed targeted G2 resolver aliases

---

### Audit Findings (pre-seed)

| Metric | Value |
|--------|-------|
| resolver_perfumes | 56,068 |
| resolver_aliases (before) | 12,889 |
| Perfumes with zero aliases | 53,822 (96%) |
| Avg aliases per perfume | 0.23 |
| Estimated resolver hit rate after G1 | ~0.3% |
| Total candidates in queue | 37,213 |

Root cause: 96% of the resolver catalog had no alias entries. The resolver hot-path
matches via `resolver_aliases.normalized_alias_text` — entities with no alias rows are
unreachable by any variant of their name. All G1 Arabic/ME query traffic was going to
`fragrance_candidates` instead of `entity_mentions`.

---

### Dry-Run Summary (no DB writes)

| Result | Count |
|--------|-------|
| Total targets | 33 |
| Found in KB | 14 |
| MISSING (perfumes not in resolver_perfumes) | 19 |
| AMBIGUOUS | 0 |
| Already existing aliases | 5 |
| Would insert | 9 |

Already-existing (seeded by prior Phase 4P runs): `lattafa`, `khamrah`,
`lattafa khamrah`, `cedrat boise`, `mancera cedrat boise`.

---

### Apply Result

9 aliases inserted — exactly matching dry-run would-insert count. No new entities created.

| Alias | Type | entity_id | Target |
|-------|------|-----------|--------|
| `armaf` | brand | 1467 | Armaf |
| `rasasi` | brand | 296 | Rasasi |
| `al haramain` | brand | 451 | Al Haramain |
| `ajmal` | brand | 308 | Ajmal |
| `swiss arabian` | brand | 708 | Swiss Arabian |
| `arabian oud` | brand | 366 | Arabian Oud |
| `initio side effect` | perfume | 50629 | Initio Side Effect |
| `rouge 540` | perfume | 2 | Maison Francis Kurkdjian Baccarat Rouge 540 |
| `br540` | perfume | 2 | Maison Francis Kurkdjian Baccarat Rouge 540 |

### Production counts after apply

| Table | Before | After | Delta |
|-------|--------|-------|-------|
| resolver_aliases | 12,889 | 12,898 | +9 |
| resolver_perfumes | 56,068 | 56,068 | 0 |
| resolver_brands | 1,608 | 1,608 | 0 |
| resolver_fragrance_master | 56,068 | 56,068 | 0 |

---

### Rollback

```sql
DELETE FROM resolver_aliases WHERE match_type = 'g2_seed';
```

All G2 aliases are tagged `match_type='g2_seed'` — fully reversible in one statement.

---

### Safety Constraints (ENFORCED)

- No new resolver_perfumes rows created
- No new resolver_fragrance_master rows created
- No new resolver_brands rows created
- No migrations run
- No pipeline files modified
- No scoring changes
- No signal threshold changes
- No entity_market changes
- Script is idempotent (ON CONFLICT DO NOTHING)

---

### Next Bottleneck — 19 Missing Perfumes

19 high-value perfume targets were MISSING from `resolver_perfumes` entirely.
These are real, high-traffic perfumes absent from the Parfumo/Kaggle dataset used
for Phase 5 catalog import:

- Armaf Club de Nuit, Armaf Club de Nuit Intense Man
- Lattafa Oud Mood, Lattafa Yara
- Rasasi Hawas
- Al Haramain Amber Oud
- Ajmal Evoke
- By Kilian Angels' Share
- Paco Rabanne 1 Million
- Yves Saint Laurent Black Opium

These require controlled entity creation in `resolver_perfumes` +
`resolver_fragrance_master` before aliases can point to them.

**Rules for next phase (G2.1):**
- Do NOT auto-create entities via `promote_candidates --allow-create` for these
- Do NOT lower signal thresholds or change scoring to compensate
- Do NOT modify entity_market to work around missing resolver entries
- Entity creation must be explicit, bounded, and dry-run verified first

→ Phase G2.1 Batch 1 — COMPLETED 2026-04-25 (see section below)

---

## Phase G2.1 — Controlled Missing Perfume Entity Seed

### Target Type
PRODUCTION_TARGETED (resolver_perfumes + resolver_fragrance_master + resolver_aliases writes only)

### Authoritative Targets
- Production PostgreSQL (`resolver_perfumes`, `resolver_fragrance_master`, `resolver_aliases`)
- `scripts/seed_g2_missing_perfumes.py` (standalone, idempotent, psycopg2 only)

### Requires Commit / Push / Deploy
YES (script committed; entities written directly via DATABASE_URL public proxy)

### Expected UI Change
INDIRECT — resolver recall improves; Arabic/ME perfume mentions now resolve instead
of going to fragrance_candidates

---

### Purpose

Seed resolver KB with high-value perfume entities absent from the Parfumo/Kaggle
Phase 5 import. Uses two operation types:

- **CREATE** — inserts new entity into `resolver_perfumes` + `resolver_fragrance_master` + aliases
- **ALIAS_TO_EXISTING** — inserts alias rows only, pointing to an already-existing entity

Source tagging:
- `resolver_fragrance_master.source = 'g2_entity_seed'`
- `resolver_aliases.match_type = 'g2_entity_seed'`

Script: `scripts/seed_g2_missing_perfumes.py` — default dry-run, `--apply` required for writes.
Batch-controlled via `--batch N`.

---

### Batch 1 — STATUS: COMPLETE — PRODUCTION APPLIED (2026-04-25)

Commit: `988765d`

#### Dry-Run Summary

| Metric | Value |
|--------|-------|
| CREATE targets | 3 |
| ALIAS_TO_EXISTING targets | 2 |
| would_create | 3 |
| would_insert aliases | 7 |
| missing brand | 0 |
| ambiguous | 0 |
| Initio Side Effect alias | EXISTING — already seeded, skipped |

#### Apply Results

**Created — `resolver_perfumes` (+3):**

| id | canonical_name | brand_id |
|----|---------------|----------|
| 113591 | Lattafa Oud Mood | 9 |
| 113592 | Lattafa Yara | 9 |
| 113593 | Ajmal Evoke | 308 |

**Created — `resolver_fragrance_master` (+3, source=`g2_entity_seed`):**

| fragrance_id | brand | perfume | perfume_id |
|-------------|-------|---------|------------|
| g2e_lattafa_oud_mood | Lattafa | Oud Mood | 113591 |
| g2e_lattafa_yara | Lattafa | Yara | 113592 |
| g2e_ajmal_evoke | Ajmal | Evoke | 113593 |

**Created — `resolver_aliases` (+7, match_type=`g2_entity_seed`):**

| alias_text | → entity_id | canonical |
|-----------|-------------|----------|
| oud mood | 113591 | Lattafa Oud Mood |
| lattafa oud mood | 113591 | Lattafa Oud Mood |
| yara | 113592 | Lattafa Yara |
| lattafa yara | 113592 | Lattafa Yara |
| ajmal evoke | 113593 | Ajmal Evoke |
| angels share | 9119 | Angels' Share (Kilian) — ALIAS_TO_EXISTING |
| kilian angels share | 9119 | Angels' Share (Kilian) — ALIAS_TO_EXISTING |

**Important notes:**
- Angels' Share was NOT created as a new entity. Aliases point to existing `resolver_perfumes.id=9119` under Kilian (brand_id=670). By Kilian (brand_id=158) has no Angels perfumes — creating there would split the KB.
- Initio Side Effect alias (`initio side effect` → id=50629) already existed and was correctly skipped.

#### Production Count Deltas

| Table | Before | After | Delta |
|-------|--------|-------|-------|
| resolver_perfumes | 56,068 | 56,071 | +3 |
| resolver_fragrance_master | 56,068 | 56,071 | +3 |
| resolver_aliases | 12,898 | 12,905 | +7 |

#### Verification Results

```
g2_entity_seed perfumes (via FM join):  3   ✅
g2_entity_seed fragrance_master:        3   ✅
g2_entity_seed aliases:                 7   ✅
Alias spot-check (all 7):               PASS ✅
Angels' Share → id=9119 (Kilian):       PASS ✅
Duplicate normalized_name check:        0 duplicates ✅
```

#### Safety Constraints (Batch 1)

- No migrations run
- No pipeline files modified
- No scoring changes
- No signal threshold changes
- No entity_market changes
- No `promote_candidates --allow-create` used
- Script is idempotent (ON CONFLICT DO NOTHING)

#### Rollback (Batch 1 only)

```sql
DELETE FROM resolver_aliases
WHERE match_type = 'g2_entity_seed'
  AND normalized_alias_text IN (
    'oud mood', 'lattafa oud mood',
    'yara', 'lattafa yara',
    'ajmal evoke',
    'angels share', 'kilian angels share'
  );

DELETE FROM resolver_fragrance_master
WHERE source = 'g2_entity_seed'
  AND canonical_name IN (
    'Lattafa Oud Mood', 'Lattafa Yara', 'Ajmal Evoke'
  );

DELETE FROM resolver_perfumes
WHERE id IN (113591, 113592, 113593);
```

Full rollback for all batches (when multiple batches applied):
```sql
DELETE FROM resolver_aliases WHERE match_type = 'g2_entity_seed';
DELETE FROM resolver_perfumes
  WHERE id IN (
    SELECT perfume_id FROM resolver_fragrance_master
    WHERE source = 'g2_entity_seed' AND perfume_id IS NOT NULL
  );
DELETE FROM resolver_fragrance_master WHERE source = 'g2_entity_seed';
```

---

### Batch 2 — STATUS: COMPLETE — PRODUCTION APPLIED (2026-04-25)

Commit: `3773269`

#### Dry-Run Summary

| Metric | Value |
|--------|-------|
| CREATE targets | 3 |
| ALIAS_TO_EXISTING targets | 0 |
| would_create | 3 |
| would_insert aliases | 6 |
| missing brand | 0 |
| CONFLICT_OTHER_ENTITY | 0 — none of the 6 alias strings existed in resolver_aliases |

#### Apply Results

**Created — `resolver_perfumes` (+3):**

| id | canonical_name | brand_id |
|----|---------------|----------|
| 113594 | Armaf Club de Nuit | 1467 |
| 113595 | Armaf Club de Nuit Intense Man | 1467 |
| 113596 | Rasasi Hawas | 296 |

**Created — `resolver_fragrance_master` (+3, source=`g2_entity_seed`):**

| fragrance_id | brand | perfume | perfume_id |
|-------------|-------|---------|------------|
| g2e_armaf_club_de_nuit | Armaf | Club de Nuit | 113594 |
| g2e_armaf_cdn_intense_man | Armaf | Club de Nuit Intense Man | 113595 |
| g2e_rasasi_hawas | Rasasi | Hawas | 113596 |

**Created — `resolver_aliases` (+6, match_type=`g2_entity_seed`):**

| alias_text | → entity_id | canonical |
|-----------|-------------|----------|
| club de nuit | 113594 | Armaf Club de Nuit |
| armaf club de nuit | 113594 | Armaf Club de Nuit |
| club de nuit intense man | 113595 | Armaf Club de Nuit Intense Man |
| armaf club de nuit intense man | 113595 | Armaf Club de Nuit Intense Man |
| hawas | 113596 | Rasasi Hawas |
| rasasi hawas | 113596 | Rasasi Hawas |

#### Cumulative g2_entity_seed counts (Batch 1 + 2)

| Table | Count |
|-------|-------|
| resolver_perfumes (via FM join) | 6 |
| resolver_fragrance_master | 6 |
| resolver_aliases | 13 |

#### Verification Results

```
Alias spot-check (all 6):            PASS ✅
Duplicate normalized_name check:     0 duplicates ✅
No pipeline/migration/scoring changes ✅
```

#### Rollback (Batch 2 only)

```sql
DELETE FROM resolver_aliases
WHERE match_type = 'g2_entity_seed'
  AND normalized_alias_text IN (
    'club de nuit',
    'armaf club de nuit',
    'club de nuit intense man',
    'armaf club de nuit intense man',
    'hawas',
    'rasasi hawas'
  );

DELETE FROM resolver_fragrance_master
WHERE source = 'g2_entity_seed'
  AND canonical_name IN (
    'Armaf Club de Nuit',
    'Armaf Club de Nuit Intense Man',
    'Rasasi Hawas'
  );

DELETE FROM resolver_perfumes
WHERE id IN (113594, 113595, 113596);
```

Full rollback for all batches:
```sql
DELETE FROM resolver_aliases WHERE match_type = 'g2_entity_seed';
DELETE FROM resolver_perfumes
  WHERE id IN (
    SELECT perfume_id FROM resolver_fragrance_master
    WHERE source = 'g2_entity_seed' AND perfume_id IS NOT NULL
  );
DELETE FROM resolver_fragrance_master WHERE source = 'g2_entity_seed';
```

---

### Batch 3 — STATUS: COMPLETE — PRODUCTION VERIFIED (2026-04-26)

Commit: `a8d6389`

#### Entities created (`resolver_perfumes` +3, `resolver_fragrance_master` +3)

| id | canonical_name | brand_id | source |
|----|---------------|----------|--------|
| 113597 | Al Haramain Amber Oud | 451 | g2_entity_seed |
| 113598 | Paco Rabanne 1 Million | 326 | g2_entity_seed |
| 113599 | Yves Saint Laurent Black Opium | 4 | g2_entity_seed |

#### Aliases added (`resolver_aliases` +6, match_type=`g2_entity_seed`)

| alias_text | → entity |
|-----------|---------|
| `al haramain amber oud` | Al Haramain Amber Oud |
| `1 million` | Paco Rabanne 1 Million |
| `paco rabanne 1 million` | Paco Rabanne 1 Million |
| `black opium` | Yves Saint Laurent Black Opium |
| `ysl black opium` | Yves Saint Laurent Black Opium |
| `yves saint laurent black opium` | Yves Saint Laurent Black Opium |

#### Alias conflict handled

`"amber oud"` was intentionally NOT added for Al Haramain Amber Oud.
Reason: entity id=3113 (PARFUMS DE NICOLAI Amber Oud EDP) already holds
alias `normalized_alias_text='amber oud'` with `match_type='exact', confidence=1.0`.
The lower-id entity wins in the in-memory resolver — adding the same alias for
Al Haramain (id=113597) would shadow it. Only `'al haramain amber oud'` is used.

#### Generic EDP alias cleanup (KB hygiene fix)

Four generic EDP aliases for entity id=408 (Alguien Eau De Parfum) were removed
from `resolver_aliases` because they caused false-positive Alguien matches on any
content containing the phrase "eau de parfum":

| Deleted id | alias_text |
|-----------|-----------|
| 2036 | `eau de parfum` |
| 2037 | `eau de parfum eau de parfum` |
| 2038 | `eau de parfum eau de parfum perfume` |
| 2039 | `eau de parfum perfume` |

Kept intact: id=2034 (`alguien eau de parfum`) and id=2035 (`alguien eau de parfum eau de parfum`).
These are specific enough to not trigger false positives on unrelated content.

After cleanup: Alguien false positives in Batch 3 re-resolution dry-run = 0.

#### Cumulative g2_entity_seed counts (Batches 1 + 2 + 3)

| Table | Count |
|-------|-------|
| resolver_perfumes (via FM join) | 9 |
| resolver_fragrance_master | 9 |
| resolver_aliases | 19 |

---

## G2 Re-resolution and Historical Backfill

### STATUS: COMPLETE — PRODUCTION VERIFIED (2026-04-25)

### Root Cause

188 content items were resolved at 16:19–16:20 UTC on 2026-04-25, before G2 aliases and
entities were seeded (16:59–17:52 UTC). Evening pipeline ingestion deduplicated the same
videos without re-resolving them. As a result, G2-relevant entities (Armaf Club de Nuit,
Rasasi Hawas, Lattafa Yara, Angels' Share, MFK Baccarat Rouge 540 via `rouge 540`/`br540`
shorthands) were missing from `resolved_signals` for all content ingested that day.

Because resolved_signals feeds the aggregation layer, all historical aggregation rows for
dates where this content was published were also missing these entity links.

---

### Remediation Script

**`scripts/reresolve_g2_stale_content.py`** — commit `a6800bc`

- Standalone, self-contained (psycopg2 only, no SDK dependency)
- Pre-loads all 12,477+ `resolver_aliases` rows into memory in one query
- Applies sliding window matching locally (mirrors `perfume_resolver.py`, `_MAX_WINDOW=6`)
- Stale cutoff: `resolved_signals.created_at < '2026-04-25 16:59:00'`
- G2 keyword filter: 24 terms (lattafa, armaf, rasasi, al haramain, ajmal, oud mood, khamrah,
  yara, club de nuit, hawas, amber oud, evoke, angels share, rouge 540, br540, etc.)
- Default dry-run; `--apply` flag required for writes
- UPSERT on `resolved_signals.content_item_id` — idempotent, safe to re-run
- Tags updated rows with `resolver_version='1.1-g2-rereresolve'`

**Re-resolution results:**
- Items checked: 188
- Items gaining new entities: 117
- Total new entity links written: 206
- Top recovered entities: MFK Baccarat Rouge 540 (52×), Armaf Club de Nuit (20×),
  Creed Aventus (19×), Rasasi Hawas (7×)

---

### 17-Date Historical Aggregation + Signal Backfill

After re-resolving `resolved_signals`, aggregation and signal detection were re-run for all
17 dates containing affected published_at content, newest-first:

2026-04-24, 2026-04-23, 2026-04-22, 2026-04-21, 2026-04-20, 2026-04-19, 2026-04-18,
2026-04-17, 2026-04-16, 2026-04-15, 2026-04-14, 2026-04-13, 2026-04-11, 2026-04-10,
2026-04-09, 2026-04-08, 2026-04-07

Commands used per date:
```bash
DATABASE_URL=<prod-url> python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date YYYY-MM-DD
DATABASE_URL=<prod-url> python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date YYYY-MM-DD
```

Signal detection is idempotent — stale signals are cleared before re-detection on each run
(`detect_breakout_signals_cleared_stale` logged per date). No duplicate signals produced.

---

### Final Verification Results

**All 17 dates populated — no gaps, no errors, no duplicate signals.**

| Date | Active Entities | Total Mentions | Signals |
|------|----------------|----------------|---------|
| 2026-04-24 | 43 | 121 | 36 |
| 2026-04-23 | 93 | 191 | 42 |
| 2026-04-22 | 85 | 195 | 67 |
| 2026-04-21 | 34 | 76 | 13 |
| 2026-04-20 | 66 | 176 | 37 |
| 2026-04-19 | 91 | 200 | 41 |
| 2026-04-18 | 54 | 168 | 32 |
| 2026-04-17 | 129 | 334 | 101 |
| 2026-04-16 | 37 | 110 | 30 |
| 2026-04-15 | 20 | 53 | 14 |
| 2026-04-14 | 18 | 31 | 6 |
| 2026-04-13 | 82 | 122 | 77 |
| 2026-04-11 | 12 | 26 | 8 |
| 2026-04-10 | 12 | 34 | 9 |
| 2026-04-09 | 26 | 65 | 23 |
| 2026-04-08 | 10 | 22 | 11 |
| 2026-04-07 | 6 | 10 | 6 |

**G2 entity mentions confirmed in `entity_mentions` table:**
- MFK Baccarat Rouge 540 — every date Apr 07–25 (retroactive `rouge 540`/`br540` aliases firing)
- Armaf Club de Nuit — Apr 15–25
- Armaf Club de Nuit Intense Man — Apr 15–25
- Rasasi Hawas — Apr 18–25
- Lattafa Yara — Apr 13, Apr 23, Apr 24
- Lattafa Khamrah — Apr 17, Apr 24
- Angels' Share — Apr 09, Apr 24, Apr 25

**entity_market rows created (4 of 6 G2 entities):**
- Armaf Club de Nuit ✅
- Armaf Club de Nuit Intense Man ✅
- Lattafa Yara ✅
- Rasasi Hawas ✅
- Lattafa Oud Mood — not yet (aliases seeded, no ingested content matched yet — expected)
- Ajmal Evoke — not yet (aliases seeded, no ingested content matched yet — expected)

**Resolver funnel (Apr 07–25):**
- entity_mentions: 2,876
- fragrance_candidates: 37,296
- mention-to-candidate ratio: 7.71%

---

### Operational Note — Future Alias/Entity Seeds

If resolver aliases or entities are seeded AFTER content has already been ingested and
resolved, a targeted re-resolution + date-specific aggregation backfill is required to
surface those entities in historical timeseries and signals.

Pattern:
1. Identify stale content (resolved before seed cutoff, containing relevant keywords)
2. Re-resolve using in-memory alias table (pre-load all aliases in one query)
3. UPSERT `resolved_signals` for affected items
4. Re-run `aggregate_daily_market_metrics --date` for each affected published_at date
5. Re-run `detect_breakout_signals --date` for each affected date (idempotent)

---

---

## G2 Batch 3 Re-resolution and Historical Backfill

### STATUS: COMPLETE — PRODUCTION VERIFIED (2026-04-26)

Commit: `a5eac76`

### Root Cause

27 content items were resolved before Batch 3 aliases were seeded (cutoff 2026-04-26 02:55:16 UTC).
These items contained Batch 3 keywords (al haramain, paco rabanne, 1 million, black opium,
yves saint laurent) but could not resolve to the new entities because the aliases did not
exist at resolution time.

### Remediation Script

**`scripts/reresolve_g2_stale_content.py`** extended with `--batch` and `--cutoff` flags
(commit `a5eac76`). Added `BATCH_CONFIGS` dict:

- Batch 1: original G2 seed (cutoff 2026-04-25 16:59:00, resolver_version `1.1-g2-rereresolve`)
- Batch 3: Al Haramain / Paco Rabanne / YSL Black Opium (cutoff 2026-04-26 02:55:16,
  resolver_version `1.2-g2-b3-reresolve`)

Default behavior (no flags → batch 1) is unchanged. Fully idempotent UPSERT.

### Batch 3 Re-resolution Results

- Items checked: 41
- Items gaining new entities: 27
- Total new entity links written: 27
- Top recovered:
  - Yves Saint Laurent Libre: 19×
  - Yves Saint Laurent Black Opium: 3×
  - Al Haramain Amber Oud: 3×
  - Paco Rabanne 1 Million: 2×

### 12-Date Historical Aggregation + Signal Backfill

Dates affected (published_at of re-resolved content):

2026-04-24, 2026-04-23, 2026-04-22, 2026-04-19, 2026-04-18, 2026-04-17,
2026-04-16, 2026-04-15, 2026-04-14, 2026-04-11, 2026-04-10, 2026-04-09

All 12 dates: exit code 0, no errors, no duplicate signals.

### Verification Results

**All 3 Batch 3 entities in `entity_market` — all `trend_state=rising`:**
- Al Haramain Amber Oud ✅ (latest score=31.53, mentions confirmed Apr 09, 11, 24)
- Paco Rabanne 1 Million ✅ (latest score=31.94, mentions confirmed Apr 22, 24)
- Yves Saint Laurent Black Opium ✅ (latest score=30.21, mentions confirmed Apr 09, 17, 19)

**YSL Libre entity mentions confirmed across all 12 backfill dates.**

**Known issue — `entity_market.brand_name` truncation:**
The 3 new Batch 3 entities have truncated `brand_name` values in `entity_market`
(`"Al Haramain Amber"`, `"Paco Rabanne 1"`, `"Yves Saint Laurent Black"`).
This is caused by existing `_rollup_brand_market_data` behavior that parses brand_name
from canonical_name rather than looking up the resolver brand table.
It does NOT affect resolution, signal detection, or entity page routing.
Deferred as a future brand-rollup display cleanup task.

### Explicit Non-Goals (as of 2026-04-26)

- No further G2 backfill is required
- Do not change signal thresholds or scoring
- Do not modify entity_market directly
- Do not run ingestion for historical dates
- Do not patch `brand_name` truncation in this step

---

## Brand Name Truncation Fix / G2 Brand Rollup Cleanup

### STATUS: COMPLETE — PRODUCTION VERIFIED (2026-04-26)

Commits:
- `52c4170` — aggregator fix: resolver lookup before heuristic split + `scripts/fix_g2_brand_mappings.py`
- `a675de2` — UUID cast fix in remediation script Step G (`ANY(%s)` → `ANY(%s::uuid[])`)

---

### Root Cause

`_upsert_brand_and_perfume_catalog_first` in `aggregate_daily_market_metrics.py` used a
`rsplit(" ", 1)` heuristic to derive a brand name when a perfume was first encountered in
ingestion but not yet present in the market `perfumes` table.

G2-seeded entities exist in `resolver_perfumes` + `resolver_fragrance_master` but NOT in
the market `perfumes` table until aggregation first writes them. The heuristic fires on
multi-word perfume parts and produces truncated phantom brand names:

| Canonical name | Phantom brand created | Correct brand |
|----------------|----------------------|---------------|
| Armaf Club de Nuit | Armaf Club de | Armaf |
| Armaf Club de Nuit Intense Man | Armaf Club de Nuit Intense | Armaf |
| Al Haramain Amber Oud | Al Haramain Amber | Al Haramain |
| Paco Rabanne 1 Million | Paco Rabanne 1 | Paco Rabanne |
| Yves Saint Laurent Black Opium | Yves Saint Laurent Black | Yves Saint Laurent |

The phantom brand cascade: wrong brand name → wrong market `brands` row →
wrong `perfumes.brand_id` → `_resolve_brand_name` reads it back → wrong
`entity_market.brand_name` → wrong brand rollup entity_id slug.

---

### Fix — `_upsert_brand_and_perfume_catalog_first`

Added resolver lookup as step 2 before the heuristic (now step 3):

1. If the perfume slug already exists in market `perfumes` — return (no change needed)
2. **NEW**: Look up `resolver_fragrance_master JOIN resolver_perfumes` by `normalized_name` →
   use `rfm.brand_name` if found (authoritative, no heuristic)
3. Fallback to `rsplit(" ", 1)` only if resolver lookup returns nothing (new entity not
   in any seed — rare path)

Wrapped in `try/except` for SQLite dev compatibility (`resolver_*` tables are Postgres-only).

---

### Data Remediation Applied — `scripts/fix_g2_brand_mappings.py`

Executed in 7 sequential steps in a single transaction (FK order):

| Step | Action | Result |
|------|--------|--------|
| A | Find/create correct market brand rows | Al Haramain, Armaf, Paco Rabanne created |
| B | `UPDATE perfumes SET brand_id` → correct brands | 5 rows updated |
| C | `UPDATE entity_market SET brand_name` for perfume rows | 5 rows updated |
| D | `DELETE FROM signals` under phantom brand entity_market UUIDs | 18 rows deleted |
| E | `DELETE FROM entity_timeseries_daily` under phantom UUIDs | 25 rows deleted |
| F | `DELETE FROM entity_market` phantom brand rows | 5 rows deleted |
| G | `DELETE FROM brands` phantom brand rows | 5 rows deleted (required `ANY(%s::uuid[])` cast) |

---

### 12-Date Aggregation + Signal Detection Backfill

After data remediation, re-ran aggregation + signal detection for all affected dates:

```
2026-04-25  2026-04-24  2026-04-23  2026-04-22  2026-04-20  2026-04-19
2026-04-18  2026-04-17  2026-04-16  2026-04-15  2026-04-11  2026-04-09
```

Signal detection is idempotent — clears stale signals before re-detecting. All 12 dates:
exit code 0, no errors, no duplicate signals.

Correct brand rollups created across affected dates:

| entity_id | canonical_name | entity_type |
|-----------|---------------|-------------|
| brand-armaf | Armaf | brand |
| brand-al-haramain | Al Haramain | brand |
| brand-paco-rabanne | Paco Rabanne | brand |
| brand-yves-saint-laurent | Yves Saint Laurent | brand |

---

### Verification Results (all PASS)

- **A** — perfumes point to correct brands: ✅ 5/5
- **B** — entity_market.brand_name corrected: ✅ 5/5
- **C** — phantom brands gone: ✅ 0 rows
- **D** — phantom entity_market rows gone: ✅ 0 rows
- **E** — correct brand rollups exist: ✅ brand-armaf, brand-al-haramain, brand-paco-rabanne, brand-yves-saint-laurent
- **F** — signals clean and populated across all 12 dates: ✅

---

### Safety Constraints (all confirmed)

- No migrations run
- No schema changes
- No scoring changes
- No signal threshold changes
- No ingestion changes
- No pipeline script changes

---

### Operational Note — Future Resolver-Seeded Entities

For any future resolver-seeded perfumes (via `seed_g2_missing_perfumes.py` or equivalent),
the aggregator now correctly derives brand_name from `resolver_fragrance_master.brand_name`
via a `JOIN resolver_perfumes ON normalized_name` lookup before falling back to the
`rsplit` heuristic. Phantom brand creation for multi-word perfume names is prevented.

---

## Phase D1.0C — Dashboard Signal Verification After Auth Repair (2026-04-26)

### Target Type
READ-ONLY INVESTIGATION — no schema changes, no migrations, no code changes

### Status
COMPLETE — data healthy, inconsistency explained and documented

---

### Auth Status (cumulative D1.0 summary)

| Component | Status |
|-----------|--------|
| `/login` page renders form | ✅ FIXED — commit 385b0f4 (force-dynamic) |
| Magic link email delivery | ✅ FIXED — commit 701ebc7 (SUPABASE_ANON_KEY server-side var) |
| `/auth/callback` session finalization | ✅ FIXED — commit adea99c (CallbackClient Server Component wrapper) |
| Dashboard loads authenticated | ✅ VERIFIED |
| Domain migration (D1.1) | ✅ CLEARED — no blockers remaining |

Root pattern across all three fixes: `NEXT_PUBLIC_*` variables are statically inlined into
the browser bundle at Next.js build time. Railway Nixpacks does not expose service variables
to the `next build` step. Every page/component that called `createBrowserClient(url, undefined)`
crashed. Fix: Server Component reads `SUPABASE_ANON_KEY` (non-NEXT_PUBLIC_, always runtime)
and passes credentials as explicit React props to Client Components. `export const dynamic =
"force-dynamic"` ensures Server Component pages execute per-request, not at build time.

---

### Dashboard Signal Verification

**Endpoints used by dashboard:**
- KPI cards + top movers + recent signals: `GET /api/v1/dashboard?top_n=20&signal_days=7`
- Catalog scale counts: `GET /api/v1/catalog/counts`
- Notes/Accords composition: `GET /api/v1/notes/top`, `GET /api/v1/accords/top`
- Chart data: entity timeseries via `GET /api/v1/entities/{type}/{id}`

**Production API state (queried 2026-04-26 ~14:40 UTC):**

```
as_of_date:              2026-04-26
active_today:            4
breakout_signals_today:  0
accel_spikes_today:      0
total_signals_today:     0
avg_market_score_today:  0.1501
recent_signals (7d):     20 (all dated 2026-04-25)
top movers latest_signal: "breakout" (historical, from Apr 25)
top movers trend_state:   "declining" (computed from Apr 26 timeseries)
```

**Root cause of Signals=0 vs Top Movers showing BREAKOUT:**

This is **expected behavior**, not a bug.

`latest_signal` on a top mover row = the most recent signal EVER in the `signals` table
for that entity (`SELECT MAX(detected_at)` per entity). This can be from any historical date.

`total_signals_today` KPI = count of signals where `detected_at.date() == latest_date`
(today's detection run). This counts only what `detect_breakout_signals` fired today.

On 2026-04-26:
- Apr 26 morning pipeline ran successfully
- Only 4 entities have real mentions (`mention_count=1.2`, `is_flood_dampened=true`)
- Scores are ~9.35 (below `breakout_min_score=15.0` threshold)
- Growth rate is -0.87 (massive decline from Apr 25 peak)
- `detect_breakout_signals` found no qualifying signals for Apr 26 → `total_signals_today=0`
- Creed Aventus's `latest_signal="breakout"` dates from Apr 25 (yesterday's detection run)
- Creed Aventus's `trend_state="declining"` is computed fresh from Apr 26 timeseries data

The two fields are measured at different points in time and have different semantics. Both
values are correct.

**UI label ambiguity:**
The `Signal` column header in TopMoversTable implies current signal status, but the field
shows the last-ever signal type. A future UI improvement could label this column
"Last Signal" instead of "Signal", or suppress the badge when the signal is stale (e.g.
`detected_at` > 48 hours old). This is a non-blocking cosmetic issue.

**`is_flood_dampened=true` on all 4 active movers:**
Flood dampening fires when multiple mentions come from the same source within a short window.
Raw mention count may have been 2+ but is dampened to 1.2. This is correct behavior —
prevents a single creator with multiple uploads from inflating the score.

**Pipeline health (Apr 26):**
- `entity_timeseries_daily` rows exist for 2026-04-26 (confirmed via `as_of_date`)
- 4 active entities with real mentions (not carry-forward)
- Signal detection ran, correctly found 0 qualifying signals
- DB: 318 total tracked entities; 4 with real activity today

**No regression from auth/env fixes:**
Auth repair commits only touched: `frontend/next.config.ts`, `frontend/src/app/(public)/login/*`,
`frontend/src/app/auth/callback/*`, `frontend/src/lib/auth/otp-client.ts`. No backend,
no pipeline, no aggregation, no signal detection — none of these were touched.

---

### D1.1 Domain Migration — CLEARED

All D1.0 blockers resolved. D1.1 may proceed.

---

## Phase D1.1 — Custom Domain Migration (COMPLETED — 2026-04-26)

### Target Type
INFRASTRUCTURE + CONFIG — no code changes, documentation only

### Status
COMPLETE — verified end-to-end on custom domain

---

### Domain

**Production domain:** `https://fragranceindex.ai`
**Registrar:** Squarespace
**Fallback (Railway technical URL):** `https://pti-frontend-production.up.railway.app`

---

### Railway Configuration

Custom domains added to the `pti-frontend` Railway service:
- `fragranceindex.ai`
- `www.fragranceindex.ai`

DNS records configured via Squarespace to point both apex and www to Railway's load balancer.

---

### Supabase Configuration

Redirect URL added to Supabase Auth settings:
- `https://www.fragranceindex.ai/auth/callback`

This allows Supabase to send magic link emails with the callback URL pointing to the custom domain.

---

### Environment Variable

`NEXT_PUBLIC_SITE_URL` updated on `pti-frontend` Railway service:
- **Before:** `https://pti-frontend-production.up.railway.app`
- **After:** `https://www.fragranceindex.ai`

This variable controls the `emailRedirectTo` value in `LoginForm.tsx`:
```typescript
const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ||
  "https://pti-frontend-production.up.railway.app";
```

---

### Root vs www Routing

Both `fragranceindex.ai` and `www.fragranceindex.ai` are registered as Railway custom domains.

`NEXT_PUBLIC_SITE_URL` is set to `https://www.fragranceindex.ai` (www-prefixed).

Magic links are sent to `https://www.fragranceindex.ai/auth/callback` — this is the canonical
callback URL. Root domain (`fragranceindex.ai`) serves the site but auth redirect targets www.

Railway fallback URL (`pti-frontend-production.up.railway.app`) remains active and functional.

---

### Verification (2026-04-26)

| Check | Status |
|-------|--------|
| `https://fragranceindex.ai` loads landing page | ✅ |
| `https://fragranceindex.ai/login` loads login form | ✅ |
| Magic link email dispatched successfully | ✅ |
| `/auth/callback` finalizes session on custom domain | ✅ |
| Authenticated dashboard loads at custom domain | ✅ |
| Railway fallback URL still functional | ✅ |

---

### Notes

- No code changes were required for the domain migration
- Auth flow (OTP dispatch, callback, session finalization) works identically on the custom domain
  as on the Railway URL — same env var pattern, same Server Component prop-passing architecture from D1.0
- The Railway URL can be used for internal debugging or infrastructure access without affecting
  the user-facing domain

---

## TODO — Dashboard Date Range Controls / KPI Period Layer

### Problem

- Current dashboard KPI cards appear to show calendar `CURRENT_DATE` only.
- This is misleading because YouTube/Reddit ingestion enriches prior `published_at` dates —
  a video published yesterday is ingested today, aggregated for yesterday's date, not today's.
- A current partial day may show 0 signals even while the latest completed market date has
  strong activity.
- Recent Signals and Movers may show historical/latest-date data while KPI cards show
  today-only data, creating visible UX inconsistency.

### Required UX

Add a date/period selector to the dashboard. Supported periods:

- Today
- Yesterday
- Last 7 days
- Last 30 days
- Last 90 days
- YTD
- Custom date range

Rules:
- KPI cards must reflect the selected period.
- Movers table must reflect the selected period.
- Recent Signals should either respect the selected period or be clearly labeled "Recent 7 days".
- Charts should align with the selected period.
- Dashboard header should show: selected period, latest data timestamp, and latest completed
  market date (the most recent date with `mention_count > 0` in `entity_timeseries_daily`).

### Backend / API Requirements

Dashboard endpoints must accept:
- `start_date` / `end_date` (explicit range)
- `period` preset (e.g. `yesterday`, `7d`, `30d`, `90d`, `ytd`)

Backend must support:
- Current calendar date
- Latest completed market date (max date with real activity — not just carry-forward)
- Rolling windows
- Custom date ranges

**Do not hardcode `CURRENT_DATE` in dashboard summary logic.** The API should return the
`as_of_date` it actually used so the frontend can display it transparently.

### Implementation Notes

1. Audit existing dashboard endpoints (`/api/v1/dashboard`) and frontend components to
   determine exactly where `CURRENT_DATE` is used vs. where latest market date is derived.
2. Compare current KPI card date logic with `latest_signal.detected_at` and
   `entity_timeseries_daily` max active date.
3. Fix likely requires both backend query params (`start_date`/`end_date`) and a frontend
   period selector component in the dashboard ControlBar.
4. Do not change scoring or signal detection thresholds for this task.

### Priority

Medium-high product UX priority.

- Do after current pipeline/data integrity work (stale identity_map fix, Reddit gap investigation).
- Complete before public user onboarding / fragranceindex.ai soft launch expansion if possible.

### Non-Goals

- Do not change signal detection logic or thresholds.
- Do not change scoring weights or composite market score formula.
- Do not change `entity_market` schema unless a follow-up audit proves it is required.
- Do not mix with domain migration or auth work.

---

## Stale Identity Map Cleanup / Invisible Mentions Fix

### STATUS: COMPLETE — PRODUCTION VERIFIED (2026-04-26)

**Script:** `scripts/fix_stale_identity_map_mentions.py`
**Commit:** `61186d4` (included in push `50f5298`)

---

### Root Cause

`perfume_identity_map.resolver_perfume_id` had a systematic **+6 offset corruption**.
The old forbidden aggregator path `identity_resolver.perfume_uuid(int(raw_eid))` looked up
`market_perfume_uuid` via this column — returning the UUID of the wrong entity (e.g., Creed
Aventus content mapped to Lattafa Ameer Al Oudh's UUID). This wrote stale duplicate
`entity_mentions` rows alongside the correct mentions already written by the `entity_uuid_map`
path. The stale rows used entity_ids not present in `entity_market`, making them invisible to
all downstream joins (timeseries, signals, entity pages, dashboard).

---

### Deletion Strategy

DELETE entity_mentions where:
1. `entity_id` NOT in `entity_market` (stale — no market row)
2. AND same `source_url` has at least one `entity_mentions` row where `entity_id` IS in
   `entity_market` (correct mention confirmed — the stale one is a duplicate)

PRESERVE entity_mentions where:
- `entity_id` is stale AND `source_url` has NO correct sibling
- These may be genuine mentions of niche brands not yet in entity_market; deleting them
  would lose real data with no confirmed duplicate

---

### Apply Result (production, 2026-04-26)

| Metric | Value |
|--------|-------|
| Total stale mentions audited | 242 |
| Stale duplicate false positives deleted | **142** |
| Isolated niche mentions preserved | **100** |
| Stale duplicate mentions remaining | **0** |
| Schema changes | None |
| Migrations | None |
| Scoring changes | None |
| Signal threshold changes | None |
| Ingestion changes | None |

Top deleted UUIDs (ALL false-positive duplicates, same source_url had correct sibling):

| PIM entity | Mentions deleted |
|-----------|-----------------|
| Lattafa Ameer Al Oudh | 46 |
| Electimuss Auster EDP | 20 |
| Initio Atomic Rose | 16 |
| MFK Baccarat Rouge 540 (stale UUID) | 15 |
| Une Nuit Nomade Suma Oriental EDP | 7 |
| Versace Bright Crystal | 6 |
| Akro Dark EDP | 6 |
| Comme des Garcons Concrete EDP | 6 |

Top preserved UUIDs (isolated — no correct sibling, potentially real niche mentions):

| PIM entity | Mentions kept |
|-----------|--------------|
| Keiko Mecheri Peau de Peche EDP | 12 |
| Alguien EDP (partial) | 6 |
| Juliette Has a Gun Vanilla Vibes | 9 |
| Divine L'Inspiratrice EDP | 9 |
| Bortnikoff Sir Winston Attar | 6 |

---

### Reaggregation Result

9 affected dates re-aggregated and signals re-detected after cleanup. All idempotent:

| Date | Active entities | Total mentions | Signals |
|------|----------------|----------------|---------|
| 2026-04-23 | 93 | 194.4 | 35 |
| 2026-04-22 | 86 | 199.2 | 71 |
| 2026-04-21 | 34 | 75.6 | 10 |
| 2026-04-20 | 65 | 176.4 | 29 |
| 2026-04-19 | 94 | 208.8 | 42 |
| 2026-04-18 | 53 | 179.6 | 38 |
| 2026-04-17 | 130 | 336.4 | 107 |
| 2026-04-15 | 21 | 57.6 | 14 |
| 2026-04-14 | 20 | 36.0 | 8 |

**Total signals across affected dates: 354**

---

### Verification Results (all PASS)

- `stale_duplicate_mentions_remaining = 0` ✅
- `invisible_mentions_remaining = 100` (intentionally preserved isolated niche) ✅
- All 9 affected dates populated in `entity_timeseries_daily` ✅
- Signal detection completed with no errors for all 9 dates ✅
- No pipeline, scoring, or schema regressions ✅

---

### Operational Note

**Future aggregator writes must not use the `perfume_identity_map` PIM lookup path.**

The correct entity UUID to write to `entity_mentions.entity_id` is `entity_market.id`,
looked up via `entity_uuid_map.get(canonical_name)`. This path is always consistent with
the market layer. The old path `identity_resolver.perfume_uuid(int(raw_eid))` uses
`resolver_perfume_id` — which is corruptible and not guaranteed to match the market UUID.

Rule: `entity_mentions.entity_id` must always reference `entity_market.id` directly via
the `entity_uuid_map` built from `entity_market` at aggregation time. Never use PIM as
an intermediary for this write.

---

## Reddit Ingestion Observability / Silent Failure Fix

### STATUS: COMPLETE — VERIFIED ON SCHEDULED RUN (2026-04-27)

**Commit:** `9244a53`

---

### Root Cause

Reddit's public JSON API intermittently blocks Railway datacenter IPs with HTTP 200 responses
containing HTML bot-detection pages (not JSON). Two silent failure modes existed:

1. **HTML 200 silent failure:** `resp.ok` was True → no error check fired → `resp.json()` raised
   `json.JSONDecodeError` → caught by the generic `except Exception` → logged as `[warn]` →
   `scripts/ingest_reddit.py` continued and exited 0 → `run_ingestion.py` saw exit 0 →
   Reddit recorded as "succeeded" with 0 posts.

2. **All-subreddits failure silent exit:** When all 3 subreddits raised exceptions, the script
   printed warnings and exited 0. `run_ingestion.py` never added Reddit to its `failures` list.
   Pipeline reported healthy. The gap was invisible.

**Production SQL evidence (gap confirmed):**
```sql
-- reddit items in canonical_content_items per day
SELECT SUBSTR(collected_at, 1, 10) AS day, COUNT(*) AS items
FROM canonical_content_items
WHERE source_platform = 'reddit'
  AND SUBSTR(collected_at, 1, 10) >= '2026-04-20'
GROUP BY 1 ORDER BY 1;
```
Results showed 0 items for 2026-04-21, 2026-04-24, 2026-04-26 — confirmed missing runs,
not deduplication suppression (PgNormalizedContentStore updates `collected_at` on re-fetch,
so zero rows = zero posts processed, not zero new posts).

---

### Fix

**File 1 — `perfume_trend_sdk/connectors/reddit_watchlist/client.py`**

Added Content-Type guard before `resp.json()` in `_get()` to catch HTML bot-detection
pages returned with HTTP 200:

```python
content_type = resp.headers.get("Content-Type", "")
if "json" not in content_type.lower():
    raise RedditAPIError(
        f"Reddit returned non-JSON response (possible bot-detection page). "
        f"HTTP {resp.status_code}  Content-Type={content_type!r}  "
        f"body_prefix={resp.text[:200]!r}"
    )
```

**File 2 — `scripts/ingest_reddit.py`**

Added per-subreddit failure tracking and hard `sys.exit(1)` conditions:

- `fetch_errors` counter incremented on each subreddit exception (`[warn]` → `[error]`)
- `zero_post_subreddits` counter for subreddits returning 0 posts without error
- `active_subreddits = len(subreddits)` for ratio reporting
- Summary dict extended with three new fields
- Three exit conditions after summary:
  - Partial success (`fetch_errors > 0` but `total_fetched > 0`): print `WARNING`, exit 0
  - Total failure (`fetch_errors == active_subreddits`): print `CRITICAL`, `sys.exit(1)`
  - Total silence (0 fetched, 0 errors): print `CRITICAL`, `sys.exit(1)`

| Condition | Old behavior | New behavior |
|-----------|-------------|--------------|
| All subreddits → exception | exit 0, silent | `sys.exit(1)`, CRITICAL logged |
| HTML 200 bot-detection page | silent `[warn]`, exit 0 | `RedditAPIError` raised, counted as fetch_error |
| 0 posts, 0 exceptions | exit 0, ambiguous | `sys.exit(1)` if all subreddits affected |
| Some subreddits fail, some succeed | all counted as errors | partial warning, exit 0 (pipeline continues) |
| Normal success | exit 0 | exit 0 (unchanged) |

---

### Smoke Test (local, 2026-04-27)

```bash
PTI_DB_PATH=outputs/pti.db \
  python3 scripts/ingest_reddit.py --limit 5 --lookback-days 1 \
  --resolver-db data/resolver/pti.db
```

| Metric | Result |
|--------|--------|
| Exit code | 0 ✅ |
| Posts fetched | 15 (5 per subreddit) ✅ |
| Subreddits active | 3 ✅ |
| fetch_errors | 0 ✅ |
| zero_post_subreddits | 0 ✅ |
| Content-Type guard | fired correctly on first test run (caught HTML page), raised `RedditAPIError` ✅ |
| New counters in summary | printed correctly ✅ |

---

### Monitoring Instructions

**Next Railway run (23:00 UTC evening pipeline / 11:00 UTC morning pipeline):**

Check `pipeline-daily` and `pipeline-evening` Railway service logs for:

1. **Success indicators:**
   - `[ingest_reddit] Done.` present
   - `fetch errors: 0`
   - `posts fetched: N` where N > 0
   - `run_ingestion` exit 0

2. **IP block detected (new visibility):**
   - `[error] fetch failed for r/fragrance: Reddit returned non-JSON response (possible bot-detection page)`
   - `[ingest_reddit] CRITICAL: all 3 subreddit(s) raised fetch errors`
   - `run_ingestion` → `failures: ['reddit']` → pipeline exits 1 → Railway records failure

3. **Partial block (new visibility):**
   - `[error] fetch failed for r/fragrance: ...`
   - `[ingest_reddit] WARNING: 1/3 subreddit(s) failed but N posts were fetched`
   - Exit 0 — pipeline continues with partial data

**If Railway logs show repeated CRITICAL exits:** Reddit IP blocking is systematic.
Long-term fix: migrate to official Reddit API (OAuth2 PRAW) for authenticated requests
at higher rate limits, from a registered app identity. Only `client.py` needs to change —
connector, parser, normalizer interfaces are stable. Requires `REDDIT_CLIENT_ID` and
`REDDIT_CLIENT_SECRET` env vars in Railway `pipeline-daily` and `pipeline-evening` services.

---

### Scheduled Run Verification (2026-04-27)

**Run verified:** Apr 26 23:00 UTC — evening pipeline

| Metric | Result |
|--------|--------|
| Reddit ingestion | SUCCESS ✅ |
| Reddit items collected | 75 |
| Latest Reddit timestamp | `2026-04-26T23:13:59 UTC` |
| YouTube items collected | 220 |
| CRITICAL logs | None |
| IP block / HTML 200 | Not triggered |
| Pipeline exit | 0 (clean) |

Reddit returned valid JSON for all 3 subreddits. Fix `9244a53` is working as intended:
silent failure modes eliminated. Any future Railway IP block will now emit a CRITICAL log
and exit 1, causing Railway to record the run as failed.

**Ongoing monitoring:** Continue checking Apr 27 11:00 UTC morning run and subsequent 1–2
scheduled runs. If CRITICAL failures appear consistently, next phase is Reddit OAuth
(PRAW authenticated API) — only `client.py` requires changes, all other interfaces are stable.

---

## Phase G4 — Candidate Promotion / Alias Intelligence Batch 1

### STATUS: COMPLETE — PRODUCTION VERIFIED (2026-04-27)

Commits:
- `554c484` — feat: seed G4 batch 1 aliases (`scripts/seed_g4_aliases.py`)
- `abed21a` — feat: extend re-resolution support for G4 aliases

---

### Step 1 — Candidate Promotion Audit

`promote_candidates.py` queue was exhausted — all high-confidence candidates had already
been processed in prior Phase 4P batches.

No `--allow-create` was used. No new `resolver_perfumes` or `resolver_brands` rows were created.

Decision: safe path chosen — manual allowlist alias-only seed targeting high-value short-form
variants that the auto-promotion pipeline cannot safely generate (EDP concentration shorthands,
brand "by X" patterns, punctuation-stripped brand abbreviations).

---

### Step 2 — G4 Batch 1 Alias Seed

**Script:** `scripts/seed_g4_aliases.py` — standalone psycopg2, default dry-run, `--apply` required for writes.

**4 aliases inserted** — `match_type='g4_seed'`, `confidence=0.90`:

| alias_text | entity_type | entity_id | canonical |
|-----------|-------------|-----------|----------|
| `baccarat rouge 540 edp` | perfume | 2 | Maison Francis Kurkdjian Baccarat Rouge 540 |
| `rouge 540 edp` | perfume | 2 | Maison Francis Kurkdjian Baccarat Rouge 540 |
| `ds durga` | brand | 370 | D.S. & Durga |
| `by lattafa` | brand | 9 | Lattafa |

**Explicitly excluded** (not safe for alias-only addition):
- `nuit intense` — ambiguous across CDN Intense variants
- `good girl` / `carolina herrera good girl` — no base Good Girl entity in KB
- `maison margiela replica` — Replica is a line, not a single perfume
- bare concentration terms (`edp`, `eau de parfum`, `extrait`, `intense`)
- all dupe/context terms

**Verification:**
- `g4_seed` count = 4 ✅
- all 4 aliases present in resolver_aliases ✅
- 0 duplicates ✅

**Rollback:** `DELETE FROM resolver_aliases WHERE match_type = 'g4_seed';`

---

### Step 3 — G4 Targeted Re-resolution

**Script:** `scripts/reresolve_g2_stale_content.py` extended with `--batch g4` support.

**Key changes to reresolve script:**
- `BATCH_CONFIGS` keys changed from `int` to `str` to support `"g4"` key
- G4 cutoff: `2026-04-27 07:00:35` UTC (apply log timestamp)
- G4 keywords: `baccarat rouge 540`, `rouge 540`, `durga`, `lattafa`
- `load_alias_table()` extended with LEFT JOIN `resolver_brands` — required for brand-type G4 aliases
- `resolve_text()` dedup key updated to `(entity_id, entity_type, canonical_name)` for brand/perfume safety
- `_build_resolved_entities()` uses `entity_type` from hit (not hardcoded `"perfume"`)
- Tags: `resolver_version='1.3-g4-reresolve'`

**Results:**
- Stale content items checked: 139
- Items gaining new entities: 89
- Total new entity links written: 137
- Top recovered: MFK Baccarat Rouge 540 (via `rouge 540 edp` / `baccarat rouge 540 edp`),
  Angels' Share, Lattafa Khamrah, Lattafa Yara, D.S. and Durga

---

### Step 4 — Historical Aggregation + Signal Backfill

All 17 affected `published_at` dates re-aggregated and signals re-detected. All idempotent.

| Date | Active Entities | Total Mentions | Signals |
|------|----------------|----------------|---------|
| 2026-04-26 | 110 | 262.8 | 64 |
| 2026-04-25 | 130 | 325.2 | 121 |
| 2026-04-24 | 48 | 139.2 | 28 |
| 2026-04-23 | 93 | 194.4 | 34 |
| 2026-04-22 | 86 | 199.2 | 71 |
| 2026-04-21 | 34 | 75.6 | 11 |
| 2026-04-20 | 65 | 176.4 | 29 |
| 2026-04-19 | 94 | 208.8 | 42 |
| 2026-04-18 | 53 | 179.6 | 38 |
| 2026-04-17 | 130 | 336.4 | 107 |
| 2026-04-16 | 38 | 114.8 | 30 |
| 2026-04-15 | 21 | 57.6 | 14 |
| 2026-04-14 | 20 | 36.0 | 7 |
| 2026-04-13 | 82 | 122.0 | 80 |
| 2026-04-11 | 16 | 31.2 | 6 |
| 2026-04-10 | 12 | 38.4 | 13 |
| 2026-04-09 | 29 | 69.6 | 25 |

Background tasks exit code 0. No failures.

**Known non-fatal issue (Apr 20):** SQLAlchemy e3q8 trend_state lookback error for
`entity_id=afe1da98-913b-45c7-bf50-8b2c7d579793` — same class of error seen in prior
backfill runs. Aggregation and signal detection completed successfully for that date.

---

### Step 5 — Verification Results

**G4 recovered entity mentions confirmed across affected dates:**
- Maison Francis Kurkdjian Baccarat Rouge 540 ✅ (across multiple dates via EDP shorthand aliases)
- Angels' Share ✅
- Lattafa Khamrah / Lattafa Yara ✅
- D.S. and Durga ✅

**G4 brand entity_market rows:**

| entity_id | max_score | total_mentions | trend_state |
|-----------|-----------|----------------|-------------|
| brand-maison-francis-kurkdjian | 68.49 | 103.4 | stable |
| brand-lattafa | 37.00 | 7.4 | rising |
| brand-ds-and-durga | 37.00 | 14.4 | rising |

---

### Safety Constraints (all observed)

- No Alembic migrations
- No schema changes
- No scoring weight changes
- No signal threshold changes
- No ingestion changes
- No pipeline schedule changes
- No `promote_candidates --allow-create`
- No new `resolver_perfumes` or `resolver_brands` rows
- Script is idempotent (ON CONFLICT DO NOTHING)

---

### Next Phase — G4 Batch 2 (PENDING)

G4 Batch 2 must only proceed after a fresh candidate audit against the current
`fragrance_candidates` queue. Potential areas for future alias-only seeds:

- `nuit intense` — requires context validation to resolve ambiguity across CDN Intense variants
- `good girl` / `carolina herrera good girl` — requires base Good Girl entity to be created first
- Additional high-confidence EDP/EDT/Extrait shorthand variants for top tracked entities
- Better Reddit n-gram noise filtering before candidate promotion (reduces review queue size)

**Rule:** Do NOT lower signal thresholds or change scoring to compensate for unresolved entities.
Entity resolution improvement is the correct path.

---

### First Scheduled Pipeline Verification After G4 Batch 1

**STATUS: PASS — HEALTHY LIVE RUN**

**Verification date:** 2026-04-27 UTC
**G4 aliases seeded:** 2026-04-27 ~07:00 UTC
**First post-G4 pipeline cycle:** Morning 11:00 UTC + Evening 23:00 UTC

---

#### Pipeline Counts

| Metric | Value |
|--------|-------|
| YouTube items — morning (11:00 UTC) | 76 |
| YouTube items — evening (23:00 UTC) | 223 |
| YouTube total | **299** |
| Reddit items — evening (23:00 UTC) | 75 |
| Total content collected | **374** |
| Reddit CRITICAL logs | None |
| Pipeline status | **HEALTHY** |

Reddit observability fix (commit `9244a53`) remains effective — all 3 subreddits returned valid JSON, no HTML 200 bot-detection events.

---

#### G4 Fresh Alias Behavior

| Alias | Phrase in fresh Apr 27 content | Resolver behavior |
|-------|-------------------------------|-------------------|
| `by lattafa` | ✅ Present (5 items) | Lattafa resolved in **13** Apr 27 content items |
| `baccarat rouge 540 edp` | ❌ Not in fresh content | No fresh impact yet — awaiting matching content |
| `rouge 540 edp` | ❌ Not in fresh content | No fresh impact yet — awaiting matching content |
| `ds durga` | ❌ Not in fresh content | D.S. & Durga has no `entity_market` row yet |

**`by lattafa` is active:** The live resolver (version `1.1`) is correctly picking up the G4
brand alias in fresh pipeline content. 13 items in Apr 27 `resolved_signals` have `Lattafa`
in `resolved_entities_json`. One item still shows `by lattafa` in `unresolved_mentions_json` —
expected when the phrase is crowded out by surrounding token windows.

**EDP aliases and `ds durga`:** No fresh content contained these exact phrases on Apr 27.
Impact will accumulate in future cycles as matching content is ingested. This is expected
behavior — alias seeds are passive until phrases appear in ingested text.

**Resolver version:** Fresh pipeline items tagged `resolver_version='1.1'` (live resolver);
G4 re-resolution backfill items tagged `resolver_version='1.3-g4-reresolve'`. Both are
correct and represent different code paths loading the same resolver_aliases table.

---

#### Apr 27 Market Data

| Metric | Value |
|--------|-------|
| entity_mentions | 19 |
| distinct entities in mentions | 13 (9 YouTube + 4 Reddit) |
| active entities (timeseries) | 74 |
| total mentions (timeseries) | 154.8 |
| signals — new_entry | 14 |
| signals — breakout | 10 |
| signals — acceleration_spike | 10 |
| signals — reversal | 3 |
| signals — total | **37** |

Apr 27 signal and mention counts are lower than Apr 25–26, which were inflated by G4
historical backfill re-resolution. Apr 27 represents a clean cold-start with live pipeline
data only — 74 active entities on a typical content day is healthy.

---

#### G4 Candidate Status

All 4 G4 aliases remain in `fragrance_candidates` as `accepted_rule_based`. This is correct
behavior — the candidates table is a write-through accumulator. Seeding resolver_aliases does
not remove candidates; it intercepts matching content and routes it to `entity_mentions` instead.

| normalized_text | status | occurrences | last_seen |
|----------------|--------|-------------|-----------|
| `baccarat rouge 540 edp` | accepted_rule_based | 15 | 2026-04-26 |
| `rouge 540 edp` | accepted_rule_based | 15 | 2026-04-26 |
| `by lattafa` | accepted_rule_based | 14 | 2026-04-27 |
| `ds durga` | accepted_rule_based | 13 | 2026-04-25 |

`by lattafa` last_seen=2026-04-27 confirms the phrase appeared in fresh content and was processed.

---

#### Warnings / Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| `by lattafa` still unresolved in 1 item | Low | Token crowding — expected edge case |
| D.S. & Durga — no `entity_market` row | Info | No fresh `ds durga` content ingested yet |
| Apr 27 mentions lower than Apr 25–26 | Info | Expected — Apr 25–26 boosted by G4 backfill |

No noise explosion. No signal threshold violations. No pipeline errors.

---

#### Conclusion

G4 Batch 1 is behaving correctly on fresh scheduled pipeline runs.

- `by lattafa` alias is active and producing resolver matches in live content ✅
- EDP shorthands and `ds durga` are passive — correctly waiting for matching content ✅
- Signal engine clean — 37 signals, no breakout spam ✅
- Reddit pipeline healthy — observability fix holding ✅
- Primary G4 value delivered via historical backfill; fresh behavioral impact accumulating

**Monitoring rule:** Monitor 2–3 more scheduled pipeline cycles before evaluating G4 Batch 2.
Do NOT start G4 Batch 2 until a fresh candidate audit confirms new safe alias opportunities.
Do NOT change signal thresholds or scoring to compensate for aliases not yet appearing in content.

---

## Phase E-UX1 — Entity Navigation / Clickable Market Graph

### STATUS: COMPLETE — PRODUCTION DEPLOYED

### Goal

Transform the product from a collection of isolated pages into a connected market graph where every entity is reachable from any other, and every KPI, signal, or note/accord reference acts as a navigation entry point.

---

### Subphases

#### E-UX1 — Signal Feed Routes + Notes/Accords Clickability
**Commit:** `83ab6cc`

- Fixed Dashboard Recent Signals feed: typed entity routing now correctly routes to `/entities/perfume/{id}` or `/entities/brand/{id}` based on `entity_type`.
- Made perfume detail page notes/accords chips clickable — each note/accord navigates to its note or accord detail page.
- Made brand detail page notes/accords chips clickable — same behavior.

#### E-UX1b — Screener Catalog Clickability (All 55,622 Perfumes + 1,608 Brands)
**Commit:** `adda3b4`
**File:** `frontend/src/app/(terminal)/screener/page.tsx`

- Made all Screener rows navigable — catalog perfumes and catalog brands — not just tracked entities.
- All 55,622 catalog perfumes and 1,608 catalog brands now link to entity pages.

#### E-UX1c — Brand Portfolio Perfumes Clickability
**Commit:** `c505e7f`

- Made all brand portfolio perfume rows on brand entity pages navigable.
- Added `resolver_id` to `BrandPerfumeRow` API schema.
- Tracked portfolio perfume routes to `entity_id` slug.
- Catalog-only portfolio perfume routes to `resolver_id` integer.

#### E-UX1d — Note/Accord Top Perfumes Clickability

- Made note and accord detail page `top_perfumes` list rows navigable for catalog-only entries.
- Added `resolver_id` to note/accord API row data.
- Tracked rows: `/entities/perfume/{entity_id}`.
- Catalog-only rows: `/entities/perfume/{resolver_id}`.

#### E-UX1e — Dashboard KPI Navigation + Perfume Brand Link
**Commit:** `d87b4c5`
**Files:** `frontend/src/components/primitives/KpiCard.tsx`, `frontend/src/components/dashboard/KpiStrip.tsx`, `frontend/src/app/(terminal)/entities/perfume/[id]/page.tsx`, `perfume_trend_sdk/api/routes/entities.py`, `frontend/src/lib/api/types.ts`

**KPI navigation:**

| KPI Card | Route |
|----------|-------|
| Known Brands | `/screener?mode=catalog_brands` |
| Known Perfumes | `/screener?mode=catalog_perfumes` |
| Active Today | `/screener?mode=active` |
| Breakouts | `/screener?signal_type=breakout&has_signals=true` |
| Accel Spikes | `/screener?signal_type=acceleration_spike&has_signals=true` |
| Signals | `/screener?has_signals=true` |
| Avg Score | *(non-clickable — no applicable filter)* |
| Avg Confidence | *(non-clickable — no applicable filter)* |

**Perfume brand link:**
- Backend: new `_brand_entity_id_for()` helper queries `entity_market` for the brand row matching `brand_name`.
- `brand_entity_id: Optional[str]` added to `PerfumeEntityDetail` API response and `frontend/src/lib/api/types.ts`.
- Perfume page: brand name renders as `<Link href="/entities/brand/{brand_entity_id}">` when `brand_entity_id` is available; plain text otherwise.
- Styling: `text-zinc-400 underline underline-offset-4 decoration-zinc-700 hover:text-zinc-200 hover:decoration-zinc-400 transition-colors cursor-pointer`.

---

### URL Route Strategy

| Entity | Tracked | Catalog-only |
|--------|---------|--------------|
| Perfume | `/entities/perfume/{entity_id}` e.g. `/entities/perfume/creed-aventus` | `/entities/perfume/{resolver_id}` e.g. `/entities/perfume/42371` |
| Brand | `/entities/brand/{entity_id}` e.g. `/entities/brand/brand-creed` | `/entities/brand/{resolver_id}` e.g. `/entities/brand/1142` |

---

### Tracked vs Catalog-Only Behavior

**Tracked entities** (have `entity_market` row + timeseries data):
- Full market intelligence view: score, trend state, signals, mentions, chart, top drivers, notes/accords.
- Signal badges, TrendStateBadge, and history chart visible.

**Catalog-only entities** (resolver-known but no ingested content yet):
- Catalog/reference mode: "In Catalog" badge, notes/accords from dataset if available.
- "No market signals yet" / "Start Tracking" placeholder messaging.
- No fake `entity_market` rows created.
- No fake signals created.
- Becomes tracked automatically when real ingested content resolves to it.

---

### Connected Graph Result

```
Dashboard KPIs → Screener
Screener rows → entity pages (tracked or catalog-only)
Entity pages → brand pages (via brand name link)
Brand pages → portfolio perfume pages
Note/accord pages → perfume entity pages
Signal feed → entity pages
```

Every surface in the terminal is now an entry point into the entity graph.

---

### Safety Constraints

- No migrations
- No schema changes (except `brand_entity_id` field addition to `PerfumeEntityDetail`)
- No scoring changes
- No signal threshold changes
- No pipeline changes
- No ingestion changes
- No fake entity_market rows
- No fake signals

---

### Next Phases

**E-UX2** — Restructure perfume detail pages into market-first layout: score, trend state, and signals above the fold; notes/accords and similar perfumes below. Step 1 (pure block reorder) is COMPLETE — see Phase E-UX2 Step 1 below.

**E-UX3** — Restructure brand detail pages into portfolio/market-first layout: brand-level KPIs, top perfumes by score, signals, and notes/accords aggregation.

**Dashboard date range controls** — Separate TODO / product UX phase. Should allow period selection (Today / Yesterday / 7d / 30d) on dashboard KPIs and movers table.

---

## Phase E-UX1.1 — Dashboard Interaction Refinement

### STATUS: COMPLETE — PRODUCTION DEPLOYED

Extends E-UX1. All commits are production-deployed to `fragranceindex.ai`.

---

### Subphases

#### Recent Signals — Non-Mover Navigation Fix
**Commit:** `839235f`
**Files:** `frontend/src/components/dashboard/SignalFeed.tsx`, `frontend/src/app/(terminal)/dashboard/page.tsx`

**Problem:** Clicking a Recent Signals row for a non-mover entity (e.g. Roja Parfums Qatar, Diptyque Do Son) showed the wrong preview chart — the `useEffect` auto-select guard immediately reset `selectedEntityId` to `filteredMovers[0]` because the signal entity was not in the filtered movers list.

**Fix:**
- `SignalFeed` now accepts `moverEntityIds?: Set<string>` prop.
- Mover signal rows: call `onSelectEntity(id)` → update preview chart (existing behavior).
- Non-mover signal rows: call `router.push(entityHref)` → navigate to entity page directly. No preview change; no misleading chart shown.
- `dashboard/page.tsx`: computes `moverEntityIds = useMemo(() => new Set(data?.top_movers.map(m => m.entity_id)), [data?.top_movers])` and passes to `<SignalFeed>`.
- `SignalFeed.tsx`: added `"use client"` + `useRouter`.

**Behavior after fix:**

| Signal row type | Click behavior |
|-----------------|---------------|
| Entity in Top Movers | Update dashboard preview chart |
| Entity not in Top Movers | Navigate to entity detail page |

---

#### Top Movers — Preview/Navigation Separation
**Commit:** `d2b99fd`
**File:** `frontend/src/components/dashboard/TopMoversTable.tsx`

**Problem:** Row click called `onSelect(entityId)` AND `router.push(href)` simultaneously — every mover click navigated away, making the preview chart unusable.

**Fix:**
- `tr onClick` now calls `onSelect(entityId)` only (preview chart, no navigation).
- `canonical_name` cell is wrapped in a `Link` with `e.stopPropagation()` — name click navigates to entity page, does not trigger row `onSelect`.
- Ticker cell: added `cursor-pointer hover:text-yellow-300 transition-colors` + `title="Click to preview chart"`.
- Name Link: added `hover:underline underline-offset-2` for direct hover affordance.
- Removed unused `useRouter` import.

**Behavior after fix:**

| Interaction | Behavior |
|-------------|----------|
| Click row / ticker | Preview chart (no navigation) |
| Click entity name | Navigate to `/entities/{type}/{entity_id}` |
| Hover ticker | `text-yellow-300` accent |
| Hover name | Underline |

---

#### EntityChartPanel — Typed Entity Route
**Commit:** `98325f8`
**File:** `frontend/src/components/dashboard/EntityChartPanel.tsx`

**Problem:** Mini-header `ArrowUpRight` link used bare `/entities/{entity_id}`, which 404s for brand entities (correct route is `/entities/brand/{entity_id}`).

**Fix:** One-line change on the `Link href`:
```ts
// Before
href={`/entities/${encodeURIComponent(mover.entity_id)}`}

// After
href={`/entities/${mover.entity_type ?? "perfume"}/${encodeURIComponent(mover.entity_id)}`}
```
`entity_type` is always present on `TopMoverRow` — no prop changes needed.

---

#### Dashboard Brand Copy Cleanup
**Commit:** `28d0d90`
**Files:** `frontend/src/components/dashboard/TopMoversTable.tsx`, `frontend/src/app/(terminal)/dashboard/page.tsx`

**Problem:** Brand rows used internal backend language that confused users.

**Changes:**

| Location | Before | After |
|----------|--------|-------|
| Brand row subline | `portfolio aggregate` | `Brand portfolio` |
| Brand badge tooltip | `Brand — composite score aggregated across perfume portfolio` | `Brand-level market signal` |
| Brand filter helper text | `↳ scores roll up from portfolio` | Removed entirely |

---

### Final Dashboard Interaction Model (post E-UX1.1)

```
Top Movers row click  → preview chart
Top Movers ticker     → preview chart (styled accent)
Top Movers name       → entity detail page
Chart mini-header ↗   → entity detail page (typed route)

Signal row (mover)    → preview chart
Signal row (non-mover)→ entity detail page

KPI cards             → screener (filtered views)
```

---

## Phase E-UX2 Step 1 — Perfume Detail Market-First Block Reorder

### STATUS: COMPLETE — PRODUCTION DEPLOYED

**Commit:** `4956d3c`
**File:** `frontend/src/app/(terminal)/entities/perfume/[id]/page.tsx`

**Change:** Pure JSX block reorder — no new components, no API changes, no backend changes.

**Section order before:**
1. Catalog quiet state
2. Header
3. Chart + Metrics
4. Notes & Accords
5. Similar by Notes
6. Top Drivers
7. WhyTrending
8. MarketInsight
9. Signal Timeline + Recent Mentions

**Section order after:**
1. Catalog quiet state
2. Header
3. Chart + Metrics
4. **Signal Timeline + Recent Mentions** ← moved up
5. Top Drivers
6. WhyTrending
7. MarketInsight
8. **Notes & Accords** ← moved down
9. **Similar by Notes** ← moved down

**Rationale:** Signal Timeline and Recent Mentions are market-intelligence content (answers "what is happening now?"). Notes & Accords and Similar by Notes are reference/enrichment content. Market terminal should show market data first.

**Safety constraints:** No migrations, no schema changes, no scoring changes, no pipeline changes, no ingestion changes.

---

## Phase L1 — Public Landing Page (COMPLETED — 2026-05-01)

### Target Type
FRONTEND_ONLY — no backend, no schema, no pipeline changes

### Authoritative Targets
- `frontend/src/app/page.tsx` (replaced)

### Requires Commit / Push / Deploy
YES

### Expected UI Change
YES — new 10-section public landing page at `/`

### Commit
`36af1f2`

---

### What was implemented

Replaced minimal 130-line placeholder with a comprehensive 10-section public marketing page.

**10 sections:**

| # | Section | Content |
|---|---------|---------|
| 1 | Hero | "The Market Terminal for Fragrance Trends" headline · live stats strip · animated Early Access badge |
| 2 | Problem | Delayed signals / no attribution / market noise — 3 problem cards |
| 3 | What It Does | 6 capability cards (Top Movers, Signal Detection, Screener, Entity Intelligence, Brand Portfolios, Source Intelligence) with emerald/amber/cyan/violet/rose/sky accents |
| 4 | Dashboard Preview | Inline mock terminal — KPI strip + 4 entity rows (score, trend badge, signal type, growth) |
| 5 | Example Signal | Creed Aventus breakout card with strength bar, top drivers, semantic topics, source attribution |
| 6 | Use Cases | Fragrance Brand / Retail Buyer / Content Strategist — 4 bullets each |
| 7 | Reports | 6 report sections + honest "in development" note (no false delivery promises) |
| 8 | Methodology | 5 steps: Ingest → Resolve → Score → Detect → Enrich — "deterministic by design" |
| 9 | Early Access Value | Full access now vs coming next — two columns |
| 10 | Final CTA | "Enter the Terminal" → `/login` |

**Design:** Dark zinc-950 background, emerald/amber/cyan/violet/rose/sky accent colors. Background grid in hero. Animate-pulse badge. Terminal-style mock with monospace fonts.

**Stats verified accurate at time of commit:**
- "55,000+" perfumes: `resolver_perfumes` = 56,067 ✅ (conservative claim)
- "1,600+" brands: `resolver_brands` = 1,608 ✅ (accurate claim)
- "2×" daily: `pipeline-daily` at 11:00 UTC + `pipeline-evening` at 23:00 UTC ✅
- "YouTube + Reddit": both verified active sources ✅

**Claims explicitly excluded:**
- No TikTok (deferred — Research API not approved)
- No paid subscription or Stripe (not live)
- No "beta" terminology
- No subscription pricing tiers

### Safety constraints

- No migrations
- No schema changes
- No env vars added to page
- No secrets in page
- Auth routes (`/login`, `/auth/callback`, `/dashboard`) completely untouched
- Build: clean (`○` static route confirmed at `/`)
- TypeScript: no new errors

---

## Public Branding — FTI Market Terminal (Updated 2026-05-01)

- **Internal project name:** PTI (Perfume Trend Intelligence SDK) — used in backend code, DB tables, Railway services, env vars, console.log lines, and authenticated shell UI. Do NOT rename.
- **Public product name:** FTI Market Terminal (Fragrance Trend Intelligence)
- **Public domain:** FragranceIndex.ai
- **Rule:** All user-visible copy on public pages (`/`, `/login`, `/glossary`, `/privacy`, `/terms`) uses "FTI Market Terminal" and "FragranceIndex.ai". The authenticated terminal shell (`StatusBar`, `Sidebar`) retains "PTI MARKET TERMINAL" / "PTI Terminal" — internal-only.
- **Do NOT change:** backend package names, DB table names, Railway service names, environment variables, or `console.log` debug lines (all tagged `[PTI ...]`).

### Final branding polish — STATUS: COMPLETE — PRODUCTION READY

**Commit:** `fe8d3ec`

- Public hero explicitly defines FTI as "Fragrance Trend Intelligence"
- Hero byline added: `"Fragrance Trend Intelligence · FragranceIndex.ai"`
- Hero paragraph connects platform + product:
  > "FragranceIndex.ai powers FTI Market Terminal — fragrance trend intelligence that monitors YouTube creators and Reddit communities to surface which perfumes and brands are breaking out, and why."
- Public naming architecture confirmed:

| Key | Value |
|-----|-------|
| Platform | FragranceIndex.ai |
| Product | FTI Market Terminal |
| Meaning | Fragrance Trend Intelligence |
| Legacy internal name | PTI / Perfume Trend Intelligence |

---

## YouTube Channel-First Ingestion — Phase 1A/1B/1B.2

### STATUS: PRODUCTION VERIFIED — MANUAL/STANDALONE ONLY

Phase 1A and 1B are implemented and production-verified. Phase 1B.2 documents the resolver
quality hardening and controlled aggregation that followed the first real ingest run.
Phase 1C (pipeline integration) is NOT yet approved and has NOT been started.

---

### Phase 1B.2 — Resolver Quality Hardening + Controlled Aggregation (COMPLETED — 2026-05-01)

#### What was verified in production

**Registry state (2026-05-01):**
- 9 channels registered in `youtube_channels`
- 3 high-priority channels ingested (first manual poll):
  - AROMATIX — 50 videos collected
  - FBFragrances — 43 videos collected
  - K&A Fragrances — 22 videos collected
- 115 videos total, ~12 YouTube API quota units consumed
- `uploads_playlist_id` cached for all 3 channels after first poll
- `ingestion_method = 'channel_poll'` confirmed on all 115 items

**Transcript queue:**
- `transcript_status = 'needed'`, `transcript_priority = 'high'` set for all channel_poll items
- `scripts/fetch_transcripts.py` verified against Jeremy Fragrance channel (local run required — YouTube blocks caption requests from Railway IPs)

**False-positive root cause (identified and fixed):**

Channel descriptions contain boilerplate footer text with affiliate links, discount codes, and
social handles — e.g. `"...check out Don Sauvage... cologne is..."`. The resolver's sliding-window
match on the full `text_content` field (title + description) was matching single-word aliases
(`don`, `cologne`, `11`, `21`, `pink`, `divine`) to unrelated perfume entities.

**Fix 1 — Title-only resolver for channel_poll:**
- `scripts/reresolve_channel_poll_items.py` — re-resolves all channel_poll items using
  `title` only (not description) as input to the resolver
- Upserts `resolved_signals` with `resolver_version + "-channel-title-only"` tag
- Result: 54 entity links across 3 channels → **2 valid links** (Dior Sauvage + YSL Libre)

**Fix 2 — Single-word alias safety guards in `perfume_resolver.py`:**

Two guards added to `resolve_text()` for `size == 1` window matches:

```python
_CONTRACTION_TAILS: frozenset[str] = frozenset({
    "t", "nt", "s", "ll", "re", "ve", "d", "m",
})
_BLOCKED_SINGLE_WORD_ALIASES: frozenset[str] = frozenset({
    "don", "pink", "dot", "smart", "standard",
    "heritage", "moth", "jack", "man", "11", "21",
})
```

- Contraction-tail guard: if next token is a contraction tail (e.g. `"don't"` → `["don", "t"]`),
  skip the match — prevents `"don"` from matching "don't" in video titles.
- Blocked alias set: single-word aliases that are too common or generic to match safely
  in social media text are suppressed entirely. Multi-word aliases (≥ 2 tokens) are unaffected.

**Fix 3 — Hard alias deletion from `resolver_aliases`:**

Five dangerous single-word alias rows permanently deleted from production PostgreSQL:

| id | alias | was pointing to |
|----|-------|----------------|
| 12453 | `don` | Xerjoff - Join the Club Don |
| 12383 | `11` | Boris Bidjan Saberi 11 |
| 12701 | `21` | Costume National 21 |
| 12745 | `pink` | Nanadebary Pink |
| 11875 | `divine` | Divine Divine |

Two additional aliases deleted earlier (ELdO Cologne false positives):
- id=12545: `cologne` → Etat Libre d'Orange Cologne
- id=12546: `cologne perfume` → Etat Libre d'Orange Cologne

**Controlled aggregation (2026-05-01):**
- `aggregate_daily_market_metrics` run manually for all 30 dates: 2026-04-01 through 2026-04-30
- `detect_breakout_signals` run manually for all 30 dates
- Total signals across 30 dates: 1,119
- `start_pipeline.sh` and `start_pipeline_evening.sh` were NOT modified

**Signal validation — 2026-04-13:**

| Entity | Mentions | Score | Trend state |
|--------|---------|-------|-------------|
| Yves Saint Laurent Libre | 2.2 | 43.95 | breakout |
| Dior Sauvage | 2.2 | 42.45 | breakout |

Both entities appear correctly on Apr 13 — driven by real channel_poll titles:
- AROMATIX: "RATING EVERY DIOR SAUVAGE IN 2026"
- FBFragrances: "The new YSL Libre Berry Crush"

**Final channel_poll entity link state (3 target channels):**

| Channel | Videos | Entity links | Resolved entities |
|---------|--------|-------------|-------------------|
| AROMATIX | 50 | 1 | Dior Sauvage ✓ |
| FBFragrances | 43 | 1 | Yves Saint Laurent Libre ✓ |
| K&A Fragrances | 22 | 0 | (none — no title matched) |

#### Tests added

`tests/unit/test_channel_poll_resolution.py` — 16 new tests in `TestResolverSingleWordGuards`:
- contraction-tail guard (`don't`, `can't`, `they're`, `it's`)
- blocked alias set (`don`, `11`, `21`, `pink`)
- multi-word aliases unaffected (`join the club don`, `armaf club de nuit`)
- `angel's share` → `angel` (not `angels`) after `normalize_text()` strips possessive

#### Next decision required before Phase 1C

Before integrating channel polling into `start_pipeline.sh`, implement adaptive polling logic:

- **Due-channel detection**: only poll channels where `last_polled_at < NOW() - poll_interval`
  (e.g. 12h for tier_1, 24h for tier_2, 72h for tier_3)
- **Quota-aware batching**: cap channel poll units per pipeline cycle
- **Backoff on consecutive_empty_polls**: reduce frequency for quiet channels

Phase 1C must not run channel polling unconditionally on every pipeline cycle.

---

---

### Motivation

Current search-based ingestion uses 47 queries × 100 units × 2 runs/day = 9,400 units/day (94% of the 10,000-unit daily limit). Channel-first polling via `playlistItems.list` costs ~1 unit per page vs 100 units per `search.list` call — approximately 23× more efficient.

Additional benefits:
- Complete coverage of a channel's output (search returns only relevance-ranked results)
- Deterministic — same channel, same results every poll
- Enables creator intelligence: quality_tier, engagement history, channel-level attribution

---

### Architecture Decisions

| Question | Decision |
|----------|----------|
| Schema | Single `youtube_channels` table (not 3-table) — derivable metrics via SQL, only editorial judgment stored |
| `activities.list` | Prohibited — deprecated for third-party channels since 2023 |
| `uploads_playlist_id` | Cached in `youtube_channels` after first `channels.list` call |
| `ingestion_method` | New column on `canonical_content_items` (`'search'` default, `'channel_poll'` for polled) |
| Attribution | `canonical_content_items.source_account_id` (already UC... format) joins to `youtube_channels.channel_id` |
| Pipeline integration | Standalone-only until Phase 1C — NOT in `start_pipeline.sh` |
| Checkpointing | `ORDER BY last_polled_at NULLS FIRST` — unpolled channels always processed first |
| source_profiles | Runtime-generated by aggregator — do NOT manually manage; `youtube_channels` is a separate table |

---

### Phase 1A — Schema + Management (COMPLETE)

**Alembic migration 023** (`alembic/versions/023_add_youtube_channels.py`):
- `youtube_channels` table with quality_tier, category, priority, uploads_playlist_id, polling state columns
- `canonical_content_items.ingestion_method VARCHAR(32) DEFAULT 'search'`
- Two indexes: `(status, priority)` and `(last_polled_at NULLS FIRST)`

**`scripts/manage_channels.py`** — management CLI:
- `--add CHANNEL_ID` — add a channel (validates UC... format, warns on similar title)
- `--list` — tabular view with optional `--status`, `--quality-tier`, `--category`, `--priority` filters
- `--disable` / `--enable` — pause/resume a channel
- `--update-tier` / `--update-priority` — editorial updates
- `--import-csv FILE` — bulk import (columns: channel_id, title, quality_tier, category, priority, notes)
- `--verify` — attribution join health report (channels vs canonical_content_items)

**quality_tier values:** `tier_1`, `tier_2`, `tier_3`, `tier_4`, `blocked`, `unrated`

**category values:** `reviewer`, `collector`, `beauty`, `brand`, `retailer`, `community`, `unknown`

---

### Phase 1B — Standalone Polling Script (COMPLETE)

**New methods in `perfume_trend_sdk/connectors/youtube/client.py`:**
- `get_uploads_playlist_id(channel_id)` — `channels.list` call, 1 quota unit, returns UU... playlist ID
- `list_channel_uploads(playlist_id, *, published_after, max_results, page_token)` — `playlistItems.list`, 1 unit per page; filtering on `published_after` is applied client-side (API does not natively support it)

**`scripts/ingest_youtube_channels.py`** — standalone channel polling script:
- Reads active channels from `youtube_channels` ordered by `last_polled_at NULLS FIRST`
- Fetches and caches `uploads_playlist_id` via `channels.list` (1 unit, only when not yet stored)
- Paginates `playlistItems.list` to collect recent video IDs (1 unit per page)
- Filters client-side by `published_after` cutoff
- Fetches video stats in batches via `videos.list`
- Normalizes and writes to `canonical_content_items` with `ingestion_method='channel_poll'`
- Resolves entities and writes to `resolved_signals` + `fragrance_candidates`
- Updates `youtube_channels` after each channel: `last_polled_at`, `last_video_count`, `consecutive_empty_polls`, `last_poll_status`, `last_poll_error`, `uploads_playlist_id`

**Flags:**
```
--limit N                 Channels to poll per run (default: 50)
--offset N                Skip first N channels
--max-results N           Videos per channel (default: 50)
--lookback-days N         Already-polled channels: look back N days (default: 3)
--first-poll-lookback-days N  Never-polled channels: look back N days (default: 30)
--quality-tier            Filter: tier_1 | tier_2 | tier_3 | tier_4 | unrated
--priority                Filter: high | medium | low
--status                  Filter: active (default) | paused | blocked | retired
--dry-run                 Print plan without API calls or DB writes
```

---

### How to Use (Phase 1A/1B Only)

**Step 1 — Apply migration (on Railway):**
```bash
# Runs automatically on next deploy via start.sh alembic upgrade head
# Or manually:
railway run --service generous-prosperity alembic upgrade head
```

**Step 2 — Add channels to the registry:**
```bash
# Single channel
DATABASE_URL=<prod-url> python3 scripts/manage_channels.py \
    --add UCxxxxxx \
    --title "Fragrance Therapy" \
    --quality-tier tier_1 \
    --category reviewer \
    --priority high

# Bulk import
DATABASE_URL=<prod-url> python3 scripts/manage_channels.py \
    --import-csv channels.csv
```

**Step 3 — Verify the registry:**
```bash
DATABASE_URL=<prod-url> python3 scripts/manage_channels.py --list
DATABASE_URL=<prod-url> python3 scripts/manage_channels.py --verify
```

**Step 4 — Dry-run channel poll:**
```bash
DATABASE_URL=<prod-url> python3 scripts/ingest_youtube_channels.py \
    --dry-run --limit 5
```

**Step 5 — Real channel poll (manually triggered):**
```bash
DATABASE_URL=<prod-url> YOUTUBE_API_KEY=<key> \
  python3 scripts/ingest_youtube_channels.py \
  --limit 20 --max-results 50 --first-poll-lookback-days 30
```

**Step 6 — Follow with aggregation:**
```bash
railway run --service pipeline-daily \
  python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date $(date +%Y-%m-%d)
```

---

### Verification Queries

```sql
-- youtube_channels table exists and has rows
SELECT COUNT(*) FROM youtube_channels;

-- ingestion_method column exists and defaults to 'search'
SELECT ingestion_method, COUNT(*)
FROM canonical_content_items
WHERE source_platform = 'youtube'
GROUP BY ingestion_method;

-- Attribution join health
SELECT COUNT(DISTINCT cci.source_account_id) AS channels_with_content
FROM canonical_content_items cci
JOIN youtube_channels yc ON yc.channel_id = cci.source_account_id
WHERE cci.source_platform = 'youtube';

-- Channel-polled items
SELECT DATE(collected_at) AS day, COUNT(*) AS items
FROM canonical_content_items
WHERE source_platform = 'youtube'
  AND ingestion_method = 'channel_poll'
GROUP BY 1
ORDER BY 1 DESC;
```

---

### Phase 1C Step 1 — Adaptive Due-Channel Polling (COMPLETED — 2026-05-01)

**STATUS: VERIFIED IN PRODUCTION — scheduled pipeline integration NOT yet enabled**

---

#### What was implemented

**Alembic migration 025** (`alembic/versions/025_add_next_poll_after_to_youtube_channels.py`):
- `youtube_channels.next_poll_after TIMESTAMPTZ NULLABLE` — computed due time for next poll
  - `NULL` = never polled → always eligible
  - Populated after every poll based on channel activity and quality_tier
- Index `idx_youtube_channels_next_poll` on `(next_poll_after, status)` — O(log n) due-channel lookup

**`scripts/ingest_youtube_channels.py`** updated:
- New `_compute_next_poll_after(last_video_count, consecutive_empty_polls, quality_tier) -> datetime`
- Due-channel WHERE filter in `_load_channels()` (bypass with `--force-all`):
  `status = 'active' AND (next_poll_after IS NULL OR next_poll_after <= NOW())`
- `next_poll_after` written back in all 3 poll-exit paths (ok, empty, error)

**Interval logic:**

| Condition | Interval |
|-----------|----------|
| `consecutive_empty_polls >= 14` | 168h (7 days) |
| `consecutive_empty_polls >= 7` | 72h |
| `consecutive_empty_polls >= 3` | 48h |
| `last_video_count >= 3` AND `consecutive_empty_polls == 0` | 12h |
| otherwise | 24h |

**Tier floors applied after base interval:**

| Tier | Max interval |
|------|-------------|
| `tier_1` | 24h (min(hours, 24)) |
| `tier_2` | 72h (min(hours, 72)) |
| `tier_3` / `unrated` | no cap |

`consecutive_empty_polls` resets to 0 whenever `last_video_count > 0`.

---

#### Production verification (2026-05-01)

**Real poll — 3 tier_2 channels:**

| Channel | Videos | Entity links | next_poll_after (UTC) |
|---------|--------|-------------|----------------------|
| Chad Secrets | 35 | 4 | 2026-05-01 22:31:58 |
| Noel Deyzel Fragrances | 29 | 0 | 2026-05-01 22:31:58 |
| Rotten Rebels | 21 | 1 | 2026-05-01 22:31:59 |

- **Total videos collected:** 85
- **next_poll_after interval:** +12h for all 3 (last_video_count ≥ 3, consecutive_empty_polls = 0, below tier_2 72h cap)
- **Transcript queue:** 85 items set to `transcript_status='needed', transcript_priority='high'`
- **API units used:** ~17 units (channels.list × 3 + playlistItems pages + videos.list batches)

**Dry-run after real poll:**
- Command: `python3 scripts/ingest_youtube_channels.py --quality-tier tier_2 --dry-run`
- Result: `No channels found matching filters. Exiting.`
- All 3 channels skipped — `next_poll_after` in the future
- Zero API calls, zero DB writes confirmed

---

#### Current state

- Migration 025 applied to production ✅
- Adaptive polling logic active in `ingest_youtube_channels.py` ✅
- Due-channel filter confirmed working end-to-end ✅
- `start_pipeline.sh` and `start_pipeline_evening.sh` NOT modified ✅
- Channel polling is still manual/standalone only

---

#### Next decision: Phase 1C Step 2

Add a non-fatal channel polling step to `start_pipeline.sh` and `start_pipeline_evening.sh`.

This requires explicit approval before implementation. Do NOT modify pipeline scripts until Phase 1C Step 2 is approved.

---

### Quota Budget Reference

| Method | Cost | Phase 1A/1B use |
|--------|------|----------------|
| `search.list` | 100 units/call | 47 queries × 2 runs = 9,400/day (unchanged) |
| `channels.list` | 1 unit/call | once per new channel (cached after) |
| `playlistItems.list` | 1 unit/page | 1–2 pages per channel per poll |
| `videos.list` | 1 unit/50 videos | shared with existing search path |

Phase 1A/1B adds minimal quota overhead from standalone manual runs only.

