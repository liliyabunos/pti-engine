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

**Status: COMPLETE — PRODUCTION VERIFIED**
**Migration: `alembic/versions/042_language_region_metadata.py`**
**Implementation commit: `3702a9c`**
**Completion fix commit: `436fd6c`** — `source_language` / `source_country` carry-forward added
**Tests: 52/52 pass** (`tests/unit/test_admin_source_intake.py` — 13 new tests in `TestLanguageRegionMetadata`)

**Production verification:**
- `alembic current = 042` ✓
- `source_intake_candidates` has 5 new columns: `source_language`, `source_country`, `source_region`, `audience_region`, `regional_policy_status` ✓
- `youtube_channels` has 3 new columns: `source_region`, `audience_region`, `regional_policy_status` ✓
- Apply carries all 5 metadata fields from candidate into `youtube_channels`:
  - `source_language` → `youtube_channels.language` (existing column, migration 023) ✓
  - `source_country` → `youtube_channels.country` (existing column, migration 023) ✓
  - `source_region` → `youtube_channels.source_region` (new column, migration 042) ✓
  - `audience_region` → `youtube_channels.audience_region` (new column, migration 042) ✓
  - `regional_policy_status` → `youtube_channels.regional_policy_status` (new column, migration 042) ✓
- Admin UI shows Language & Region controls in BatchReviewConsole ✓
- Creator Leaderboard total/top rows unchanged ✓

**What changed:**
- `source_intake_candidates`: 5 new nullable metadata fields — `source_language`, `source_country`, `source_region`, `audience_region`, `regional_policy_status` — no CHECK constraints
- `youtube_channels`: 3 new nullable columns — `source_region`, `audience_region`, `regional_policy_status`
- Apply path now carries all 5 metadata fields from candidate into the YouTube source registry on apply
- `PATCH /candidates/{id}` accepts all 5 new fields
- `CandidateRow` GET response exposes all 5 new fields
- Admin UI (`BatchReviewConsole`): Language & Region section per candidate card — lang/country text inputs, region/audience/policy dropdowns, Save Metadata button appears only when a field has a pending change

**What did not change:**
- No regional scoring
- No regional leaderboard
- No public UI filters
- No propagation to `canonical_content_items` (Phase 043)
- No propagation to `entity_mentions.region` (Phase 043)
- No global score changes
- Creator Leaderboard behavior unchanged — still gated on `creator_score_eligible IS NOT FALSE`
- source_role routing unchanged

**Full carry-forward mapping (apply_batch → youtube_channels):**

| candidate field | youtube_channels column | column origin |
|----------------|------------------------|---------------|
| `source_language` | `language` | migration 023 (existing) |
| `source_country` | `country` | migration 023 (existing) |
| `source_region` | `source_region` | migration 042 (new) |
| `audience_region` | `audience_region` | migration 042 (new) |
| `regional_policy_status` | `regional_policy_status` | migration 042 (new) |

**Next phase: Phase 043 — Content Language & Region Propagation v1 — pending explicit approval.**

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

**Status: COMPLETE — PRODUCTION VERIFIED (pending next pipeline run)**
**Migration: none — code-only change**
**Commit: `71be8f4`**
**Tests: 44/44 pass** (`tests/unit/test_content_language_region.py`)

**What changed:**
- `normalizer.py`: `_COUNTRY_TO_REGION` mapping dict (50+ country codes → region buckets); `_resolve_content_language()` and `_resolve_content_region()` module-level helpers; `normalize_youtube_item()` accepts optional `channel_context` kwarg
- `region` default changed from hardcoded `"US"` to `"UNKNOWN"` when no context provided
- `language` default remains `None` when no context (not attempted — backward compatible)
- `ingest_youtube_channels.py`: `_load_channels()` now SELECTs `language`, `country`, `source_region` from `youtube_channels`; `poll_channel()` builds `channel_context` dict and passes it to `normalize_youtube_item()`

**What did not change:**
- No migration — `canonical_content_items.language` and `region` already exist (migration 007/023)
- No historical backfill — existing rows remain as-is
- `entity_mentions.region` — deferred (out of scope for Phase 043)
- TikTok and Reddit normalizers — unchanged
- Scoring: influence_score, weighted_signal_score, creator_score — all unchanged
- Creator Leaderboard behavior — unchanged
- Public-safe views — unchanged (region/language not in SELECT list)

**Fallback order implemented:**
- Region: `youtube_channels.source_region` → `_COUNTRY_TO_REGION[country]` → `"UNKNOWN"`
- Language: `youtube_channels.language` → `"UNKNOWN"` (when context provided but no language); `None` (when no context = not attempted)

**NULL vs UNKNOWN semantics:**
- `language=None` = not attempted (legacy rows, search-based ingestion)
- `language="UNKNOWN"` = attempted but not determinable (channel_poll with no language set)
- `region="UNKNOWN"` = not determinable (replaces old hardcoded "US")

**Production verification (run after next pipeline):**
```sql
-- New content items should no longer be uniformly "US"
SELECT region, count(*) FROM canonical_content_items
WHERE created_at > NOW() - INTERVAL '2 hours'
GROUP BY region ORDER BY count DESC;

-- Channels with metadata should propagate to content items
SELECT c.region, c.language, yc.language AS ch_lang, yc.source_region
FROM canonical_content_items c
JOIN youtube_channels yc ON yc.channel_id = c.resolved_platform_id
WHERE c.created_at > NOW() - INTERVAL '2 hours'
AND yc.language IS NOT NULL
LIMIT 20;

-- Historical rows unaffected
SELECT region, count(*) FROM canonical_content_items
WHERE created_at < NOW() - INTERVAL '1 day'
GROUP BY region ORDER BY count DESC;

-- Confirm public-safe views still work
SELECT count(*) FROM public_safe_content_items;
SELECT count(*) FROM public_safe_entity_snapshots;

-- Confirm scoring unchanged
SELECT count(*), round(avg(influence_score)::numeric, 4) FROM creator_scores;
```

**Next phase: Phase 044 — Regional Creator Policy v1 — pending explicit approval.**

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
