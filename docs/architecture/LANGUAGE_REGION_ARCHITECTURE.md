# Language & Region Architecture Roadmap — FragranceIndex.ai

## Purpose

We have completed the first source-role foundation:

- Migration 039 — `youtube_channels.source_role` + `creator_score_eligible`
- Migration 040 — `source_intake_candidates.source_role` + `creator_score_eligible`
- Source Intake Role Routing v1
- Creator Leaderboard protection via `creator_score_eligible IS NOT FALSE`
- Source Intake Policy after Migration 040 documented
- Migration 041 — DB-persisted pipeline health log

This solved the source-role problem:

> accepted source ≠ creator leaderboard eligible source

But language and region architecture is not complete yet.

This roadmap defines the remaining work needed so FragranceIndex.ai can support multilingual and multi-region fragrance intelligence without turning the platform into noisy global soup.

---

## Core Principle

FragranceIndex.ai should remain:

> one global English intelligence interface  
> with multilingual and multi-region signal ingestion underneath

Do not build separate worlds for each language.

Instead:

- perfume/brand entities remain canonical/global
- each source/content/mention gets language and region metadata
- global score and regional score are separated later
- non-English creators are not rejected just because they are non-English
- local/regional trends should be preserved, not mixed blindly into the global leaderboard

---

## Already Implemented

### Source Role Foundation

Implemented:

- `youtube_channels.source_role`
- `youtube_channels.creator_score_eligible`
- `source_intake_candidates.source_role`
- `source_intake_candidates.creator_score_eligible`
- source intake apply now carries role/eligibility into `youtube_channels`
- creator leaderboard excludes rows where `creator_score_eligible=FALSE`

Current source roles:

- `independent_creator`
- `brand_official`
- `retailer_shop`
- `formulation_education`
- `aggregator`
- `unknown`

Current policy:

- `OPERATOR_REJECTED` = true noise only
- `DEFERRED` = valuable but uncertain / policy-pending
- non-creator sources are `creator_score_eligible=FALSE`
- non-English creators remain policy-pending until language/region handling is defined

---

# Remaining Architecture Work

---

## Phase 042 — Language & Region Metadata v1

**Status: PENDING**

### Goal

Add first-class language and region metadata to source intake and YouTube source registry without changing scoring.

This phase is metadata only.

Do not implement:

- regional scoring
- regional leaderboard
- global score changes
- public UI filters
- market availability scoring

### Why

Right now some schema fields already exist, but the language/region model is incomplete.

Existing but underused fields:

- `youtube_channels.language`
- `youtube_channels.country`
- `canonical_content_items.language`
- `canonical_content_items.region`
- `entity_mentions.region`
- `brands.country`

Problems:

- channel language/country exists but is only beginning to be populated
- `canonical_content_items.region` was historically hardcoded as `US`
- `canonical_content_items.language` is not reliably populated
- `entity_mentions.region` is not populated
- there is no normalized `source_region`
- there is no `audience_region`
- there is no regional policy status

### Proposed schema additions

Add nullable fields to `source_intake_candidates`:

```sql
source_language       VARCHAR(16) NULL
source_country        VARCHAR(8)  NULL
source_region         VARCHAR(64) NULL
audience_region       VARCHAR(64) NULL
regional_policy_status VARCHAR(64) NULL
```

Add nullable fields to `youtube_channels`:

```sql
source_region          VARCHAR(64) NULL
audience_region        VARCHAR(64) NULL
regional_policy_status VARCHAR(64) NULL
```

No CHECK constraints. Keep all fields extensible.

### Suggested region taxonomy

Use these normalized region buckets:

```
US_CANADA
UK_IRELAND
EU_DACH
EU_FRANCOPHONE
EU_SOUTH
LATAM
BRAZIL
MIDDLE_EAST_GCC
SOUTH_ASIA
EAST_ASIA
SOUTHEAST_ASIA
GLOBAL_ENGLISH
UNKNOWN
```

### Suggested regional policy statuses

```
approved_global
approved_regional
regional_policy_pending
excluded_from_global
needs_operator_review
unknown
```

No CHECK constraint.

### Data capture requirements

- Source intake candidates should be able to store: source language, source country, source region, audience region, regional policy status
- YouTube channel apply path should carry these fields into `youtube_channels`
- If YouTube API provides `snippet.country` and `snippet.defaultLanguage`, store them when available
- Do not infer aggressively. If unknown, leave NULL or `UNKNOWN`
- Do not treat country as region: `country` = raw country code or platform-provided location; `source_region` = normalized analytical region bucket

### Admin UI requirements

In `/admin/source-intake`, expose compact optional metadata controls:

- source language
- source country
- source region
- audience region
- regional policy status

Simple dropdown/input UI. Do not make it heavy.

### Tests

Add tests for:

- PATCH candidate language/region fields
- apply carries language/region fields into `youtube_channels`
- NULL values are backward compatible
- unknown metadata does not block apply
- non-English creator can be deferred with language/region notes

### Production verification

After deploy, verify:

- Alembic current = new migration head
- source intake candidate fields exist
- `youtube_channels` fields exist
- admin UI displays fields
- patching fields works
- applying a candidate carries fields into `youtube_channels`
- existing leaderboard totals unchanged

### Completion documentation

After completion, update this roadmap and CLAUDE.md with:

```
Phase 042 — Language & Region Metadata v1 — COMPLETE / PRODUCTION VERIFIED
Migration:
Commit:
Tests:
Production verification:
Notes:
```

---

## Phase 043 — Content Language & Region Propagation v1

**Status: PENDING**

### Goal

Start propagating language and region metadata from source/channel level into content items and mentions.

This phase still does not create regional scores.

### Why

Regional intelligence cannot work only at channel level.

We eventually need:

```
source/channel metadata
→ canonical_content_items.language / region
→ entity_mentions.region
→ future regional aggregation
```

### Requirements

- Stop blindly hardcoding `canonical_content_items.region='US'` unless there is a legitimate reason
- Determine safe fallback order for content region:
  1. explicit content region if available
  2. else `youtube_channels.source_region`
  3. else `youtube_channels.country` mapped to `source_region`
  4. else `UNKNOWN`
- Determine safe fallback order for content language:
  1. explicit detected content language if available
  2. else `youtube_channels.language`
  3. else `UNKNOWN`
- Propagate region to `entity_mentions.region` where possible
- Keep all changes backward compatible
- Do not change scoring yet

### Tests

Add tests for:

- content item receives language from channel when content language unavailable
- content item receives region from source_region fallback
- `entity_mentions.region` is populated when content region exists
- UNKNOWN/null does not break pipeline
- no global scoring changes

### Production verification

Verify:

- new content items are no longer all blindly US
- language starts appearing when available
- `entity_mentions.region` starts populating for new data
- existing public-safe views still work
- daily pipeline still completes

### Completion documentation

After completion, update this roadmap and CLAUDE.md with:

```
Phase 043 — Content Language & Region Propagation v1 — COMPLETE / PRODUCTION VERIFIED
Migration:
Commit:
Tests:
Production verification:
Notes:
```

---

## Phase 044 — Regional Creator Policy v1

**Status: PENDING**

### Goal

Define how non-English and regional independent creators are handled in source intake and creator intelligence.

This phase is policy + admin behavior. No regional scoring yet.

### Core decision

Do not create `regional_creator` as a source role unless absolutely necessary.

Preferred model:

```
source_role = independent_creator
source_language = es/ar/pt/de/etc.
source_region = LATAM/MIDDLE_EAST_GCC/etc.
regional_policy_status = approved_regional or regional_policy_pending
```

Reason: "Regional" is not a source role. It is geography/context. A Spanish-speaking independent fragrance reviewer is still an independent creator.

### Policy rules

- Do not reject non-English fragrance creators only because they are non-English
- Clear non-English fragrance creators should usually be:
  - `source_role = independent_creator`
  - `regional_policy_status = regional_policy_pending`
  - status = `DEFERRED`
  - until language/region display rules are ready
- Strong global non-English creators may be applied manually if operator explicitly accepts that they may appear in current Creator Leaderboard
- Once language/region filters exist, approved regional creators may be applied safely
- `creator_score_eligible` should not automatically be false just because the creator is non-English
- The question is not "English or non-English." The question is:
  - is this an independent fragrance creator?
  - what language is the content?
  - what region does the signal represent?
  - should it appear in current global creator leaderboard?

### Admin workflow

Add/confirm operator decision patterns:

- Approve as Global Creator
- Defer as Regional Policy Pending
- Approve as Regional Creator
- Reject Noise
- Route as Brand/Retail/Formulation

### Tests

Add tests for:

- non-English independent creator can be stored without rejection
- regional policy pending does not imply terminal status
- deferred regional candidates can later be approved
- `creator_score_eligible` remains explicit/operator-controlled

### Completion documentation

After completion, update this roadmap and CLAUDE.md with:

```
Phase 044 — Regional Creator Policy v1 — COMPLETE / DOCUMENTED
Commit:
Tests:
Production verification:
Notes:
```

---

## Phase 045 — Regional Filters v1

**Status: PENDING**

### Goal

Expose internal/admin filtering by language and region before changing scoring.

This can begin as admin-only or API-level filters. Do not yet create new public regional leaderboards.

### Requirements

Add filters where safe:

**Creator API:**

```
?source_language=
?source_region=
?audience_region=
?regional_policy_status=
```

**Source Intake admin:**

- filter by `source_role`
- filter by `source_language`
- filter by `source_region`
- filter by `regional_policy_status`

**Optional — Creator Leaderboard internal/admin mode:**

- show language
- show region
- show audience region if present

Default public Creator Leaderboard behavior must remain unchanged unless explicitly approved.

### Tests

Add tests for:

- filtering creators by `source_region`
- filtering candidates by language/region
- default query remains unchanged
- backward compatibility for NULL values

### Completion documentation

After completion, update this roadmap and CLAUDE.md with:

```
Phase 045 — Regional Filters v1 — COMPLETE / PRODUCTION VERIFIED
Migration:
Commit:
Tests:
Production verification:
Notes:
```

---

## Phase 046 — Regional Signal Aggregation Design

**Status: PENDING**

### Goal

Design regional signal aggregation before implementation.

**This is design-first. Do not implement until approved.**

### Concepts to define

**Regional score:** signal strength inside a region

**Global score:** cross-region validated trend strength

They must not be the same.

### Proposed principles

- Single-region hype should not automatically inflate global score
- Regional signal should remain visible and valuable
- Global score should reward cross-region validation
- Availability should affect global interpretation later
- Brand/retail/formulation sources should remain separate from independent creator trend signals

### Proposed inputs

**Regional signal may use:**

- mention count
- unique creators
- creator quality/reach
- source role
- mention quality
- recency decay
- platform
- region baseline volume

**Global signal may use:**

- number of active regions
- normalized regional scores
- source diversity
- cross-region spread timing
- availability factor later

### Deliverable

Claude should provide a design report only:

**Regional Signal Aggregation v1 Proposal**

Include:

- tables impacted
- whether new table is needed
- formulas
- thresholds
- risks
- migration plan
- backfill plan
- UI implications

No code until approved.

### Completion documentation

After completion, update this roadmap and CLAUDE.md with:

```
Phase 046 — Regional Signal Aggregation Design — COMPLETE / PROPOSAL READY
Commit:
Notes:
Approval needed before implementation:
```

---

## Phase 047 — Market Availability Metadata v1

**Status: PENDING**

### Goal

Add market availability metadata so local/regional perfumes are not misrepresented as global trends.

### Why

A perfume can be hot in Spain, India, Brazil, or the Middle East but not available in the US. This should be shown honestly, not flattened into global trend score.

### Proposed values

```
global
us_available
eu_available
regional_only
limited_distribution
unknown
```

### Possible locations

Entity-level: `entity_market.market_availability`

or separate table `entity_market_availability`:

```sql
entity_id        uuid
entity_type      varchar
market_region    varchar
availability_status varchar
source           varchar
confidence       float
updated_at       timestamptz
```

Market availability is not the same as brand origin. Design before implementation.

### Completion documentation

After completion, update this roadmap and CLAUDE.md with:

```
Phase 047 — Market Availability Metadata v1 — COMPLETE / PROPOSAL READY or IMPLEMENTED
Migration:
Commit:
Tests:
Production verification:
Notes:
```

---

## Phase 048 — Regional UI Concepts

**Status: PENDING**

### Goal

Design how regional intelligence should appear in the product UI.

**Do not implement until metadata/scoring foundation exists.**

### Possible UI concepts

**Default public view:** Global Trends

**Filters:**

- Region: Global / US / LATAM / Middle East / South Asia / DACH / France / Brazil
- Language: Any / English / Spanish / German / Arabic / Portuguese / Hindi
- Signal Type: Creator / Brand Push / Retail / Formulation
- Availability: Global / US Available / Regional Only

**Entity page additions:**

- Regional Heat
- Source Mix
- Languages Detected
- Availability Tag
- Spread Pattern

**Example — cross-regional trend:**

```
Lattafa Khamrah

Global Score: 82
Regional Heat:
  Middle East GCC: 93
  US/Canada: 78
  LATAM: 65
  UK/Ireland: 59

Availability: International online
Spread Pattern: Cross-regional breakout
```

**Example — regional phenomenon:**

```
Mercadona Mango Sunrise

Global Score: 18
Regional Score Spain/EU South: 91
Regional Score LATAM: 76

Availability: Spain / limited
Label: Regional fragrance trend — limited global availability
```

### Completion documentation

After completion, update this roadmap and CLAUDE.md with:

```
Phase 048 — Regional UI Concepts — COMPLETE / DESIGN READY
Commit:
Notes:
Approval needed before implementation:
```

---

## Operating Rules for Claude

### Documentation Rule

After every phase, Claude must update this roadmap and CLAUDE.md with:

```
Phase:
Status:
Migration:
Commit:
Tests:
Production verification:
What changed:
What did not change:
Next recommended step:
```

### No Silent Architecture Changes

Do not silently change:

- scoring formulas
- public leaderboard behavior
- source intake semantics
- public-safe views
- regional/global interpretation

without explicit approval.

### Migration Discipline

Every migration must include:

- migration number
- short purpose
- downgrade path
- production verification query
- CLAUDE.md update

### Production Safety

Default behavior should remain unchanged unless the phase explicitly says otherwise.

Especially protect:

- Creator Leaderboard
- public-safe views
- daily/evening pipelines
- existing source intake statuses
- legal/compliance boundary

---

## Current Recommended Next Phase

**Phase 042 — Language & Region Metadata v1**

Scope:

- metadata only
- source intake + youtube_channels
- no scoring
- no public regional UI
- no global score changes

**Do not begin until explicitly approved.**
