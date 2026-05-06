# FragranceIndex.ai / FTI Market Terminal — Operating Guide

## Read This First
- This file is the short operating index.
- Do not expand historical docs unless the task requires it.
- Use targeted grep/sed reads, not cat.
- For phase history, read only the relevant file/section.
- Keep reports concise.

---

## D1.1A — Apex Domain + App Route Canonicalization Hotfix
**STATUS: NEEDS DNS + RAILWAY + SUPABASE CONFIG (Step 1 code deployed 2026-05-06)**
**Commit: 6299ff8**

### Root cause (mixed)
| Layer | Issue |
|-------|-------|
| DNS (primary) | `fragranceindex.ai` apex has NO A/ALIAS record. Only SOA/NS/TXT present. DNS managed by Google Domains nameservers (`ns-cloud-a{1-4}.googledomains.com`). |
| Railway (secondary) | `pti-frontend` only has `www.fragranceindex.ai` as custom domain. Apex not registered. |
| Code (tertiary) | `NEXT_PUBLIC_SITE_URL=https://www.fragranceindex.ai` in Railway env → auth callbacks go to www. Fallbacks in next.config.ts + LoginForm.tsx pointed to Railway URL. Fixed in this commit. |
| Supabase (quaternary) | Likely missing `https://fragranceindex.ai/**` in allowed redirect URLs. |

### Code changes deployed (6299ff8)
- `next.config.ts`: `NEXT_PUBLIC_SITE_URL` fallback → `https://fragranceindex.ai`
- `LoginForm.tsx`: same fallback fix
- `layout.tsx`: `metadataBase: new URL("https://fragranceindex.ai")` added
- www → apex redirect: intentionally deferred until apex DNS confirmed live

### Liliya — Required manual actions (in order)

**Step 1: Railway — Add apex custom domain**
- Railway dashboard → pti-frontend service → Settings → Networking → Custom Domains
- Add: `fragranceindex.ai`
- Railway will show the DNS target to add (note it down)

**Step 2: DNS — Add apex record at Google Domains / Squarespace Domains**
- Go to domains.squarespace.com (formerly domains.google.com) → fragranceindex.ai → DNS
- Add record: Type `ALIAS` (or `ANAME`), Host `@`, Value = Railway's provided hostname (same as `oaifw38m.up.railway.app` unless Railway assigns a different one for apex)
- If ALIAS is not available, add Type `A`, Host `@`, Value = Railway IP (currently `66.33.22.52` — but IPs can change, ALIAS is preferred)
- Wait for propagation (typically 5–30 min with Google Domains TTL)

**Step 3: Supabase — Add apex to redirect URLs**
- Supabase dashboard → Authentication → URL Configuration
- Site URL: consider setting to `https://fragranceindex.ai`
- Redirect URLs: add `https://fragranceindex.ai/**`
- Keep `https://www.fragranceindex.ai/**` during transition

**Step 4: Railway — Update NEXT_PUBLIC_SITE_URL env var**
- Railway dashboard → pti-frontend service → Variables
- Change `NEXT_PUBLIC_SITE_URL` from `https://www.fragranceindex.ai` → `https://fragranceindex.ai`
- Trigger redeploy after saving

**Step 5 (post-DNS verified): www → apex redirect**
- After apex resolves and is confirmed working, enable the redirect in middleware.ts
- One-line change — Claude can implement this when you confirm apex is live

### Verification commands (run after DNS propagates)
```bash
dig fragranceindex.ai +short               # Should return Railway IP
dig www.fragranceindex.ai +short           # Should still resolve
curl -I https://fragranceindex.ai          # Should return HTTP 200 or 307
curl -I https://fragranceindex.ai/dashboard # Should return 307 (auth redirect)
curl -I https://fragranceindex.ai/login    # Should return 200
curl -I https://www.fragranceindex.ai      # Should return 301 → apex (after Step 5)
curl -I https://pti-frontend-production.up.railway.app/dashboard  # Fallback still works
```

### Current domain state (2026-05-06)
- `www.fragranceindex.ai` → resolves → HTTP 200 ✓ (only working public URL)
- `fragranceindex.ai` → ERR_NAME_NOT_RESOLVED ✗ (no DNS record)
- `pti-frontend-production.up.railway.app` → HTTP 307 ✓ (Railway fallback)

---

## Compliance Boundary v1 — Aggregated Market Intelligence, Not Personal Data Brokerage

FragranceIndex.ai is an aggregated fragrance market intelligence platform — not a personal data broker or creator directory.

**What we do:**
- Surface aggregated perfume/brand/topic/momentum signals from public fragrance conversations
- Use creator/source data as attribution/provenance (who mentioned what, when) — not as the product
- Link public content via `source_url` and `title` only — no raw body text exposed

**What we do NOT do:**
- Sell personal profiles, follower/subscriber lists, or contact data
- Sell or resell raw Reddit/YouTube/TikTok datasets
- Score, rank, or target individuals as a product
- Expose raw comment text, post bodies, or private messages in public APIs

**Compliance files:**
- `config/public_export_policy.yaml` — authoritative allow/deny field list + retention guidance
- `perfume_trend_sdk/compliance/policy.py` — runtime enforcement utilities
- `alembic/versions/032_add_public_safe_views.py` — PostgreSQL public-safe views
- `tests/unit/test_compliance_boundary.py` — 40 automated compliance tests

**Status: COMPLETE — PRODUCTION VERIFIED (2026-05-06):** commit a75dd62
- 40/40 tests pass
- Migration 032 applied to Railway production — alembic current: `032`
- Views live and verified (all denied fields absent):
  - `public_safe_entity_snapshots`: 2,163 rows · 17 columns · CLEAN
  - `public_safe_signals`: 4,559 rows · 8 columns · CLEAN
  - `public_safe_content_items`: 8,043 rows · 8 columns · CLEAN
- Schema corrections applied during migration: `entity_market` has no `state` column (removed); `breakout_signals` → `signals` (production table name)
- No infrastructure split — logical boundary only (per approved scope)

**Verification commands:**
```bash
python3 -m pytest tests/unit/test_compliance_boundary.py -v
```

---

## Current Production
- Domain: https://fragranceindex.ai
- Backend: FastAPI / Railway / PostgreSQL
- Frontend: Next.js / Railway
- Auth: Supabase magic link
- Main sources: YouTube, Reddit
- TikTok: planned after Creator Intelligence model

## Active Roadmap
- G4-E deployed, awaiting first active experiments
- UI-T1/T1.1 complete production verified
- **C1 Foundation COMPLETE (2026-05-05)**
  - C1.1 subscriber counts: 149/149 channels ✓
  - C1.2 mention_sources: 100% coverage ✓ (aggregator maintains)
  - C1.3 `creator_entity_relationships`: 2,135 rows, 689 creators, 741 entities ✓
  - C1.4 `creator_scores`: 689 rows, v1 influence score ✓
  - Migration 031 applied · commit e6f8054
- **C1.5 Creator Daily Refresh — DEPLOYED (2026-05-05)**
  - Steps 2b/2c added to morning pipeline (`start_pipeline.sh`) after Step 2 aggregation
  - Evening pipeline unchanged
  - PRODUCTION VERIFIED after next morning run
- **C1 Product/API Step 1 — Creator Intelligence API — COMPLETE (2026-05-05)**
  - `GET /api/v1/creators` — leaderboard (sort, filter, paginate) · 689 creators · PRODUCTION VERIFIED ✓
  - `GET /api/v1/creators/{creator_id}` — profile + entity portfolio + recent content ✓
  - `GET /api/v1/entities/perfume/{id}/creators` — top creators for perfume entity ✓
  - `GET /api/v1/entities/brand/{id}/creators` — top creators for brand entity ✓
  - Files: `routes/creators.py`, `schemas/creators.py`, `routes/entities.py`, `main.py`
  - commit 959d48e · deployed
- **C1 Product/UI Step 2A — Creators Leaderboard Page — DEPLOYED (2026-05-05)**
  - `/creators` page with influence score, tier/category filters, sort controls
  - Sidebar nav link added (Users icon)
  - Files: `app/(terminal)/creators/page.tsx`, `lib/api/creators.ts`, `Sidebar.tsx`
  - Build clean · PRODUCTION VERIFIED ✓ (307 auth-redirect confirms route live)
- **C1 Product/UI Step 2B COMPLETE — PRODUCTION VERIFIED (2026-05-05)** — Top Creators block on perfume entity pages · commit 51ca2a5
  - Baccarat Rouge 540 shows 10 creators with tier badges, Early Signal indicators, mentions, avg views, first/last seen, influence, signal count ✓
- **C1 Product/UI Step 2C COMPLETE — PRODUCTION VERIFIED (2026-05-06)** — Creator Profile Page · commit 5dabf87
  - Route: `/creators/{creator_id}` — header, score breakdown, entity portfolio, recent content
  - Leaderboard rows and entity Top Creators rows now clickable → profile
  - The Perfume Guy (UCFarEEFsV90-pvUU0XdUdgQ): 20 portfolio entities all have canonical_name ✓, 10 recent content items with valid YouTube URLs ✓, frontend route 307 confirmed ✓
  - Portfolio routing uses canonical_name slug (not UUID) — entity links resolve correctly ✓
- **FIX: Responsive control bar layout (2026-05-06)** — commit 5563bae
  - ControlBar: removed fixed h-9, flex-wrap, right slot full-width on mobile
  - RangeSelector: preset buttons overflow-x-auto, custom date inputs wrap below
  - Dashboard + Screener: search+filters row 1, range selector row 2 on narrow viewports
- **Legal Content Audit + Compliance Pages COMPLETE (2026-05-05)** — commit 8b0e055
  - New pages: /data-sources, /privacy/california, /cookies, /copyright, /privacy/request
  - Privacy Policy rewritten (15 sections: EEA/UK/CCPA/CPRA/GDPR, data broker statement)
  - Terms of Use rewritten (16 sections, removed "fair use principles")
  - Homepage copy: de-risked creator-profiling language, added data-brokerage disclaimer
  - All pti.market emails migrated to fragranceindex.ai equivalents
  - Footer: 9 legal links + "not personal data brokerage" disclaimer
  - Emails: privacy@fragranceindex.ai, legal@fragranceindex.ai, support@fragranceindex.ai
- **Compliance + Legal Content Baseline — COMPLETE — PRODUCTION VERIFIED (2026-05-06)**
  - Compliance Boundary v1 · commit fef5738 · 40/40 tests · policy YAML + Python utilities
  - Legal Content Audit · commit 8b0e055 · all pages live on fragranceindex.ai
  - Migration 032 applied · alembic current: `032` · views verified on Railway production:
    - `public_safe_entity_snapshots`: 2,163 rows · 17 cols · 0 denied fields ✓
    - `public_safe_signals`: 4,559 rows · 8 cols · 0 denied fields ✓
    - `public_safe_content_items`: 8,043 rows · 8 cols · 0 denied fields ✓
  - C1 Product/UI Step 2C: The Perfume Guy profile smoke tested · API ✓ · routing ✓ · frontend 307 ✓

## Semantic Phase 5 — Dupe / Alternative Entity Role Mapping
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-06)**
**Commits: 64f3a02 (backend + tests), 96772e0 (frontend badges + reference_original hero line)**

**Problem observed:** Armaf Club de Nuit (brand="Armaf") showed NICHE ORIGINAL badge because "armaf" was in `_NICHE_ORIGINALS`. Armaf is a mass-market clone brand, not a niche house.

**Why Phase 3/4 were not enough:** Phase 3/4 fixed dupe/alternative SEMANTICS (topics, opportunities, narrative) for originals. Phase 5 fixes entity ROLE CLASSIFICATION — specific clone perfumes now carry `dupe_alternative`, `designer_alternative`, or `celebrity_alternative` roles with `reference_original` and `dupe_family` metadata.

**Mapping approach:**
- `_DUPE_RAW` dict in `entity_role.py` — curated (brand, canonical_name) → DupeProfile mapping
- Dupe map checked FIRST before brand-set lookup; perfume-specific, not brand-wide
- `get_dupe_profile(brand_name, canonical_name) → Optional[DupeProfile]` exported for API use
- New roles: `dupe_alternative`, `designer_alternative`, `celebrity_alternative`
- `reference_original` + `dupe_family` fields added to `PerfumeEntityDetail` API response

**Brand list cleanup:**
- Removed from `_NICHE_ORIGINALS`: armaf, lattafa, zimaya, fragrance world, orientica, arabiyat, ard al zaafaran, afnan (mass-market clone/affordable brands — incorrectly classified)
- Kept: rasasi, swiss arabian, ajmal, al haramain (have genuine premium segments)

**Initial dupe seed:**
- Armaf CDNIM / Club de Nuit Intense Man → Creed Aventus (dupe_alternative)
- Montblanc Explorer → Creed Aventus (designer_alternative)
- Lattafa Khamrah → Kilian Angels' Share (dupe_alternative)
- Zara Red Temptation → MFK Baccarat Rouge 540 (dupe_alternative)
- Ariana Grande Cloud → MFK Baccarat Rouge 540 (celebrity_alternative)

**Frontend:**
- New badges: DUPE / ALTERNATIVE (amber), DESIGNER ALTERNATIVE (blue), CELEBRITY ALTERNATIVE (pink)
- "Alternative to: {reference_original}" line in entity hero (amber text, shown only when set)

**Tests:** `tests/unit/test_semantic_phase5.py` — 63/63 pass. Combined: 186/186 semantic tests pass.

**Production sanity sweep — 8 entities (2026-05-06, commits 64f3a02 + 96772e0):**
- Creed Aventus: entity_role=niche_original · reference_original=None · narrative="alternative demand around this reference scent" ✓
- Armaf Club de Nuit Intense Man: entity_role=dupe_alternative · reference_original="Creed Aventus" · dupe_family="Aventus alternatives" · narrative="gaining attention as an alternative to Creed Aventus, with active comparison activity" ✓
- Armaf Club de Nuit (broad line): entity_role=unknown · no false badge · competitors=['Creed Aventus'] (DB-resolved only) ✓
- MFK Baccarat Rouge 540: entity_role=niche_original · reference_original=None ✓
- Lattafa Khamrah: entity_role=dupe_alternative · reference_original="Maison Francis Kurkdjian Baccarat Rouge 540" · dupe_family="BR540 alternatives" ✓
- Zara Red Temptation: NOT IN entity_market (not yet tracked) — dupe map entry ready for when added ✓
- Ariana Grande Cloud: NOT IN entity_market (not yet tracked) — dupe map entry ready for when added ✓
- Montblanc Explorer: NOT IN entity_market (not yet tracked) — dupe map entry ready for when added ✓

All 5 tracked entities pass. 3 untracked entities have correct dupe map entries.

**No schema migration. No backfill.**

---

## Semantic Phase 4 — Production Verification + Compared-Against Cleanup
**STATUS: COMPLETE (2026-05-06)**

Production verification of Phase 2/3 logic + elimination of query-phrase pollution in Compared Against.

**Deploy status:**
- Backend (`generous-prosperity`): SUCCESS 2026-05-06 11:26:35 — Phase 3 commit (82a1485) confirmed live
- Frontend (`pti-frontend`): SUCCESS 2026-05-06 11:26:34 — Phase 3 commit confirmed live
- No recompute needed — semantic routing runs at API request time from entity_topic_links

**Compared-Against cleanup (`routes/entities.py`):**
- Removed raw-query fallback from `_find_competitor_names`
- Before: no DB match → raw candidate string included ("baccarat rouge 540 review", "erba pura review")
- After: only entities resolved from entity_market are included; unresolved candidates silently dropped

**Live API verification (production, commit 82a1485):**
- Creed Aventus: entity_role=niche_original · no "dupe / alternative" in differentiators · "alternative demand" in intents · opportunities=[alternative_demand, …] · narrative="alternative demand around this reference scent"
- Dior Sauvage: entity_role=designer_original · opportunities=[alternative_demand, …] · narrative="alternative demand around this reference scent" · competitors=[Creed Aventus, MFK Baccarat Rouge 540]
- Baccarat Rouge 540: entity_role=niche_original · opportunities=[alternative_demand, …] · narrative="alternative demand around this reference scent" · competitors=[Creed Aventus] (query phrases removed)

**No schema migration. No broad backfill.**

---

## Semantic Phase 3 — Demand Type Splitting + Role-Aware Dupe Semantics
**STATUS: COMPLETE (2026-05-06)**

Role-aware routing for "dupe / alternative" signals. Original/reference fragrances no longer rendered as clone/dupe-positioned.

**Logic:**
- `semantic.py`: For `designer_original / niche_original / original` — "dupe / alternative" rerouted from Differentiators to Intents as "alternative demand"
- `market_intelligence.py`: Role-aware opportunity flags replace `dupe_market`:
  - Originals → `alternative_demand` ("Alternative Demand")
  - Clone roles → `clone_market` ("Clone-Positioned")
  - Unknown → `alternative_search_interest` ("Alternative Search Interest")
- Narrative copy is role-aware: originals get "alternative demand around this reference scent", not "alternative / dupe positioning"

**Before/After (Creed Aventus, Dior Sauvage, Baccarat Rouge 540):**
- Before: Differentiators included "dupe / alternative" · Opportunity: "Dupe Market" · Narrative: "alternative / dupe positioning"
- After: Differentiators clean · Why People Search includes "alternative demand" · Opportunity: "Alternative Demand" · Narrative: "alternative demand around this reference scent"

**Tests:** `tests/unit/test_semantic_phase3.py` — 31/31 pass. Combined with Phase 2: 123/123 pass.

**No schema migration performed.** Logic change only — takes effect on next API request, no backfill needed.

---

## Semantic Phase 2 — Entity Role Classification (I7.5)
**STATUS: COMPLETE (2026-05-06)**

Deterministic brand-tier badge on perfume entity pages. No AI, no DB, pure frozenset lookup.

**New file:** `perfume_trend_sdk/analysis/topic_intelligence/entity_role.py`
- `classify_entity_role(brand_name, perfume_name=None) → str`
- NFD normalization: strips accents, apostrophes, ampersands, collapses whitespace
- Returns: `"designer_original"` | `"niche_original"` | `"unknown"` (Phase 2 scope)
- `ROLE_LABELS` + `RENDERABLE_ROLES` exports for UI

**API:** `entity_role: str` field added to `PerfumeEntityDetail` Pydantic model + TypeScript interface. Default `"unknown"` — backward compatible.

**Frontend:** `EntityRoleBadge` component in `entities/perfume/[id]/page.tsx`. Sky for designer, violet for niche; suppressed when `"unknown"`.

**Tests:** `tests/unit/test_entity_role.py` — 92/92 pass. Covers designer originals, niche originals, normalization edge cases, unknown, None/empty, ROLE_LABELS exports.

**Example outputs:**
- Creed Aventus → `"niche_original"` → "Niche Original" badge (violet)
- Dior Sauvage → `"designer_original"` → "Designer Original" badge (sky)
- Baccarat Rouge 540 → `"niche_original"` → "Niche Original" badge (violet)
- Unknown clone → `"unknown"` → no badge

**Phase 3 reserved:** `clone_positioned`, `inspired_alternative`, `flanker` — name-level signals from perfume title + topic context.

---

## Execution Rules
- Move fast but keep production safe.
- Commit + push after verified changes.
- Update CLAUDE.md only with short status changes.
- Move long reports into docs/history or docs/verification.
- Do not paste large DB outputs.
- Do not read entire CLAUDE.md or large docs unless necessary.
- Production verification required before COMPLETE — PRODUCTION VERIFIED.
- If auth blocks git push, report clearly and do not pretend deploy happened.

## Documentation Map
- Full phase history: docs/history/PHASE_LOG.md
- Resolver architecture: docs/architecture/RESOLVER_ARCHITECTURE.md
- Pipeline architecture: docs/architecture/DATA_PIPELINE.md
- Creator roadmap: docs/architecture/CREATOR_INTELLIGENCE.md
- SDK contracts and sprint plan: docs/architecture/SDK_ARCHITECTURE.md
- Verification queries: docs/verification/VERIFICATION_QUERIES.md
- Deployment notes: docs/history/DEPLOYMENT_NOTES.md

---

## Key Commands

**Start backend locally:**
```bash
cd /Users/liliyabunos/Claude_projects/Perfume_Trend_Intelligence_SDK
python3 -m uvicorn perfume_trend_sdk.api.main:app --reload --port 8000
```

**Run aggregation:**
```bash
python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date YYYY-MM-DD
```

**Run signal detection:**
```bash
python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date YYYY-MM-DD
```

**Ingest YouTube (search-based):**
```bash
python3 scripts/ingest_youtube.py --max-results 50 --lookback-days 2
```

**Ingest YouTube (channel polling):**
```bash
python3 scripts/ingest_youtube_channels.py --limit 50
```

**Ingest Reddit:**
```bash
python3 scripts/ingest_reddit.py --lookback-days 1
```

**Verify market state:**
```bash
python3 scripts/verify_market_state.py
```

**Apply Alembic migrations (Railway):**
```bash
railway run --service generous-prosperity alembic upgrade head
```

**Backfill trend states:**
```bash
python3 scripts/backfill_trend_state.py
```

**Re-resolve stale content after alias seed:**
```bash
python3 scripts/reresolve_g2_stale_content.py --batch <batch_name> --apply
```

---

## Database Rules

- All shared state MUST be stored in Postgres. Local filesystem is NOT a valid persistence layer.
- Production: `DATABASE_URL` env var → Railway PostgreSQL.
- Dev: `PTI_DB_PATH=outputs/market_dev.db` (set in `.env`).
- `outputs/pti.db` = legacy resolver SQLite — do NOT pass to FastAPI.
- `entity_mentions.entity_id` must always reference `entity_market.id` — never resolver UUIDs.
- Schema managed by Alembic only. Never call `Base.metadata.create_all()` in request paths.
- `PTI_ENV=production` enforced on all compute services — missing `DATABASE_URL` fails fast.
- All aggregation jobs are idempotent — re-running for the same date produces no duplicates.
- Real sources for serving: `source_platform IN ('youtube', 'reddit')` only.

---

## Architecture Constraints (NEVER VIOLATE)

1. **Interfaces first, then implementation** — define contracts before writing logic.
2. **No source dictates the data model** — connectors adapt to canonical schema.
3. **No analytics inside connectors** — connectors return raw data only.
4. **Each layer stores its own result separately** — raw ≠ normalized ≠ signals ≠ enriched.
5. **Every block must have a clear replacement point** — weak coupling everywhere.
6. **Historical data must be reprocessable** — never overwrite raw with interpreted data.
7. **Loose coupling** — connector knows nothing about scoring; scoring doesn't depend on collection method.
8. **AI is optional** — pipeline must work without it. Rule-based extractor is always the fallback.
9. **Aggregation collapses concentration suffixes** — "Dior Sauvage EDP" and "Dior Sauvage" are the same market entity.

---

## Phase Status

| Phase | Status | Date |
|-------|--------|------|
| I1–I8 Intelligence Layer | COMPLETE | 2026-04-25 |
| E1–E3 Entity Hygiene + Brand Market | COMPLETE | 2026-04-23 |
| G1 YouTube Query Expansion | COMPLETE | 2026-04-25 |
| G2/G2.1 Resolver Alias Seed | COMPLETE | 2026-04-26 |
| G3-A Batch Safe Alias Seed (85k aliases) | COMPLETE | 2026-05-03 |
| G3-R Reddit Subreddit Expansion | COMPLETE | 2026-05-03 |
| G3-C YouTube Channel Auto-Discovery | COMPLETE | 2026-05-03 |
| G4 Batch 1 Alias Intelligence | COMPLETE | 2026-04-27 |
| G4 Batch 2 Arabic/ME Entities | COMPLETE | 2026-05-04 |
| G4-E Emerging → Query Feedback Loop | DEPLOYED — awaiting first experiments | 2026-05-05 |
| E0/E1/E2/E3 Emerging Trend Detection | COMPLETE | 2026-05-02 |
| E-UX1/E-UX1.1/E-UX2 Entity Navigation | COMPLETE | 2026-04-28 |
| L1 Public Landing Page | COMPLETE | 2026-05-01 |
| FIX-1 entity_mentions Dedup + Integrity | COMPLETE | 2026-05-02 |
| YouTube Channel-First Ingestion (1A/1B/1C) | COMPLETE | 2026-05-01 |
| UI-T1 Time Range Selector | COMPLETE | 2026-05-05 |
| UI-T1.1 Custom Date Range Picker | COMPLETE | 2026-05-05 |
| C1.1 Subscriber Count Backfill | COMPLETE | 2026-05-05 |
| C1.2 mention_sources backfill | NOT NEEDED (100% coverage) | 2026-05-05 |
| C1.3 creator_entity_relationships table | COMPLETE | 2026-05-05 |
| C1.4 creator_scores table | COMPLETE | 2026-05-05 |
| C1.5 Creator Daily Refresh (pipeline) | COMPLETE | 2026-05-05 |
| C1 Product/API — Creator endpoints (3) | COMPLETE | 2026-05-05 |
| C1 Product/UI 2A — Creators Leaderboard | COMPLETE — PRODUCTION VERIFIED | 2026-05-05 |
| C1 Product/UI 2B — Entity Top Creators | COMPLETE — PRODUCTION VERIFIED | 2026-05-05 |
| C1 Product/UI 2C — Creator Profile Page | COMPLETE — PRODUCTION VERIFIED | 2026-05-06 |
| Compliance Boundary v1 (policy + views + tests) | COMPLETE — PRODUCTION VERIFIED | 2026-05-06 |
| Legal Content Audit + Compliance Pages | COMPLETE — PRODUCTION VERIFIED | 2026-05-06 |
| I7.5 Semantic Phase 2 — Entity Role Classification | COMPLETE | 2026-05-06 |
| I7.5 Semantic Phase 3 — Demand Type Splitting + Role-Aware Dupe Semantics | COMPLETE | 2026-05-06 |
| I7.5 Semantic Phase 4 — Production Verification + Compared-Against Cleanup | COMPLETE | 2026-05-06 |
| I7.5 Semantic Phase 5 — Dupe / Alternative Entity Role Mapping | COMPLETE — PRODUCTION VERIFIED | 2026-05-06 |

---

## Alembic Migrations

Current production: **migration 032**

| Migration | What |
|-----------|------|
| 023 | `youtube_channels` + `ingestion_method` on `canonical_content_items` |
| 025 | `next_poll_after` on `youtube_channels` |
| 026 | UNIQUE index `uq_entity_mentions_entity_source` on `entity_mentions` |
| 027 | `emerging_signals` table |
| 028 | `youtube_query_experiments` table |
| 029 | `subscriber_count_fetched_at` on `youtube_channels` |
| 030 | `creator_entity_relationships` table (C1.3) |
| 031 | `creator_scores` table (C1.4) |
| 032 | `public_safe_*` views — Compliance Boundary v1 |

Earlier key migrations: 008 (Fragrantica tables), 014 (resolver_* Postgres tables), 017 (resolver_perfume_notes/accords), 018-019 (source_profiles/mention_sources), 020 (weighted_signal_score), 021 (trend_state), 022 (content_topics/entity_topic_links).

---

## Creator Intelligence — C1.3 + C1.4 (COMPLETED — 2026-05-05)

### C1.3 — `creator_entity_relationships` (migration 030)

**Script:** `scripts/compute_creator_entity_relationships.py`
**Flags:** `--dry-run` (default), `--apply`, `--limit N`, `--verify`

**What it computes** (aggregated per `(platform, creator_id, entity_id)`):
- `mention_count`, `unique_content_count`
- `first_mention_date`, `last_mention_date`
- `total_views`, `avg_views`, `total_likes`, `total_comments`
- `avg_engagement_rate` (from `mention_sources` if available, else derived from views/likes/comments)
- `mentions_before_first_breakout`, `days_before_first_breakout` (vs first `breakout`/`acceleration_spike` signal per entity)

**Source join:** `entity_mentions JOIN canonical_content_items` via `(cci.source_url = em.source_url OR cci.id = em.source_url)`. YouTube only (`source_platform='youtube'`, valid `UC...` channel IDs).

**Important SQL notes:**
- `engagement_json` is TEXT in `canonical_content_items` — always cast `::jsonb` before accessing fields
- `entity_id` in `entity_mentions` is varchar UUID — cast `::uuid` for UUID comparisons
- SQL regex `{22}` must be escaped as `{{22}}` inside Python `.format()` strings

**Production results (2026-05-05):**

| Metric | Value |
|--------|-------|
| `creator_entity_relationships` rows | **2,135** |
| Unique YouTube creators | **689** |
| Unique entities covered | **741** |
| Duplicate `(platform, creator_id, entity_id)` | **0** |
| Rows with early signal (`mentions_before_first_breakout > 0`) | **221** |

**Top 5 by mention_count (creator → entity):**
Cherayeslifestyle → (various entities, 47+ mentions), The Perfume Guy → entities with 30+ mentions each.

**Top early-signal creator:** Cherayeslifestyle — 30 days before first breakout signal.

---

### C1.4 — `creator_scores` (migration 031)

**Script:** `scripts/compute_creator_scores.py`
**Flags:** `--dry-run` (default), `--apply`, `--limit N`, `--verify`

**v1 Influence Score formula** (6 weighted components, all normalized 0.0–1.0):

| Component | Weight | Formula |
|-----------|--------|---------|
| reach | 25% | `min(log10(subscriber_count+1) / log10(10_000_000), 1.0)` |
| signal_quality | 20% | `max(0.0, min(1.0 - noise_rate, 1.0))` where `noise_rate = content_with_entity_mentions / total_content_items` (inverted: lower noise = higher quality) |
| entity_breadth | 20% | `min(unique_entities_mentioned / 50.0, 1.0)` |
| volume | 15% | `min(log10(total_entity_mentions+1) / log10(1000), 1.0)` |
| early_signal | 10% | `min(early_signal_count / 20.0, 1.0)` |
| engagement | 10% | `min((avg_engagement_rate or 0.0) / 0.1, 1.0)` |

**JSONB handling note:** psycopg2 returns PostgreSQL JSONB columns as native Python dicts — do NOT call `json.loads()` on them. Use `isinstance(r[2], dict)` check before parsing.

**Production results (2026-05-05):**

| Metric | Value |
|--------|-------|
| `creator_scores` rows | **689** |
| Unique YouTube creators scored | **689** |
| Creators with `influence_score > 0` | **689** |
| Creators with `early_signal_count > 0` | **106** |
| Score distribution: top-tier (≥0.7) | **3** |
| Score distribution: mid (0.4–0.7) | **35** |
| Score distribution: low (<0.4) | **645** |
| Score distribution: minimal (<0.1) | **6** |

**Top 10 by influence_score:**

| Creator | Tier | Subscribers | Entities | Early signals | Score |
|---------|------|------------|---------|--------------|-------|
| The Perfume Guy | tier_1 | 333,000 | 138 | 10 | **0.7940** |
| Gents Scents | tier_1 | 634,000 | 49 | 10 | **0.7470** |
| Cherayeslifestyle | tier_2 | 115,000 | 50 | 11 | **0.7326** |
| Eau de Jarino | tier_2 | 52,600 | 67 | 8 | **0.6723** |
| Triple B | tier_2 | 337,000 | 38 | 9 | **0.6686** |

**Top 3 by early_signal_count:**
1. Cherayeslifestyle — 11 early signals
2. Gents Scents — 10 early signals
3. The Perfume Guy — 10 early signals

**Score components (The Perfume Guy):**
`reach=0.789, signal_quality=0.857, entity_breadth=1.000, volume=0.749, early_signal=0.500, engagement=0.631`

---

### C1 Completion Criteria

- [x] `subscriber_count` populated for 149/149 channels (100%) — C1.1 ✅
- [x] `mention_sources` coverage 100% of `entity_mentions` — C1.2 verified ✅
- [x] `creator_entity_relationships` table populated (2,135 rows, 689 creators, 741 entities) — C1.3 ✅
- [x] `creator_scores` table populated (689 rows, all with influence_score > 0) — C1.4 ✅
- [ ] `engagement_json` column JSONB migration — C1.5 (planned)
- [ ] Creator leaderboard API + frontend — C1 Product phase (planned)
- [ ] Top Creators panel on entity pages — C1 Product phase (planned)

**Recompute commands (run after each pipeline cycle for fresh scores):**
```bash
DATABASE_URL=<prod-url> python3 scripts/compute_creator_entity_relationships.py --apply
DATABASE_URL=<prod-url> python3 scripts/compute_creator_scores.py --apply
```

---

## Scheduled Pipeline

### Morning cycle — `start_pipeline.sh` (11:00 UTC)
- Step 1: YouTube search ingest (`ingest_youtube.py --max-results 50 --lookback-days 2`)
- Step 1a: YouTube channel polling (`ingest_youtube_channels.py --limit 50`)
- Step 1.5: Temp query experiment management (G4-E)
- Step 1.5b: Temp experiment YouTube ingest (max 5 results each, morning only)
- Step 1b: Aggregate candidates
- Step 1c: Validate candidates
- Step 2: Aggregate daily market metrics
- Step 3: Detect breakout signals
- Step 3b: Extract entity topics (`--rebuild-links`)
- Step 4c: Extract emerging signals (`--days 7`)
- Step 4d: Evaluate temp query experiments
- Step 5: Detect stale entities + metadata gaps + run maintenance
- Step 5b: YouTube channel auto-discovery (`discover_youtube_channels.py --apply --limit 100`)
- Verify market state (morning only)

### Evening cycle — `start_pipeline_evening.sh` (23:00 UTC)
- Step 1: YouTube search ingest + Reddit ingest
- Step 1a: YouTube channel polling
- Step 2: Aggregate daily market metrics
- Step 3: Detect breakout signals
- Step 3b: Extract entity topics
- Step 3c: Extract emerging signals
- Step 3d: Evaluate temp query experiments
- (no verify_market_state)

All steps are non-fatal. Missing `DATABASE_URL` in production fails fast. All jobs idempotent.

---

## Public Branding

- **Internal:** PTI / Perfume Trend Intelligence — backend code, DB tables, Railway services, env vars, console.log. Do NOT rename.
- **Public:** FTI Market Terminal (Fragrance Trend Intelligence) on all public pages.
- **Domain:** FragranceIndex.ai
- **Rule:** Public pages (`/`, `/login`, `/privacy`, `/terms`) use "FTI Market Terminal". Authenticated terminal shell retains "PTI MARKET TERMINAL".

---

## Entity Mentions Integrity Rule

`entity_mentions.entity_id` must always reference `entity_market.id` directly via the `entity_uuid_map` built from `entity_market` at aggregation time. Never use `perfume_identity_map` as an intermediary for this write. The old path `identity_resolver.perfume_uuid(int(raw_eid))` uses `resolver_perfume_id` — which is corruptible and not guaranteed to match the market UUID.

---

## Resolver Alias Seed History (cumulative production state)

| Batch | Rows | match_type |
|-------|------|-----------|
| G2 seed | 9 | g2_seed |
| G2.1 entities (batches 1–3) | 19 | g2_entity_seed |
| G4 batch 1 | 4 | g4_seed |
| G4 batch 2 | 23 | g4_batch2_seed |
| G3-A safe alias seed | 85,635 | g3_safe_alias_seed |
| Total resolver_aliases | ~98,531 | — |
| Perfumes with at least 1 alias | ~89.6% of 56k catalog | — |

Rollback any batch: `DELETE FROM resolver_aliases WHERE match_type = '<tag>';`
