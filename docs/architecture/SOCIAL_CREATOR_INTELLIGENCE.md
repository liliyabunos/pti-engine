# Social Creator Intelligence Roadmap (SC series)

**Status:** Strategic roadmap — no implementation started
**Owner:** Liliya / Engineering
**Production domain:** https://fragranceindex.ai
**Business entity:** Liliya's Flowers, LLC
**Product:** FragranceIndex.ai / FTI Market Terminal

---

## 1. Strategic principle

FragranceIndex.ai should not depend on creators voluntarily logging in as the primary ingestion strategy.

Creator OAuth / account connection is valuable, but adoption is uncertain. Many creators will hesitate to authorize TikTok, Meta, or Snapchat accounts on a new platform because of trust, account safety, and platform-ban concerns.

**Creator login is not the foundation of social data coverage.**
**Creator login is a future optional trust/claim/verification module.**

The primary system must work from compliant public signals, known-source monitoring, user-submitted URLs, and creator discovery from already-ingested market conversations.

### Correct priority

```
OLD (wrong):   Layer 1 → Layer 2 (creator login) → Layer 3

CORRECT:       Layer 1 (URL / mention / embed)
                  ↓
               Layer 3 (seeded watchlist + compliant public monitoring)
                  ↓
               Layer 2 (optional creator claim / verified module)
```

YouTube remains the benchmark source. TikTok is the highest-priority new social channel (SC1). Snapchat is SC2. Meta/Instagram is SC3.

---

## 2. Platform strategy

### 2.1 YouTube (existing — C1 series)

YouTube remains the strongest structured creator source. Already provides stable public APIs and rich metadata. Current creator leaderboard (689 creators, influence scores, tier/category, early signals) is YouTube-only.

YouTube should remain the benchmark for creator ranking quality. All new platforms are measured against YouTube signal reliability.

### 2.2 TikTok — SC1

TikTok is handled through three separate layers, implemented in order:

#### TikTok Layer 1 — URL / mention / embed foundation (SC1.1)

Purpose: accept TikTok URLs through `/submit-source`, detect TikTok links inside already-ingested YouTube descriptions / Reddit posts / Reddit comments, store URL + author handle where available, render TikTok embeds on entity pages, extract handles for creator discovery.

**Critical rule — no double-counting:**

If a Reddit post says *"Everyone is talking about Bianco Latte because of this TikTok: \<url\>"* — the Reddit post creates the signal. The TikTok URL is enrichment/context only.

```
Derived TikTok mention:
  platform = tiktok
  tiktok_layer = 1
  referencing_source_id = <reddit_or_youtube_content_id>
  mention_weight = 0.0

Direct TikTok submission from /submit-source:
  platform = tiktok
  tiktok_layer = 1
  referencing_source_id = null
  mention_weight = 0.7
```

Layer 1 = enrichment and discovery, not full TikTok market intelligence.

#### TikTok Layer 3 — seeded creator watchlist / public monitoring (SC1.2)

Purpose: manually seed 100–300 fragrance TikTok creators and monitor their public pages for new video URLs.

This is the practical TikTok coverage layer for the current business stage.

Suggested creator/source registry fields:

```
creator_id
platform
platform_handle
platform_url
display_name
category
tier
status  (active / pending_review / paused / rejected / invite_pending / claimed / verified)
seed_source
added_by
added_at
last_checked_at
last_new_content_at
notes
```

Layer 3 output:

```
platform = tiktok
tiktok_layer = 3
source_method = public_creator_monitoring
creator_handle = @creator
content_url = new TikTok video URL
engagement_quality = limited
```

Expected capabilities:
- detect whether a seeded creator has a new public video
- save the video URL
- connect the video to a creator
- send the video through the resolver
- allow entity-level TikTok visibility
- support creator-level trend analysis

Expected limitations:
- engagement metrics may be missing, unstable, or delayed
- comments are out of scope
- private/restricted content is out of scope
- no creator login required
- no anti-detect infrastructure
- no third-party scraper APIs as default strategy

Required safeguards:
- strict rate limits
- honest service identity
- no login simulation
- no account automation
- kill switch via env/config
- audit logging for every external fetch (`external_api_audit_log`)
- easy disable per platform

#### TikTok Layer 2 — optional creator claim / verified module (SC-V1, built last)

Purpose: allow creators to voluntarily connect through official platform login, long after Layer 1 and Layer 3 are working.

Positioning:
> "Claim your FragranceIndex creator profile. Verify your TikTok presence. Get discovered by fragrance brands."

NOT:
> "Connect TikTok so we can collect your data."

Conservative target: 10–20 verified creators within 6 months after launch.
Layer 2 must never block baseline TikTok signal coverage.

### 2.3 Meta / Instagram — SC3

Near-term role:
- store and rank known Instagram/Facebook creator profiles
- accept Instagram/Facebook URLs through `/submit-source`
- extract Meta handles from YouTube descriptions, Reddit posts, creator bios
- use Meta profiles as part of creator identity graph
- use Meta as creator-discovery and brand-presence signal before deeper integration

Do not depend on Instagram creator login for initial coverage.

Same layer priority as TikTok:
- Layer 1: URL / handle / mention detection → SC3.1
- Layer 3: seeded public profile monitoring → SC3.2 (future)
- Layer 2: optional official creator/business claim → SC-V1 (cross-platform)

Important near-term fields:

```
instagram_handle
facebook_page_url
meta_profile_type
cross_platform_creator_id
source_confidence
```

Meta content should not receive strong market-signal weight until stable metadata quality and repeatable ingestion are confirmed.

### 2.4 Snapchat — SC2

Snapchat = future/experimental. Near-term: store Snapchat handles where creators publicly list them. Detect Snapchat links/handles in YouTube bios, TikTok bios, Instagram bios, Reddit, creator websites, or user submissions. Use Snapchat presence as a creator-profile enrichment field only.

```
platform = snapchat
source_method = handle_discovery
signal_weight = 0.0   # until reliable signal exists
```

---

## 3. Unified creator registry (SC0.1)

Platform-neutral creator registry representing the same creator across multiple channels.

### Table: `creators`

```
id
display_name
primary_platform
primary_category
creator_type        (reviewer / collector / dupe_creator / seller / brand_founder /
                     esthetician / beauty_creator / lifestyle_creator / celebrity / unknown)
country_or_region
language
status
created_at
updated_at
```

### Table: `creator_platform_accounts`

```
id
creator_id
platform            (youtube / tiktok / instagram / facebook / snapchat / reddit / blog / website)
platform_handle
platform_url
display_name
follower_count
subscriber_count
avg_views
last_seen_at
last_checked_at
status
verification_status
source_method       (manual_seed / cross_platform_link / content_mention / user_submission /
                     operator_review / creator_claim / official_api / public_profile_monitoring)
confidence
created_at
updated_at
```

### Table: `creator_identity_edges`

Links platform accounts that likely belong to the same creator.

```
id
from_account_id
to_account_id
edge_type           (manual_confirmed / same_handle / cross_linked_in_bio /
                     cross_linked_in_description / operator_reviewed / creator_claimed)
confidence          (1.0=manual confirmed / 0.9=creator claimed / 0.8=cross-linked official /
                     0.6=same handle+display name / 0.4=weak candidate)
evidence
created_at
updated_at
```

**Rule:** No automatic merge below a safe confidence threshold.

---

## 4. Creator filtering framework (SC0.2)

Current Creators leaderboard filters (tier, category, sort) evolve into a cross-platform creator intelligence filter system.

### 4.1 Platform filter

Single: All / YouTube / TikTok / Instagram / Facebook / Snapchat / Reddit / Blogs
Multi-select: YouTube + TikTok / TikTok + Instagram / All video platforms / All social

### 4.2 Category filter (expanded)

```
Reviewer / Collector / Dupe & Alternative / Luxury & Niche / Designer Fragrance /
Affordable Fragrance / Gourmand & Vanilla / Middle Eastern Fragrance / Men's Fragrance /
Women's Fragrance / Unisex Fragrance / Beauty & Lifestyle / Retail & Seller /
Brand & Founder / Educational / Trend & Viral / Unknown
```

A creator may have multiple categories.

### 4.3 Tier — per-platform and global

```
youtube_tier / tiktok_tier / instagram_tier / global_tier
T1 = high authority / high influence / strong consistency
T2 = meaningful creator / medium authority
T3 = emerging creator
T4 = low signal / experimental / watch only
```

### 4.4 Signal role filter

```
Early Signal Creator / High Reach Creator / High Trust Reviewer / High Noise Creator /
Dupe Driver / Brand Amplifier / Niche Authority / Viral Trend Carrier /
Cross-Platform Amplifier / Emerging Creator
```

### 4.5 Noise filter

```
Low:    0–20%
Medium: 20–45%
High:   45%+
```

High-noise TikTok creators can still be useful but should carry lower signal weight.

### 4.6 Entity relevance filter

Entity count / Brand count / Perfume count / Top influenced brands / Top influenced perfumes / Entity diversity

### 4.7 Early signal filter

```
0 / 1–3 / 4–10 / 10+ early signals
Early signal rate = early_signals / total_resolved_mentions
```

Early signal rate is more important than raw reach. A smaller creator who repeatedly finds trends early may be more valuable than a large creator who only repeats known trends.

### 4.8 Engagement quality filter

Platforms expose different engagement levels:

```
YouTube         = full engagement (views, likes, comments, engagement_rate)
TikTok Layer 2  = full if creator-authorized
TikTok Layer 3  = limited or partial
Instagram       = depends on access method
Snapchat        = likely limited
```

UI must clearly show engagement quality so users know confidence level of any metric.

---

## 5. Creator scoring model evolution

Current YouTube influence score → multi-factor cross-platform model.

```
Influence Score =
  reach_score              (subscribers / followers / views where available)
  + engagement_score       (avg views, likes, comments, velocity where available)
  + entity_relevance_score (resolved fragrance entities, brand/perfume specificity)
  + early_signal_score     (mentions entities before broader market movement)
  + cross_platform_score   (confirmed presence across multiple platforms)
  + low_noise_score        (content resolves cleanly to fragrance entities)
  + consistency_score      (relevant fragrance content published repeatedly over time)
```

All components normalized 0–1. Weights documented and human-reviewable.

---

## 6. Platform signal weights

Initial hypotheses — reviewed every 60 days.

| Source | Weight | Notes |
|--------|--------|-------|
| YouTube | 1.0–1.2 | Benchmark source, stable metadata |
| Reddit | 1.0 | Community signal |
| TikTok Layer 1 derived | 0.0 | Enrichment only, no double-count |
| TikTok Layer 1 direct (/submit-source) | 0.7 | Candidate signal |
| TikTok Layer 3 public monitoring | 0.8–0.9 | Main TikTok coverage path |
| TikTok Layer 2 creator-authorized | 1.0 | Full weight, future |
| Meta/Instagram | 0.5–0.8 | Depends on data quality |
| Snapchat | 0.0 | Identity/discovery only at launch |

### Table: `weight_calibration_log`

Every 60 days, run a retrospective: for breakouts that became real market movements, which platform showed the earliest useful signal? Adjust weights based on evidence.

```
id
platform
old_weight
new_weight
reason
evidence_window_start
evidence_window_end
approved_by
created_at
```

Platform weights must be human-reviewed and documented — never silently changed.

---

## 7. Creator discovery pipeline

Creators enter through multiple safe paths:

```
Discovery source → source_method field
---
manual seed list                → manual_seed
YouTube channels already tracked → cross_platform_link
TikTok handles found in content  → content_mention
Instagram handles from bios       → content_mention
user submissions (/submit-source) → user_submission
operator review                   → operator_review
creator claim                     → creator_claim
```

No discovered creator automatically becomes high-confidence without evidence.

---

## 8. Admin / operator workflow

Operator queue tabs:

- Pending TikTok Creators
- Pending Instagram Creators
- Pending YouTube Creators
- Potential Duplicates
- Cross-Platform Identity Matches
- High-Noise Creators
- High-Early-Signal Creators
- Rejected / Paused

Each item shows: creator handle, platform, source, evidence URL, candidate category, suggested tier, confidence, last seen.

Operator actions: approve / reject / pause / merge with existing creator / mark duplicate / assign category / assign tier override / add notes / invite to claim profile.

---

## 9. Creator profile page evolution

Each creator should eventually have a detail page with sections:

Overview / Platform Accounts / Influence Score / Early Signals / Top Perfumes Mentioned / Top Brands Mentioned / Content Timeline / Noise & Quality / Cross-Platform Presence / Related Creators / Source Evidence / Operator Notes

For unclaimed creators:
> "This profile is generated from public market signals and tracked source references."

For claimed creators:
> "This creator has verified their profile."

Creator claim must NOT be required for the profile to exist.

---

## 10. Creators UI roadmap

### Current columns (C1, YouTube-only)
Creator / Influence / Subscribers / Avg Views / Mentions / Entities / Brands / Early Signals / Noise Rate / Tier / Category

### Add in SC phases
Primary Platform / All Platforms / TikTok Status / Instagram Status / Creator Role / Last Seen / New Content / Engagement Quality / Claim Status

### Sorting additions
TikTok Momentum / YouTube Authority / Cross-Platform Score / Entity Diversity / Low Noise / Recently Active

---

## 11. Compliance rules (permanent)

- No third-party scraper APIs as default architecture
- No account automation
- No fake creator login or login simulation
- No collection of private content
- No bypassing platform authentication
- No comments collection without official approved method
- No hidden anti-detect infrastructure
- Kill switch via env/config for every platform monitor
- All external platform fetches must be auditable

### Table: `external_api_audit_log`

```
id
platform
source_method
endpoint_or_url
related_creator_account_id
related_content_id
http_status
result_status
fetched_at
error_message
terms_safe_flag
```

This protects the company's credibility with brands, investors, and partners.

---

## 12. SC implementation phases (ordered)

### SC0.1 — Unified creator registry

Goal: create platform-neutral creator/account data model.

Tasks:
- Add `creators` table (or equivalent model)
- Add `creator_platform_accounts` table
- Add `creator_identity_edges` table
- Map existing 689 YouTube creators into the new registry
- Preserve current Creators UI behavior entirely
- Add migration tests
- Update CLAUDE.md after deployment

Production verification:
- existing creator leaderboard still loads
- current creators remain visible with same counts
- no broken dashboard/screener/entity routes

---

### SC0.2 — Creator filters v1

Goal: improve the Creators page filtering system.

Tasks:
- Add platform filter
- Expand category filter (full list from §4.2)
- Add creator role filter
- Add noise level filter
- Add early signal range filter
- Add cross-platform filter placeholder
- Keep current sort options

Production verification:
- filters do not break pagination
- reviewer category still works
- existing sort buttons still work
- mobile/tablet layout does not overlap

---

### SC1.1 — TikTok Layer 1 — URL / embed / mention foundation

Goal: support TikTok URLs, embeds, and derived-vs-direct mention distinction.

Tasks:
- Accept TikTok URLs in submit-source validation
- Detect TikTok URLs inside already-ingested content
- Normalize TikTok URLs
- Store `platform='tiktok'`, `tiktok_layer=1`
- Add `referencing_source_id` field
- Add `source_method` field
- Add oEmbed metadata cache where available
- Derived TikTok mentions: `mention_weight=0.0`
- Direct TikTok submissions: `mention_weight=0.7`
- Render TikTok embeds on entity pages

Production verification:
- same TikTok URL does not duplicate
- deleted/unavailable TikTok URL soft-fails gracefully
- derived TikTok mention does not increase `mention_count`
- direct TikTok submission can enter candidate/resolver flow

---

### SC1.2 — TikTok Layer 3 — seeded creator watchlist + public monitoring

Goal: allow operator-seeded TikTok creators and detect new public videos.

#### SC1.2A — Schema + Registry (COMPLETE — PRODUCTION VERIFIED 2026-05-08)

Migration 035 added two tables:

**`creator_platform_accounts`** — platform-neutral creator registry
- UNIQUE on `(platform, platform_handle)` — one row per creator per platform
- 5 valid statuses: `pending_review`, `active`, `paused`, `rejected`, `error`
- 5 source methods: `manual_seed`, `url_submission`, `mention_derived`, `auto_discovery`, `creator_claim`
- Columns: `follower_count`, `last_checked_at`, `tier`, `category`, `seed_source`, `notes`, `platform_url`, `display_name`
- On duplicate seed: COALESCE-based update preserves existing values

**`creator_watchlist_audit_log`** — append-only audit trail
- Indexed on `(platform, platform_handle)`
- `action`, `old_status`, `new_status`, `source_method`, `note`, `created_at`

Service layer: `perfume_trend_sdk/services/tiktok_watchlist.py`
- `normalize_handle(raw)` — strips `@`/URL prefix, rejects video URLs, validates `^[A-Za-z0-9._]{1,24}$`
- `add_account()`, `change_status()`, `bulk_import()` — write to both tables atomically

API routes: `GET/POST /api/v1/tiktok-watchlist/`, `GET/PATCH /{handle}`, `GET /{handle}/audit`

Tests: `tests/unit/test_sc1_2_watchlist.py` — 44/44 pass

#### SC1.2B — Seed Import Script (COMPLETE — PRODUCTION VERIFIED 2026-05-08)

Script: `perfume_trend_sdk/scripts/seed_tiktok_creators.py`

Usage:
```bash
python3 -m perfume_trend_sdk.scripts.seed_tiktok_creators \
    --file data/tiktok_creators_seed.csv [--dry-run] [--activate]
```

- CSV columns: `handle` (required), `profile_url`, `display_name`, `category`, `tier`, `notes`, `seed_source`
- `--dry-run`: connects to DB, prints would_insert / would_update counts without writing
- `--activate`: imports with `status=active` (default: `status=pending_review`)
- Pre-validates all rows before any DB writes; rejects video URLs, empty handles

#### SC1.2C — Safe TikTok Seeded Creator Monitoring Worker (COMPLETE — PRODUCTION VERIFIED 2026-05-08)

**Status: profile reachability + metadata harvest only. Video discovery NOT implemented.**

Worker: `perfume_trend_sdk/jobs/monitor_tiktok_seeded_creators.py`
Parser: `perfume_trend_sdk/ingest/tiktok_page_parser.py`
Tests: `tests/unit/test_sc1_2c_monitor.py` — 24/24 pass

##### What the worker does

- Reads `creator_platform_accounts` where `platform='tiktok'` and `status='active'`
- Fetches each profile via plain HTTPS GET (Chrome/124 UA, no cookies, no auth, no automation)
- Parses `__UNIVERSAL_DATA_FOR_REHYDRATION__` script tag in the SSR HTML
- Extracts: `follower_count`, `video_count`, `verified`, `sec_uid`, `nickname` from `webapp.user-detail.userInfo`
- Updates `follower_count` and `last_checked_at` in `creator_platform_accounts`
- Writes `action=monitor_profile_check` to `creator_watchlist_audit_log`
- Polite 4-second sleep between requests (`--sleep-seconds` override available)
- Skips creators checked within 24 hours unless `--force`

##### What the worker does NOT do

- Does NOT create `entity_mentions` rows — TikTok monitoring is not yet a market signal source
- Does NOT create `canonical_content_items` rows
- Does NOT use browser automation, Playwright, Puppeteer, or any headless browser
- Does NOT use third-party scraper APIs
- Does NOT simulate login or use session cookies

##### TikTok simple HTTP limitation (verified 2026-05-08)

TikTok profile pages served via plain HTTPS always return an **empty `itemList`** in the SSR JSON. The internal `/api/post/item_list/` endpoint returns an empty body without authenticated session cookies. Video discovery is therefore not possible via simple HTTP.

**Confirmed on three live handles:** `@rawscents`, `@scentofself`, `@perfumedude` — all returned `itemList: []` in SSR, with follower/video counts successfully extracted from `userInfo.stats`.

The worker logs this clearly:
```
TIKTOK_MONITOR_CREATOR_WARNING handle=@rawscents video_list_unavailable=true
  reason='itemList empty in SSR JSON — video discovery requires authenticated API
  or approved browser-based method (not in SC1.2C)'
```

Video discovery will require a separately approved approach (e.g. TikTok Research API, or a browser-based method reviewed for ToS compliance). This is deferred to a future SC phase.

##### Kill switch

```bash
TIKTOK_PUBLIC_MONITORING_ENABLED=false  # default — worker exits safely
TIKTOK_PUBLIC_MONITORING_ENABLED=true   # enables live fetching
```

Log markers:
- `TIKTOK_MONITOR_DISABLED` — kill switch active, safe exit
- `TIKTOK_MONITOR_STARTED` — run beginning
- `TIKTOK_MONITOR_CREATOR_OK` — profile reachable, metadata updated
- `TIKTOK_MONITOR_CREATOR_WARNING` — reachable but video list unavailable (always, in SC1.2C)
- `TIKTOK_MONITOR_CREATOR_ERROR` — fetch failed or profile unreachable
- `TIKTOK_MONITOR_COMPLETE` — run finished with summary counts

##### Usage

```bash
python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators
python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators --limit 5
python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators --handle rawscents --dry-run
python3 -m perfume_trend_sdk.jobs.monitor_tiktok_seeded_creators --force
```

##### Production verification results (2026-05-08)

- Kill switch: `TIKTOK_MONITOR_DISABLED` logged when `TIKTOK_PUBLIC_MONITORING_ENABLED` not set ✓
- Live run on `@rawscents`: `TIKTOK_MONITOR_CREATOR_OK followers=2 videos=0 verified=False` ✓
- `follower_count=2`, `last_checked_at` updated in `creator_platform_accounts` ✓
- Audit log entry: `action=monitor_profile_check source_method=public_creator_monitoring` ✓
- `entity_mentions` rows with `platform='tiktok'`: 0 ✓ (worker does not create these)
- `canonical_content_items` rows with `source_method='public_creator_monitoring'`: 0 ✓

##### What SC1.2C does NOT wire

- No production cron entry — must be manually verified with a real seed list before scheduling
- No market signal weight — profile checks do not produce market signals in this phase

---

### SC1.3 — Multi-field resolver adaptation (COMPLETE — PRODUCTION VERIFIED 2026-05-08)

**Status: PRODUCTION ENABLED — `MULTI_FIELD_RESOLVER_ENABLED=true` on Railway generous-prosperity. Commit: ee1d8ba.**

#### Production verification results (2026-05-08 manual pipeline run)

| Metric | Value | Baseline | Status |
|--------|-------|---------|--------|
| PIPELINE_HEALTH_OK | ✓ | — | PASS |
| entity_mentions | 180 | 183–189/day | PASS |
| signals | 142 | 113–216/day | PASS |
| resolved_signals 1.1-mf | 558 | new | ACTIVE |
| resolved_signals 1.1 (old) | 74 | legacy morning | expected |
| content_items (yt+reddit) | 1203 | — | PASS |
| public_safe_entity_snapshots | 2318 | 2259 pre | stable |
| public_safe_signals | 4976 | 4837 pre | stable |
| public_safe_content_items | 9644 | 9159 pre | stable |
| dashboard API | HTTP 200 | — | PASS |
| false positive spike | None new | — | PASS |

False-positive note: noise aliases (Scent of, I will, You Are) match in Reddit body at same rate as pre-SC1.3 — confirmed pre-existing, not introduced by SC1.3. YouTube title-only noise filter working correctly.

Goal: prepare resolver for platform-aware multi-field resolution where title alone is insufficient.

#### Architecture

New module: `perfume_trend_sdk/resolvers/perfume_identity/multi_field_resolver.py`

`PerfumeResolver.resolve_content_item()` branches on the feature flag:
- Flag off (default) → `_resolve_content_item_single()` — unchanged v1.1 path
- Flag on → `_resolve_content_item_multi()` → `resolve_multi_field()` with platform weights

No schema migration. No DB change.

#### text_signal schema

```python
{
    "title": str | None,
    "description": str | None,      # YouTube description; TikTok caption
    "hashtags": str | None,         # space-joined hashtag list
    "body": str | None,             # Reddit: title + selftext
    "referencing_context": str | None,  # TikTok derived: surrounding text
    "user_context": str | None,     # TikTok direct: operator-supplied context
    "audio_transcript": None,       # reserved — SC1.4T
    "ocr_overlays": None,           # reserved — future
    "platform": str,
    "source_method": str | None,    # "derived" | "direct" | None
    "tiktok_layer": int | None,
}
```

#### Platform field weights

| Platform key | Field | Weight |
|---|---|---|
| youtube | title | 1.0 |
| youtube | description | 0.5 |
| youtube | hashtags | 0.3 |
| reddit | body | 1.0 |
| reddit | title | 0.7 |
| reddit | hashtags | 0.3 |
| tiktok_derived | referencing_context | 1.0 |
| tiktok_derived | hashtags | 0.5 |
| tiktok_derived | description | 0.3 |
| tiktok_derived | title | 0.2 |
| tiktok_direct | user_context | 1.0 |
| tiktok_direct | hashtags | 0.6 |
| tiktok_direct | referencing_context | 0.4 |
| tiktok_direct | description | 0.4 |
| tiktok_direct | title | 0.5 |
| tiktok_layer3 | user_context | 0.8 |
| tiktok_layer3 | title | 0.7 |
| tiktok_layer3 | hashtags | 0.6 |
| tiktok_layer3 | description | 0.5 |

`final_confidence = max(field_weight × raw_confidence)` across all matched fields.
Minimum threshold: 0.3 — matches below are suppressed.

#### Guardrails

**TikTok generic title protection:**
Titles containing phrases like "omg", "you need this", "run don't walk", "must try", "best perfume", etc. are suppressed before `resolve_text()` is called for TikTok derived/direct items.

**YouTube title noise filter:**
Resolver aliases that are also common English phrases (e.g. "I will", "You Are", "Beach Vibes", "So Sweet", "Scent of", "Men's Cologne") are suppressed when the match comes from the YouTube `title` field only. If the same entity is also found in `description` or `hashtags`, the match passes (corroborated).

#### Replay report (2026-05-04 → 2026-05-07, 2000 items)

| Metric | Value |
|---|---|
| Old resolver resolved | 624 / 2000 |
| New resolver resolved | 807 / 2000 |
| Items with gains | 209 |
| Items with losses | 0 |
| YouTube regressions | 0 ✓ |
| Reddit regressions | 0 ✓ |

Selected gains (all legitimate): Dior Sauvage EDP, Armani Acqua di Gio, Rasasi Hawas, BYREDO Mojave Ghost, MFK Baccarat Rouge 540 Extrait, MFK Grand Soir, Chanel Bleu de Chanel, Creed Aventus EDP, Creed Wild Vetiver, Imperial Valley (Gissah), Hawas Ice.

Reddit: 0 changes (Reddit body already concatenated title + selftext → no new fields).

**Conclusion:** Safe to enable. No production enablement without explicit approval.

#### Replay / backtest tool

```bash
PYTHONPATH=. DATABASE_URL=<prod-url> python3 scripts/replay_multi_field_resolver.py \
    --start 2026-05-04 --end 2026-05-07 [--platform youtube] [--limit 2000]
```

Output: console report + `outputs/replay_mf_resolver_<start>_<end>.json`

#### Tests

`tests/unit/test_sc1_3_multi_field_resolver.py` — 67/67 pass.

Covers: feature flag, platform key routing, generic title detection, signal extraction,
YouTube title/description resolution, Reddit body resolution, TikTok derived/direct,
confidence threshold, debug metadata, multiple entities, noise filter, backward compat.

#### Enabled in production

```bash
# Railway → generous-prosperity service → Variables — already set
MULTI_FIELD_RESOLVER_ENABLED=true
```

Production enabled 2026-05-08. Replay (2026-05-04–07, 2000 items): old=624 → new=807, +183 resolved, 0 regressions.

---

### SC2.1 — Snapchat foundation

Goal: store Snapchat presence as creator enrichment only.

Tasks:
- Accept Snapchat handles/URLs where user-submitted
- Store Snapchat as `creator_platform_accounts` entry
- Add Snapchat filter placeholder in Creators UI
- `signal_weight = 0.0` — not included in market scoring

Production verification:
- Snapchat profile fields save correctly
- Snapchat signal weight remains 0.0 unless explicitly changed

---

### SC3.1 — Meta / Instagram foundation

Goal: add Meta/Instagram as creator identity and discovery layer before deeper ingestion.

Tasks:
- Accept Instagram/Facebook URLs in submit-source
- Extract Instagram/Facebook handles from known content
- Store platform accounts in `creator_platform_accounts`
- Add Instagram/Facebook filter in Creators UI
- Status = `pending_review` for discovered accounts
- `signal_weight = 0.5–0.8` depending on source_method — configurable

Production verification:
- Instagram/Facebook accounts can be linked to creators
- no market signal weight unless explicitly configured
- creator profile can show Meta presence

---

### SC-V1 — Optional creator claim / verified creator module

Goal: allow creators to voluntarily claim profiles. Built LAST, after SC1 + SC3 are working.

Tasks:
- Build claim profile flow
- Show profile preview before asking for account connection
- Add `claimed` / `verified` status
- Add creator-facing profile dashboard
- Add opt-out / disconnect language

Positioning:
> "Claim your FragranceIndex creator profile. Verify your fragrance influence. Get discovered by fragrance brands."

Conservative target: 10–20 verified creators within 6 months.

---

## 13. Success metrics

| Metric | Near-term target |
|--------|-----------------|
| TikTok creators seeded | 100–300 |
| Useful TikTok creator profiles within 90 days | 50+ |
| New TikTok creators discovered from cross-platform mentions | 30+ |
| Creator login dependency for baseline TikTok coverage | 0 |
| Claimed creators (conservative, within 6 months) | 10–20 |
| Creators with 5+ resolved fragrance mentions | grow from 689 |
| Creators with early signals (cross-platform) | grow from 106 |

---

## 14. Final principle

FragranceIndex.ai is a market intelligence system, not a social login product.

The platform must first prove that it can detect, rank, and explain creator-driven fragrance trends without asking creators to trust it.

Creator claim and platform login come later as optional trust and verification features.

```
Primary strategy:
  1. Detect public market signals
  2. Build creator intelligence
  3. Rank creators by usefulness
  4. Let creators claim profiles later
  5. Never make creator login a dependency for coverage
```
