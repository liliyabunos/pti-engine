# Creator / Influencer Intelligence Roadmap

Extracted from CLAUDE.md on 2026-05-05.

## Strategic Goal

The Creator Intelligence layer must answer 6 business questions:

1. **Which creator is pushing a perfume or brand right now?** — real-time attribution of market movement to specific content creators
2. **Which entities does a creator mention?** — creator portfolio view: what perfumes and brands a creator covers
3. **Who mentioned an entity before the breakout signal fired?** — early-signal attribution: identifying predictive creators
4. **Who are the early signal sources?** — leaderboard of creators consistently ahead of trend detection
5. **What is the engagement quality behind a trend signal?** — signal quality: are mentions from high-reach, high-engagement sources, or noise?
6. **Is a creator suitable for a campaign, and would they cause noise?** — campaign suitability scoring (C3)

---

## Current Audit Findings

### What Exists (Foundation)

| Layer | State |
|-------|-------|
| `youtube_channels` table | **149 channels** registered, quality_tier, next_poll_after, adaptive polling active; `subscriber_count` populated for all 149 via C1.1 (min=17, max=4.15M, avg=187,758) |
| `canonical_content_items` | 3,168+ YouTube items with `source_account_id` (UC... format), `source_account_handle`, `engagement_json` (as TEXT — requires `::jsonb` cast in all queries) |
| `entity_mentions` | 3,942+ rows — creator→entity link via `source_url` join |
| `mention_sources` | **100% coverage** of `entity_mentions` — daily aggregator pipeline maintains full coverage; C1.2 verified not needed |
| `source_profiles` | 313 profiles — `subscriber_count` populated in `youtube_channels`; `source_profiles.subscribers` not yet backfilled (deferred) |
| G3-C continuous discovery loop | New channels auto-promoted from `canonical_content_items` to `youtube_channels` every morning pipeline cycle |
| `subscriber_count_fetched_at` | New column on `youtube_channels` (migration 029, 2026-05-05) — tracks when stats were last fetched |

### Major Gaps

| Gap | Impact |
|-----|--------|
| No `creator_entity_relationships` table | Cannot answer "which entities does creator X cover" at scale without expensive JOIN — **C1.3 NEXT** |
| No `creator_scores` table | No influence score, no signal quality score, no early-signal rate stored — **C1.4 NEXT** |
| No creator leaderboard or profile API | Creator intelligence invisible to frontend — C1 Product/API phase |
| No Top Creators section on entity pages | Entity pages do not show who is driving movement — C1 Product/API phase |
| No campaign suitability scoring | C3 not started |
| ~~`subscriber_count` always NULL~~ | **RESOLVED — C1.1 (2026-05-05)**: all 149 channels have real subscriber/video/view counts |
| ~~`mention_sources` coverage gap~~  | **RESOLVED — verified 100% coverage** before C1.2 was needed; daily aggregator maintains coverage |
| `engagement_json` stored as TEXT | Every query requires `(cci.engagement_json::jsonb->>'views')::int` cast — C1.5 migration planned |

---

## Approved Roadmap

### C0 — Foundation (COMPLETE)

What already exists and is operational:
- `youtube_channels` registry (**149 channels**, adaptive polling, subscriber_count populated)
- `canonical_content_items` with `source_account_id` and `engagement_json`
- `entity_mentions` creator→entity join via `source_url`
- `mention_sources` source quality scoring (**100% coverage**, maintained by daily aggregator)
- `source_profiles` table structure (subscribers not backfilled — deferred to C1 Product phase)
- G3-C continuous channel auto-discovery loop (runs every morning pipeline cycle)
- Phase I1 / I2 — Source Intelligence and Signal Weighting already deployed

---

### C1 — Creator Intelligence Foundation

TARGET TYPE: PRODUCTION_TARGETED

**C1.1 — Subscriber Count Backfill — STATUS: COMPLETE (2026-05-05)**

- Alembic migration 029: added `subscriber_count_fetched_at TIMESTAMPTZ` column to `youtube_channels`
- Script: `scripts/fetch_channel_subscriber_counts.py` — standalone psycopg2, batches 50 channels per `channels.list` call
- Flags: `--dry-run` (default), `--apply`, `--force` (re-fetch all), `--limit N`, `--verify`
- `hiddenSubscriberCount=true` → stores NULL (not error)
- Cost: 3 API calls total (50+50+49 = 149 channels = 3 units)

**Production results (2026-05-05):**

| Metric | Value |
|--------|-------|
| Channels processed | 149 |
| Updated in DB | 149 |
| Not returned by API | 0 |
| Batch API errors | 0 |
| min subscriber_count | 17 |
| max subscriber_count | 4,152,000 (Alex Costa) |
| avg subscriber_count | 187,758 |
| alembic_version | 029 ✅ |

**Top channels by subscribers (sample):**
- Alex Costa: 4.15M (tier_3, auto-discovered)
- Jeremy Fragrance: 2.53M (tier_1)
- Fragrantica: 2.0M (tier_3, auto-discovered)
- Chad Secrets: 1.51M (tier_2)

**C1.2 — Backfill `mention_sources` Gap — STATUS: NOT NEEDED (verified 2026-05-05)**

Pre-flight check showed `mention_sources` was already at 100% coverage of `entity_mentions`.
G3-A expanded `entity_mentions` from 1,135 to 3,942 rows, but the daily aggregator pipeline
maintained full `mention_sources` coverage automatically. `backfill_source_intelligence.py`
was not required.

**Rule:** Daily aggregator maintains `mention_sources` coverage automatically. Only run
`backfill_source_intelligence.py` if aggregator misses a batch (e.g. pipeline outage covers
a date range with real YouTube/Reddit engagement data).

**C1.3 — `creator_entity_relationships` Table — STATUS: NEXT**
- Alembic migration
- Columns: `channel_id`, `entity_id` (FK to `entity_market`), `mention_count`, `first_mention_at`, `last_mention_at`, `avg_views`, `top_signal_type`, `early_signal_count`, `updated_at`
- UNIQUE on `(channel_id, entity_id)`
- Populated by new job `compute_creator_entity_relationships.py` — aggregates from `canonical_content_items JOIN entity_mentions JOIN mention_sources`
- Add to morning pipeline Step 5c (non-fatal, timeout 300s)

**C1.4 — `creator_scores` Table — STATUS: PLANNED (after C1.3)**
- Alembic migration
- Columns: `channel_id`, `influence_score`, `reach_score`, `signal_quality_score`, `entity_breadth`, `volume_score`, `early_signal_rate`, `computed_at`
- UNIQUE on `channel_id`
- Influence Score v1 formula (weighted composite):
  - reach (30%): `log10(subscriber_count + 1) / log10(10_000_000)`
  - signal_quality / noise rate (25%): `AVG(source_score)` from `mention_sources`
  - entity_breadth (20%): `COUNT(DISTINCT entity_id) / 50` (capped at 1.0)
  - volume (15%): `log10(total_mentions + 1) / log10(1_000)`
  - early_signal_rate (10%): fraction of mentions that preceded a breakout/acceleration signal
- Populated by `compute_creator_scores.py`, add to morning pipeline after C1.3 job
- **Prerequisite:** `subscriber_count` populated ✅ (C1.1 complete)

**C1.5 — `engagement_json` JSONB Migration — STATUS: PLANNED**
- Alembic migration: `ALTER TABLE canonical_content_items ALTER COLUMN engagement_json TYPE JSONB USING engagement_json::jsonb`
- Eliminates the silent-NULL risk from TEXT→JSONB cast in all downstream queries
- One-time migration; idempotent
- After migration: all existing queries using `::jsonb` cast continue to work unchanged

**C1 Completion Criteria:**
- [x] `subscriber_count` populated for ≥80% of `youtube_channels` — **149/149 (100%) ✅**
- [x] `mention_sources` coverage ≥90% of `entity_mentions` rows — **100% ✅**
- [ ] `creator_entity_relationships` table populated and refreshed daily — C1.3
- [ ] `creator_scores` table populated and refreshed daily — C1.4
- [ ] `engagement_json` column is JSONB (no cast required) — C1.5
- [ ] All new jobs are non-fatal pipeline steps

---

### C1 Product / API (PLANNED — after C1 Foundation verified)

- `GET /api/v1/creators` — creator leaderboard: ranked by influence_score, filterable by quality_tier, category
- `GET /api/v1/creators/{channel_id}` — creator profile: scores, entity portfolio, top mentions, early-signal history
- `GET /api/v1/entities/{type}/{id}/creators` — entity page: Top Creators driving this entity's trend
- Frontend: Top Creators panel on perfume and brand entity pages (replaces or extends Top Drivers section)
- Frontend: Creator leaderboard page (new route `/creators`)
- Frontend: Creator profile page (new route `/creators/{channel_id}`)

---

### C2 — Trend Attribution (PLANNED — after C1 Product/API)

Answer: **Who caused this trend?**

- Early-signal attribution: cross-reference `signals.detected_at` vs `canonical_content_items.published_at` for each entity
- For each breakout/acceleration signal: identify which creators published content within 7 days before signal fired
- `first_mover_score` per creator per entity: weighted by how early the mention preceded the signal
- Attribution visible on entity signal timeline: "Creed Aventus breakout — first covered by [creator] 5 days before signal"
- Attribution feed: cross-entity view of which creators are early movers on the most entities

---

### C3 — Campaign Suitability (PLANNED — after C2)

Answer: **Is this creator right for a campaign, and will they cause noise?**

- Noise rate: fraction of creator's mentions that resulted in false-positive or low-quality signal
- Category alignment: does creator's entity portfolio match the target brand's category?
- Engagement authenticity: engagement_rate vs subscriber_count ratio (anomaly detection for inflated accounts)
- `campaign_suitability_score`: composite of influence_score, noise_rate, category_alignment, authenticity
- Explicit "no blind suitability" rule: score must always be explainable (constituent factors visible in UI)
- Not implemented until C2 attribution data is available and validated

---

### TikTok Creator Integration (AFTER CREATOR MODEL — do not start before C2)

**Critical rule:** TikTok will be creator-first. Every TikTok item must be attributed to a creator identity.
The creator model established in C1/C2 on YouTube is the foundation TikTok will plug into.

**Platform-neutral schema requirement:**
- `creator_entity_relationships.channel_id` → rename to `creator_id` at migration time
- Add `platform` column: `'youtube'` | `'tiktok'` | `'instagram'` | `'reddit'`
- UNIQUE on `(platform, creator_id, entity_id)`
- `creator_scores` same extension: `(platform, creator_id)` composite key
- `youtube_channels` remains the YouTube-specific table; a future `tiktok_creators` table follows same pattern

**TikTok Research API readiness checklist (before integration):**
- [ ] Research API production credentials approved by TikTok
- [ ] `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET` in Railway `pipeline-daily` env vars
- [ ] TikTok connector (`connectors/tiktok_watchlist/`) tested and verified
- [ ] Creator identity confirmed available via Research API response schema

---

## Design Principles

**1. Platform-neutral schema**
Creator tables must use `(platform, creator_id)` as the composite key — not `channel_id` (YouTube-only). Schema designed from the start to accommodate TikTok, Instagram, and Reddit creator identities without redesign.

**2. Views are not enough**
Reach (subscriber count, view count) is one dimension. Signal quality (entity mention rate, noise rate), entity breadth, and early-signal rate are equally important. A creator with 10k subscribers who consistently mentions entities 5 days before breakout is more valuable than a 1M creator with low mention accuracy.

**3. Quality over volume**
Creator scoring must penalize noise. A creator who mentions 50 entities per video but most are false positives reduces signal quality. Noise rate must be a first-class scoring dimension (C1.4, C3).

**4. Explainable scoring**
Every influence score and campaign suitability score must expose its constituent factors. Never surface a single black-box number. Users must be able to see: reach=0.72, signal_quality=0.65, early_signal_rate=0.41, noise_rate=0.08.

**5. No blind campaign suitability (C3)**
Campaign Suitability scoring must not be implemented until Trend Attribution (C2) data is available and validated. C3 depends on C2's early-signal and noise-rate data to be meaningful. Implementing C3 without C2 produces arbitrary scores.

**6. TikTok-ready from the start**
Every C1 design decision must pass the question: "Does this work when `platform='tiktok'`?" If the answer is no, redesign before implementation. The YouTube creator model is the template — not the limit.

**7. Creator identity is (platform, creator_id) — never handle**
The canonical creator key across all tables and APIs is the composite `(platform, creator_id)`.

- **YouTube:** `creator_id` = `youtube_channels.channel_id` = `canonical_content_items.source_account_id` (UC... format, e.g. `UCxxxxxxxxxxxxxxxxxxxxxx`)
- **TikTok (future):** `creator_id` = stable TikTok unique user identifier returned by the Research API (NOT the `@handle` — handles can change)
- **Reddit:** `creator_id` = `author` field from Reddit post (stable string identifier)
- **Do NOT use `creator_handle` as a primary identity key** — handles change, are not unique across platforms, and are not guaranteed stable. Store as a display/search field only.
- All future creator tables (`creator_entity_relationships`, `creator_scores`) must use `(platform, creator_id)` as their UNIQUE constraint, never `(platform, creator_handle)`.
