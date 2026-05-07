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

Tasks:
- Add TikTok creator watchlist support
- Seed initial 100–300 fragrance TikTok creators
- Add daily monitoring worker with strict rate limits
- Store newly detected video URLs
- Tag content as `tiktok_layer=3`
- Add `external_api_audit_log` entries for every fetch
- Add kill switch (env/config flag)
- Add admin operator queue for TikTok creator review

Production verification:
- seeded creators can be listed
- worker runs without blocking existing pipelines
- new video URL detection is idempotent
- kill switch stops TikTok monitoring immediately
- audit log records all fetches

---

### SC1.3 — Multi-field resolver adaptation

Goal: prepare resolver for TikTok/Instagram-style content where title alone is insufficient.

New resolver input:

```python
text_signal = {
  "title": ...,
  "description": ...,
  "hashtags": [...],
  "referencing_context": ...,
  "platform": ...,
  "source_method": ...
}
```

Tasks:
- Add backward-compatible resolver wrapper
- Keep old title-only flow working (no YouTube/Reddit regression)
- Add per-field weights by platform
- Add feature flag
- Replay historical YouTube/Reddit content before enabling
- Add tests for hashtag-driven and context-driven matches

Production verification:
- YouTube resolved count does not regress
- Reddit resolved count does not regress
- TikTok Layer 1 derived uses `referencing_context`
- TikTok Layer 3 uses title/snippet/available text

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
