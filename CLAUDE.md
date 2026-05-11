# FragranceIndex.ai / FTI Market Terminal — Operating Guide

## Read This First
- This file is the short operating index.
- Do not expand historical docs unless the task requires it.
- Use targeted grep/sed reads, not cat.
- For phase history, read only the relevant file/section.
- Keep reports concise.

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

## Active Roadmap

**Language & Region Architecture**
Full roadmap: `docs/architecture/LANGUAGE_REGION_ARCHITECTURE.md`
Phase 042 — COMPLETE — PRODUCTION VERIFIED
Phase 043 — IMPLEMENTED — PENDING PIPELINE VERIFICATION — commit `71be8f4` — code-only, no migration, no backfill — 44/44 new + 117/117 existing tests pass
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
  - **Next step:** Scheduled pipeline will poll 41 new channels; mark PRODUCTION_VERIFIED after confirmed ingestion

- **YT-CREATOR-EXPANSION-01 — COMPLETE — PRODUCTION VERIFIED (2026-05-10)** — commit 914652e — Added 8 verified fragrance YouTube creator channels (189 → 197 total). Scripts: `scripts/youtube/verify_candidate_channels.py` (resolution + activity check + dedup), `scripts/youtube/seed_yt_creator_expansion_01.py` (idempotent INSERT). Reports: `reports/youtube_candidate_intake_2026-05-10.{md,csv,json}`. Reviewed 20 candidates: 8 ADD / 3 SKIP_DUPLICATE / 4 SKIP_INACTIVE_30D / 5 NEEDS_OPERATOR_REVIEW. All 8 polled and ingested (89 new content items). Channels added: Christopher Lee Fragrances (412K, tier_2), Soki London (151K, tier_2), The Niche Fragrance Collector (136K, tier_2), The Scented (126K, tier_2), Paulina&Perfumes (85K, tier_2), Gabby Loves Perfumes (34K, tier_3), Seldomly Often (22K, tier_3), Des Paons Dansent Cent Heures (5K, tier_4).
- **SC1.2A+B TikTok Watchlist Registry — COMPLETE (2026-05-08)** — commit pending — migration 035: `creator_platform_accounts` (platform-neutral, unique on `(platform, platform_handle)`) + `creator_watchlist_audit_log`. Service: `perfume_trend_sdk/services/tiktok_watchlist.py` (add_account, list_accounts, get_account, change_status, bulk_import). Handles: bare/`@handle`/profile URL normalized; video URLs rejected. Statuses: pending_review|active|paused|rejected|error. API: `GET/POST /api/v1/tiktok-watchlist`, `GET/PATCH /{handle}`, `GET /{handle}/audit`. Seed script: `python3 -m perfume_trend_sdk.scripts.seed_tiktok_creators --file CSV [--dry-run] [--activate]`. Production: 6 creators seeded, 9 audit entries, duplicate protection verified, YouTube creator_scores (711 rows) untouched. 44/44 tests pass.
- **SC1.2C TikTok Seeded Creator Monitoring Worker — COMPLETE (2026-05-08)** — `perfume_trend_sdk/jobs/monitor_tiktok_seeded_creators.py` + `perfume_trend_sdk/ingest/tiktok_page_parser.py`. Kill switch: `TIKTOK_PUBLIC_MONITORING_ENABLED=false` (default). Reads active TikTok creators, fetches profile pages via plain HTTPS (no auth/cookies/automation), extracts follower_count/video_count from `webapp.user-detail.userInfo`. Updates `creator_platform_accounts.follower_count + last_checked_at`. Writes `creator_watchlist_audit_log`. Does NOT create entity_mentions or canonical_content_items. **TikTok SSR limitation (verified 2026-05-08):** `itemList` is ALWAYS empty in server-rendered HTML — video discovery is not possible via simple HTTP. Worker logs `TIKTOK_MONITOR_CREATOR_WARNING video_list_unavailable=true` on every run until a future approved method (TikTok Research API or reviewed browser-based approach) is implemented. Verified on `@rawscents`: followers=2 updated in DB, audit log written, 0 entity_mentions created. 24/24 tests pass.
- **SC1.3 Multi-field Resolver — COMPLETE — PRODUCTION VERIFIED (2026-05-08)** — commit ee1d8ba — `perfume_trend_sdk/resolvers/perfume_identity/multi_field_resolver.py`. Feature flag: `MULTI_FIELD_RESOLVER_ENABLED=true` (Railway generous-prosperity). Platform-specific field weights: YouTube title(1.0)/description(0.5)/hashtags(0.3); Reddit body(1.0)/title(0.7); TikTok derived referencing_context(1.0)/hashtags(0.5)/description(0.3)/title(0.2); TikTok direct user_context(1.0)/hashtags(0.6)/description(0.4)/title(0.5). Confidence threshold 0.3. TikTok generic title protection + YouTube title noise filter. 67/67 tests pass. **Replay (2026-05-04–07):** old=624, new=807, +183 resolved, 0 regressions. **Production pipeline (2026-05-08) verified:** PIPELINE_HEALTH_OK · entity_mentions=180 (baseline 183-189) · signals=142 (baseline 113-216) · resolved_signals 1.1-mf=558, 1.1=74 · content_items=1203 (yt=997, reddit=206) · public_safe views 2318/4976/9644 · dashboard 200 OK (2373 entities, 19 breakouts) · no new false positives (noise aliases pre-existing, within historical range).
- **P3 Pipeline Health Check — COMPLETE (2026-05-08)** — commit 58ff5c6 — `perfume_trend_sdk/jobs/pipeline_health_check.py` runs at end of morning + evening pipelines. 4 checks: entity_mentions (CRITICAL<50/WARNING<100), Reddit entity_mentions (WARNING morning=0/CRITICAL evening=0), content items by platform, signals count. Markers: `PIPELINE_HEALTH_OK/WARNING/CRITICAL`. Exit always 0. Verified retroactively: 05-06 collapse correctly fires `PIPELINE_HEALTH_WARNING` (reddit_items=0, mentions=64). 21/21 tests pass.
- **Phase 042 — Language & Region Metadata v1 — COMPLETE — PRODUCTION VERIFIED (2026-05-11)** — migration `alembic/versions/042_language_region_metadata.py` · implementation commit `3702a9c` · completion fix commit `436fd6c`. Adds 5 nullable metadata fields to `source_intake_candidates` (`source_language`, `source_country`, `source_region`, `audience_region`, `regional_policy_status`) and 3 new columns to `youtube_channels` (`source_region`, `audience_region`, `regional_policy_status`). Apply path carries all 5 into the YouTube source registry: `source_language` → `language`, `source_country` → `country` (existing columns, migration 023), plus 3 new columns. PATCH endpoint accepts and saves all 5. CandidateRow GET exposes all 5. Admin UI: Language & Region section in BatchReviewConsole per candidate (lang/country inputs, region/audience/policy dropdowns, Save Metadata button). No regional scoring. No regional leaderboard. No public filters. No canonical_content_items propagation (Phase 043). Creator Leaderboard behavior unchanged. 52/52 tests pass.
- **P3.1 Pipeline Health Log — COMPLETE — PRODUCTION VERIFIED (2026-05-11)** — commit 8b49fd2 — `alembic/versions/041_pipeline_health_log.py` · `pipeline_health_log` table. Upserts one row per `(run_date, run_label)` after each health check run. ON CONFLICT (run_date, run_label) DO UPDATE — idempotent re-runs overwrite the row without duplicating. Trims rows older than 90 days at persist time (no separate cron). `pipeline_service` captured from `PIPELINE_SERVICE` env var (operator-set Railway override) or `RAILWAY_SERVICE_NAME` (Railway built-in), NULL if neither set. run_label supports: morning | evening | manual | backfill | unknown — no CHECK constraint. Pipeline scripts already pass `--run-label morning` / `--run-label evening` — no script changes needed. Ad-hoc and backfill runs use `--run-label manual`. Persist errors are non-fatal (logged as WARNING, pipeline continues). Admin UI deferred. 30/30 tests pass.
  **Operational note:** After the next scheduled morning or evening pipeline run, verify that a new row appears: `SELECT run_date, run_label, overall_level, pipeline_service FROM pipeline_health_log ORDER BY recorded_at DESC LIMIT 5;`
- **Phase 043 — Content Language & Region Propagation v1 — IMPLEMENTED — PENDING PIPELINE VERIFICATION (2026-05-11)** — commit `71be8f4` — code-only, no migration, no backfill. `normalizer.py`: added `_COUNTRY_TO_REGION` map + `_resolve_content_language()` / `_resolve_content_region()` helpers; `normalize_youtube_item()` accepts optional `channel_context` kwarg. `region` default changed from hardcoded `"US"` to `"UNKNOWN"` when no context. `ingest_youtube_channels.py`: `_load_channels()` now SELECTs `language, country, source_region`; `poll_channel()` passes `channel_context` to normalizer. Channel_poll content items now get honest language/region from `youtube_channels` metadata. Fallback: `source_region` → `country→region map` → `"UNKNOWN"`. `entity_mentions.region` deferred. TikTok/Reddit normalizers unchanged. Scoring unchanged. Public-safe views unchanged. 44/44 new + 117/117 existing tests pass. **Production verification SQL prepared in LANGUAGE_REGION_ARCHITECTURE.md — run after next scheduled pipeline.**
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
- **FIX: Dashboard + Screener responsive controls overlap (2026-05-11)** — commit 9717562
  - Root cause (actual): ControlBar outer was `flex flex-wrap`. Left wrapper had `flex-1` (basis=0) + `min-w-0` (min-width=0), so flex calculated left=0 + right=100% = 100% — no overflow, no wrap → both slots on same line at all widths. `w-full` on right slot was ineffective.
  - Fix: ControlBar outer changed from `flex flex-wrap` to `flex flex-col`. Column layout guarantees each slot is its own full-width row. At ≥2xl (1536px+) switches to `flex-row justify-between`.
  - Search: `w-full 2xl:w-48 2xl:shrink-0` — full width on its own row at <2xl, fixed 192px inline at ≥2xl
  - 390px / 768px / 1024px / 1280px / 1440px: Row 1 = search+chips, Row 2 = range+counts — no overlap possible
  - 1536px+: single row, left/right side by side
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
| P3.1 Pipeline Health Log — DB-persisted health history | COMPLETE — PRODUCTION VERIFIED | 2026-05-11 |
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
| 042 — Language & Region Metadata v1 | COMPLETE — PRODUCTION VERIFIED | 2026-05-11 |
| 043 — Content Language & Region Propagation v1 | IMPLEMENTED — PENDING PIPELINE VERIFICATION | 2026-05-11 |
| 044 — Regional Creator Policy v1 | PENDING | — |
| 045 — Regional Filters v1 | PENDING | — |
| 046 — Regional Signal Aggregation Design | PENDING | — |
| 047 — Market Availability Metadata v1 | PENDING | — |
| 048 — Regional UI Concepts | PENDING | — |
| SC2.1 Snapchat foundation | DEFERRED | — |
| SC3.1 Meta / Instagram foundation | DEFERRED | — |
| SC-V1 Optional creator claim / verified module | DEFERRED | — |

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

Current production: **migration 042** (head)

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
