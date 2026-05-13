# IG1 — Instagram Public Signal Layer
# Architecture & Readiness Document

**Phase:** IG1 / IG1-R  
**Status:** APP REVIEW DEMO FLOW IMPLEMENTED — PRODUCTION ACCESS PENDING META BUSINESS VERIFICATION + APP REVIEW APPROVAL  
**Gate 0 Result (2026-05-13 update):** TEST CAPABILITY VERIFIED IN GRAPH API EXPLORER; production credentials pending App Review approval  
**Created:** 2026-05-13  
**Depends on:** M0, DATA0, PUB1 (all complete)  
**Next parallel track:** PUB2 (neither blocks the other)

---

## 1. Purpose of IG1

Add Instagram as the third official social signal source for FragranceIndex.ai. YouTube and Reddit are currently active. Instagram adds:

- Cross-platform trend corroboration (3-platform confidence vs 2-platform)
- Visual/aesthetic fragrance demand signals (gifting, unboxing, aesthetics categories)
- "Trending across 3 platforms" as evidence in future Deep Dive reports
- Brand-official content signals
- Historical data accumulation starting as early as possible (history is irreversible — every week delayed is permanently unrecoverable)

Signal accumulation begins on the first day of ingestion. There is no retroactive backfill for Instagram history.

---

## 2. Gate 0 Capability Verification Result

### Result: TEST CAPABILITY VERIFIED — Production access pending App Review

**Initial result (2026-05-13):** BLOCKED — no credentials in codebase environment.

**Updated result (2026-05-13 — founder manual verification):**

The founder verified the following directly in Meta Graph API Explorer:

| Check | Finding |
|-------|---------|
| Facebook Page → IG Business Account resolution | VERIFIED — Page ID `1141692112357701` → IG Business Account ID `17841426873066676` (username: `fragranceindex_ai`) |
| Hashtag Search endpoint | VERIFIED — `GET /ig_hashtag_search?user_id=17841426873066676&q=perfume` returned a valid hashtag ID |
| Recent Media endpoint | VERIFIED — `GET /{hashtag_id}/recent_media?user_id=...&fields=id,caption,timestamp,permalink,media_type,comments_count,like_count` returned real public media items with captions and metadata |
| Fields confirmed available | `id`, `caption`, `timestamp`, `permalink`, `media_type`, `comments_count`, `like_count` |
| Username in hashtag media response | NOT available (confirmed — Meta API design limitation) |
| Meta Business Verification | SUBMITTED — currently "In review" |
| App Review | BEING PREPARED — see `docs/ops/META_APP_REVIEW_INSTAGRAM_PUBLIC_CONTENT.md` |
| Production credentials in Railway | NOT YET SET — pending App Review approval |

**Security note:** A test access token was accidentally visible in a paging.next URL from Graph API Explorer during verification. That token must be rotated before any production use. Do NOT use that token.

**Gate 0 status:** TEST CAPABILITY VERIFIED. Production capability pending:
1. Meta Business Verification approval
2. Meta App Review approval for Instagram Public Content Access
3. Long-lived production token generated and set in Railway env

**Conclusion:** Hashtag Search and Recent Media work for our app in test access. The IG1 architecture is confirmed viable. Live ingestion blocked only on Meta approval process, not on technical viability.

---

## 3. Exact Meta API Capability Required for IG1

### IG1 requires: Instagram Graph API — Hashtag Search

This is a specific subset of the Instagram Graph API that enables trend monitoring by hashtag, not general media access or creator-specific data.

#### Capability map

| Capability | Required for IG1? | Notes |
|------------|-------------------|-------|
| Instagram Graph API — Hashtag Search (`/ig-hashtags`) | **YES — primary** | Resolves a hashtag text → IG Hashtag Object ID |
| Instagram Graph API — Hashtag Top Media (`/{hashtag-id}/top_media`) | **YES** | Returns top-performing posts for a hashtag |
| Instagram Graph API — Hashtag Recent Media (`/{hashtag-id}/recent_media`) | **YES** | Returns most recent posts for a hashtag |
| Instagram Basic Display API | **NO** | For end-user login/personal media access; not relevant |
| Instagram Graph API — Account media / profile | **NO** | For owned accounts; not the trend monitoring path |
| Facebook/Instagram OAuth for user login | **NO** | C2.2A / V1 creator consent flow; separate from IG1 |
| Instagram Creator/Business account insights | **NO** | For verified connected accounts; not hashtag monitoring |

### What IG1 does NOT use

- Creator OAuth / account linking (that is V1 / C3)
- Private account data
- Comment text (compliance boundary)
- Direct Messages
- Personal user profiles

### Why Hashtag Search specifically

The only compliant, scalable way to monitor public fragrance conversations on Instagram at the trend-intelligence level is via hashtag search. Following individual creator accounts would require OAuth grants per creator. Hashtag search allows monitoring the public conversation around topics (`#perfume`, `#fragrance`, `#nicheperfume`) without requiring individual creator consent — consistent with how we use YouTube search and Reddit subreddit monitoring.

---

## 4. Meta App Requirements — Exact Setup Needed

To get IG1 operational, the following must be true simultaneously:

### 4.1 Facebook Developer App

- A Meta (Facebook) Developer App must exist at developers.facebook.com
- App type: **Business** (not Consumer/Gaming)
- Instagram Graph API must be added as a product to the app
- App must be in **Live** mode (not Development mode) for production access beyond test users

### 4.2 Connected Instagram Business Account

- An Instagram account must be an **Instagram Business Account** or **Creator Account** (not Personal)
- This IG Business Account must be connected to a **Facebook Page**
- The Facebook Page must be linked to the Developer App

Hashtag Search endpoints require an `{ig-user-id}` parameter. This is the ID of a connected Instagram Business Account, not an arbitrary user. This account acts as the "querying account" for all hashtag lookups.

### 4.3 Access Token

- A **User Access Token** or **Page Access Token** with `instagram_basic` permission
- For long-lived access: exchange short-lived token for a **60-day long-lived token** via `GET /oauth/access_token?grant_type=fb_exchange_token`
- For production: implement **token refresh** before expiry or use a System User token from Meta Business Suite

The stored access token in `INSTAGRAM_ACCESS_TOKEN` env var should be a **long-lived Page/User token** with at minimum `instagram_basic` scope.

### 4.4 App Review / Permission Level

- Hashtag Search (`ig-hashtag-search`) is available at **Standard Access** level
- Standard Access (formerly Advanced Access) requires Meta App Review
- Development mode allows testing with approved testers only — NOT production-scale ingestion
- **App Review must be completed for production use**

---

## 5. Founder Action Required — Meta Verification Checklist

Before Gate 0 can pass, the founder must verify each item and provide the result:

```
[ ] 1. Meta Developer App exists at developers.facebook.com
       → App ID: _____________
       → App type: Business

[ ] 2. Instagram Graph API is added as a product to the app
       → Verify: App Dashboard → Add Product → Instagram Graph API present

[ ] 3. A connected Instagram Business/Creator account exists
       → IG Account username: _____________
       → IG Account type: Business / Creator (not Personal)
       → Connected to Facebook Page: YES / NO
       → IG User ID (numeric): _____________

[ ] 4. App is in Live mode (not Development mode)
       → App Status: Live / Development

[ ] 5. App Review status for instagram_basic permission
       → instagram_basic: Approved / Not submitted / Pending
       → Hashtag Search (ig-hashtag-search): Approved / Not submitted / Pending

[ ] 6. A valid long-lived access token exists
       → Token type: User Token / Page Token / System User Token
       → Expiry date: _____________
       → Scopes confirmed: instagram_basic (minimum)

[ ] 7. Live test from command line (run after completing above):
```

### Verification test command

Once credentials are available, run this exact test to confirm Gate 0 PASS:

```bash
# Step 1: Resolve hashtag ID
export IG_USER_ID="<your_ig_business_account_numeric_id>"
export IG_TOKEN="<your_long_lived_access_token>"
export HASHTAG="fragrance"

curl -s "https://graph.facebook.com/v21.0/ig_hashtag_search?user_id=${IG_USER_ID}&q=${HASHTAG}&fields=id&access_token=${IG_TOKEN}"
# Expected: {"data":[{"id":"<hashtag_id>"}]}

# Step 2: Fetch recent media for that hashtag
export HASHTAG_ID="<id_from_step_1>"
curl -s "https://graph.facebook.com/v21.0/${HASHTAG_ID}/recent_media?user_id=${IG_USER_ID}&fields=id,caption,timestamp,permalink,like_count,media_type&access_token=${IG_TOKEN}" | python3 -m json.tool | head -40
# Expected: {"data": [...media objects with caption, timestamp, permalink...]}
```

Record:
- Whether Step 1 returns a hashtag ID (not an error)
- Whether Step 2 returns media objects
- What fields are present in the media response
- Any `OAuthException`, `IGApiException`, or permission error text

Gate 0 = PASS only if both calls succeed with media data returned.

---

## 6. Hashtag Budget Architecture

### Constraint

Instagram Hashtag Search has a strict **30 unique hashtags per rolling 7-day window** per IG user per app. This is not per-request — it counts unique hashtag IDs resolved, not API calls made. Querying the same hashtag ID multiple times does not consume additional budget.

### Implication

- A naïve implementation that queries many new hashtags burns the weekly budget in minutes
- The hashtag universe must be curated, small, and stable
- Hashtag IDs (once resolved) should be cached and reused — do not re-resolve the same hashtag text daily
- New hashtags should only be introduced deliberately, not from code logic

### IG1 First-Wave Hashtag Plan (MVP — 6 hashtags)

These are proposed for the first production run. Selection rationale: high fragrance community signal, global usage, consistent with FTI source strategy.

| Hashtag | Rationale | Budget slot |
|---------|-----------|-------------|
| `perfume` | Broadest signal; highest volume | 1 |
| `fragrance` | Direct equivalent to YouTube search terms | 2 |
| `nicheperfume` | Niche community; strong signal/noise ratio | 3 |
| `fragrancecommunity` | Community anchor tag | 4 |
| `perfumereview` | Review-intent signal; aligns with resolver | 5 |
| `scentsoftheday` | SOTD = strong engagement + product mentions | 6 |

**Not included in IG1 MVP:**
- `perfumedupe` / `perfumedupe` — valid but adds volume without differentiation from first 6
- Brand-specific hashtags — save for future rotation
- `perfumetok` — TikTok-specific hashtag, lower Instagram signal
- Generic lifestyle tags — too noisy

**Remaining budget:** 24 of 30 slots reserved for future weeks / rotation.

### Hashtag Registry Design (config-first for MVP)

For IG1 MVP, a YAML config file is the right approach. DB migration is deferred until rotation logic or >20 hashtags are needed.

**File:** `configs/instagram/hashtag_registry.yaml`

```yaml
# IG1 Hashtag Budget Registry
# Max 30 unique hashtags per rolling 7-day window per IG user per app.
# Add new hashtags ONLY deliberately — each addition consumes weekly budget.

meta:
  window_days: 7
  max_unique_hashtags_per_window: 30
  ig1_reserved_slots: 6
  available_slots: 24

hashtags:
  - tag: perfume
    priority: tier_1
    active: true
    notes: "Broadest signal — query daily"

  - tag: fragrance
    priority: tier_1
    active: true
    notes: "Direct FTI source term match"

  - tag: nicheperfume
    priority: tier_1
    active: true
    notes: "Niche community; high quality signal"

  - tag: fragrancecommunity
    priority: tier_2
    active: true
    notes: "Community anchor"

  - tag: perfumereview
    priority: tier_2
    active: true
    notes: "Review-intent alignment with resolver"

  - tag: scentsoftheday
    priority: tier_2
    active: true
    notes: "SOTD engagement; strong product mentions"
```

The ingestion job reads only `active: true` hashtags. Operator adds new hashtags by editing this file — never from code logic. This prevents budget accidents.

**Hashtag ID cache:** Resolved hashtag IDs must be persisted so the same hashtag is not re-resolved on every run. Options:
- Small SQLite/Postgres table `instagram_hashtag_cache (tag TEXT PK, hashtag_id TEXT, resolved_at TIMESTAMPTZ)`
- Or stored in the job state file alongside run metadata

For IG1 MVP, a DB table `instagram_hashtag_cache` is cleaner and consistent with the existing Postgres-first policy.

---

## 7. Ingestion Flow

```
hashtag_registry.yaml (active=true hashtags)
    ↓
load_hashtag_ids_from_cache(db)
    ↓ (cache miss)
GET /ig_hashtag_search?q={tag} → store id in instagram_hashtag_cache
    ↓
for each hashtag_id:
    GET /{hashtag_id}/recent_media?fields=id,caption,timestamp,permalink,...
    ↓
normalize_instagram_item(raw_media) → canonical dict
    ↓
persist to canonical_content_items (source_platform='instagram')
    ↓ (idempotent — ON CONFLICT DO NOTHING on external_content_id)
multi_field_resolver → entity_mentions
    ↓
aggregate_daily_market_metrics (existing job — picks up instagram mentions)
```

### Job file

`scripts/ingest_instagram_public_content.py`

Pattern: matches `scripts/ingest_youtube_channels.py` style — standalone script, reads from env, uses DB session, logs structured counts, idempotent.

### Cadence

- **Not** run on every pipeline cycle initially — hashtag recent_media has its own cadence
- Morning pipeline: run once daily (sufficient — Instagram posts are visible for days)
- Evening pipeline: skip Instagram (avoid double-counting same-day posts)
- Manual run always supported: `python3 scripts/ingest_instagram_public_content.py --hashtag fragrance --limit 50`

---

## 8. Normalizer / Resolver Integration

### Normalizer

Add `normalize_instagram_item()` to `perfume_trend_sdk/normalizers/social_content/normalizer.py`.

**Field mapping from Instagram Hashtag Recent/Top Media response:**

| Instagram API field | Canonical field | Notes |
|--------------------|----------------|-------|
| `id` | `external_content_id` | IG media object ID |
| `caption` | `title` + `description` | Caption split at first newline for title; full text for description |
| `timestamp` | `published_at` | ISO8601 → datetime |
| `permalink` | `source_url` | Full post URL |
| `like_count` | `likes` | May be absent (optional field) |
| `media_type` | (metadata) | IMAGE / VIDEO / CAROUSEL — store for future use |
| `username` | **NOT AVAILABLE** | Hashtag media endpoints do NOT return username |
| channel/creator ID | **NOT AVAILABLE** | Same — no creator attribution from hashtag endpoints |

**Critical field limitation:** The Instagram Hashtag Search API does NOT return `username`, `owner`, or any stable creator identifier in the media response (unlike owned-account endpoints). This is a deliberate Meta API design decision. Creator attribution is NOT available from this path.

`source_platform = 'instagram'`

### Resolver integration

Instagram caption text → `normalize_instagram_item()` → resolver reads `title` + `description` fields.

Multi-field resolver `_get_platform_key()`: add `"instagram"` routing:
```python
if platform == "instagram":
    return "instagram"
```

Add to `PLATFORM_WEIGHTS`:
```python
"instagram": {
    "title": 1.0,       # First line of caption — highest signal
    "description": 0.7, # Full caption — very relevant on Instagram
    "hashtags": 0.8,    # Instagram hashtags are primary discovery mechanism
},
```

### Mention weight

Instagram platform mention weight: **0.8** (conservative initial value).

Rationale:
- YouTube weight baseline: 1.0 (most mature signal)
- Reddit weight: 1.0 (community signal, well-calibrated)
- Instagram: 0.8 — new platform, caption quality varies, no view-count quality scoring yet
- This is conservative per roadmap hypothesis; can be raised to 1.0 after signal quality is confirmed over 30-60 days
- Applied as `mention_weight_override=0.8` on Instagram content items (consistent with TikTok pattern)

---

## 9. Storage Model

### Tables touched (no migration needed for core flow)

| Table | Change | Notes |
|-------|--------|-------|
| `canonical_content_items` | `source_platform='instagram'` rows added | VARCHAR, no enum constraint — no migration |
| `entity_mentions` | `source_platform='instagram'` rows added | VARCHAR, no enum constraint — no migration |
| `instagram_hashtag_cache` | **NEW TABLE** | Required for hashtag ID caching — needs migration |

### New table: `instagram_hashtag_cache`

```sql
CREATE TABLE instagram_hashtag_cache (
    tag              VARCHAR(128) PRIMARY KEY,
    hashtag_id       VARCHAR(64)  NOT NULL,
    resolved_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_queried_at  TIMESTAMPTZ,
    query_count      INTEGER      NOT NULL DEFAULT 0
);
```

No Alembic migration number assigned yet — will be **migration 044** when IG1 goes live.

### public_safe_content_items view

Currently hardcoded:
```sql
WHERE cci.source_platform IN ('youtube', 'reddit')
```

Must be updated when IG1 goes live to include:
```sql
WHERE cci.source_platform IN ('youtube', 'reddit', 'instagram')
```

This is a view update (not a table migration) — can be done as part of migration 044 or as a standalone view refresh.

### aggregate_daily_market_metrics.py

The `_compute_mention_quality_score()` function currently returns `None` for non-YouTube/Reddit platforms. Instagram should eventually get its own quality formula (like_count-based), but for IG1 MVP, `None` is acceptable — it means no quality boost/penalty, which is conservative and safe.

---

## 10. Creator Attribution Limitations

### Hard constraint

The **Instagram Hashtag Search API does NOT return creator identity** for media items. Specifically:
- `username` field is NOT available in `/{hashtag-id}/recent_media` response
- `owner` field is NOT available
- `id` field (media ID) cannot be reliably traced to a creator account without additional API calls that would require per-creator scopes

### IG1 Position

IG1 stores Instagram content items **without creator attribution**. `source_account_handle` and `source_account_id` in `canonical_content_items` will be NULL for Instagram items.

Creator attribution for Instagram is deferred to a future phase (C3 / V1) that uses:
- Creator OAuth grants
- Brand-official account monitoring (separate scope)
- Creator-linked content via approved Instagram Graph API paths

### This is not a blocker for IG1

The primary value of IG1 is **entity-level trend signals from hashtag content**, not creator attribution. The resolver extracts entity mentions from caption text and creates `entity_mentions` rows. These flow into `entity_timeseries_daily` and signals. The attribution gap only affects:
- Creator leaderboard (no Instagram entries until C3)
- "Who drives it" section in future reports (will say "Instagram signal — creator attribution pending")

---

## 11. Pipeline Cadence

| Pipeline cycle | Instagram step | Rationale |
|---------------|---------------|-----------|
| Morning (11:00 UTC) | YES — run once | Daily hashtag scan sufficient |
| Evening (23:00 UTC) | NO | Avoid double-counting same-day posts |
| Manual | Supported always | `--hashtag`, `--limit`, `--dry-run` flags |

Pipeline health check: add Instagram item count to existing health check output after IG1 goes live.

---

## 12. Compliance / Public-Safe Boundary

### What IG1 stores

- Post caption (title/description) — used for resolver only, never displayed raw on public pages
- Post permalink — stored as `source_url`, not displayed on public entity pages (same as YouTube/Reddit)
- Timestamp, like_count (if available) — internal metadata
- No profile photos, no DM content, no private account data, no follower lists

### Public entity pages

Public perfume/brand pages (`/perfumes/[slug]`, `/brands/[slug]`) display only aggregated intelligence (score, trend_state, top_opportunity, differentiators, creator names). No raw Instagram content is ever surfaced publicly. Instagram items flow into the aggregation pipeline identically to YouTube/Reddit items, and only their aggregated signal output appears on public pages.

### Meta Platform Policy compliance

- Using only officially granted Instagram Graph API scopes
- Hashtag Search is explicitly permitted under the Instagram Graph API terms
- No scraping, no headless browser, no unofficial endpoints
- No raw comment text ingestion (comments endpoint not used)
- Caption text stored for internal resolver use only — not redistributed
- Consistent with existing compliance boundary documented in `config/public_export_policy.yaml`

### Instagram-specific usage constraints

- Hashtag content cannot be resold as a dataset
- Per Meta's developer terms, the content is used only for trend intelligence within the FTI platform
- No personal profile data is collected from the hashtag endpoint (username not available)
- This should be noted in `docs/ops/DATA_RETENTION_POLICY.md` when IG1 goes live

---

## 13. Known Limitations and Deferred Follow-ups

| Limitation | Deferred to |
|------------|------------|
| Creator attribution from Instagram | C3 / V1 (requires per-creator OAuth or brand account scope) |
| Like/engagement quality scoring | IG1 v2 (after signal quality data accumulates, ~30-60 days) |
| Hashtag rotation / budget expansion | IG1 v2 (after MVP hashtags validated) |
| Instagram Reels / Stories discovery | Future (different API scope; Stories are ephemeral — not suited for trend intelligence) |
| Instagram creator leaderboard entries | C3 (requires creator identity linkage) |
| Brand-official account monitoring | Future brand intelligence layer (separate from hashtag search) |
| Multi-region Instagram signals | Phase 045+ (Language & Region architecture) |
| public_safe_content_items view update | Migration 044 (when IG1 goes live) |
| Instagram comment text | Permanently deferred (compliance boundary) |

---

## 14. Files to Create When Gate 0 Passes

| File | Action |
|------|--------|
| `scripts/ingest_instagram_public_content.py` | CREATE |
| `perfume_trend_sdk/normalizers/social_content/normalizer.py` | ADD `normalize_instagram_item()` |
| `perfume_trend_sdk/resolvers/perfume_identity/multi_field_resolver.py` | ADD `"instagram"` to `PLATFORM_WEIGHTS` + `_get_platform_key()` |
| `configs/instagram/hashtag_registry.yaml` | CREATE |
| `alembic/versions/044_ig1_instagram_hashtag_cache.py` | CREATE (migration 044) |
| `tests/unit/test_ig1_instagram_ingestion.py` | CREATE |
| `start_pipeline.sh` | ADD Instagram ingest step to morning cycle |

---

## 15. Blockers Summary

| Blocker | Owner | Action |
|---------|-------|--------|
| Meta Developer App with Instagram Graph API | Founder | Create or confirm at developers.facebook.com |
| Instagram Business Account connected to Facebook Page | Founder | Convert IG account to Business/Creator type + connect to Page |
| App Review for instagram_basic / hashtag search | Founder | Submit Meta App Review; wait for approval |
| Long-lived access token | Founder | Generate after App Review approval; set `INSTAGRAM_ACCESS_TOKEN` in Railway env |
| Gate 0 live test | Founder + Claude | Run verification curl commands above after credentials ready |
