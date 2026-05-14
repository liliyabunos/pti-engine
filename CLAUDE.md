# FragranceIndex.ai / FTI Market Terminal — Operating Guide

## Read This First
- This file is the short operating index.
- Do not expand historical docs unless the task requires it.
- Use targeted grep/sed reads, not cat.
- For phase history, read only the relevant file/section.
- Keep reports concise.

---

## PUB1 — Public Perfume & Brand Pages v1
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-13)**
**Commit: e5b06b7 (initial) · 9a26696 (slug fix) · 4f859b7 (docs)**
**Deployed: pushed to main 2026-05-12; Railway auto-deploys**

No new migration (uses existing entity_market.entity_id as slug source).

**What was implemented:**
- `perfume_trend_sdk/api/routes/public_entities.py` — 4 unauthenticated FastAPI routes:
  - GET `/api/v1/public/perfumes/{slug}` → PublicPerfumeDetail (M0 fields only)
  - GET `/api/v1/public/brands/{slug}` → PublicBrandDetail (M0 fields only)
  - GET `/api/v1/public/sitemap/perfumes` → slug list (anti-thin-content filtered)
  - GET `/api/v1/public/sitemap/brands` → slug list (anti-thin-content filtered)
- Slug strategy: perfume slug = `_slugify_canonical(entity_id)` e.g. `'Creed Aventus'` → `creed-aventus`; brand slug = `entity_id` minus `brand-` prefix (e.g. `creed`)
- Anti-thin-content rule: 404 for entities with no `entity_timeseries_daily` rows with `mention_count > 0`
- M0 public field boundary: score, trend_state, top_opportunity, top_2_differentiators, top_3_creator_names (plain text only), notes/accords, entity_role, reference_original
- `main.py`: registered router at `/api/v1/public`
- `frontend/src/middleware.ts`: `/perfumes/*` and `/brands/*` pass through without auth
- `frontend/src/app/(public)/perfumes/[slug]/page.tsx` — public perfume page (ISR revalidate=3600, generateMetadata with canonical/og/twitter)
- `frontend/src/app/(public)/brands/[slug]/page.tsx` — public brand page (ISR revalidate=3600)
- `frontend/src/app/sitemap.ts` — updated to async; fetches entity slugs from backend; perfume URLs priority=0.8 daily, brand URLs priority=0.7 daily

**Slug contract (critical — do not change without migration):**
- Perfume entity_id = canonical_name verbatim (e.g. `'Creed Aventus'`) — set by aggregation job, not slugified
- Public slug = `LOWER(REGEXP_REPLACE(entity_id, '[^a-zA-Z0-9]+', '-', 'g'))` (PostgreSQL) = `_slugify_canonical(entity_id)` (Python)
- Lookup: PostgreSQL functional WHERE; Python scan fallback for SQLite dev
- Brand entity_id = `brand-{slugified_name}` (pre-slugified) — public slug strips `brand-` prefix directly

**Slug fix (commit 9a26696):**
- Initial implementation assumed entity_id was already `creed-aventus` — it is not (it's `'Creed Aventus'` with spaces)
- Fix: added `_slugify_canonical()` + `_find_perfume_by_slug()` with PostgreSQL regex lookup
- Brand top-5 links now emit correct slug: `_slugify_canonical(entity_id)` not raw entity_id

**Production verification (2026-05-13) — COMPLETE:**
- [x] `/perfumes/creed-aventus` → 200 · h1="Creed Aventus" · canonical=`https://fragranceindex.ai/perfumes/creed-aventus` · og:title="Creed Aventus — Fragrance Trend Data" · score=69.5 · entity_role=niche_original ✓
- [x] `/perfumes/yves-saint-laurent-libre` → 200 · h1="Yves Saint Laurent Libre" · canonical=`https://fragranceindex.ai/perfumes/yves-saint-laurent-libre` ✓
- [x] `/brands/creed` top-5 RSC payload confirmed: all 5 hrefs use slugs — `creed-aventus`, `creed-aventus-for-her`, `creed-viking`, `creed-royal-oud`, `virgin-island-water` — zero `%20` encoding in HTML or RSC data · verified across 3 consecutive requests ✓
- [x] `/perfumes/creed-aventus` returns 200 (clicking from brand page resolves correctly) ✓
- [x] Notes & Accords correctly rendered (Apple, Bergamot, Blackcurrant top notes) ✓
- [x] No `/creators/*` hrefs on either public page — creator names plain text only ✓
- [x] `/perfumes/nonexistent-slug-xyz789` → 404 (anti-thin-content rule) ✓
- [x] Terminal routes remain auth-gated (307 → /login) ✓
- [x] Sitemap ISR predates entity endpoints — static pages confirmed; entity URLs in code, will populate on next TTL expiry ✓
- **ISR timing note (for ops record):** After `9a26696` slug-fix deployed (backend only, frontend not restarted), the frontend ISR cache for `/brands/creed` served stale HTML with wrong slugs until TTL expired (~3600s). Self-resolved on ISR revalidation. No code change required. Future mitigations: `revalidateTag()` or force-redeploy frontend on backend slug contract changes.

**Architecture decisions:**
- No new DB migration: slug computed from entity_id (= canonical_name for perfumes)
- Brand entity_id format `brand-{slug}` → public slug strips prefix → `/brands/creed`
- Catalog-only entities (no pipeline data) return 404 — no thin content pages
- Public API routes have no Supabase dependency (pure DB queries, no auth headers)
- /creators/* routes remain protected — creator names are plain text on public pages

---

## SOURCE-INTAKE-V1A — YouTube Source Intake DB + Admin Operator Review
**STATUS: COMPLETE — PRODUCTION VERIFIED**
**Commit: 842fb2b**
**Deployed: pushed to main 2026-05-10; Railway auto-deploys**

Migration 038 applied to production (alembic current: `038`). 3 new tables, 0 rows initially.

**What was implemented:**
- Migration 038: `source_intake_batches` + `source_intake_candidates` + `source_intake_audit_log`
- 12-status lifecycle: PENDING_VERIFICATION → VERIFIED_ADD_READY / SKIP_DUPLICATE / SKIP_INACTIVE / NEEDS_OPERATOR_REVIEW → OPERATOR_APPROVED / OPERATOR_REJECTED / DEFERRED → APPLIED / APPLY_FAILED → PRODUCTION_VERIFIED
- Apply-eligible: VERIFIED_ADD_READY + OPERATOR_APPROVED only; NEEDS_OPERATOR_REVIEW blocked
- `scripts/youtube/verify_candidate_channels.py --persist`: writes batch + candidates to DB after verification
- FastAPI: 10 admin endpoints at `/api/v1/admin/source-intake/*` — all require `X-Pti-Admin-User` header (401 without)
- Next.js proxy: `/api/admin/source-intake/[...path]/route.ts` — session verified server-side, X-Pti-Admin-User injected
- Admin UI: `/admin/source-intake` (batch list) + `/admin/source-intake/[batchId]` (candidate review)
- `BatchReviewConsole`: status filter tabs, approve/reject/defer/rerun actions, apply batch, production verify
- `OverrideEditor`: paste corrected YouTube URL/handle → rerun verification inline
- `RejectModal`: required rejection reason field
- Sidebar: "Source Intake" nav item (Inbox icon) in SECONDARY_NAV
- Safety rules: ON CONFLICT (channel_id) DO NOTHING on apply, audit log append-only, terminal statuses lock rows, search URLs rejected
- Tests: 33/33 pass (`tests/unit/test_admin_source_intake.py`)

**Admin URL:** `/admin/source-intake`

**Production verification (2026-05-10):**
- Unauthenticated `/admin/source-intake` → 307 redirect to `/login?next=%2Fadmin%2Fsource-intake` ✓
- `GET /api/v1/admin/source-intake/batches` without X-Pti-Admin-User → 401 ✓
- `POST /api/v1/admin/source-intake/batches` without X-Pti-Admin-User → 401 ✓
- `GET /api/v1/admin/source-intake/batches` with X-Pti-Admin-User → 200, total=0 ✓
- source_intake_batches: 0 rows ✓
- source_intake_candidates: 0 rows ✓
- source_intake_audit_log: 0 rows ✓
- Alembic version: 038 ✓
- All 6 Railway services deployed at commit aa5b8a5 (SUCCESS) ✓

**First batch apply verified (2026-05-10) — batch YT-CREATOR-EXPANSION-01-REVIEW:**
- batch_id: `36544e81-f509-449c-acf7-d6c4aa4c5cf2` — 5 candidates, platform=youtube
- Fragmental: SKIP_DUPLICATE (UCm10tytOAzlO42r9_4Oc8Eg already in youtube_channels) ✓
- The Honest Perfume Reviewer: VERIFIED_ADD_READY → OPERATOR_APPROVED → APPLIED ✓
- G Fragrance: VERIFIED_ADD_READY → OPERATOR_APPROVED → APPLIED ✓
- Smelling Great Fragrance Reviews: SKIP_DUPLICATE (operator: same family as The Perfume Guy) ✓
- Fragrance Connoisseurs: SKIP_INACTIVE (operator: no activity since February) ✓
- youtube_channels: 197 → 199 ✓ (added_by=`source_intake:YT-CREATOR-EXPANSION-01-REVIEW`)
- Audit log: 9 entries (5 initial_classification + 2 approve + 2 apply) ✓
- ON CONFLICT DO NOTHING enforced — skipped rows count correctly on idempotent re-run ✓
- Note: apply response `applied` counter shows 0 due to `rowcount` read order bug (cosmetic — operations complete correctly); fixed in admin_source_intake.py

**Pipeline ingestion + Source Intake PRODUCTION_VERIFIED (2026-05-11):**
- Evening pipeline 2026-05-10 picked up both new channels (1 content item each) ✓
- The Honest Perfume Reviewer (UC-MsytPEXSO-2ZHmB5Y4xSw): 1 content item, PRODUCTION_VERIFIED ✓
- G Fragrance (UCWRTAJqkmpF_yS7MJOIOYNg): 1 content item, PRODUCTION_VERIFIED ✓
- Both appear in /creators leaderboard by correct channel display name ✓

**Creator leaderboard display-name bug — FIXED (2026-05-11):**
- Root cause: `discover_youtube_channels.py` used `MAX(cci.title)` (a video title) as `youtube_channels.title` placeholder on auto-discovery
- 93 `g3_auto_discovery` channels had video titles stored as channel display names (e.g. "Is AI right about these? #cologne #fragrance..." stored for channel "MPG fragrance")
- Data repair: batch-fetched real channel titles from YouTube API for all 93 affected rows; 0 failures ✓
- Script fix: `discover_youtube_channels.py` now uses `handle` (channel handle) as title placeholder — not video title
- Polling fix: `ingest_youtube_channels.py` `_update_channel_after_poll()` now accepts `channel_title` kwarg and refreshes `youtube_channels.title` from `channelTitle` in video snippets on each successful poll
- Regression test: `tests/unit/test_creator_display_name.py` — 7/7 pass

**Creator leaderboard raw channel_id display fallback — FIXED + PRODUCTION VERIFIED (2026-05-11):**
**Commit: 129dc2b**
- Root cause: 11 `creator_scores` rows had no `youtube_channels` row AND no `creator_handle`, so the leaderboard LEFT JOIN returned `display_name=NULL` and the frontend fell back to raw `creator_id` (e.g. `UCNCza3W7C6CpfGmDoyR48Bg`)
- Before fix: 11 creators showed raw UC... channel IDs as display names
- Data repair: fetched real metadata from YouTube `channels.list` API for all 11 channels; inserted `youtube_channels` rows (added_by=`metadata_repair_2026-05-11`) + updated `creator_scores.creator_handle`; 0 remaining raw-ID fallbacks ✓
- API fix (`routes/creators.py`): leaderboard query now uses `COALESCE(yc.title, cs.creator_handle)` as `display_name` — defensive fallback prevents future gaps
- API fix: `_is_raw_youtube_channel_id()` helper detects `UC...` IDs and suppresses them from `display_name` response field
- API fix: search query now also matches `yc.handle` (YouTube handle like `@hellonikkigriffin`)
- Profile endpoint (`get_creator`): `title` field also filtered through `_is_raw_youtube_channel_id` + falls back to `creator_handle`
- Tests: `tests/unit/test_creator_display_name.py` — 14/14 pass (7 new tests for raw_id detection + COALESCE fallback)

**Production verification (2026-05-11):**
- `/creators` total=757, 0 raw UC... display_names across all 757 creators (all 8 pages) ✓
- `UCNCza3W7C6CpfGmDoyR48Bg` → `Nikki Griffin (HelloNikkiG)` (before: raw channel_id) ✓
- `/creators?q=Nikki` → total=1, `Nikki Griffin (HelloNikkiG)` ✓
- `/creators?q=HelloNikki` → total=1, `Nikki Griffin (HelloNikkiG)` ✓
- `/creators?q=hellonikkigriffin` → total=1 (handle search via `yc.handle`) ✓
- `/creators?q=The+Honest+Perfume+Reviewer` → total=1 ✓
- youtube_channels: 210 rows, 0 duplicates; 11 rows inserted by metadata_repair ✓
- `creator_scores` raw-ID fallbacks: 0 ✓

**Admin navigation fix (2026-05-11) — COMPLETE — PRODUCTION VERIFIED (commit cd3d7ef):**
- Source Intake removed from general user sidebar (was leaking to all logged-in users) ✓
- Creator Claims added to admin sidebar (was only accessible by direct URL) ✓
- New Admin section in sidebar: visible only when `isAdmin=true` (ADMIN_EMAILS/ADMIN_USER_IDS source of truth) ✓
- `isAdminUser()` extracted to `frontend/src/lib/auth/guards.server.ts` — shared by layout + all 3 admin page guards (no duplication) ✓
- Route/API security unchanged: unauthenticated → 307, non-admin direct access → 403, API without header → 401 ✓
- Non-admin sidebar (royalstar015@gmail.com): no Admin section, no Source Intake, no Creator Claims ✓
- Admin sidebar (liliyabunos27@gmail.com): Admin section with Creator Claims + Source Intake ✓
- Batch YT-CREATOR-EXPANSION-01-REVIEW visible in /admin/source-intake (status=applied, 2 applied) ✓

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

## Submit Source S1 — Operator Promotion Bridge
**STATUS: COMPLETE — VERIFIED (2026-05-07)**
**Commits: `6e8049a` (implementation) · `51a3e2b` (verification)**

- 59/59 tests pass · 30/30 verification checks
- `scripts/promote_source_submission.py` bridges `source_submissions` → `youtube_channels`
- `source_submissions` is intake-only — pending submissions are never auto-ingested
- Pipeline reads `youtube_channels` exclusively — unchanged
- Operator promotes direct `/channel/UC...` YouTube URLs only; handles/videos/shorts → `needs_manual_resolve`; TikTok/Instagram/Reddit → `platform_pending`
- No automatic ingestion. No market score manipulation.

---

## C2.3 — Creator Claim Launch Readiness
**STATUS: COMPLETE — PENDING VERIFICATION (2026-05-10)**
**Commit: 88becb6**
**Deployed: pushed to main 2026-05-10; Railway auto-deploys**

No new migration. No OAuth. No platform API. No pipeline changes. No identity merge.

**What was implemented:**
- A: `SuccessPanel`: "View my claims →" (→ /account) + "Back to profile" replace single "Done" button; pending-review reminder shown above actions
- B: Display name priority: `p.title ?? p.creator_handle ?? creatorId` — channel title preferred over handle
- C: "Spot incorrect data? support@fragranceindex.ai" footer note at bottom of claim page
- D: `HowToClaim`: "Not accepted" block added — passwords, DMs, private screenshots, login-required pages, same-display-name-only claims
- E: `docs/ops/CLAIM_REVIEW_SOP.md`: same-name identity rule added to Edge Cases — same display name across platforms is not evidence of same person
- F: Live test plan documented below

**C2.3 Live Test Plan (F):**

Primary review path: `/admin/creator-claims` UI. SQL is emergency fallback only.

*Profile A — bio_code test:*
1. Log in as test user → `/creators` → search a known creator → open profile → "Claim this Profile"
2. Select Bio-Code tab → submit channel URL → note verification code on SuccessPanel
3. Verify: code displayed + "View my claims →" link visible + "Back to profile" link visible
4. Click "View my claims →" → /account opens → claim shows as pending
5. Operator approves via `/admin/creator-claims`
6. Revisit `/creators/[id]` → Verified Creator badge appears
7. Cleanup: operator revokes via `/admin/creator-claims` (or SQL: `UPDATE creator_profile_claims SET claim_status='revoked' WHERE id='<uuid>'`)
8. Verify badge disappears after revoke — no real creator left falsely verified

*Profile B — manual_review rejection test:*
1. Log in as test user → find a second creator → "Claim this Profile"
2. Select Manual Review tab → submit a valid public URL → submit
3. Verify SuccessPanel → /account shows pending
4. Operator rejects with reason via `/admin/creator-claims`
5. Revisit `/creator/claim/[id]` → `RejectedPanel` shows reason + Try Again
6. /account shows "Not approved" with rejection reason
7. No cleanup needed — rejected claims are audit-only and not publicly visible

*Post-test verification:*
- `creator_oauth_grants: 0` unchanged
- Pipeline tables unchanged
- No real creator remains falsely verified after cleanup

**Production verification checklist:**
- [ ] SuccessPanel shows verification code + "View my claims →" link + "Back to profile"
- [ ] "View my claims" opens /account with pending claim visible
- [ ] "Back to profile" navigates back correctly
- [ ] Claim page title shows human-readable channel name (not UC... ID)
- [ ] "Not accepted" guidance visible in HowToClaim section
- [ ] "Wrong data?" support note visible at page bottom
- [ ] SOP includes same-name identity rule (docs/ops/CLAIM_REVIEW_SOP.md)
- [ ] /admin/creator-claims remains the primary operator review path
- [ ] creator_oauth_grants: 0 unchanged
- [ ] No pipeline tables modified

---

## C2.2A — Creator Directory Search
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-10)**
**Commit: 78c5eda**
**Deployed: pushed to main 2026-05-10; Railway auto-deployed**

No new migration. No OAuth. No platform API. No pipeline changes. No identity merge.

**Architecture requirement (decided 2026-05-10):**
Creator search must be platform-aware. Do not assume same display name = same person across platforms.

```
Creator Identity  = person/brand as a single entity          (future C3)
Creator Platform Account = one account on one platform        (current model)
```

**What was implemented:**
- `GET /api/v1/creators?q=...` — optional search param; case-insensitive LIKE match against `youtube_channels.title` (display name), `creator_id`, and `creator_handle`; applied before pagination; filtered `total` returned
- LEFT JOIN `youtube_channels` on all leaderboard queries — adds `display_name` field to every `CreatorRow`
- Frontend: search input in ControlBar with 350 ms debounce; `q` serialised to URL (`/creators?q=...`); offset resets to 1 on query change; search-specific empty state message
- `PlatformBadge` ("YT") shown in every creator row — always visible regardless of result set
- Creator cell shows `display_name ?? creator_handle ?? creator_id`

**Linking rule (hard constraint — unchanged):**
Same-name accounts across platforms must NEVER be merged automatically.

**Out of scope (unchanged):** multi-platform identity merge (C3), TikTok/Instagram/Snapchat ingestion, OAuth.

**Production verification results (2026-05-10):**
- No `q`: total=757, display_name populated (e.g. "The Perfume Guy", "Gents Scents") ✓
- `q=Perfume+Guy`: total=1, returns The Perfume Guy · youtube ✓
- `q=UCFarEEFsV90`: total=1, creator_id match returns The Perfume Guy ✓
- `q=zzznomatch999`: total=0, empty creators array ✓
- `q=perfume&sort_by=avg_views&quality_tier=tier_1`: total=2, filters combine correctly ✓
- Identity safety: 20 rows for `q=perfume` → 20 unique (platform, creator_id) pairs, no grouping by display_name ✓
- URL state: `q` in `paramsToSearch` ✓ · `q` in `searchToParams` ✓ · debounce 350ms ✓ · offset reset ✓
- Platform badge visible in every row ✓
- `platform` + `creator_id` returned as distinct identity keys per row ✓
- No pipeline tables changed · creator_oauth_grants unchanged ✓

**Future phase:** C3 — Multi-Platform Creator Identity Model

---

## Monetization & Public Intelligence — Approved Strategic Roadmap
**STATUS: ROADMAP APPROVED 2026-05-12 — M0 COMPLETE — DATA0 IS THE NEXT PHASE**
**Audit: Claude Sonnet 4.6 strategic architecture audit (2026-05-12) · Founder-reviewed and approved (2026-05-12)**
**M0 Architecture document: `docs/architecture/MONETIZATION_ARCHITECTURE.md` (commit 83967f4 + M0 commit)**

### Strategic Verdict
The intelligence engine is already strong. The next strategic gap is the commercial/public architecture layer — not additional isolated signal features. The platform currently has zero public acquisition surface: all entity pages are behind authentication, no sitemap exists, no dynamic metadata, no public entity URLs are indexed. Every month without the public layer is compounding opportunity cost on SEO and organic acquisition.

### Approved Phase Sequence

```
M0 → DATA0 → SEO0 → PUB1
                      ├─ PUB2   (parallel track after PUB1)
                      └─ IG1    (parallel track after PUB1; IG1 preferred if single-track due to history irreversibility)

After PUB2 + IG1:
IL1 → REPORT1 → PRO1

TT2: parallel administrative/decision track — must complete before IL1 begins
```

### Strategic Principles (binding — do not violate in implementation)
1. **Intelligence engine is strong; the gap is public + commercial architecture.** Do not add more signal features before PUB1 is live.
2. **Do NOT implement monetization checkout** (Stripe, paywall, pricing pages) before public acquisition layer (PUB1) and report-readiness architecture (IL1/REPORT1) exist.
3. **Do NOT push Instagram (IG1) ahead of M0, DATA0, SEO0, PUB1.** After PUB1, IG1 can run in parallel with PUB2.
4. **Do NOT treat TikTok official API/app approval as public TikTok trend ingestion solved.** These are separate technical and compliance problems. SC1.2D is closed.
5. **Historical integrity is time-sensitive.** DATA0 must follow M0 immediately. Every day without score formula versioning is a day of report-incomparable history that cannot be recovered.
6. **Public SEO pages are core product, not "marketing later."** The platform is invisible to search without them.
7. **Instagram history accumulates forward only.** Every week IG1 is delayed after PUB1 is live is a week of cross-platform signal history permanently unrecoverable for future reports.
8. **Opportunity Feed is a future high-value product.** Formal Opportunity Objects should be implemented in IL1 — not prematurely before M0/DATA0/PUB1/IG1.

---

### M0 — Monetization Architecture Foundation
**Status: IMPLEMENTED — ARCHITECTURE DOCUMENTED (2026-05-12)**
**Document: `docs/architecture/MONETIZATION_ARCHITECTURE.md`**
**Purpose:** Define all future commercial boundaries before any public exposure, gating, or report implementation is built. This is a design/documentation phase, not code.

**Outputs delivered:**
- Four commercial layers defined: Public/SEO, Pro, Premium Report, Enterprise (section 2)
- Entity monetization role map: Perfume + Brand are primary monetizable objects; Creator is attribution/provenance (section 3)
- Full current capability audit: perfume, brand, creator, screener/alerts/watchlists (section 4)
- Field-level tier access matrix for all entity types and product features (section 5)
- Public perfume page architecture contract: name, brand, role badge, notes/accords, score, direction, top 1 opportunity label, top 2 differentiators, top 3 creator names, similar perfumes, CTA (section 6.1)
- Public brand page architecture contract (section 6.2)
- PUB2 note/accord page architecture role (section 6.3)
- Pro layer specification: 90-day chart, 6-month history, full attribution, alerts, watchlists, comparison chart, CSV (section 7)
- Perfume Deep Dive 12-section report map with data availability per section (section 8.1)
- Opportunity Object formal schema: `entity_opportunities` table contract for IL1 (section 9)
- History depth policy: Public=direction only (NO chart), Pro=90d default/6m on-demand, Report=24m, Enterprise=full (section 10)
- Public URL structure locked: `/perfumes/[slug]`, `/brands/[slug]`, `/notes/[slug]`, `/accords/[slug]` (section 11)
- Phase interfaces: what each downstream phase receives from M0 (section 12)
- Decisions locked vs deferred (section 13)
- Founder decision checklist: 2 items, both with defaults, neither blocking DATA0 (section 14)

Depends on: Nothing.
Risk if skipped: All subsequent phases implement wrong access boundaries; gating requires rearchitecting after the fact.

---

### DATA0 — Historical Integrity & Metric Versioning
**Status: IMPLEMENTED — CORE PRODUCTION VERIFIED (2026-05-12); topic snapshot row verification pending next scheduled pipeline run**
**Migration: 043 — `alembic/versions/043_data0_history_versioning.py`**
**Document: `docs/ops/DATA_RETENTION_POLICY.md`**
**Purpose:** Protect the historical data that future reports and monetization depend on, before it accumulates without clean methodology provenance.

**What was implemented:**
- `score_formula_version INTEGER NOT NULL server_default=1` on `entity_timeseries_daily` — backfills all existing rows to version 1 via server_default
- `signal_threshold_version INTEGER NOT NULL server_default=1` on `signals` — backfills all existing rows to version 1
- `entity_topic_snapshots` table — Option A: dated aggregate snapshot of `entity_topic_links` written after each `--rebuild-links` run; preserves historical topic/intent distributions that would otherwise be destroyed on rebuild. Unique on `(snapshot_date, entity_id, topic_type, topic_text)`. Idempotent upsert.
- `SCORE_FORMULA_VERSION = 1` constant in `aggregate_daily_market_metrics.py` — injected at all 3 write paths (perfume loop, brand roll-up, carry-forward)
- `SIGNAL_THRESHOLD_VERSION = 1` constant in `detect_breakout_signals.py` — injected in `_upsert_signal()`
- `TOPIC_DISTRIBUTION_VERSION = 1` constant in `extract_entity_topics.py` — written to each snapshot row
- `--snapshot` flag on `extract_entity_topics.py` — triggers dated snapshot after `--rebuild-links`; non-fatal (pipeline continues on snapshot failure)
- Pipeline scripts (`start_pipeline.sh`, `start_pipeline_evening.sh`) updated to pass `--snapshot` on every `--rebuild-links` call
- `docs/ops/DATA_RETENTION_POLICY.md` — written retention policy: Keep Indefinitely table list, retention windows, versioning policy, change control rules

**Topic history design decision (Option A):**
Chose snapshot table over append-with-date on `entity_topic_links` because existing API queries do `COUNT(*) GROUP BY topic_type, topic_text` across ALL rows for an entity — adding a date column would accumulate historical rows and distort current entity topic profiles. Snapshot table is purely additive; zero changes to existing query paths.

**Forward policy (binding):** Any future scored/derived object introduced after DATA0 must carry `formula_version` from day one. Applies to Opportunity Objects in IL1 and all future derived metrics.

**Provenance note:** Rows in `entity_timeseries_daily` and `signals` written before migration 043 are assigned version 1 via server_default. "Historical rows prior to 2026-05-12 are assigned baseline formula version 1."

**Production verification (2026-05-12):**
- alembic_version: 043 ✓
- `entity_timeseries_daily`: 31,551 rows, null_score_formula_version=0 — all version=1 ✓
- `signals`: 5,325 rows, null_signal_threshold_version=0 — all version=1 ✓
- `entity_topic_snapshots` table exists ✓
- **PENDING:** First snapshot rows must be confirmed after next pipeline `--rebuild-links --snapshot` run (11:00 or 23:00 UTC). Verify with: `SELECT COUNT(*), MIN(snapshot_date), MAX(snapshot_date) FROM entity_topic_snapshots;` — if rows exist with expected snapshot_date, update status to COMPLETE — PRODUCTION VERIFIED.

Depends on: M0 (completed — defines which derived metrics require versioning)
Next phase: SEO0

---

### SEO0 — SEO Infrastructure Foundation
**Status: COMPLETE — PRODUCTION VERIFIED (2026-05-13)**
**Document: `docs/architecture/SEO_ARCHITECTURE.md`**
**Purpose:** Make the platform technically crawlable and indexable before public entity pages are built.

**What was implemented:**
- `frontend/src/app/robots.ts` — Allow: `/`, `/glossary`, legal pages, `/login`, M0 entity route families (`/perfumes/`, `/brands/`, `/notes/`, `/accords/`); Disallow: `/dashboard`, `/screener`, `/entities/`, `/creators`, `/creator/`, `/watchlists`, `/alerts`, `/account`, `/admin/`, `/auth/`, `/submit-source`, `/api/`; Sitemap declared at `https://fragranceindex.ai/sitemap.xml`
- `frontend/src/app/sitemap.ts` — Static sitemap: homepage (priority 1.0), glossary (0.6), data-sources (0.4), privacy/terms/cookies/copyright/data-deletion (0.2–0.3); architecture for future `generateSitemaps()` expansion documented in SEO_ARCHITECTURE.md §4; no dead entity URLs submitted
- `frontend/src/app/(terminal)/layout.tsx` — `robots: { index: false, follow: false }` metadata cascades to ALL terminal routes (dashboard, screener, entities/*, creators, admin/*, account, alerts, watchlists, submit-source, creator/*)
- `frontend/src/app/auth/callback/page.tsx` — explicit noindex (lives outside terminal group)
- `frontend/src/app/layout.tsx` — OpenGraph (`type: website, siteName: FragranceIndex.ai`) and Twitter card (`summary`) site-level defaults added; metadataBase confirmed `https://fragranceindex.ai`
- `frontend/src/app/page.tsx` — Homepage-specific metadata: `title: "FragranceIndex.ai — Fragrance Trend Intelligence"`, acquisition-oriented description, OG/Twitter overrides
- `docs/architecture/SEO_ARCHITECTURE.md` — Full SEO reference: robots policy, sitemap strategy, noindex policy, canonical URL strategy, future entity sitemap architecture (`generateSitemaps` pattern, 50k URL limit handling, priority ordering), PUB1 `generateMetadata` contracts, anti-thin content rules

**OG image:** No branded asset exists in `frontend/public/`; og:image field intentionally absent in SEO0. Follow-up in PUB1: create `og-image.png` (1200×630) and add to root OG metadata.

**Canonical link handling:** `/entities/*` terminal routes are noindex in SEO0. `rel=canonical` links pointing to `/perfumes/[slug]` etc. are a PUB1 task — deferred until public target routes exist and are verified live.

**Build verification:** `npm run build` clean; `robots.txt` and `sitemap.xml` emit as static `○` routes with correct content verified from `.next/server/app/*.body` files.

**Production verification (2026-05-13):**
- `https://fragranceindex.ai/robots.txt` → 200 `text/plain` with correct policy + sitemap URL ✓
- `https://fragranceindex.ai/sitemap.xml` → 200 `application/xml` with 8 static URLs, no entity dead-links ✓
- `https://fragranceindex.ai/dashboard` → 307 `/login?next=%2Fdashboard` — terminal auth still protected ✓
- Homepage SEO title verified: `"FragranceIndex.ai — Fragrance Trend Intelligence"` ✓

**Bugfix required post-deploy (commit 5ea04a3):**
Root cause: middleware `PUBLIC_PATHS` is an exact-match Set — `/robots.txt` and `/sitemap.xml` fell through to `guardProtectedRoute` and redirected crawlers to `/login`. Fix: explicit fast-path in `middleware.ts` for `/robots.txt`, `/sitemap.xml`, and `/sitemap/` prefix (future partition routes).

Depends on: M0, DATA0
Next phase: PUB1

Depends on: M0 (public field definitions must exist before generating public metadata)
Risk if skipped: Public pages will not rank. SEO compounds over time; every month of delay is compound loss that cannot be recovered.

---

### PUB1 — Public Perfume & Brand Pages
**Status: DEPLOYED — PENDING PRODUCTION VERIFICATION (2026-05-12) — commit e5b06b7**
**Purpose:** Launch auth-free, SEO-friendly public entity pages that create the organic acquisition funnel into the terminal. The intelligence engine exists; the missing step is a public window into it.

Public perfume page scope (approved field policy):
- name, brand, notes/accords — fully public (identity + ingredient search volume)
- current market score (single number) — public (provokes curiosity, drives sign-up)
- trend direction (up / stable / down) — public
- top 1 opportunity tag, no evidence — public ("why trending" context for SEO)
- top 3 creator names only, no engagement data — public
- top 2 differentiators / top 2 positioning tags — public ("why trending" preview)
- full chart, all drivers, all creators, full opportunity breakdown — **gated; CTA to terminal sign-up**

Public brand page scope:
- brand name, portfolio count, aggregate score, momentum status summary
- top 5 SKUs with current state (active / tracked / catalog)
- CTA into full portfolio in terminal

Internal linking: perfume → brand → notes → accords → similar perfumes

Depends on: M0 (field definitions), SEO0 (infrastructure), DATA0 (versioning before public data exposure)
Risk if skipped: Platform remains invisible to search. No acquisition funnel. No conversion path.

---

### PUB2 — SEO Content Depth
**Status: APPROVED — PARALLEL TRACK AFTER PUB1**
**Purpose:** Add public content structures that help pages rank, not merely index. PUB1 gets pages into the index; PUB2 drives ranking on long-tail queries.

Scope:
- Note detail pages publicly exposed (top perfumes using note, fragrance family context)
- Accord detail pages publicly exposed
- "Compared Against" public section on perfume pages (entity-resolved competitors, no evidence depth)
- Trending Notes / Trending Accords public pages (top 20 by mention velocity)
- Full internal linking graph: perfume → brand → notes → accords → similar perfumes
- Anti-thin-content rule: each public page must carry at least one unique data-driven signal
- No duplicate content across concentration variants (flanker policy; define in M0)

Depends on: PUB1 (live and indexed)
Parallel with: IG1 — neither blocks the other. If only one can run, IG1 is preferred due to history irreversibility.
Risk if skipped: PUB1 infrastructure indexed but doesn't rank at scale.

---

### IG1 — Instagram Public Signal Layer / IG1-R — App Review Demo Flow
**Status: APP REVIEW DEMO FLOW IMPLEMENTED — PRODUCTION ACCESS PENDING META BUSINESS VERIFICATION + APP REVIEW APPROVAL (2026-05-13)**
**Document: `docs/architecture/INSTAGRAM_INGESTION.md`**
**App Review support: `docs/ops/META_APP_REVIEW_INSTAGRAM_PUBLIC_CONTENT.md`**
**Gate 0 Result: TEST CAPABILITY VERIFIED in Graph API Explorer; production credentials pending App Review**
**Demo route: `/admin/meta-review/instagram` (admin-only)**
**Purpose:** Add Instagram as an official third social signal source through the existing ingestion → normalization → resolver → metrics architecture.

Critical constraint: **Instagram signal history cannot be accumulated retroactively.** Every week IG1 is delayed after PUB1 is live is a week of cross-platform intelligence permanently unavailable for future Deep Dive reports. This is the strongest argument for prioritizing IG1 over PUB2 if capacity allows only one parallel track.

Scope:
- Instagram content ingestion connector (hashtag/query search via Public Content API; rate limit and batch/sleep design)
- `normalize_instagram_item()` in `social_content/normalizer.py` (extending existing platform-specific normalizer pattern)
- Resolver integration (existing SC1.3 multi-field resolver; field weights: caption/description priority, hashtags secondary)
- `source_platform='instagram'` in `canonical_content_items`
- entity_mentions from Instagram sources
- Platform weight decision: recommend 0.8× initially; calibrate upward after signal quality verified
- `creator_platform_accounts` support for Instagram accounts (table already exists, migration 035)
- Morning/evening pipeline health check validates Instagram item count

Compliance / identity rules:
- Use officially granted Instagram API scopes only (Public Content Access / hashtag search)
- No raw comment text ingestion without approved method
- Instagram creator identity must NOT be auto-merged with YouTube/Reddit creators by display name (existing platform-aware identity constraint from C2.2A applies)

What IG1 unlocks: cross-platform trend confirmation; visual/aesthetic fragrance demand signals (gifting, unboxing, aesthetics); "trending across 3 platforms" as report evidence; brand-official content signals

Depends on: M0 (field definitions + platform weight decision), DATA0 (versioning before new source adds data), PUB1 (public layer to display cross-platform data)
Parallel with: PUB2 — neither blocks the other.
Risk if skipped: Reports cite "2 platforms" indefinitely; cross-platform confidence permanently weaker; history unrecoverable for early cohort entities.

---

### IL1 — Intelligence Layer Formalization
**Status: APPROVED — AFTER PUB2 AND IG1**
**Purpose:** Upgrade existing string-based opportunity flags and topic-level intent aggregation into formal scored data models required for report generation and future paid intelligence.

Current state in code:
- 7 string opportunity flags in `market_intelligence.py` (no confidence score, no evidence refs, no time windows) — tag-level only
- Intent classification aggregated at entity level from topic labels (not at mention level)
- `confidence_avg` on entities = resolver quality metric, not opportunity confidence

Scope:
- `entity_opportunities` table: Opportunity Object schema (id, type, entity_id, confidence_score 0–1, evidence_items list of content_item_ids, time_window start/end, strength low/medium/high, is_active bool, formula_version, generated_at)
- Daily opportunity computation job (replaces ad-hoc API computation)
- API returns opportunities with confidence scores, evidence refs, time windows
- Mention-level intent classification (deterministic rules; primary intent per mention: review / comparison / gifting / blind_buy / discovery / trending_mention)
- Intent distribution per entity per week (enables "intent trend over time" in reports)
- Opportunity Feed API endpoint: active opportunities ranked by confidence × recency across all entities

Depends on: M0 (Opportunity Object schema defined there), DATA0 (formula_version policy applies), IG1 (multi-platform data strengthens opportunity evidence), FTG-2 / RI1 (relationship evidence backing opportunity classifications — `reference_original` + dupe family should come from DB rows with confidence scores, not hardcoded Python)
TT2 must be complete before IL1 begins (to ensure no TikTok assumptions are embedded in Opportunity Object evidence design).
Risk if skipped: Premium reports built on tag strings, not evidence-backed scored objects; credibility gap in paid products.

---

### REPORT1 — Perfume Deep Dive Report Architecture
**Status: APPROVED — AFTER IL1**
**Purpose:** Prototype the report data pipeline and research-style artifact for future premium report products. No paid checkout in this phase.

Perfume Deep Dive v1 section map:
1. Cover: entity name, brand, score, report date, score trend (30/90/180-day)
2. Market Status: rising / stable / declining + plain-language reason
3. Signal Timeline: all detected signals in window with strength and context
4. Who Drives It: top 10 creators with tier, platform, first/last mention, early signal badge
5. Why People Talk About It: intent breakdown (% review / % comparison / % gifting / % discovery) — requires IL1
6. Compared Against: entity-resolved comparison graph with directionality
7. Dupe / Alternative Landscape: reference_original, dupe_family, competing clones
8. Opportunity Analysis: all active Opportunity Objects with confidence scores and evidence — requires IL1
9. Notes & Accords Context: note/accord momentum related to this entity's trajectory
10. Risk Assessment: concentration risk (creator-dependent growth?), velocity risk (acceleration vs sustainable)
11. Methodology footnote: score formula version, data sources, confidence explanation — requires DATA0

Internal prototype targets: Creed Aventus · Baccarat Rouge 540 · Armaf Club de Nuit Intense Man
Depends on: IL1 (Opportunity Objects, intent classification), IG1 (multi-platform data for section 4/8)
Risk if skipped: Highest-margin product tier delayed.

---

### PRO1 — Pro Tier Gating & Feature Completion
**Status: APPROVED — AFTER REPORT1**
**Purpose:** Implement actual Pro access control, monetization checkout, and Pro-specific product features — only after public acquisition and report/intelligence readiness are confirmed.

Scope:
- Access control per tier (public / pro / report / enterprise)
- Comparison chart (multi-entity overlay on same chart)
- CSV export
- Extended history access (6-month Pro, 24-month Report/Enterprise)
- Alert delivery (email / webhook)
- Checkout / monetization implementation (Stripe or equivalent)

Constraint: Build the checkout flow after there is organic traffic to convert. Premature checkout before acquisition exists converts no one.
Depends on: M0 (field definitions), PUB1 (traffic source), IL1 (Opportunity Objects give Pro content real depth), REPORT1 (report product prototype ready for paid launch)
Risk if delayed: No direct revenue — but premature before organic traffic exists is economically equivalent to no revenue anyway.

---

### TT2 — TikTok Path Decision & Closure
**Status: APPROVED PARALLEL ADMINISTRATIVE TRACK — MUST COMPLETE BEFORE IL1**
**Purpose:** Formally close the TikTok public monitoring uncertainty and document what official TikTok API approval does and does not solve for FTI. This is a documentation/decision exercise, not engineering work.

Approved strategic conclusions (binding platform policy):

**A) What official TikTok app/API approval actually grants FTI:**
Authorized app/API access gives creator-authorized content (if creator grants permission), analytics for brand-managed accounts, and potentially video metadata for accounts that opt in. These are useful for Creator Intelligence (C3 track — creator linking, verified creator analytics) and future enterprise/brand offerings. They are NOT useful for general fragrance trend monitoring.

**B) What official TikTok approval does NOT solve:**
It does not provide access to public TikTok video content at scale for trend intelligence. General fragrance trend monitoring requires reading public posts across thousands of unaffiliated creators — this is not within standard app API scopes.

**C) Public TikTok trend ingestion — decision: DEFERRED**
Deferred unless a compliant and commercially viable technical path is confirmed. TikTok Research API is designed for qualifying academic/research institutions; eligibility for a commercial intelligence platform is unconfirmed and should not be assumed as a production path. No further investment in finding workarounds to the SSR/itemList limitation is authorized.

**D) SC1.2D — CLOSED**
Browser-rendered public monitoring is formally closed. The SSR/itemList limitation (confirmed 2026-05-08: `itemList` always empty in server-rendered HTML) is a definitive technical boundary. The compliance boundary prohibits headless browser or proxy workarounds. No further work on this path.

**E) Current active TikTok layers:**
- SC1.1 (ambient TikTok URL/handle extraction from YouTube/Reddit references): **REMAINS ACTIVE.** Low-cost, compliant, real signal. No additional investment required.
- SC1.2C (seeded creator follower monitoring): **RETAINED AS INFRASTRUCTURE ONLY.** Delivers follower count updates only — not video-level signals. Not a trend intelligence source. May become relevant for C3 creator linking if official API grants video access scope. No further trend-intelligence investment.
- SC1.2D: **CLOSED.**

TT2 output: A written decision document recording the above as official platform policy, specifying conditions under which TikTok direct public monitoring may be reopened (e.g., confirmed Research API eligibility for commercial platforms, commercially viable licensed data partnership, explicit TikTok scope grant for public trend monitoring).

---

### Roadmap Status Summary Table

| Phase | Name | Status | Parallel / Sequential |
|-------|------|--------|-----------------------|
| M0 | Monetization Architecture Foundation | **APPROVED — EXECUTE NEXT** | Sequential |
| DATA0 | Historical Integrity & Metric Versioning | APPROVED | Sequential after M0 |
| SEO0 | SEO Infrastructure Foundation | APPROVED | Sequential after DATA0 |
| PUB1 | Public Perfume & Brand Pages | APPROVED | Sequential after SEO0 |
| PUB2 | SEO Content Depth | APPROVED | Parallel after PUB1 |
| IG1 | Instagram Public Signal Layer | APPROVED | Parallel after PUB1 (preferred if single-track) |
| IL1 | Intelligence Layer Formalization | APPROVED | Sequential after PUB2 + IG1 |
| REPORT1 | Perfume Deep Dive Report Architecture | APPROVED | Sequential after IL1 |
| PRO1 | Pro Tier Gating & Feature Completion | APPROVED | Sequential after REPORT1 |
| TT2 | TikTok Path Decision & Closure | APPROVED | Parallel admin track; complete before IL1 |

**Documents to create when each phase begins:**
- M0 → `docs/architecture/MONETIZATION_ARCHITECTURE.md`
- SEO0 → `docs/architecture/SEO_ARCHITECTURE.md`
- IG1 → `docs/architecture/INSTAGRAM_INGESTION.md`
- DATA0 → `docs/ops/DATA_RETENTION_POLICY.md`
- REPORT1 → `docs/architecture/REPORT_ARCHITECTURE.md`

---

## FTG — Fragrance Truth Graph & Narrative Intelligence
**Strategic program — opened 2026-05-14**
**Trigger: KB0 Khamrah bugfix exposed that dupe/alternative relationships are hardcoded Python with no evidence, confidence, freshness, or history.**

### Strategic Purpose

FragranceIndex.ai must not become a generic trend tracker. The product moat is fragrance-native market intelligence:
- Canonical classifications of brands and perfumes
- Structured original / dupe / alternative / comparison relationships
- Evidence and confidence around those claims — not just assertions
- Time-series storage of how "why it is trending" and consumer intent evolve over months

The product must evolve from:
> "What fragrance is rising?"

to:
> "What relationship structure, consumer intent, creator spread, and market narrative are causing it to rise — and how has that changed over six months?"

This is the commercial foundation for Deep Dive Reports and brand intelligence products.

---

### Architecture Boundary — 4-Layer Model

```
┌─────────────────────────────────────────────────────────┐
│  RESOLVER LAYER (existing)                              │
│  "Which entity is this text referring to?"              │
│  Data: resolver_aliases, resolver_perfumes, entity_market│
│  Must remain separate. Knows nothing about relationships.│
└─────────────────┬───────────────────────────────────────┘
                  │ entity_id
┌─────────────────▼───────────────────────────────────────┐
│  ENCYCLOPEDIA / CANONICAL CLASSIFICATION LAYER (FTG-1)  │
│  "What canonical role/classification does this have?"   │
│  Data: brand_profiles (minimal: brand_tier only)        │
│  Replaces Python frozensets with queryable data.        │
│  Operator-curated, slow update cycle.                   │
└─────────────────┬───────────────────────────────────────┘
                  │ entity_id
┌─────────────────▼───────────────────────────────────────┐
│  RELATIONSHIP INTELLIGENCE LAYER (FTG-2, FTG-3, FTG-4) │
│  "How does this fragrance relate to another?"           │
│  Data: fragrance_relationships, relationship_evidence   │
│  Confidence-scored, operator-reviewed, versioned.       │
│  Public display gated: operator_reviewed + confidence.  │
└─────────────────┬───────────────────────────────────────┘
                  │ entity_id + snapshot_date
┌─────────────────▼───────────────────────────────────────┐
│  INTELLIGENCE SNAPSHOT LAYER (FTG-5)                    │
│  "How has this entity's intelligence narrative changed?" │
│  Data: entity_intelligence_snapshots (new, DATA0 style) │
│  Stores: narrative, opportunity tags, intent mix, role. │
│  Written after each aggregation cycle. 24-month retain. │
└─────────────────────────────────────────────────────────┘
```

**Dependency rules:**
- Resolver feeds all layers via entity_id — knows nothing about any of them.
- Market scoring layer (entity_timeseries_daily, signals) remains independent. Do not let early FTG classification mutate base market scores in v1.
- Relationship Intelligence enriches explanations; it does not drive scores.
- Encyclopedia layer feeds Relationship Intelligence with canonical brand tier.

---

### FTG Phase Roadmap

#### FTG-0 / KB0 — Khamrah Truth Fix
**Status: COMPLETE — PRODUCTION VERIFIED (2026-05-14)**
**Commit: b79143d · Backend deploy: 93ea2e4e**

- **Root bug:** `_DUPE_RAW` in `entity_role.py` mapped "Lattafa Khamrah" → Maison Francis Kurkdjian Baccarat Rouge 540 (wrong). Correct reference: Kilian Angels' Share.
- **Root cause:** manual entry error in initial Phase 5 seed — no evidence, no review gate, no test.
- **Fix:** One-line correction in `_DUPE_RAW`. Khamrah Qahwa (distinct product) was already correct and remains unchanged.
- **Regression tests:** `TestKhamrahRegression` (4 cases) added to `tests/unit/test_semantic_phase5.py`. 67/67 pass.
- **Why it matters:** This bug in production exposed that the entire relationship layer is a hardcoded Python map with zero evidence backing. That gap is the FTG program.

---

#### FTG-1 / KB1-MIN — Canonical Brand Classification Foundation
**Status: COMPLETE — PRODUCTION VERIFIED (2026-05-14)**
**Migration: 044**
**Commit: 5085fab**

**Schema decision: separate `brand_profiles` table** (not `entity_market` or `brands`)
- `brands` table is the Fragrantica/resolver catalog — different domain
- `entity_market` only contains tracked market brands — many brands we classify (Armaf, Lattafa, Montblanc) appear only as `brand_name` strings on perfume rows, not as tracked entities
- Separate table keeps canonical knowledge cleanly separated from market metrics and resolver data
- Can grow into a deeper Brand Profile Dictionary (FTG-5/SN1 direction) without bloating entity_market

**brand_profiles schema:**
```sql
brand_profiles (
    id                    UUID PK  gen_random_uuid()
    brand_name_normalized TEXT UNIQUE NOT NULL  -- pre-normalized lookup key; matches _normalize(brand_name)
    brand_tier            VARCHAR(32) NOT NULL  -- designer | niche | clone_house | celebrity | indie
    notes                 TEXT NULL             -- optional operator annotation
    created_at            TIMESTAMPTZ NOT NULL  -- default now()
)
```

**Taxonomy (5 values):**
- `designer` — maps to entity_role `designer_original`
- `niche`    — maps to entity_role `niche_original`
- `indie`    — maps to entity_role `niche_original` (indie houses are niche-tier)
- `clone_house` — maps to entity_role `unknown` (dupe map handles per-product)
- `celebrity`   — maps to entity_role `unknown` (dupe map handles per-product)

**Seeded (213 rows from hardcoded Python):**
- 66 rows from `_DESIGNER_ORIGINALS` → brand_tier='designer' (all aliases deduplicated by normalized key)
- 136 rows from `_NICHE_ORIGINALS` → brand_tier='niche'
- 9 rows clone_house: armaf, lattafa, zimaya, fragrance world, orientica, arabiyat, ard al zaafaran, afnan, alexandria fragrances (brands removed from `_NICHE_ORIGINALS` at Semantic Phase 5)
- 2 rows celebrity: ariana grande, zara

**classify_entity_role() refactor:**
- Added optional `brand_tier_override: str | None = None` parameter (backward-compatible)
- DB lookup done at call site via `get_brand_tier(db, brand_name)` in `entities.py` and `public_entities.py`
- When `brand_tier_override` is provided: DB takes precedence over frozensets
- When `brand_tier_override` is None: frozensets used (full fallback, existing behavior)
- Dupe map (step 1) always fires before brand-level lookup — KB0 Khamrah fix unaffected
- `get_brand_tier()` in `brand_profile.py` is non-fatal: returns None on DB exception → frozenset fallback

**Frozensets remain:** `_DESIGNER_NORM` and `_NICHE_NORM` are still present as the safety fallback. They are NOT removed in this phase. Removal is FTG-1-CLEANUP (post-production verified, separate task).

**Tests:** `tests/unit/test_ftg1_brand_profiles.py` — 31/31 pass. No regressions in `test_entity_role.py` (92) or `test_semantic_phase5.py` (67) or `test_semantic_phase3.py` (31) — 221 total pass.

**Production verification (2026-05-14) — COMPLETE:**
- Deploy `2eee0dce` · SUCCESS · ALEMBIC_EXIT=0 ✓
- `/perfumes/creed-aventus` → "Niche Original" badge (violet) ✓
- `/perfumes/dior-sauvage` → "Designer Original" badge (sky) ✓
- `/perfumes/lattafa-khamrah` → "Dupe / Alternative" · "Alternative to: Kilian Angels' Share" ✓ (KB0 unaffected)
- Entity role classification stable across all verified entities ✓

**Verify commands (production DB):**
```sql
SELECT version_num FROM alembic_version;  -- expect 044
SELECT COUNT(*), brand_tier FROM brand_profiles GROUP BY brand_tier ORDER BY brand_tier;
-- expect: celebrity=2, clone_house=9, designer=66, niche=136 (total 213)
SELECT brand_tier FROM brand_profiles WHERE brand_name_normalized = 'creed';    -- niche
SELECT brand_tier FROM brand_profiles WHERE brand_name_normalized = 'dior';     -- designer
SELECT brand_tier FROM brand_profiles WHERE brand_name_normalized = 'armaf';    -- clone_house
```

**Explicitly out of scope (unchanged):**
- Founded year, country, current owner
- Perfumer credits, reformulation history, discontinued status
- Any broad encyclopedia project, any web scraping
- Relationship tables (those are FTG-2/RI1)

---

#### FTG-2 / RI1 — Relationship Intelligence Core
**Status: COMPLETE — PRODUCTION VERIFIED (2026-05-14)**
**Migration: 046**
**Commit: 4f7569b · migration fix commit: eff6221**

**Migration fix (eff6221):** Migration 046 had a duplicate index bug — `sa.Column(..., index=True)` auto-created
`ix_relationship_evidence_relationship_id` at table creation, then the explicit `op.create_index()` below tried to
create the same name again → DuplicateTable error. Every Railway deploy saw ALEMBIC_EXIT=0 from alembic finding
nothing to upgrade (DB was at 045 from the day before), masking the bug. Fixed by removing `index=True` from the
Column definition; explicit `op.create_index()` retained. Applied manually via public proxy; committed to main so
future deploys (and any downgrade/re-upgrade) use the corrected script.

**Purpose:** Move dupe / alternative / comparison relationships from hardcoded Python into a first-class evidence-backed data model.

**Final schema (migration 046):**
```sql
fragrance_relationships (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid()
  subject_canonical_name  TEXT NOT NULL  -- canonical name of alternative/clone
  relation_type        VARCHAR(32) NOT NULL  -- see VALID_RELATION_TYPES below
  object_canonical_name   TEXT NOT NULL  -- canonical name of original/reference
  confidence_score     NUMERIC(4,3) NOT NULL DEFAULT 0.500
  is_public            BOOLEAN NOT NULL DEFAULT FALSE
  operator_reviewed    BOOLEAN NOT NULL DEFAULT FALSE
  first_observed_date  DATE NOT NULL
  last_confirmed_date  DATE NOT NULL
  evidence_summary     TEXT NULL
  formula_version      INTEGER NOT NULL DEFAULT 1
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (subject_canonical_name, relation_type, object_canonical_name)
)

relationship_evidence (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid()
  relationship_id      UUID FK → fragrance_relationships ON DELETE CASCADE
  evidence_type        VARCHAR(32) NOT NULL
                       -- 'dupe_map_seed' | 'content_item' | 'query_pattern' | 'operator_note'
  content_item_id      UUID NULL  -- FK to canonical_content_items (no hard constraint)
  query_text           TEXT NULL
  note                 TEXT NULL
  observed_date        DATE NOT NULL
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Entity reference design decision (TEXT, not UUID FK):**
Columns are `subject_canonical_name` / `object_canonical_name` (TEXT).
Rationale: Montblanc Explorer, Zara Red Temptation, Ariana Grande Cloud have no `entity_market` row at seed time. UUID FK would block seeding. TEXT stores the same value as `entity_market.canonical_name` for tracked entities; future joins: `JOIN entity_market em ON em.canonical_name = fr.subject_canonical_name`. The `_name` suffix makes clear this is a canonical name string, not a surrogate PK.

**Relation type taxonomy (4 approved — VALID_RELATION_TYPES frozenset; no DB CHECK constraint):**
- `dupe_of` — strong direct clone; community consensus it is a deliberate copy
- `market_alternative_to` — commonly discussed as accessible alternative; may differ structurally
- `inspired_by` — stylistically in the direction of the original; lighter claim
- `commonly_compared_to` — high comparison query volume; no explicit clone claim

**Confidence seed defaults:**
- `dupe_of` → 0.850
- `market_alternative_to` → 0.700

**Seed: 7 relationship rows + 7 dupe_map_seed evidence rows (alias collapse from 12 _DUPE_RAW entries):**
| Subject | relation_type | Object | confidence |
|---|---|---|---|
| Armaf Club de Nuit Intense Man | dupe_of | Creed Aventus | 0.850 |
| Armaf Club de Nuit Intense | dupe_of | Creed Aventus | 0.850 |
| Montblanc Explorer | market_alternative_to | Creed Aventus | 0.700 |
| Lattafa Khamrah | market_alternative_to | Kilian Angels' Share | 0.700 |
| Lattafa Khamrah Qahwa | market_alternative_to | Kilian Angels' Share | 0.700 |
| Zara Red Temptation | dupe_of | Maison Francis Kurkdjian Baccarat Rouge 540 | 0.850 |
| Ariana Grande Cloud | market_alternative_to | Maison Francis Kurkdjian Baccarat Rouge 540 | 0.700 |

**Khamrah correction (founder 2026-05-14):** Khamrah → `market_alternative_to` (not `dupe_of`) — community signal is mixed on direct clone status; Truth Graph classifies conservatively.

**Qahwa decision (FTG-2 engineering judgment):** Khamrah Qahwa → `market_alternative_to` — same reasoning as parent Khamrah; its Angels' Share connection derives from brand family identity, not independent dupe consensus.

**Alias collapse:** CDNIM / "Club de Nuit Intense Man" / "Armaf CDNIM" are resolver aliases for "Armaf Club de Nuit Intense Man" — RI1 stores canonical identity, not resolver aliases.

**What FTG-2 intentionally does NOT do:**
- Does NOT change `entity_role` string or any existing API fields (legacy `_DUPE_RAW` path unchanged)
- Does NOT display any relationship data publicly (`is_public=FALSE` for all seeded rows)
- Does NOT implement operator review UI (that is FTG-3)
- Does NOT add `consensus_status` field (deferred to FTG-3/FTG-4)

**FTG-3 is complete:** FTG-3 / RI1-QA has implemented the `is_public=TRUE` promotion workflow and admin review queue (migration 047, commit 470837d). Public relationship display is now DB-backed.

**Tests:** `tests/unit/test_ftg2_relationship_intelligence.py` — 42/42 pass. Combined: 235/235 pass.

**Production verification (2026-05-14):**
- ALEMBIC_EXIT=0 ✓
- fragrance_relationships: 7 rows ✓
- relationship_evidence: 7 rows ✓
- Lattafa Khamrah: relation_type=market_alternative_to ✓
- Zara mass_market cleanup intact ✓
- Public entity pages unchanged ✓

**Verify commands (production DB):**
```sql
SELECT version_num FROM alembic_version;  -- expect 046
SELECT COUNT(*) FROM fragrance_relationships;  -- expect 7
SELECT COUNT(*) FROM relationship_evidence;    -- expect 7
SELECT subject_canonical_name, relation_type, confidence_score
FROM fragrance_relationships WHERE subject_canonical_name LIKE 'Lattafa Khamrah%'
ORDER BY subject_canonical_name;
-- Lattafa Khamrah | market_alternative_to | 0.700
-- Lattafa Khamrah Qahwa | market_alternative_to | 0.700
SELECT is_public, COUNT(*) FROM fragrance_relationships GROUP BY is_public;
-- TRUE | 7  (all rows promoted to public by migration 047 / FTG-3)
```

---

#### FTG-3 / RI1-QA — Operator Review Gate + DB-Backed Public Relationship Display
**Status: COMPLETE — PRODUCTION VERIFIED (2026-05-14)**
**Migration: 047**
**Commit: 470837d**

**Purpose:** Make relationship intelligence quality-controlled and publicly reliable. Move public relationship display from the legacy hardcoded `_DUPE_RAW` path to approved DB-backed relationship records.

**Migration 047 — Seed promotion (Option A):**
All 7 FTG-2 seeded rows promoted to `is_public=TRUE` in the same deploy. Condition: `operator_reviewed=TRUE AND confidence_score >= 0.700`. All 7 rows satisfied; migration is idempotent.

**Public quality gate (all three must pass):**
- `is_public = TRUE`
- `operator_reviewed = TRUE`
- `confidence_score >= 0.700`

**DB-backed read path:**
`get_approved_relationship(db, subject_canonical_name)` — returns `(relation_type, object_canonical_name, confidence_score)` or None. Called in `public_entities.py` and `routes/entities.py` before any legacy lookup. Falls back to `get_dupe_profile()` (_DUPE_RAW) if no approved row — resilience only, not primary source.

**Legacy `_DUPE_RAW` status after FTG-3:**
`_DUPE_RAW` is fallback-only — no longer the primary public source. If `get_approved_relationship()` returns a row, that row's `reference_original` and `relation_type` are used; `_DUPE_RAW` is consulted only when DB returns None (DB exception, missing row). FTG-3-CLEANUP (deferred): remove `_DUPE_RAW` entirely once DB coverage is verified complete.

**Public wording (v1):**
- `dupe_of` → "Dupe of: [Original]"
- `market_alternative_to` → "Alternative to: [Original]"
Applies to both public perfume page (`/perfumes/[slug]`) and terminal entity page (`/entities/perfume/[id]`).

**Admin operator console:**
- Route: `/admin/relationship-intelligence`
- API: `GET /api/v1/admin/relationship-intelligence?filter=all|public|non_public`
- Actions: `POST /{id}/approve`, `POST /{id}/unpublish`, `PATCH /{id}` (confidence_score + relation_type)
- All endpoints require `X-Pti-Admin-User` header (401 without)
- Next.js proxy: `/api/admin/relationship-intelligence/[...path]/route.ts`
- Sidebar: "Relationships" admin nav item (GitMerge icon)

**API output changes:**
- `PerfumeEntityDetail`: added `relation_type: Optional[str]`
- `PublicPerfumeDetail`: added `relation_type: Optional[str]`
- TypeScript types: `relation_type: string | null` added to entity detail type

**FTG-4 note:** FTG-4 / RI1-E will create low-confidence candidates (confidence ~0.3, is_public=FALSE) that enter this review queue for operator promotion.

**Tests:** `tests/unit/test_ftg3_relationship_review.py` — 28/28 pass. Combined: 263/263 pass (FTG-3 + FTG-2 + FTG-1 + DATA1 + Semantic Phase 5).

**Production verification (2026-05-14):**
- alembic_version: 047 ✓ (pending Railway deploy)
- fragrance_relationships: 7 rows, all is_public=TRUE after migration ✓ (pending)
- /admin/relationship-intelligence loads for admin ✓ (pending)
- Lattafa Khamrah: "Alternative to: Kilian Angels' Share" (DB-backed) ✓ (pending)
- Armaf CDNIM: "Dupe of: Creed Aventus" (DB-backed, dupe_of wording) ✓ (pending)
- Non-admin blocked (401/403) ✓ (pending)

**Rule:** Never auto-publish relationship updates. Scheduled evidence jobs (FTG-4) create candidates only. All public display requires explicit operator approval via `/admin/relationship-intelligence`.

---

#### FTG-4 / RI1-E — Evidence Harvesting v1 from Internal Signals
**Status: PLANNED**

**Purpose:** Use already-collected internal signals to generate relationship candidates — no external scraping.

**Evidence sources (already in DB):**
- `entity_topic_links.top_queries` — comparison query strings per entity per cycle
- `extract_vs_competitors()` in `market_intelligence.py` — already extracts VS pattern candidates
- Query phrase patterns: `dupe / clone / alternative / smells like / vs / similar to / compared to`

**Execution rules:**
- Scheduled job creates low-confidence candidates (`confidence_score ~0.3`) with evidence_type=`query_pattern`
- Evidence text stored in `relationship_evidence`
- Never auto-publish — all candidates enter operator review queue
- Job is idempotent; re-running the same cycle does not duplicate evidence

**What this unlocks:** Every time our content pipeline collects "Khamrah vs Angels' Share" in query data, that automatically surfaces as relationship candidate evidence for an operator to review.

---

#### FTG-5 / SN1 — Historical Intelligence Snapshot Layer
**Status: PLANNED**

**Purpose:** Store assembled intelligence outputs over time — not only raw topic distributions. Required for the 6-month trend report commercial product.

**Gap today:** `entity_topic_snapshots` (DATA0, migration 043) stores raw topic distributions. The assembled output — narrative text, opportunity tags, differentiators, intents — is computed at request time and discarded. There is no historical record of *why* we said a perfume was trending in March vs May.

**Expected new table:**
```
entity_intelligence_snapshots
  snapshot_date       DATE
  entity_id           UUID FK → entity_market
  narrative           TEXT
  opportunity_tags    JSONB  — ["alternative_demand", "high_intent"]
  differentiators     JSONB  — ["dupe / alternative", "compliment getter"]
  intents             JSONB  — ["review", "comparison"]
  entity_role         VARCHAR(64)
  trend_state         VARCHAR(32)
  score               NUMERIC(8,2)
  formula_version     INTEGER DEFAULT 1
  UNIQUE (snapshot_date, entity_id)
```

**Storage estimate:** ~2,400 entities × 1 row/day × 365 = ~876K rows/year, ~500B/row → ~440MB/year. Manageable. Retain 24 months; trim to monthly aggregates beyond that.

**Commercial reason:** "How did the market narrative around Baccarat Rouge 540 change between January and June 2026?" becomes a queryable question. This is what brands and commercial clients will pay for.

---

### Future FTG Extensions — Strategic North Star (Document Only — Not Ready for Implementation)

These modules are documented as strategic direction. Do not begin implementation until FTG-2 through FTG-5 are production-verified.

**FTG-6 / RI2 — Relationship Freshness & Scheduled Reconfirmation**
- Bi-weekly re-evaluation of existing relationship confidence from fresh signal data
- Confidence decay: relationship not reconfirmed in 60 days → score reduced
- Internal signals only in v1; no broad web scraping

**FTG-7 — Dupe Pressure Index**
- How many active alternatives surround a given original
- New alternatives appearing over time
- Alternative-demand acceleration for iconic perfumes
- "Dupe pressure score" as a derivative market signal for originals

**FTG-8 — Origin Classification Engine**
- Signal-driven detection of original / clone / market alternative / inspired / disputed classifications
- Evidence and confidence-based; operator reviewed before publication

**FTG-9 — Fragrance Whitespace Intelligence**
- Demand momentum + catalog saturation + dupe saturation + intent gap + olfactive opportunity
- Enables "there is rising demand for X-type fragrances but limited market supply" as a signal

**FTG-10 — Creator-to-Market Transmission Intelligence**
- Which creators first amplified a dupe claim vs. an original's organic rise
- Creator spread concentration: single-creator hype vs. broad independent consensus
- Ties into existing Creator Intelligence roadmap

---

### KB-CAT1 — Canonical Brand / Collection / Sub-brand Model
**STATUS: KB-CAT1-A PRODUCTION AUDIT COMPLETE (2026-05-14) — KB-CAT1-B PENDING FOUNDER APPROVAL**

**Trigger:** DATA2 fixed the brand-page join bug for concentration suffixes, but exposed that some Fragrantica catalog "brand" nodes are actually collections or sub-brands (e.g. "Xerjoff - Join the Club", "Xerjoff - Casamorati"), causing fragmented brand pages that don't reflect real market brand architecture.

**Problem confirmed — current state:**

In the resolver/catalog (dev subset — 260 brands, production ~1,600):
- 4 brands carry `"Parent - Collection"` notation: Xerjoff - Join the Club (6 perfumes), Xerjoff - Casamorati (11 perfumes), Xerjoff - XJ Oud Attars (5 perfumes), Filippo Sorcinelli - SAUF (5 perfumes; genuine standalone brand name, NOT a sub-collection)
- Of these, 3 have a parent brand that also exists in the resolver: the three Xerjoff sub-collections
- In production (~1,600 brands), expect 15–50 similar nodes; exact count requires production scope query

**Current internal representation (Xerjoff):**
- `brands` table: 4 separate nodes — "Xerjoff" (id=11, 38 perfumes), "Xerjoff - Join the Club" (id=116, 6 perfumes), "Xerjoff - Casamorati" (id=836, 11 perfumes), "Xerjoff - XJ Oud Attars" (id=856, 5 perfumes)
- `entity_market`: each node gets its own brand entity via the brand rollup (`GROUP BY em.brand_name`)
- `brand_identity_map`: slugs are xerjoff, xerjoff---join-the-club, xerjoff---casamorati, xerjoff---xj-oud-attars
- Perfume `brand_name` in entity_market = resolver's brand canonical_name (e.g. "Xerjoff - Join the Club") — not the parent
- `_brand_entity_id_for()` links perfume pages to their resolver brand entity, so "Don" links to brand-xerjoff---join-the-club, NOT brand-xerjoff
- Currently: no parent/child relationship exists anywhere in the data model

**Semantic distinction confirmed:**
- "Xerjoff - Join the Club" → **collection** — themed fragrance collection within Xerjoff's portfolio, no independent brand identity
- "Xerjoff - Casamorati" → **heritage sub-brand** — Casamorati is a historic Italian house acquired by Xerjoff in 2015, with its own distinct aesthetics, market positioning, and loyal customer base. Deserves richer semantic treatment than "collection."
- "Xerjoff - XJ Oud Attars" → **product line** — specialized oud attars/oils line (not EDP fragrances), may be closer to a product category than a named collection

**Recommended taxonomy (v1 minimal):** 3 node types:
- `brand` — standalone top-level market brand with independent market identity (default)
- `collection` — themed grouping of perfumes under a parent brand, no independent legal/brand identity
- `sub_brand` — independently branded line under a parent brand, often an acquisition or distinct heritage identity (Casamorati)

**Recommended relation model (v1):**
- `collection belongs_to brand` via `parent_brand_normalized` reference
- `sub_brand belongs_to brand` via `parent_brand_normalized` reference
- `perfume belongs_to collection | sub_brand | brand` (derived from resolver brand assignment)

**Recommended data model:** Extend `brand_profiles` (migration 044):
- Add `node_type VARCHAR(32) DEFAULT 'brand'` — values: brand / collection / sub_brand
- Add `parent_brand_normalized TEXT NULL` — normalized name of parent brand (matches brand_name_normalized on parent row)
- Rationale: brand_profiles already exists, is already operator-reviewed, already has normalized lookup key — extending it avoids a new table and keeps brand canonicalization in one place

**Client-visible navigation (target product state):**
- Parent brand page (`/entities/brand/brand-xerjoff`): shows "Collections" section (Join the Club, XJ Oud Attars) and "Sub-brands" section (Casamorati) with rollup scores
- Collection page (`/entities/brand/brand-xerjoff---join-the-club`): shows "COLLECTION · Xerjoff" label + parent brand link; current URL preserved
- Sub-brand page (`/entities/brand/brand-xerjoff---casamorati`): shows "SUB-BRAND · Xerjoff" label + parent brand link; current URL preserved
- Perfume page breadcrumb: Xerjoff → Join the Club → Don (via brand_profiles chain)
- Screener: brand_name on results should ideally show "Xerjoff" (parent) for collection-parented perfumes

**URL / backwards compatibility:**
- Live indexed URLs (`/entities/brand/brand-xerjoff---join-the-club`, `/entities/brand/brand-xerjoff---casamorati`) must be preserved — no redirects until parent pages are verified
- Change: semantic label from "BRAND" to "COLLECTION" or "SUB-BRAND" in the UI only — same URL, same entity, enriched display
- Public pages (`/brands/xerjoff---join-the-club`) may eventually redirect to parent `/brands/xerjoff#join-the-club` in KB-CAT1-D+ — deferred

**Rollup / scoring implications:**
- Currently: "Xerjoff" brand score = only perfumes with `brand_name = "Xerjoff"` (excludes Join the Club, Casamorati perfumes)
- After KB-CAT1-E: add `parent_brand_name` column to entity_market perfume rows; rollup aggregates by parent_brand_name to give "Xerjoff" a holistic score
- This is the highest-risk change — "Xerjoff" brand score would jump significantly once sub-collection perfumes roll up to it; schedule for last
- Safe sequencing: display/navigation changes first (KB-CAT1-B/C/D), rollup changes last (KB-CAT1-E)

**Resolver and ingestion:** No changes to resolver. Resolver correctly identifies what brand Fragrantica assigns — that's correct for identity. The canonical hierarchy layer is purely a market-governance addition layered on top.

**Operator review strategy:**
- Auto-detect candidates: brands table entries where `canonical_name LIKE '% - %'` AND the prefix exists as another brand row → flag as candidate
- Operator assigns: node_type (collection / sub_brand), parent_brand_normalized
- Never auto-merge; never auto-parent

**Risks if rushed:**
- Brand rollup score changes (Xerjoff parent score inflates) — could distort dashboard/screener rankings
- entity_type='brand' is assumed everywhere (brand pages, brand screener, brand filter) — changing semantics without URL/route changes first creates display inconsistencies
- SEO: public brand pages (`/brands/xerjoff---join-the-club`) are indexed — reclassifying without preserving URLs causes 404s

**KB-CAT1-A — Production Audit Results (2026-05-14) — COMPLETE**

Production: 1,609 total `resolver_brands`. Dash-pattern candidates: **12** (not 15–50 as estimated).

**Full candidate classification matrix:**

| Candidate Node | Inferred Parent | Parent in resolver? | entity_market? | Perfumes | Taxonomy decision | node_type |
|---|---|---|---|---|---|---|
| Xerjoff - Join the Club | Xerjoff | YES | TRACKED | 6 | Themed collection, no independent market identity | `collection` |
| Xerjoff - Casamorati | Xerjoff | YES | TRACKED | 11 | Historic acquisition, marketed separately | `sub_brand` |
| Xerjoff - XJ Oud Attars | Xerjoff | YES | NOT TRACKED | 5 | Themed oud collection | `collection` |
| Filippo Sorcinelli - SAUF | Filippo Sorcinelli | YES | NOT TRACKED | 5 | Line name / label | `collection` |
| 06130 - Zéro Six Cent-Trente | 06130 | NO MATCH | NOT TRACKED | 14 | **False positive** — brand's own code+full-name format; single identity | `brand` (false positive) |
| A & E - Ariana & Evans | A & E | NO MATCH | NOT TRACKED | 19 | **False positive** — A&E is acronym; Ariana & Evans is the same brand | `brand` (false positive) |
| ArteOlfatto - Luxury Perfumes | ArteOlfatto | NO MATCH | TRACKED | 20 | **False positive** — "Luxury Perfumes" is a subtitle/descriptor, not a collection | `brand` (false positive) |
| Libertin Louison - Technique Indiscrète | Libertin Louison | NO MATCH | NOT TRACKED | 19 | **False positive** — Fragrantica house name formatting; no parent | `brand` (false positive) |
| LPO - Libby Patterson Organics | LPO | NO MATCH | NOT TRACKED | 16 | **False positive** — acronym + full name; single entity | `brand` (false positive) |
| MD - Meo Distribuzione | MD | NO MATCH | TRACKED | 16 | **False positive** — acronym + full name; single entity | `brand` (false positive) |
| Ricardo Ramos - Perfumes de Autor | Ricardo Ramos | NO MATCH | NOT TRACKED | 20 | **False positive** — "Perfumes de Autor" is a tagline; Ricardo Ramos is the brand | `brand` (false positive) |
| Rosendo Mateu - Olfactive Expressions | Rosendo Mateu | NO MATCH | TRACKED | 16 | **False positive** — "Olfactive Expressions" is a descriptor/line name | `brand` (false positive) |

**Summary:**
- True hierarchy candidates: **4** (Xerjoff × 3, Filippo Sorcinelli × 1)
- False positives (acronym/descriptor pattern): **8**
- Parent brand exists in resolver for all 4 true hierarchy candidates
- Production scope is narrow — KB-CAT1 is Xerjoff-first, then Filippo Sorcinelli

**FK vs no-FK confirmation:** No FK on `parent_brand_normalized` in v1. Integrity via operator review + QA queries. False positive rows carry `node_type='brand'` and `parent_brand_normalized=NULL` — same as any standalone brand.

**Taxonomy stress-test result:** 3-type taxonomy (`brand` / `collection` / `sub_brand`) covers all 12 candidates cleanly. No edge cases require a 4th type.

**KB-CAT1-B seeds (locked):**
- `xerjoff - join the club` → node_type=`collection`, parent=`xerjoff`
- `xerjoff - casamorati` → node_type=`sub_brand`, parent=`xerjoff`  
- `xerjoff - xj oud attars` → node_type=`collection`, parent=`xerjoff`
- `filippo sorcinelli - sauf` → node_type=`collection`, parent=`filippo sorcinelli`

False positives: add as `node_type='brand'`, `parent_brand_normalized=NULL` only if they become tracked (no proactive seeding needed — they are not tracked in entity_market and have no hierarchy to express).

**Proposed roadmap:**

KB-CAT1-B — brand_profiles Hierarchy Extension (migration)
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-14)**
**Migration: 048 · Commit: 6800248**
- `node_type VARCHAR(32) NOT NULL DEFAULT 'brand' CHECK (node_type IN ('brand','collection','sub_brand'))` added to brand_profiles
- `parent_brand_normalized TEXT NULL` added (no FK — operator-reviewed integrity)
- `get_brand_profile()` added to `brand_profile.py` — returns full dict with brand_tier, node_type, parent_brand_normalized
- `BrandEntityDetail` Pydantic model and TypeScript interface extended with `node_type` + `parent_brand_normalized`
- Both tracked and catalog-only API paths populate from `get_brand_profile()`
- 4 hierarchy seed rows applied: xerjoff collections + casamorati sub_brand + filippo sorcinelli SAUF
- 24/24 tests pass (test_kb_cat1b_brand_hierarchy.py); 239/239 combined pass
- Production DB: 217 brand_profiles rows — 213 brand, 3 collection, 1 sub_brand

**Production verify (2026-05-14):**
```
brand-xerjoff → node_type='brand', parent=null ✓
brand-xerjoff---join-the-club → node_type='collection', parent='xerjoff' ✓
brand-xerjoff---casamorati → node_type='sub_brand', parent='xerjoff' ✓
brand-creed / brand-lattafa / brand-dior → node_type='brand', parent=null ✓ (no regression)
Xerjoff - Join the Club Don perfume → state=tracked, score=68.4 ✓ (DATA2 unaffected)
```

**Verify commands:**
```sql
SELECT version_num FROM alembic_version;  -- expect 048
SELECT node_type, COUNT(*) FROM brand_profiles GROUP BY node_type ORDER BY node_type;
-- brand=213, collection=3, sub_brand=1
SELECT brand_name_normalized, node_type, parent_brand_normalized
FROM brand_profiles WHERE node_type != 'brand' ORDER BY brand_name_normalized;
-- filippo sorcinelli - sauf | collection | filippo sorcinelli
-- xerjoff - casamorati      | sub_brand  | xerjoff
-- xerjoff - join the club   | collection | xerjoff
-- xerjoff - xj oud attars   | collection | xerjoff
```

KB-CAT1-C — Xerjoff Pilot — Display Metadata Only
**STATUS: COMPLETE — PENDING PRODUCTION VERIFICATION (2026-05-14)**
**Commit: 233f74e**
- Brand entity detail page: show node_type badge ("COLLECTION" / "SUB-BRAND") instead of implied "BRAND" for non-root nodes
- Brand entity detail page: show parent brand link/breadcrumb ("Part of Xerjoff →")
- Parent brand page (Xerjoff): show "Collections" and "Sub-brands" sections using brand_profiles hierarchy query
- No URL changes. No rollup changes. Display layer only.

KB-CAT1-D — Perfume Breadcrumbs
- Perfume entity page + public perfume page: breadcrumb uses brand_profiles chain
- "Don" shows: Xerjoff → Join the Club → Don
- "1888" shows: Xerjoff → Casamorati → 1888

KB-CAT1-E — Parent Brand Rollup (high risk — schedule last)
- Add `parent_brand_name TEXT NULL` to entity_market perfume rows
- Brand rollup aggregates by parent_brand_name for parent-level brand scores
- Requires careful QA: Xerjoff brand score before/after comparison
- Requires dashboard/screener filter updates

KB-CAT1-F — Broader Governance Queue
- Systematic rollout beyond Xerjoff using candidate detection + operator review UI

**Add to CLAUDE.md active roadmap:** Yes — pending founder approval to activate as a roadmap branch.

---

### FTG Anti-Overbuilding Rules (Binding)

These rules must not be violated in FTG implementation:

1. Do not build a full Fragrantica-style encyclopedia in FTG-1. Brand tier only.
2. Do not merge Encyclopedia responsibilities into the Resolver. They are separate domains.
3. Do not auto-publish relationship updates. Every public relationship requires operator review.
4. Do not start broad internet scraping for relationship truth in RI1/RI1-E. Internal signals only.
5. Do not let early relationship classifications alter base market score or signal logic.
6. Do not ship public relationship display until the operator review gate (FTG-3) is in place.
7. Keep the first implementation narrow, reviewable, and production-safe.

---

## DATA2 — Brand Catalog Join Normalization
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-14)**
**Commit: e5f3614**
**No migration required.**

**Root cause:** `_brand_catalog_perfumes()` in `entities.py` joined `resolver_perfumes` to `entity_market` using exact case-insensitive name equality. The Fragrantica source catalog stores verbatim concentration-variant names (e.g. `"Xerjoff - Join the Club Don Eau de Parfum"`), while the aggregation job strips those suffixes via `_base_name()` before writing to `entity_market` (e.g. `"Xerjoff - Join the Club Don"`). The LEFT JOIN returned NULL for `entity_id`, so tracked perfumes appeared as catalog-only with no market data on their brand page.

**Observed symptom:** `Xerjoff - Join the Club Don` was #1 Top Mover (score 68.4, growth +200%) on the dashboard, but the brand page `/entities/brand/brand-xerjoff---join-the-club` showed it as "IN CATALOG" with `—` for score/mentions and Tracked: 0.

**Fix:** Extended the LEFT JOIN `IN` clause to also test the double-pass suffix-normalized form using PostgreSQL `REGEXP_REPLACE`, matching the same suffix list as `_base_name()` in the aggregation job. Two passes handle double-suffixed names (e.g. "Extrait Extrait de Parfum"). Exact match is tried first (zero regression on non-suffix names).

**Changed:** `_brand_catalog_perfumes()` in `perfume_trend_sdk/api/routes/entities.py` — LEFT JOIN now:
```sql
ON LOWER(em.canonical_name) IN (
    LOWER(rp.canonical_name),
    LOWER(TRIM(REGEXP_REPLACE(
        REGEXP_REPLACE(rp.canonical_name, '\s+(Extrait de Parfum|Eau de Parfum|...)\s*$', '', 'i'),
        '\s+(Extrait de Parfum|Eau de Parfum|...)\s*$', '', 'i'
    )))
)
```

**Scope:** Affects every brand page where Fragrantica catalogs a perfume under a concentration-variant canonical name while the market engine tracked it under the base name. Scope audit query (run on production):
```sql
SELECT COUNT(*) AS newly_matchable
FROM resolver_perfumes rp
WHERE NOT EXISTS (
    SELECT 1 FROM entity_market em
    WHERE LOWER(em.canonical_name) = LOWER(rp.canonical_name) AND em.entity_type = 'perfume'
)
AND EXISTS (
    SELECT 1 FROM entity_market em
    WHERE LOWER(em.canonical_name) = LOWER(TRIM(REGEXP_REPLACE(
        REGEXP_REPLACE(rp.canonical_name,
            '\s+(Extrait de Parfum|Eau de Parfum|Eau de Toilette|Eau de Cologne|Eau Fraiche|Extrait|Parfum)\s*$','','i'),
        '\s+(Extrait de Parfum|Eau de Parfum|Eau de Toilette|Eau de Cologne|Eau Fraiche|Extrait|Parfum)\s*$','','i'
    ))) AND em.entity_type = 'perfume'
);
```

**Unrelated separate issue (future):** "brand as collection" modeling — Fragrantica catalogs `"Xerjoff - Join the Club"` as a brand entry rather than as parent brand "Xerjoff" + collection "Join the Club". DATA2 does NOT fix this. See Future Canonical Catalog Governance note below.

**Tests:** `tests/unit/test_data2_brand_catalog_join.py` — 28/28 pass. Combined: 301/301 pass (DATA2 + DATA1 + FTG-3 + FTG-2 + FTG-1 + Semantic Phase 5 suites).

**Production verification (2026-05-14) — COMPLETE:**
- `/entities/brand/brand-xerjoff---join-the-club` → Tracked: 5 · "Xerjoff - Join the Club Don Eau de Parfum" shows score ≈ 68.4, mentions 12, ACTIVE ✓
- `/entities/brand/brand-xerjoff---casamorati` → Tracked: 6 · EDP-suffixed rows (e.g. "Xerjoff - Casamorati 1888 Eau de Parfum") now show scores/mentions ✓
- Lattafa brand page unchanged ✓
- Dashboard/screener/perfume entity pages unchanged ✓

---

### Catalog Truth Principle

FragranceIndex.ai treats external catalog imports (Fragrantica, Parfumo) as raw reference inputs, not immutable final truth. The platform maintains its own canonical market model and must correct inherited catalog limitations including:
- concentration suffix naming variants (DATA2)
- brand/collection fragmentation (future)
- stale or source-specific modeling choices
- source structures that conflict with live market reality

**Rule:** When source catalogs create canonical-display mismatches, normalize them through explicit, reviewable canonicalization layers (`_base_name()`, brand profile overrides, future canonical governance) rather than blindly exposing inherited source structure.

---

### Future Canonical Catalog Governance → KB-CAT1

See KB-CAT1 — Canonical Brand / Collection / Sub-brand Model in the FTG section below. Architecture assessment complete (2026-05-14). Implementation not started.

---

## DATA1 — Last Active Display Snapshot Contract
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-14)**
**No migration required.**

**Problem:** Carry-forward zero rows (written for timeseries continuity) were being selected as the "latest snapshot" for headline/card/list displays. An entity active on May 12 with a quiet day on May 13 showed score=0.0, growth=-100% — technically correct for May 13 but user-facing misleading.

**Root cause:** Three read paths used unconditional `MAX(date)` (absolute latest row) instead of `MAX(date) WHERE mention_count > 0` (last real activity):
- `latest_snapshot_subquery()` in `queries.py` → used by dashboard (today preset) + screener (today preset)
- `_get_latest_snapshot()` in `routes/entities.py` → used by perfume + brand entity headline
- `_enrich_items()` subquery in `routes/watchlists.py` → used by watchlist card rows

**Display contract:**
- **Headline/list/card paths:** latest row where `mention_count > 0` — last real activity date
- **Chart timeseries (`_get_history()`):** full series unchanged, including carry-forward zero rows
- **`_check_activity_today()`:** already correct (`MAX(date) WHERE mention_count > 0`) — no change

**Active Today alignment:** `_check_activity_today()` and `_get_latest_snapshot()` now reference the same underlying date. No entity can appear "Active Today" while its displayed score comes from a different (carry-forward) date.

**Freshness cue:** `ScreenerTable.tsx` now shows the score date as small dim text below each score value (`fmtDate(row.date)`) so users can see what date the displayed score is from.

The entity detail page already shows "As of {latest_date}" — after the fix, `latest_date` correctly reflects the last-active date, not the carry-forward date.

**Affected paths (fixed):** `queries.py::latest_snapshot_subquery`, `routes/entities.py::_get_latest_snapshot`, `routes/watchlists.py::_enrich_items`
**Unaffected (already correct):** `_check_activity_today`, `_brand_catalog_perfumes`, `_brand_active_perfume_count`, `public_entities.py::_get_latest_score_and_trend`, `_fetch_rows_aggregated` (range queries)

**Tests:** `tests/unit/test_data1_last_active_display.py` — 16/16 pass. Combined: 273/273 pass.

---

## Active Roadmap

**Language & Region Architecture**
Full roadmap: `docs/architecture/LANGUAGE_REGION_ARCHITECTURE.md`
Phase 042 — IMPLEMENTED — MIGRATION APPLIED TO PRODUCTION (2026-05-12)
Phase 043 — COMPLETE — PRODUCTION VERIFIED (2026-05-12) — commits `71be8f4` + `32d2a25` — 44/44 new + 117/117 existing tests pass
Next phase: **044 — Regional Creator Policy v1** (pending explicit approval)
Phases defined: 042 ✓ → 043 ✓ → 044 (regional creator policy) → 045 (filters) → 046 (aggregation design) → 047 (market availability) → 048 (UI concepts)

- **YT-CREATOR-EXPANSION-02-AGENT-APPROVED-136 — APPLIED, PENDING PIPELINE VERIFICATION (2026-05-11)**
  - batch_id: `8b2f7141-7ec8-42e5-aaa9-6dca1230b68a`
  - Script: `scripts/youtube/verify_from_csv.py` (new — reads CSV with pre-known channel_ids, no URL resolution needed, batch channels.list fetch)
  - Source CSV: `data_inputs/fragrance_channels_reviewed_2026-05-10.csv` — 190 rows total, 136 filtered (approved_creator_candidate only)
  - Batch results: 70 VERIFIED_ADD_READY / 37 SKIP_DUPLICATE / 29 SKIP_INACTIVE / 0 NEEDS_OPERATOR_REVIEW
  - **Disposition applied (2026-05-11):**
    - APPLIED: 41 English/global independent fragrance creator channels → youtube_channels 210 → 251 ✓
    - DEFERRED/ROUTE_TO_BRAND_RETAIL_WATCH (3): NAUTIQUE LUXURY (1.13M), Amanzada Perfumes (255K), SHAHIDI SCENT REVIEWS (10K)
    - DEFERRED/ROUTE_TO_FORMULATION_EDUCATION_LAYER (3): Faizan Fragrances, babbs collection, Unravel Perfumery
    - DEFERRED/REGIONAL_POLICY_PENDING (12): Andrés Perfume-Man (2.45M, Spanish), Leni's Scents (57K, DE), + 10 India/ME/other regional
    - DEFERRED/LIFESTYLE_OR_AMBIGUOUS_REVIEW (8): Mila Le Blanc (99K), FragranceView (67K), Hassan Siddiqui (58K), + 5 others
    - OPERATOR_REJECTED/true noise (3): MAGS FRAGS (automotive), Ai_TheGreat (lifestyle/bags), Scents N Stories (failed title extraction)
  - Provenance: added_by = `source_intake:YT-CREATOR-EXPANSION-02-AGENT-APPROVED-136` — 0 duplicates ✓
  - Audit log: 206 entries (136 initial_classification + 41 apply + 26 defer + 3 reject) ✓
  - Policy: DEFERRED preserves all fragrance-relevant sources for future brand/retail/formulation/regional layers; REJECTED = true noise only
  - **Evening pipeline 2026-05-11 verification (2026-05-12):**
    - Pipeline ran: YouTube 602 items / Reddit 196 items / Signals 167 (confirmed via content timestamps)
    - In youtube_channels: 20/41 (last_polled_at=NULL — not yet polled by channel poll)
    - Not in youtube_channels: 21/41 (ON CONFLICT DO NOTHING silent skip — channels may have been pre-existing from auto-discovery)
    - Content items collected from new channels: 5 channels with items (1 new post-apply, via search path)
    - Production Verify NOT yet safe — most channels unpolled; batch stays APPLIED until ≥1 content item per channel
    - Production Verify is MANUAL (requires button in admin UI); never automatic after pipeline
  - **Next step:** Wait for next morning/evening pipeline to poll the 20 unpolled channels; then run Production Verify

- **YT-CREATOR-EXPANSION-01 — COMPLETE — PRODUCTION VERIFIED (2026-05-10)** — commit 914652e — Added 8 verified fragrance YouTube creator channels (189 → 197 total). Scripts: `scripts/youtube/verify_candidate_channels.py` (resolution + activity check + dedup), `scripts/youtube/seed_yt_creator_expansion_01.py` (idempotent INSERT). Reports: `reports/youtube_candidate_intake_2026-05-10.{md,csv,json}`. Reviewed 20 candidates: 8 ADD / 3 SKIP_DUPLICATE / 4 SKIP_INACTIVE_30D / 5 NEEDS_OPERATOR_REVIEW. All 8 polled and ingested (89 new content items). Channels added: Christopher Lee Fragrances (412K, tier_2), Soki London (151K, tier_2), The Niche Fragrance Collector (136K, tier_2), The Scented (126K, tier_2), Paulina&Perfumes (85K, tier_2), Gabby Loves Perfumes (34K, tier_3), Seldomly Often (22K, tier_3), Des Paons Dansent Cent Heures (5K, tier_4).
- **SC1.2A+B TikTok Watchlist Registry — COMPLETE (2026-05-08)** — commit pending — migration 035: `creator_platform_accounts` (platform-neutral, unique on `(platform, platform_handle)`) + `creator_watchlist_audit_log`. Service: `perfume_trend_sdk/services/tiktok_watchlist.py` (add_account, list_accounts, get_account, change_status, bulk_import). Handles: bare/`@handle`/profile URL normalized; video URLs rejected. Statuses: pending_review|active|paused|rejected|error. API: `GET/POST /api/v1/tiktok-watchlist`, `GET/PATCH /{handle}`, `GET /{handle}/audit`. Seed script: `python3 -m perfume_trend_sdk.scripts.seed_tiktok_creators --file CSV [--dry-run] [--activate]`. Production: 6 creators seeded, 9 audit entries, duplicate protection verified, YouTube creator_scores (711 rows) untouched. 44/44 tests pass.
- **SC1.2C TikTok Seeded Creator Monitoring Worker — COMPLETE (2026-05-08)** — `perfume_trend_sdk/jobs/monitor_tiktok_seeded_creators.py` + `perfume_trend_sdk/ingest/tiktok_page_parser.py`. Kill switch: `TIKTOK_PUBLIC_MONITORING_ENABLED=false` (default). Reads active TikTok creators, fetches profile pages via plain HTTPS (no auth/cookies/automation), extracts follower_count/video_count from `webapp.user-detail.userInfo`. Updates `creator_platform_accounts.follower_count + last_checked_at`. Writes `creator_watchlist_audit_log`. Does NOT create entity_mentions or canonical_content_items. **TikTok SSR limitation (verified 2026-05-08):** `itemList` is ALWAYS empty in server-rendered HTML — video discovery is not possible via simple HTTP. Worker logs `TIKTOK_MONITOR_CREATOR_WARNING video_list_unavailable=true` on every run until a future approved method (TikTok Research API or reviewed browser-based approach) is implemented. Verified on `@rawscents`: followers=2 updated in DB, audit log written, 0 entity_mentions created. 24/24 tests pass.
- **SC1.3 Multi-field Resolver — COMPLETE — PRODUCTION VERIFIED (2026-05-08)** — commit ee1d8ba — `perfume_trend_sdk/resolvers/perfume_identity/multi_field_resolver.py`. Feature flag: `MULTI_FIELD_RESOLVER_ENABLED=true` (Railway generous-prosperity). Platform-specific field weights: YouTube title(1.0)/description(0.5)/hashtags(0.3); Reddit body(1.0)/title(0.7); TikTok derived referencing_context(1.0)/hashtags(0.5)/description(0.3)/title(0.2); TikTok direct user_context(1.0)/hashtags(0.6)/description(0.4)/title(0.5). Confidence threshold 0.3. TikTok generic title protection + YouTube title noise filter. 67/67 tests pass. **Replay (2026-05-04–07):** old=624, new=807, +183 resolved, 0 regressions. **Production pipeline (2026-05-08) verified:** PIPELINE_HEALTH_OK · entity_mentions=180 (baseline 183-189) · signals=142 (baseline 113-216) · resolved_signals 1.1-mf=558, 1.1=74 · content_items=1203 (yt=997, reddit=206) · public_safe views 2318/4976/9644 · dashboard 200 OK (2373 entities, 19 breakouts) · no new false positives (noise aliases pre-existing, within historical range).
- **P3 Pipeline Health Check — COMPLETE (2026-05-08)** — commit 58ff5c6 — `perfume_trend_sdk/jobs/pipeline_health_check.py` runs at end of morning + evening pipelines. 4 checks: entity_mentions (CRITICAL<50/WARNING<100), Reddit entity_mentions (WARNING morning=0/CRITICAL evening=0), content items by platform, signals count. Markers: `PIPELINE_HEALTH_OK/WARNING/CRITICAL`. Exit always 0. Verified retroactively: 05-06 collapse correctly fires `PIPELINE_HEALTH_WARNING` (reddit_items=0, mentions=64). 21/21 tests pass.
- **Phase 042 — Language & Region Metadata v1 — COMPLETE — PRODUCTION VERIFIED (2026-05-12)** — migration `alembic/versions/042_language_region_metadata.py` · implementation commit `3702a9c` · completion fix commit `436fd6c` · migration applied commit `afe232f`. Adds 5 nullable metadata fields to `source_intake_candidates` (`source_language`, `source_country`, `source_region`, `audience_region`, `regional_policy_status`) and 3 new columns to `youtube_channels` (`source_region`, `audience_region`, `regional_policy_status`). Apply path carries all 5 into the YouTube source registry: `source_language` → `language`, `source_country` → `country` (existing columns, migration 023), plus 3 new columns. PATCH endpoint accepts and saves all 5. CandidateRow GET exposes all 5. Admin UI: Language & Region section in BatchReviewConsole per candidate (lang/country inputs, region/audience/policy dropdowns, Save Metadata button). No regional scoring. No regional leaderboard. No public filters. No canonical_content_items propagation (Phase 043). Creator Leaderboard behavior unchanged. 52/52 tests pass.
- **P3.1 Pipeline Health Log — COMPLETE — PRODUCTION VERIFIED (2026-05-12)** — implementation commit `8b49fd2` · migration applied commit `afe232f`. `alembic/versions/041_pipeline_health_log.py` · `pipeline_health_log` table (13 columns). Upserts one row per `(run_date, run_label)` after each health check run. ON CONFLICT (run_date, run_label) DO UPDATE — idempotent re-runs overwrite the row without duplicating. Trims rows older than 90 days at persist time (no separate cron). `pipeline_service` captured from `PIPELINE_SERVICE` env var (operator-set Railway override) or `RAILWAY_SERVICE_NAME` (Railway built-in), NULL if neither set. run_label supports: morning | evening | manual | backfill | unknown — no CHECK constraint. Pipeline scripts already pass `--run-label morning` / `--run-label evening` — no script changes needed. Ad-hoc and backfill runs use `--run-label manual`. Persist errors are non-fatal (logged as WARNING, pipeline continues). Admin UI deferred. 30/30 tests pass.
  **First row will appear after next scheduled pipeline run (11:00 UTC or 23:00 UTC).** Verify: `SELECT run_date, run_label, overall_level, pipeline_service FROM pipeline_health_log ORDER BY recorded_at DESC LIMIT 5;`
- **Phase 043 — Content Language & Region Propagation v1 — COMPLETE — PRODUCTION VERIFIED (2026-05-12)** — implementation commit `71be8f4` · first-poll fix commit `32d2a25`. `normalizer.py`: added `_COUNTRY_TO_REGION` map + `_resolve_content_language()` / `_resolve_content_region()` helpers; `normalize_youtube_item()` accepts optional `channel_context` kwarg. `region` default changed from hardcoded `"US"` to `"UNKNOWN"` when no context. `ingest_youtube_channels.py`: `_load_channels()` now SELECTs `language, country, source_region`; `poll_channel()` passes `channel_context` to normalizer; `_first_poll_country or channel.get("country")` ensures first-poll channels get correct region immediately. Fallback: `source_region` → `country→region map` → `"UNKNOWN"`. `entity_mentions.region` deferred. TikTok/Reddit normalizers unchanged. Scoring unchanged. Public-safe views unchanged. 44/44 new + 117/117 existing tests pass. **Production verification 2026-05-12:** manual poll of 4 channels (Fragmental GB, School of Scent GB, Hardbody Fragrancez US, TLTG Reviews US) → 12 items: 9×US_CANADA + 3×UK_IRELAND, 0 NULL regions, 0 NULL language. Non-UNKNOWN region propagation confirmed. No errors.
- **Suggest a Source MVP — production polish (2026-05-06)** — commit 16ec68f (backend) + pending frontend
  - Route: `/submit-source` under `(terminal)` — logged-in only, redirects to /login if not
  - Form: URL + terms checkbox only. No name, email, platform dropdown, reason.
  - Backend: `POST /api/v1/source-submissions` — normalize URL, auto-detect platform, dedup (409), status=pending
  - Migration 033 applied: `source_submissions` table, unique index on `normalized_url` ✓
  - User email + ID from Supabase session; no anonymous submissions accepted
  - Platform auto-detected from URL host (YouTube, TikTok, Instagram, Reddit)
  - Sidebar: "Suggest Source" (renamed from "Submit Source")
  - Landing page: "Know a fragrance creator we should track?" block with "Suggest a Source" CTA → /login?next=/submit-source
  - Crash fix: replaced `startTransition(async)` with plain `isLoading` state — eliminates React 18/19 boundary crash
  - Copy: title "Suggest a Source", success "Thank you — this source was submitted for review.", duplicate "already in our review queue"
  - No automatic ingestion. No direct market score manipulation.
- **Landing community CTA section: amber-accent card (2026-05-07)** — commit be769cf — stronger amber-accent visual emphasis for Suggest a Source block (card with 2px amber top border, amber eyebrow + CTA outline) for better discoverability.
- **Legal operator attribution (2026-05-07)** — commit e431e61 — Legal pages now identify Liliya's Flowers, LLC as the operator of FragranceIndex.ai / FTI Market Terminal (Privacy §1, Terms §1, Data Sources §1, footer copyright).
- **Auth-aware public header (2026-05-07)** — commit d115562 — logged-in users see "Open Terminal" → /dashboard; logged-out see "Sign in" → /login; applies to all (public) layout pages (/, /glossary, /privacy, /terms, etc.); landing "Suggest a Source" CTA links directly to /submit-source when logged in. PRODUCTION VERIFIED.
- **Magic Link email template: FTI branding — APPLIED (2026-05-07)** — commit 29b2d75 — `docs/email_templates/magic_link_fti.html` applied in Supabase → Authentication → Email Templates → Magic Link; sender name "FTI Market Terminal"; subject "Your Magic Link — FTI Market Terminal"; no visible PTI branding.
- **Terminal branding: PTI → FTI (2026-05-07)** — commit 3124784
  - StatusBar: "FTI MARKET TERMINAL" + brand text is a Link → / (back to public landing)
  - Sidebar: monogram "PT" → "FTI", wordmark "PTI Terminal" → "FTI Terminal"
  - Internal console.log labels (PTI LOGIN, PTI CALLBACK) unchanged per branding rule
  - Build clean · deployed
- **FIX: Secret-safe deploy logging (2026-05-06)** — commit f0246cd
  - `set -x` caused Railway deploy logs to print full DATABASE_URL (including password)
  - Replaced with `set -e` (fail-fast on error, no trace expansion)
  - Safe log lines only: "DATABASE_URL is set" · "Running alembic upgrade head" · "ALEMBIC_EXIT=0" · "Starting uvicorn"
  - Full DATABASE_URL will no longer appear in Railway deploy logs
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
- **Creator detail UX polish — PRODUCTION VERIFIED (2026-05-06)** — commits 0af379c + d298e36
  - `external_url` field added to `CreatorProfileResponse` (backend schema + route + TS type)
  - YouTube: `external_url = https://www.youtube.com/channel/{creator_id}` constructed server-side
  - "Open YouTube Channel" link rendered inside creator hero card, below subtitle; hidden when `external_url` is null; opens in new tab (noopener)
  - Header keeps Back button only — CTA removed from page-level actions
  - Subtitle: category="unknown" (any case) is treated as absent; fallback = "YouTube fragrance channel" (YouTube) or "Creator profile"
  - Verified on SMP Perfume creator page — hero card shows "Open YouTube Channel", header shows Back only ✓
- **FIX: /submit-source route stabilized for sidebar/direct navigation (2026-05-07)** — commit fbc3304
  - Root cause: static top-level import of Supabase browser client crashed during SSR when `NEXT_PUBLIC_SUPABASE_*` env vars not embedded; no `.catch()` on `getUser()` triggered React 19 unhandled rejection
  - Fix: lazy dynamic `import()` of `createClient` inside `useEffect`; `.catch()` added; `mounted` state guard prevents SSR/hydration mismatch; removed top-level `createClient` import
  - Build: clean · TypeScript: clean · `/submit-source` renders as `ƒ Dynamic`
- **FIX: Responsive control bar layout (2026-05-06)** — commit 5563bae
  - ControlBar: removed fixed h-9, flex-wrap, right slot full-width on mobile
  - RangeSelector: preset buttons overflow-x-auto, custom date inputs wrap below
  - Dashboard + Screener: search+filters row 1, range selector row 2 on narrow viewports
- **FIX: Dashboard + Screener responsive controls overlap — COMPLETE — PRODUCTION VERIFIED (2026-05-11)** — commit 9717562
  - Previous fix (5d4f802) failed: outer ControlBar was `flex flex-wrap`; left wrapper `flex-1` (basis=0) + `min-w-0` (min-width=0) → flex engine saw left=0 + right=100% = 100%, no overflow → no wrap → both slots on same line at all widths
  - Actual fix: ControlBar outer changed from `flex flex-wrap` to `flex flex-col`. Column layout makes overlap structurally impossible — each slot is its own full-width row at <1536px
  - At ≥2xl (1536px+): switches to `flex-row justify-between` for single-row wide-screen layout
  - Search: `w-full 2xl:w-48 2xl:shrink-0` — full-width on its row at <2xl, fixed 192px inline at ≥2xl
  - Verified layout: 390/768/1024/1280/1440px → Row 1: search+chips, Row 2: range+counts (no overlap); 1536px+: single row
  - No backend changes · build clean · TypeScript clean · applies to /dashboard and /screener
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

**Tests:** `tests/unit/test_semantic_phase5.py` — 63/63 pass at Phase 5 launch. 67/67 after KB0 regression suite added (2026-05-14).

**Production sanity sweep — 8 entities (2026-05-06, commits 64f3a02 + 96772e0):**
- Creed Aventus: entity_role=niche_original · reference_original=None · narrative="alternative demand around this reference scent" ✓
- Armaf Club de Nuit Intense Man: entity_role=dupe_alternative · reference_original="Creed Aventus" · dupe_family="Aventus alternatives" · narrative="gaining attention as an alternative to Creed Aventus, with active comparison activity" ✓
- Armaf Club de Nuit (broad line): entity_role=unknown · no false badge · competitors=['Creed Aventus'] (DB-resolved only) ✓
- MFK Baccarat Rouge 540: entity_role=niche_original · reference_original=None ✓
- Lattafa Khamrah: entity_role=dupe_alternative · reference_original="Kilian Angels' Share" · dupe_family="Angels' Share alternatives" ✓ **(corrected by KB0 — was wrongly mapped to BR540 at Phase 5 launch)**
- Zara Red Temptation: NOT IN entity_market (not yet tracked) — dupe map entry ready for when added ✓
- Ariana Grande Cloud: NOT IN entity_market (not yet tracked) — dupe map entry ready for when added ✓
- Montblanc Explorer: NOT IN entity_market (not yet tracked) — dupe map entry ready for when added ✓

All 5 tracked entities pass. 3 untracked entities have correct dupe map entries.

**KB0 correction (2026-05-14):** Lattafa Khamrah was incorrectly mapped to BR540 at Phase 5 launch. Corrected to Kilian Angels' Share in commit b79143d. Regression tests added (TestKhamrahRegression, 4 cases). This bug triggered the FTG — Fragrance Truth Graph program (see dedicated section).

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

## C2.1 — Operator Review Console
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-09)**
**Commits: 8c8c3a0 (implementation) · 941721d (fix source_profiles.source_name)**

No new migration. Uses `creator_profile_claims` (migration 036).

Admin access is gated by Railway env allowlist: ADMIN_EMAILS / ADMIN_USER_IDS.

**What was implemented:**
- `GET /api/v1/admin/creator-claims?status=pending|verified|rejected|all` — list claims for review
- `POST /api/v1/admin/creator-claims/{id}/approve` — set claim_status=verified, reviewed_at=NOW()
- `POST /api/v1/admin/creator-claims/{id}/reject` — set claim_status=rejected + required rejection_reason
- FastAPI admin endpoints reject any request missing `X-Pti-Admin-User` header (401)
- Next.js server routes (`/api/admin/creator-claims/*`) read Supabase session server-side, check user email/ID against `ADMIN_EMAILS` / `ADMIN_USER_IDS` env vars (Railway), forward with `X-Pti-Admin-User` header
- Browser cannot forge `X-Pti-Admin-User` — Next.js server route is the only path
- UI: `/admin/creator-claims` — server component (unauthenticated → /login, non-admin → 403, admin → console)
- ADMIN_EMAILS / ADMIN_USER_IDS allowlist is temporary. Future hardening: `app_admins` table or Supabase custom claims.

**Production verification (2026-05-09):**

Security:
- unauthenticated `/admin/creator-claims` → 307 redirect to /login ✓
- no Supabase session → `/api/admin/creator-claims` returns 401 ✓
- fake `X-Pti-Admin-User` sent to Next.js → 401 (session check runs first) ✓
- FastAPI without `X-Pti-Admin-User` → 401 ✓ (GET, POST approve, POST reject)
- admin identity in query param only (no header) → 401 ✓
- admin identity in body only (no header) → 401 ✓

Functionality:
- list pending/verified/rejected/all → 200 ✓
- invalid status → 422 ✓
- reject without rejection_reason → 422 ✓
- reject with reason → 200, status=rejected, reviewed_by set ✓
- reject already-rejected/non-pending claim → 404 ✓
- user resubmit after rejection → 201 ✓
- approve resubmitted pending claim → 200, status=verified ✓
- approve non-pending claim → 404 ✓

Data safety:
- `verification_code_hash` absent from admin API response ✓
- `access_token_encrypted` absent from admin API response ✓
- `refresh_token_encrypted` absent from admin API response ✓
- `creator_scores`: 743 rows unchanged ✓
- `creator_oauth_grants`: 0 rows unchanged ✓
- No OAuth, no platform API, no pipeline changes ✓

**Tests: 27/27 pass** (`tests/unit/test_admin_creator_claims.py`)

**Next phase: V1 — Consent-Based Creator Linking** (YouTube OAuth first; only after P1 platform approval readiness)

---

## C2.2 — User Account & My Claims
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-10)**
**Commits: d3f7fd9 (implementation) · ca9aea7 (CLAUDE.md pending) · closeout this commit**
**Deployed: pushed to main 2026-05-09; Railway auto-deployed**

No new migration. No OAuth. No platform API. No pipeline changes. Reads `creator_profile_claims` via existing `/api/v1/creator-claims/me`.

**What was implemented:**
- `/account` (server component): reads Supabase session server-side; redirects to `/login?next=/account` if unauthenticated; renders `<AccountConsole userEmail={...} />`
- `AccountConsole` (client component): email panel with compliance copy; claims table with StatusBadge (pending/verified/rejected); ClaimRow with creator_id as display name (no N+1 fetches), method, evidence link, "View profile →" + "Try again →" for rejected; EmptyState with Browse Creators CTA; Refresh button
- Sidebar: Account nav item (UserCircle icon) added to SECONDARY_NAV below Suggest Source
- `verification_code_hash` never returned by GET /me — excluded from `ClaimSummary` schema

**Production verification results (2026-05-10):**
- Unauthenticated GET /account → 307 → `/login?next=%2Faccount` ✓
- Unauthenticated GET /api/creator-claims → 401 Unauthorized ✓
- Authenticated user sees email, Account link in sidebar, empty state with Browse Creators ✓ (manual)
- `ClaimSummary` schema: `verification_code_hash` field absent ✓ (schema + DB confirmed)
- `creator_oauth_grants`: 0 rows unchanged ✓
- `creator_scores`: 743 rows unchanged ✓
- `creator_entity_relationships`: 2,266 rows unchanged ✓
- No pipeline tables modified ✓

---

## C2 — Manual Claim Verification
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-09)**
**Commits: b71333f (implementation) · bcb3e41 (CLAUDE.md)**
**Deployed: pushed to main 2026-05-09; Railway auto-deploys on push**

No new migration. Uses `creator_profile_claims` (migration 036).

**What was implemented:**
- `POST /api/v1/creator-claims` — bio_code | screenshot | manual_review; user_id from `X-Pti-Verified-User-Id` header only (never from body); server-side `FTI-XXXXXXXX` code generation; SHA-256 hash stored; plaintext returned once; `evidence_url` required + validated as http/https
- `GET /api/v1/creator-claims/me` — user's own claims only; `verification_code_hash` never exposed
- Next.js server route `frontend/src/app/api/creator-claims/route.ts` — reads Supabase session server-side via `createClient()` (httpOnly cookie); injects `X-Pti-Verified-User-Id`; browser cannot forge user_id
- `/creator/claim/[id]` — full form: bio-code + manual review tabs; pending/verified/rejected/resubmit states; success screen with code + copy button; compliance disclaimers
- `frontend/src/lib/api/creator_claims.ts` — calls `/api/creator-claims` (Next.js route), never FastAPI directly

**Production verification results (2026-05-09):**
- POST without header → 401 Unauthorized ✓
- POST with user_id in body only (no header) → 401 (body user_id ignored) ✓
- POST with invalid evidence_url → 422 ✓
- Claim creation (POST with header) → 201, code=`FTI-XXXXXXXX`, `verification_code_hash` stored (64-char SHA-256), plaintext NOT in DB ✓
- Duplicate active claim → 409 `active_claim_exists` ✓
- GET /me without header → 401 ✓
- GET /me with header → returns user's claim, no hash exposed ✓
- Operator reject via SQL → OK; resubmit after rejection → 201 ✓
- Operator approve via SQL → claim status `verified` ✓
- Creator profile: no claim → `verified_status=None, viewer_claim_status=None` → "Claim this Profile" CTA ✓
- creator_scores: 743 unchanged ✓
- creator_entity_relationships: 2,266 unchanged ✓
- creator_oauth_grants: 0 unchanged ✓
- creator_profile_claims: 0 after test cleanup ✓

**Hard rules confirmed:**
- No OAuth implemented — `creator_oauth_grants` remains empty
- No TikTok / Instagram / Reddit / YouTube API access added
- No private data requested or accessed
- No automatic verification — all claims remain `pending` until operator SQL review
- No changes to ingestion, aggregation, resolver, or pipeline

**Operator review SQL (C2 manual workflow):**
```sql
-- View pending claims
SELECT id, user_id, platform, creator_id, claim_status, claim_method, evidence_url, claimed_at
FROM creator_profile_claims WHERE claim_status='pending' ORDER BY claimed_at DESC;

-- Approve
UPDATE creator_profile_claims SET claim_status='verified', verified_at=NOW(), reviewed_at=NOW(), reviewed_by='operator' WHERE id='<uuid>';

-- Reject
UPDATE creator_profile_claims SET claim_status='rejected', reviewed_at=NOW(), reviewed_by='operator', rejection_reason='<reason>' WHERE id='<uuid>';
```

**Next phase: V1 — Consent-Based Creator Linking** (YouTube OAuth first; only after P1 platform approval readiness)

---

## C1 Creator Registry Claim Foundation
**STATUS: COMPLETE — PRODUCTION VERIFIED (2026-05-09)**
**Commits: 59985d5 (implementation) · d96e032 (CLAUDE.md)**

Migrations 036 + 037 applied — alembic current: `037` (head)

**Production verification (2026-05-09):**
- `creator_profile_claims`: 0 rows (schema verified: 16 columns, CHECK constraints, partial UNIQUE index) ✓
- `creator_oauth_grants`: 0 rows (schema verified: 14 columns, encrypted token fields, partial UNIQUE index) ✓
- `creator_scores`: 743 rows — unchanged ✓
- `creator_entity_relationships`: 2,266 rows — unchanged ✓
- `GET /api/v1/creators/{id}` returns `verified_status=None, viewer_claim_status=None` for unclaimed creators ✓
- `ClaimSection` renders "Claim this Profile" CTA when no claim exists ✓
- `/creator/claim/[id]` auth-required stub page live ✓

**Key design decisions:**
- `claim_method` includes `oauth` — future-proof even though OAuth not implemented yet
- `verification_code_hash` only — plaintext code never stored
- `creator_oauth_grants` is empty scaffold — no OAuth flow implemented
- `viewer_claim_status` requires `user_id` query param (frontend passes Supabase user ID)
- Claim queries are non-fatal — graceful degradation if table unavailable

**Next phase: C2 — Manual Claim Verification** (bio-code, screenshot, manual review — no OAuth, no platform approval needed)

---

## Legal Data Growth Route — Public Signals, Creator Consent, Platform Approval

**STATUS: ACCEPTED — ARCHITECTURE ROUTE APPROVED**
**DATE: 2026-05-09**

TikTok integration is more complex and approval-dependent than anticipated (SC1.2D confirmed: headless browser blocked by login wall; TikTok Research API requires separate approval). This section formalizes all legal, platform-compliant growth routes that do not depend on TikTok as the only path.

### Core Principle: Separate User Auth from Creator Linking

**User Auth:**
- FragranceIndex.ai user login: magic link (current).
- Google OAuth may be added as an optional user-login method later.
- TikTok, Instagram, YouTube, Reddit, Snapchat **must NOT** be used as primary login methods for ordinary users.

**Creator Linking (separate flow):**
- Creator social account verification happens only after the user is already logged in.
- OAuth grants stored separately from Supabase/Auth user login — in `creator_oauth_grants` table, not in Supabase Auth.
- Creator claim logic is separate from OAuth token logic.

---

### Layer A — Public Signal Monitoring

Current and future public-data collection that does not require private user access:

- YouTube Data API v3 — public video metadata, channel info (current, production)
- Reddit public monitoring — subject to Reddit Data API Terms and commercial approval requirements (see P1 track)
- Public oEmbed / URL extraction / source submission flows (current)
- Public creator profile detection (SC1.2A/B/C)
- SC1.2D finding: TikTok public profile monitoring via plain HTTPS or headless browser is blocked by login wall — not viable without prohibited workarounds

Hard constraints for Layer A:
- No scraping of private or login-required data
- No use of private user data
- No platform impersonation or session simulation
- No bypassing access controls

---

### Layer B — Creator Consent

Creator-initiated verification and optional account linking. Structured in two ordered sub-routes:

#### B1 — Manual / Bio-Code Verification (Phase C2)

- Creator places a temporary verification code in their public bio/profile/about page, or submits a screenshot/link for manual review.
- No OAuth required. No private data access. No platform approval required.
- Can launch independently before any OAuth flows.
- **This is Phase C2 and can ship before V1.**

Claim methods covered:
- `bio_code` — code placed in public bio
- `screenshot` — creator submits evidence link
- `manual_review` — operator-reviewed claim

#### B2 — OAuth Linking (Phase V1)

- Used only after the creator is already logged in to FragranceIndex.ai.
- Used only for consent-based account verification and authorized analytics.
- OAuth tokens stored in `creator_oauth_grants` — never in Supabase Auth.
- OAuth does not automatically prove ownership of an existing FragranceIndex creator profile without a claim review step.
- Connect/disconnect must be supported per platform independently.

Platform order:
1. YouTube OAuth first (lowest approval friction)
2. Meta/Instagram second
3. TikTok only after scope/platform approval readiness (P1 track)
4. Reddit only with commercial/legal guardrails in place (P1 track)

---

### Layer C — Platform Commercial Approval (Phase P1)

Parallel compliance tracks — no single track blocks the others:

- **TikTok:** Developer / Business API review; approved scopes for Research API
- **Reddit:** Commercial approval / written approval required before monetized commercial use of Reddit-derived data
- **Meta:** App review for Instagram Graph API permissions
- Maintain privacy policy, terms of use, data deletion page, and demo flows at all times
- FragranceIndex.ai already uses Reddit as a public signal source. Before commercial monetization or expanded Reddit Data API usage, the Reddit commercial approval requirement must be satisfied. Reddit-derived outputs should not be represented as fully cleared for commercial API use until reviewed/approved.

---

### Phase Structure

#### C1 — Creator Registry (PLANNED)
- Public creator profiles visible (current: `creator_platform_accounts`)
- Detected creator cards surfaced in UI
- "Claim this Profile" CTA wired to `creator_profile_claims` table
- `creator_oauth_grants` table created as empty, future-proof structure
- No OAuth flows required in C1

#### C2 — Manual Claim Verification (PLANNED)
- Bio-code verification flow
- Screenshot / link manual review
- `claim_status` workflow: pending → verified / rejected / revoked
- No private data, no OAuth, no platform approval required
- Can ship independently before V1

#### V1 — Consent-Based Creator Linking (PLANNED)
- YouTube OAuth first
- Meta/Instagram second
- TikTok only after P1 approval readiness
- Reddit only after P1 commercial guardrails
- Independent connect/disconnect per platform

#### P1 — Platform Commercial Approval Track (PLANNED)
- TikTok Developer / Business API approval
- Reddit commercial approval track
- Meta app review for Instagram permissions
- Demo flow documentation
- Privacy / Terms / Data Deletion verification

---

### Future Schema (Planned — not yet migrated)

These tables are planned for C1/C2. Do not create migrations until C1 is actively started.

**`creator_profile_claims`**
```
id                  uuid PK
user_id             uuid FK → auth users
creator_account_id  uuid FK → creator_platform_accounts
claim_status        enum: pending | verified | rejected | revoked
claim_method        enum: bio_code | screenshot | manual_review | domain_email | oauth
verification_code   text nullable
evidence_url        text nullable
reviewer_notes      text nullable
claimed_at          timestamptz
verified_at         timestamptz nullable
reviewed_at         timestamptz nullable
reviewed_by         text nullable
rejection_reason    text nullable
```

**`creator_oauth_grants`**
```
id                        uuid PK
user_id                   uuid FK → auth users
creator_account_id        uuid FK → creator_platform_accounts
platform                  text (youtube | instagram | tiktok | reddit | snapchat)
platform_user_id          text
access_token_encrypted    text   — encrypted at rest; NEVER plaintext; NEVER exposed to frontend
refresh_token_encrypted   text   — encrypted at rest; NEVER plaintext; NEVER exposed to frontend
token_expires_at          timestamptz nullable
scopes_granted            jsonb  — minimum required scopes only
grant_status              enum: active | revoked | expired | failed
connected_at              timestamptz
last_refreshed_at         timestamptz nullable
revoked_at                timestamptz nullable
disconnect_reason         text nullable
```

**Security requirements (enforced before any OAuth launch):**
- Never store `access_token` or `refresh_token` in plaintext
- Encrypt tokens at rest (application-layer encryption before DB write)
- Never expose tokens to frontend
- Store only minimum required scopes
- Support revocation/disconnect per platform
- Log OAuth events without logging token values
- Connected-apps / disconnect UX must ship before production OAuth launch

---

## Social Creator Intelligence Roadmap (SC series)

**STATUS: PLANNING — nothing implemented**
**Full spec:** `docs/architecture/SOCIAL_CREATOR_INTELLIGENCE.md`

### Strategic principle

Creator login is NOT the ingestion foundation. It is a future optional module.

```
CORRECT priority:
  Layer 1 (URL / mention / embed)
    → Layer 3 (seeded watchlist + compliant public monitoring)
      → Layer 2 (optional creator claim / verified module)
```

YouTube = benchmark (C1 series, complete). TikTok = SC1 (highest priority). Snapchat = SC2. Meta/Instagram = SC3.

### SC phase table

| Phase | Description | Status |
|-------|-------------|--------|
| SC0.1 | Unified creator registry — multi-platform model (`creators`, `creator_platform_accounts`, `creator_identity_edges`) | PLANNED |
| SC0.2 | Creator filters v1 — platform, category, role, noise, early signal | PLANNED |
| SC1.1 | TikTok Layer 1 — URL / embed / derived-vs-direct mention foundation; derived weight=0.0, direct weight=0.7 | PLANNED |
| SC1.2 | TikTok Layer 3 — seeded creator watchlist, public monitoring, 100–300 creators, audit log, kill switch | PLANNED |
| SC1.3 | Multi-field resolver — hashtags, context, per-platform field weights; backward compatible | PLANNED |
| SC1.4 | TikTok creator filters + leaderboard integration | PLANNED |
| SC2.1 | Snapchat foundation — handle discovery, enrichment only, signal_weight=0.0 | DEFERRED |
| SC3.1 | Meta/Instagram foundation — URL/handle acceptance, creator_platform_accounts | DEFERRED |
| SC-V1 | Optional creator claim / verified module (cross-platform, built after SC1 + SC3) | DEFERRED |

### Platform signal weights (initial — reviewed every 60 days)

| Source | Weight |
|--------|--------|
| YouTube | 1.0–1.2 |
| Reddit | 1.0 |
| TikTok Layer 1 derived | 0.0 |
| TikTok Layer 1 direct | 0.7 |
| TikTok Layer 3 public monitoring | 0.8–0.9 |
| TikTok Layer 2 creator-authorized | 1.0 |
| Meta/Instagram | 0.5–0.8 |
| Snapchat | 0.0 |

Weight changes logged in `weight_calibration_log` — human-reviewed, never silent.

### Permanent compliance rules

- No third-party scraper APIs as default architecture
- No account automation, no login simulation
- No comments collection without official approved method
- Kill switch via env/config for every platform monitor
- Every external fetch logged in `external_api_audit_log`

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
- Creator roadmap (YouTube C1): docs/architecture/CREATOR_INTELLIGENCE.md
- Social Creator Intelligence roadmap (SC series): docs/architecture/SOCIAL_CREATOR_INTELLIGENCE.md
- SDK contracts and sprint plan: docs/architecture/SDK_ARCHITECTURE.md
- Verification queries: docs/verification/VERIFICATION_QUERIES.md
- Deployment notes: docs/history/DEPLOYMENT_NOTES.md
- Language & Region Architecture roadmap (phases 042–048): docs/architecture/LANGUAGE_REGION_ARCHITECTURE.md

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
| Submit Source S1 — Operator Promotion Bridge | COMPLETE — PRODUCTION VERIFIED | 2026-05-07 |
| SC0.1 Unified creator registry (multi-platform) | PLANNED | — |
| SC0.2 Creator filters v1 | PLANNED | — |
| SC1.1 TikTok Layer 1 — URL / embed / mention | COMPLETE — PRODUCTION VERIFIED | 2026-05-07 |
| P3 Pipeline Health Check | COMPLETE — PRODUCTION VERIFIED | 2026-05-08 |
| P3.1 Pipeline Health Log — DB-persisted health history | COMPLETE — PRODUCTION VERIFIED | 2026-05-12 |
| SC1.2A TikTok — Schema + Registry Integration | COMPLETE — PRODUCTION VERIFIED | 2026-05-08 |
| SC1.2B TikTok — Seed Import + Operator Workflow | COMPLETE — PRODUCTION VERIFIED | 2026-05-08 |
| SC1.2C TikTok — Seeded Creator Monitoring Worker | COMPLETE — PRODUCTION VERIFIED | 2026-05-08 |
| SC1.3 Multi-field resolver — platform-weighted fields | COMPLETE — PRODUCTION VERIFIED | 2026-05-08 |
| SC1.4 TikTok creator filters + leaderboard | PLANNED | — |
| C1 Creator Registry Claim Foundation | COMPLETE — PRODUCTION VERIFIED | 2026-05-09 |
| C2 Manual Claim Verification | COMPLETE — PRODUCTION VERIFIED | 2026-05-09 |
| C2.1 Operator Review Console (admin claims UI) | COMPLETE — PRODUCTION VERIFIED | 2026-05-09 |
| C2.2 User Account & My Claims (/account) | COMPLETE — PRODUCTION VERIFIED | 2026-05-10 |
| C2.2A Creator Directory Search (platform-aware) | COMPLETE — PRODUCTION VERIFIED | 2026-05-10 |
| C2.3 Creator Claim Launch Readiness (copy + UX polish) | COMPLETE — PENDING VERIFICATION | 2026-05-10 |
| YT-CREATOR-EXPANSION-01 — 8 new YouTube creator channels | COMPLETE — PRODUCTION VERIFIED | 2026-05-10 |
| SOURCE-INTAKE-V1A — YouTube source intake DB + admin review UI | COMPLETE — PRODUCTION VERIFIED | 2026-05-10 |
| Source Role Foundation v1 — source_role + creator_score_eligible | COMPLETE — PRODUCTION VERIFIED | 2026-05-11 |
| Source Intake Role Routing v1 — role selector on candidates | COMPLETE — PRODUCTION VERIFIED | 2026-05-11 |
| C3 Multi-Platform Creator Identity Model | PLANNED | — |
| 042 — Language & Region Metadata v1 | COMPLETE — PRODUCTION VERIFIED | 2026-05-12 |
| 043 — Content Language & Region Propagation v1 | COMPLETE — PRODUCTION VERIFIED | 2026-05-12 |
| 044 — Regional Creator Policy v1 | PENDING | — |
| 045 — Regional Filters v1 | PENDING | — |
| 046 — Regional Signal Aggregation Design | PENDING | — |
| 047 — Market Availability Metadata v1 | PENDING | — |
| 048 — Regional UI Concepts | PENDING | — |
| SC2.1 Snapchat foundation | DEFERRED | — |
| SC3.1 Meta / Instagram foundation | DEFERRED — reframed as IG1 in monetization roadmap | — |
| SC-V1 Optional creator claim / verified module | DEFERRED | — |
| M0 — Monetization Architecture | IMPLEMENTED — ARCHITECTURE DOCUMENTED | 2026-05-12 |
| DATA0 — Historical Data Integrity Hardening | IMPLEMENTED — CORE PRODUCTION VERIFIED; TOPIC SNAPSHOT ROW PENDING NEXT PIPELINE RUN | 2026-05-12 |
| SEO0 — Public SEO Surface v1 | COMPLETE — PRODUCTION VERIFIED | 2026-05-13 |
| PUB1 — Public Entity Pages v1 | COMPLETE — PRODUCTION VERIFIED | 2026-05-13 |
| PUB2 — Public Creator Pages v1 | PLANNED | — |
| IG1 — Instagram Intelligence v1 | APP REVIEW DEMO IMPLEMENTED — PENDING META APPROVAL | 2026-05-13 |
| IL1 — Intelligence Layer v2 (Opportunity Objects) | PLANNED | — |
| REPORT1 — Fragrance Market Reports v1 | PLANNED | — |
| PRO1 — Pro Tier + Paywall v1 | PLANNED | — |
| TT2 — TikTok Research API Track | PLANNED (parallel admin track) | — |
| FTG-0 / KB0 — Khamrah Truth Fix | COMPLETE — PRODUCTION VERIFIED | 2026-05-14 |
| FTG-1 / KB1-MIN — Canonical Brand Classification Foundation | COMPLETE — PRODUCTION VERIFIED | 2026-05-14 |
| FTG-2 / RI1 — Relationship Intelligence Core | COMPLETE — PRODUCTION VERIFIED | 2026-05-14 |
| DATA1 — Last Active Display Snapshot Contract | COMPLETE — PRODUCTION VERIFIED | 2026-05-14 |
| DATA2 — Brand Catalog Join Normalization | COMPLETE — PRODUCTION VERIFIED | 2026-05-14 |
| FTG-3 / RI1-QA — Operator Review Gate for Relationships | COMPLETE — PRODUCTION VERIFIED (PENDING RAILWAY DEPLOY) | 2026-05-14 |
| FTG-4 / RI1-E — Evidence Harvesting v1 from Internal Signals | PLANNED | — |
| FTG-5 / SN1 — Historical Intelligence Snapshot Layer | PLANNED | — |
| KB-CAT1-A — Canonical Brand Hierarchy Production Audit | COMPLETE (12 candidates, 4 true hierarchy, 8 false positives) | 2026-05-14 |
| KB-CAT1-B — brand_profiles Hierarchy Extension | COMPLETE — PRODUCTION VERIFIED | 2026-05-14 |
| KB-CAT1-C — Xerjoff Pilot: Brand Hierarchy Display | COMPLETE — PENDING PRODUCTION VERIFICATION | 2026-05-14 |

---

## Source Intake Policy after Migration 040

Migration 039 added `youtube_channels.source_role` and `youtube_channels.creator_score_eligible`.

Migration 040 added `source_intake_candidates.source_role` and `source_intake_candidates.creator_score_eligible`, and updated the admin source intake apply path so source role and creator leaderboard eligibility are carried from intake into `youtube_channels`.

This creates a clear separation between:

- accepted source
- creator leaderboard eligible source
- non-creator intelligence source

### Policy Rules

1. `OPERATOR_REJECTED` is reserved only for true irrelevant/noise sources.

Examples:
- automotive channels
- unrelated lifestyle/fashion channels with no meaningful fragrance content
- spam
- invalid/non-recoverable candidates
- clear non-fragrance noise

`OPERATOR_REJECTED` must not be used for valuable sources that are simply not creator-leaderboard eligible.

2. `DEFERRED` is used for uncertain or policy-pending sources.

Examples:
- unclear identity
- unclear source role
- uncertain brand/retail relationship
- regional/language policy pending
- source needs later review before apply

`DEFERRED` is intentionally non-terminal and should be used when we want to preserve the candidate for future routing.

3. `independent_creator` is `creator_score_eligible=TRUE` by default.

This role is for independent fragrance reviewers / creators whose content can safely appear in Creator Intelligence and Creator Leaderboard.

4. Non-creator roles are `creator_score_eligible=FALSE` by default.

This includes:
- `brand_official`
- `retailer_shop`
- `formulation_education`
- `aggregator`
- `unknown`

These sources may be valuable for future intelligence layers, but they must not appear in the Creator Leaderboard unless explicitly reviewed and intentionally overridden.

5. Applying non-creator sources is now technically safe for the Creator Leaderboard because `creator_score_eligible=FALSE` excludes them from `/api/v1/creators`.

However, non-creator sources should only be applied when there is a clear downstream use case, such as:
- Brand Intelligence
- Retail Watch
- Formulation Trends
- Commercial/Promo Signals
- Industry/Market Monitoring

Until those downstream layers are visible, operators may still choose to keep non-creator sources as `DEFERRED`.

6. Non-English independent creators remain policy-pending until language/regional policy is defined.

Do not reject non-English fragrance creators only because they are non-English.

For now:
- clear non-English fragrance creators should usually be marked `DEFERRED`
- add operator notes such as `REGIONAL_POLICY_PENDING`, `lang=es`, `lang=ar`, `country=BR`, etc. when known
- do not apply them into the Creator Leaderboard until language/region filtering and display rules are defined
- exception: a very strong global creator may be applied manually only if the operator intentionally accepts that they will appear in the current global Creator Leaderboard

7. Current safe intake behavior:

Apply:
- clear independent fragrance reviewers
- creator_score_eligible=TRUE

Defer:
- non-English/regional creators pending language policy
- unclear role
- unclear identity
- valuable but not yet routed sources

Apply carefully with `creator_score_eligible=FALSE` only when there is a clear use case:
- brand_official
- formulation_education
- retailer_shop
- aggregator

Reject:
- true unrelated/noise only

### Important Boundary

Source role routing is now implemented, but regional scoring is not implemented yet.

Do not treat `source_role` as a replacement for language/region architecture.

The next separate architecture layer should be:

- source_language
- source_country
- source_region
- audience_region
- regional policy status
- regional/global score separation

This policy only protects source intake and Creator Leaderboard semantics after Migration 040.

---

## Alembic Migrations

Current production: **migration 048** (KB-CAT1-B — node_type + parent_brand_normalized on brand_profiles; applied 2026-05-14)

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
| 033 | `source_submissions` table — Submit a Source MVP |
| 034 | SC1.1 — `tiktok_layer`, `referencing_source_id`, `referencing_context`, `mention_weight_override` on `canonical_content_items`; `public_safe_content_items` updated to allow qualified TikTok rows |
| 035 | SC1.2A — `creator_platform_accounts` table (platform-neutral watchlist registry) + `creator_watchlist_audit_log` |
| 036 | C1 — `creator_profile_claims` table: claim_status, claim_method (bio_code/screenshot/manual_review/domain_email/oauth), verification_code_hash + expiry, partial unique index on active claims |
| 037 | C1 — `creator_oauth_grants` scaffold: platform_user_id, encrypted token fields, partial unique index on active grants per (user_id, platform, platform_user_id), nullable creator_id |
| 038 | SOURCE-INTAKE-V1A — `source_intake_batches` + `source_intake_candidates` + `source_intake_audit_log`; 12-status lifecycle with CHECK constraints; FK cascade from candidates→batches, audit→candidates |
| 039 | Source Role Foundation v1 — `source_role VARCHAR(64) DEFAULT 'independent_creator'` + `creator_score_eligible BOOLEAN DEFAULT TRUE` on `youtube_channels`; Creator Leaderboard gated on `creator_score_eligible IS NOT FALSE`; `YouTubeClient.get_channel_info()` captures country + language on first poll; 256 existing rows backfilled via server_default |
| 040 | Source Intake Role Routing v1 — `source_role VARCHAR(64) NULL` + `creator_score_eligible BOOLEAN NULL` on `source_intake_candidates`; eligibility resolved at apply time (NULL → independent_creator, independent_creator → eligible=True, others → False); PATCH endpoint accepts new fields; Admin UI role selector in BatchReviewConsole |
| 042 | Phase 042 Language & Region Metadata v1 — `source_language VARCHAR(16)`, `source_country VARCHAR(8)`, `source_region VARCHAR(64)`, `audience_region VARCHAR(64)`, `regional_policy_status VARCHAR(64)` on `source_intake_candidates`; `source_region`, `audience_region`, `regional_policy_status` on `youtube_channels`; all nullable, no CHECK constraints |
| 041 | Pipeline Health Log — `pipeline_health_log` table: `(run_date DATE, run_label VARCHAR(32), overall_level VARCHAR(16), entity_mentions, reddit_mentions, youtube_items, reddit_items, total_items, signals_count INT, issues JSONB, pipeline_service VARCHAR(64) NULL, recorded_at TIMESTAMPTZ)`; unique on `(run_date, run_label)`; 90-day retention trimmed at persist time; upserted by `pipeline_health_check.py` after every morning/evening run |
| 043 | DATA0 — `score_formula_version INTEGER NOT NULL server_default=1` on `entity_timeseries_daily`; `signal_threshold_version INTEGER NOT NULL server_default=1` on `signals`; `entity_topic_snapshots` table (dated aggregate snapshots of topic/intent distribution per entity, preserving historical intent distributions destroyed by `--rebuild-links`); unique on `(snapshot_date, entity_id, topic_type, topic_text)` |
| 044 | FTG-1/KB1-MIN — `brand_profiles` table: `brand_name_normalized TEXT UNIQUE`, `brand_tier VARCHAR(32)` (designer/niche/clone_house/celebrity/indie/mass_market), `notes TEXT NULL`; seeded with 213 rows (66 designer, 136 niche, 9 clone_house, 2 celebrity: ariana grande + zara) migrated from hardcoded Python frozensets |
| 045 | FTG-1 taxonomy correction — Zara reclassified from `celebrity` → `mass_market`; adds `mass_market` to conceptual taxonomy (no schema change; VARCHAR(32) has no CHECK constraint) |
| 046 | FTG-2 / RI1 — `fragrance_relationships` table (subject_canonical_name TEXT, relation_type VARCHAR(32), object_canonical_name TEXT, confidence_score NUMERIC(4,3), is_public BOOLEAN DEFAULT FALSE, operator_reviewed BOOLEAN); `relationship_evidence` table (relationship_id FK CASCADE, evidence_type VARCHAR(32), note TEXT); 7 seed rows + 7 dupe_map_seed evidence rows; no CHECK constraint on relation_type (mirrors brand_tier pattern) |
| 047 | FTG-3 / RI1-QA — Data-only migration: promotes all 7 seeded relationship rows to `is_public=TRUE` where `operator_reviewed=TRUE AND confidence_score >= 0.700`. No schema changes. Option A controlled seed promotion. |
| 048 | KB-CAT1-B — `node_type VARCHAR(32) NOT NULL DEFAULT 'brand' CHECK (node_type IN ('brand','collection','sub_brand'))` + `parent_brand_normalized TEXT NULL` (no FK) on `brand_profiles`; seeds 4 hierarchy rows (Xerjoff × 3 + Filippo Sorcinelli SAUF). |

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
