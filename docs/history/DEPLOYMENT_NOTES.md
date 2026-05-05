# Deployment Notes

Extracted from CLAUDE.md on 2026-05-05.

## O3 — Railway Production Service Map & Runtime Guards

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

## Phase D1.0 — Auth Stabilization

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


---

## Phase D1.1 — Custom Domain Migration

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

---

## O2 — Server Deployment & Soft Launch Layer

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

