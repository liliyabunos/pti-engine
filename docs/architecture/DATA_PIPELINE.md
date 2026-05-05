# Data Pipeline Architecture

Extracted from CLAUDE.md on 2026-05-05.

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


---

## O1-O3 Runtime and Deployment

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


---

## O6 — Deployment Target Rule

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


---

## O4 — Backup & Recovery Policy

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

