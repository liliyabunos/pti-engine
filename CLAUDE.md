# FragranceIndex.ai / FTI Market Terminal — Operating Guide

## Read This First
- This file is the short operating index.
- Do not expand historical docs unless the task requires it.
- Use targeted grep/sed reads, not cat.
- For phase history, read only the relevant file/section.
- Keep reports concise.

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
- **Next: C1 Product/API** — creator leaderboard, entity page Top Creators

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

---

## Alembic Migrations

Current production: **migration 031**

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
