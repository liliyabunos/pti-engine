# CLAUDE.md — Perfume Trend Intelligence SDK

This project must optimize for correctness, recomputability, and low API cost over maximum automation.

## Perfume Trend Intelligence SDK — architecture guardrails

### Core principles
- Prioritize low-cost, deterministic pipelines over frequent LLM calls.
- Do not use OpenAI/Gemini for every mention or every text item.
- LLMs are optional arbiters for ambiguous entity resolution, not the default parser for the whole dataset.
- Always prefer: exact match -> fuzzy match -> optional AI validation.
- Preserve raw inputs and resolution metadata so history can be recomputed later.

### Environment and secrets
- API keys must be loaded from environment variables first.
- Priority for secrets: `.env` / environment variables -> config yaml fallback.
- Never hardcode API keys in source files.
- `YOUTUBE_API_KEY` must come from environment first.
- `OPENAI_API_KEY` must come from environment first.

### Budget safety rules
- AI validation must be behind a feature flag.
- Default config should keep AI validation off unless explicitly enabled.
- Limit AI calls per run with a hard cap, for example:
  - `ai_enabled: false`
  - `ai_max_items_per_run: 5`
- Before sending text to an LLM:
  - deduplicate
  - remove short/noisy texts
  - prioritize by source weight / influence / freshness
- Cache AI results by content hash to avoid repeated API spend.
- Prefer batch analysis over one-request-per-item when possible.

### Resolver architecture
Entity resolution must use the following order:
1. Pre-normalization
2. Exact alias match
3. Fuzzy match
4. Optional AI arbitration
5. Unresolved queue

### Pre-normalization rules
Before matching entities:
- lowercase text
- trim whitespace
- normalize unicode
- collapse repeated spaces
- strip punctuation where safe
- normalize common perfume abbreviations
- separate concentration terms from perfume name:
  - EDP
  - Body Spray (Body Mist)
  - EDT
  - Extrait
  - Parfum
- "Body Spray" and "Body Mist" are the same canonical product-form entity for matching and analytics:
  - map both to one canonical value: `body_spray`
  - remove both from perfume-name candidate text before resolver matching
  - return `body_spray` in the metadata concentration field
  - do not treat them as separate analytics entities

Example:
- `Baccarat Rouge 540 Extrait` -> base name: `baccarat rouge 540`, concentration: `extrait`
- `BR540` -> normalized alias candidate for `Baccarat Rouge 540`

## Knowledge Base Layer (Fragrance Master Data)

The system must maintain a **static fragrance knowledge base** as the primary source of truth for entity resolution.

### Source
- Fragrance Database (Kaggle / GitHub datasets)
- Loaded as initial seed dataset

### Purpose
- Provide canonical perfume and brand names
- Enable high-accuracy entity resolution (target: 90–95% coverage)
- Reduce dependency on AI for entity matching
- Standardize aliases across all pipelines

### Data Model Extension

#### fragrance_master (seed table)
- `fragrance_id`
- `brand_name`
- `perfume_name`
- `canonical_name`
- `normalized_name`
- `release_year` (optional)
- `gender` (optional)
- `source` (e.g. kaggle)
- `created_at`

### Rules
- This dataset is **read-mostly**
- Must be loaded before any extraction/resolution pipeline runs
- Must not be overwritten by dynamic pipeline data
- Can be extended but not replaced by runtime signals

---

## Alias Generation System

Aliases must be generated automatically from fragrance_master to support high recall in entity resolution.

### Alias Sources
For each perfume:
- Full canonical name
- Brand + perfume
- Short perfume name
- Common abbreviations (when possible)

### Example
Canonical: `parfums de marly delina`

Generated aliases:
- `delina`
- `pdm delina`
- `delina perfume`
- `parfums marly delina`

### Rules
- All aliases must be normalized (lowercase, cleaned)
- Aliases must be stored in `aliases` table with `match_type = exact`, `confidence = 1.0`
- Auto-generated aliases must be distinguishable from manual, fuzzy, and AI-confirmed aliases

---

## Discovery Layer (Emerging Entities)

The system must detect and track **new or unknown perfumes** not present in fragrance_master.

### When triggered
If resolver fails exact match, fuzzy match, and AI validation → entity is not discarded.

### Storage

#### fragrance_candidates
- `id`
- `raw_name`
- `normalized_name`
- `source`
- `first_seen_at`
- `mention_count`
- `status` (`unverified` | `promoted` | `rejected`)

### Promotion Logic
- Consistent mentions over time + increasing engagement → can be promoted into `fragrance_master`

### Rejection Logic
- Low frequency or noise/spam patterns

### Rules
- Never drop unknown entities
- Discovery is required for identifying early trends

---

## Phase 3 — Growth Engine (Self-Learning System)

The system must evolve from a static knowledge base into a **self-improving intelligence engine**.

### Goal

Continuously increase entity resolution coverage by:
- discovering new perfumes and brands from real data
- validating them
- promoting them into the knowledge base

---

## Growth Loop (MANDATORY)

The system must implement the following loop:

```
Ingest → Resolve → Unresolved Queue → Candidate Extraction → Validation → Promotion → Knowledge Base
```

### Step 1 — Ingest
Fetch raw content from sources (YouTube, TikTok, Instagram).

### Step 2 — Resolve
Run `PerfumeResolver` against `fragrance_master` aliases.
- Exact match → resolved → stored in `resolved_signals`
- No match → goes to unresolved queue

### Step 3 — Unresolved Queue
Store all unresolved mentions in `fragrance_candidates` with:
- `raw_name` — original candidate text
- `normalized_name` — cleaned version
- `source` — where it came from
- `first_seen_at` — timestamp
- `mention_count` — incremented on repeat
- `status = unverified`

### Step 4 — Candidate Validation
Periodically review top candidates by `mention_count`:
- **Rule-based check**: does it look like a real perfume name?
- **Optional AI check**: confirm via LLM if ambiguous
- **Manual review**: human approves high-value candidates

### Step 5 — Promotion
Approved candidates are written into `fragrance_master` + `aliases`.
Status updated to `promoted`.

### Step 6 — Re-resolution
Historical unresolved mentions can be re-resolved after promotion.
This is why raw text must always be preserved.

---

## Growth Loop — Full Cycle

```
Unresolved Mentions → Candidate Aggregation → Validation → Seed Update → Resolver Improvement
```

This loop is the primary driver of system intelligence growth.

---

## Step 1 — Candidate Aggregation

Unresolved mentions must be aggregated into structured candidates.

### Source
- unresolved_mentions (from Resolver)
- fragrance_candidates table

### Aggregation rules
- group by normalized_name
- track:
  - mention_count
  - distinct_sources_count
  - first_seen_at
  - last_seen_at

### Output file (required)

`outputs/top_unresolved_candidates.json`

### Example structure
```json
[
  {
    "text": "lattafa khamrah",
    "count": 5,
    "sources": 3,
    "first_seen_at": "...",
    "last_seen_at": "..."
  }
]
```

---

## Step 2 — Candidate Filtering

Not all candidates should be promoted.

### Promotion thresholds (initial defaults)
- `mention_count >= 2`
- OR `distinct_sources_count >= 2`

### Rejection rules
- extremely short tokens (<= 3 chars)
- generic words (e.g. "perfume", "best scent")
- spam patterns

Filtering must be deterministic and configurable.

---

## Step 3 — Candidate Structuring

Candidates must be converted into structured entities.

### Basic parsing
- split into brand + perfume when possible
- fallback: store as unresolved structured entity

### Example
- `"lattafa khamrah"` → brand: Lattafa, perfume: Khamrah
- `"arabians tonka"` → brand unknown → perfume candidate

### Rules
- Do NOT assume perfect parsing
- Store raw + parsed versions

---

## Step 4 — Promotion Pipeline

New entities must NOT directly enter `fragrance_master`.

### Required step: Promotion Workflow

New workflow: `workflows/promote_candidates.py`

### Promotion logic
- read filtered candidates
- convert into seed rows
- append to: `perfume_trend_sdk/data/fragrance_master/seed_master.csv`

### Required fields
- `brand_name`
- `perfume_name`
- `source = "discovery"`

---

## Step 5 — Knowledge Base Reload

After promotion:

```
load_fragrance_master → rebuild aliases → resolver updated
```

This step must be explicit and logged.

---

## Step 6 — Resolver Feedback Loop

After reload:
- rerun ingestion pipeline
- measure:
  - resolved rate increase
  - unresolved reduction

### Required metrics
- `resolution_rate`
- `unresolved_rate`
- `new_entities_added`

---

## Auto-Learning Modes

| Mode | Description |
|------|-------------|
| Mode 1 — Manual (default, safe) | human reviews candidates, approves before promotion |
| Mode 2 — Semi-Automatic (recommended) | auto-promote high-confidence candidates, log all changes |
| Mode 3 — Fully Automatic (future) | promote based on statistical thresholds only |

---

## Discovery Layer Upgrade (REQUIRED)

Extend `fragrance_candidates` with:
- `distinct_sources_count`
- `confidence_score`
- `promotion_status` (`pending` | `approved` | `rejected`)
- `last_promoted_at`

---

## Alias Expansion from Discovery

When a new entity is promoted:
- generate aliases immediately
- mark:
  - `match_type = discovery_generated`
  - `confidence = 0.7–0.9`

---

## System-Level Requirement

The system must improve over time WITHOUT increasing AI usage.

Priority order:
1. Knowledge base expansion
2. Alias coverage increase
3. Fuzzy matching tuning
4. AI usage (last resort)

---

## Success Criteria for Phase 3

- Resolver coverage improves run-over-run
- Unresolved mentions decrease over time
- Niche / TikTok / emerging brands begin to resolve correctly
- New entities appear in trend reports within 1–2 pipeline cycles

---

## Critical Constraint

The system must NEVER:
- overwrite canonical entities without explicit promotion
- create entities directly inside resolver
- mix runtime signals with knowledge base data

---

## Future Extensions (Phase 3.5+)

- Fragrantica integration (new releases, reviews)
- TikTok caption ingestion (high-priority signal source)
- Reddit ingestion (early trend detection)
- AI-assisted entity validation (only for high-value candidates)

---

## Phase 4A — Fragrantica Integration (Discovery + Enrichment Source)

The system must integrate Fragrantica as a **secondary intelligence source** for:

1. Enrichment of known perfume entities
2. Discovery of new perfumes and brands

Fragrantica is NOT a canonical source of truth.

---

## Role of Fragrantica

Fragrantica operates as:

- Discovery Layer Extension
- Metadata Enrichment Source

It must NOT:
- override canonical entities
- create entities directly inside resolver
- redefine brand or perfume naming in fragrance_master

---

## Integration Modes

### Mode 1 — Enrichment (Primary)

Used for already resolved perfumes.

#### Input
- `fragrance_id`
- `canonical_name`

#### Output
Additional metadata:
- accords
- top / middle / base notes
- rating_value
- rating_count
- release_year (optional)
- perfumer (optional)
- gender (optional)
- similar_perfumes (optional)

#### Rules
- Enrichment must NOT overwrite canonical_name
- Enrichment must be additive only
- Missing fields must not break pipeline

---

### Mode 2 — Discovery

Used to identify new perfumes not present in fragrance_master.

#### Sources
- Fragrantica perfume pages
- discovery lists (e.g. new / popular perfumes)

#### Output
- unresolved candidates must be routed to:
  - `fragrance_candidates`
  - Phase 3 Growth Loop

---

## Fragrantica Connector Rules

### Connector responsibilities
- fetch raw HTML only
- respect retry/backoff rules
- configurable user-agent
- configurable timeout

### Strict rule
Connector MUST NOT:
- parse business logic
- perform extraction or analytics

---

## Raw Storage Requirement

All fetched pages must be stored BEFORE parsing.

Required fields:
- `source_name = "fragrantica"`
- `source_url`
- `fetched_at`
- `raw_html`

This ensures:
- replayability
- parser improvements without re-fetch

---

## Parser Requirements

Parser must be:
- deterministic
- tolerant to missing fields
- independent from pipeline logic

### Required fields (v1)
- brand_name
- perfume_name
- accords
- notes_top
- notes_middle
- notes_base
- rating_value
- rating_count

### Optional fields
- release_year
- perfumer
- gender
- similar_perfumes

---

## Normalization Rules

Parsed Fragrantica data must be mapped into a structured internal record: `FragranticaPerfumeRecord`

### Rules
- normalization must preserve source_url
- normalization must NOT resolve entities
- normalization must NOT mutate canonical data

---

## Enrichment Pipeline

New workflow: `workflows/enrich_from_fragrantica.py`

### Flow
Resolved perfumes → Fragrantica fetch → parse → normalize → enrich entity metadata

### Rules
- enrichment is applied AFTER resolution
- enrichment must not block pipeline if fails
- enrichment must be idempotent

---

## Discovery Pipeline

New workflow: `workflows/ingest_fragrantica_discovery.py`

### Flow
Fragrantica pages → parse → normalize → unresolved → fragrance_candidates

### Rules
- discovered perfumes must go through Phase 3 Growth Engine
- direct insertion into fragrance_master is forbidden

---

## Alias Expansion from Fragrantica

When Fragrantica provides alternative names or similar perfumes, these may be used to:
- generate alias candidates
- improve resolver recall

### Rules
- store as alias candidates
- do NOT auto-promote to exact aliases without validation
- mark:
  - `match_type = external_source`
  - `confidence < 1.0`

---

## Data Separation Rules

Fragrantica data must be stored separately from canonical data.

| Layer | Tables |
|-------|--------|
| Canonical | `fragrance_master`, `aliases` |
| External Source | `fragrantica_records`, enrichment metadata |

**Rule:** External data must NEVER redefine canonical identity directly.

---

## Failure Handling

| Stage | Behavior |
|-------|----------|
| fetch failure | retry |
| parse failure | log + skip |
| enrichment failure | must not stop pipeline |

---

## Logging Requirements

Each stage must log:
- `fetch_count`
- `parse_success` / `parse_fail`
- `enriched_entities_count`
- `discovered_entities_count`

---

## Success Criteria
- Known perfumes enriched with accords and notes
- Reports include note-level intelligence
- Discovery pipeline produces new candidates
- Resolver coverage improves via Phase 3 loop

---

## Critical Constraint

Fragrantica must enhance intelligence without increasing system fragility.

---

## Future Extensions (Phase 4A+)
- review sentiment aggregation
- rating trend tracking
- note popularity modeling
- similarity graph between perfumes

---

## Phase 4B — Reddit Ingestion v1 (Community Intelligence Source)

The system adds Reddit as a **community intelligence source** focused on authentic consumer discussion, recommendation language, objections, and early niche discovery.

Reddit is valuable because it captures:
- real user opinions
- comparison language
- buyer objections
- niche and dupe discovery
- recommendation phrasing not always present in creator-led content

Reddit must be treated as a **social/community signal source**, not as a canonical source of truth.

**Reddit v1 uses public JSON endpoints — no OAuth, no API credentials required.**
Data is fetched from subreddit feeds (e.g. `/r/fragrance/new.json`).
Ingestion is read-only public data access. Reddit data is treated as a **real data source** equivalent to YouTube in the serving layer.

---

### Role of Reddit

Reddit operates as:

- Community Intelligence Source
- Discovery Layer Input
- Insight Layer Support

It should help answer:
- what real users like or dislike
- which perfumes are compared against each other
- which notes are being praised or criticized
- which niche or clone fragrances are rising in conversation

---

## Reddit v1 Implementation Notes

- **Access method:** public JSON endpoints (`/r/<subreddit>/new.json`, `/.json` suffix on any listing URL)
- **No credentials required:** no Reddit API key, no OAuth, no app registration for v1
- **Subreddit watchlist:** config-driven list of subreddits to poll
- **Rate-limited polite fetching:** respect Reddit's public rate limits (1 req/sec, `User-Agent` header required)
- **Raw payload storage required** before normalization — same architecture rule as all sources
- **Normalization:** into `CanonicalContentItem` via `normalize_reddit_item()` in `SocialContentNormalizer`
- **`source_platform = "reddit"`** — Reddit is a named first-class platform in the serving layer

Run order:
```bash
python3 scripts/ingest_reddit.py --lookback-days 3
python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date YYYY-MM-DD
```

---

## Reddit API (Future Integration — TODO)

> **TODO / FUTURE WORK — do not implement yet.**

The current v1 Reddit connector uses public JSON endpoints.
A future version may migrate to the **official Reddit API** when higher reliability or richer data is needed.

### Potential benefits of official Reddit API

- Higher rate limits (authenticated requests get significantly more headroom)
- Richer metadata: full comment trees, user karma, subreddit subscriber counts, crosspost data
- Reliability guarantees (no breakage risk from HTML/JSON format changes)
- Access to private or age-gated subreddits if approved

### Requirements for official Reddit API

- Reddit developer application registration
- OAuth 2.0 app credentials (`client_id`, `client_secret`)
- Compliance with Reddit API terms of service (usage limits, attribution)
- Possible partnership / review process for data products

### Migration path (when needed)

1. Replace `client.py` fetch logic with `praw` or direct OAuth requests
2. Add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` to `.env`
3. Keep connector interface (`connector.py`, `parser.py`) unchanged — only the client layer changes
4. No changes to normalizer, resolver, or pipeline contracts

This migration is not required for v1. Public JSON ingestion is sufficient for initial serving.

---

### Scope for v1

Reddit v1 is intentionally limited.

**In scope:**
- subreddit watchlist ingestion via public JSON endpoints
- post title ingestion
- selftext/body ingestion
- basic engagement metadata (score, num_comments)
- extraction/resolution through existing pipeline
- unresolved routing into discovery flow

**Out of scope for v1:**
- official Reddit API / OAuth authentication
- full-platform Reddit scan
- full comment ingestion
- sentiment AI analysis by default
- quote mining from large comment trees
- real-time monitoring

---

### Source Targets (Initial)

Recommended initial subreddit watchlist:
- `r/fragrance`
- `r/FemFragLab`
- `r/Colognes`
- `r/Perfumes` (optional)

The watchlist must remain config-driven.

---

### Reddit Connector Rules

Create source package:

```text
connectors/reddit_watchlist/
  connector.py
  client.py
  parser.py
  config.py
```

**Connector responsibilities:**
- fetch raw Reddit post payloads only
- support subreddit-based watchlist
- support bounded fetch windows / limits
- configurable retry/backoff and timeout
- no extraction, analytics, scoring, or entity resolution inside connector

**Strict rule:** Connector MUST NOT compute trend scores, resolve perfumes, classify notes, or enrich entities.

---

### Raw Storage Requirement

All Reddit raw payloads must be stored before normalization.

Required fields to preserve:
- `source_name = "reddit"`
- `subreddit`
- `post_id`
- `permalink` / `url`
- `fetched_at`
- raw payload

This guarantees replayability, parser upgrades without re-fetch, and traceability.

---

### Required Reddit Fields (v1)

The parser must extract, when available:

- `external_content_id`
- `subreddit`
- `source_url`
- `source_account_handle` (author if available)
- `title`
- `selftext`
- `published_at`
- `score`
- `num_comments`
- `link_flair_text` (optional)

**Rules:**
- parser must be deterministic
- parser must tolerate missing body/selftext
- parser must preserve raw metadata where useful

---

### Normalization Rules

Reddit content must reuse the canonical social content path where possible.

Normalized Reddit item should map into:
- `source_platform = "reddit"`
- `content_type = "post"`
- `title`
- `text_content = title + " " + selftext`
- `engagement`: `likes` mapped from Reddit `score`, `comments` mapped from `num_comments`

**Rules:**
- normalization must preserve subreddit in `media_metadata`
- normalization must preserve `source_url`
- normalization must not perform entity resolution

---

### Reddit Workflow Integration

Reddit must flow through the same core path as existing sources:

```
fetch → raw storage → normalize → extract → resolve → store
```

**Rules:**
- existing extractors should operate on Reddit normalized text
- unresolved mentions must route into Discovery / Growth Engine
- Reddit must not require a separate analytics model for v1

---

### Discovery Value from Reddit

Reddit is especially valuable for:
- niche perfume discovery
- clone / dupe discovery
- comparison language
- consumer objections
- recommendation phrases

Examples of useful patterns:
- "better than baccarat rouge"
- "smells expensive"
- "too synthetic"
- "long lasting vanilla"
- "blind buy worthy"

These patterns must remain preserved in raw and normalized text for future insight work.

---

### Source Intelligence Rules for Reddit

Source intelligence should support Reddit items where possible.

Attach or derive:
- `source_type = "community"`
- influence / weight from engagement signals
- subreddit metadata for context

**Rules:**
- Reddit influence must not be treated the same as influencer reach
- `score` and discussion depth should matter more than follower logic

---

### Logging Requirements

Structured logs must include:
- `fetch_started`, `fetch_succeeded`, `fetch_failed`
- `normalized_count`, `extracted_count`, `resolved_count`, `unresolved_count`
- `subreddit`

---

### Tests for Reddit v1

Required:
- raw Reddit post fixture
- parser unit test
- normalization integration test
- end-to-end ingestion test for Reddit source

---

### Success Criteria for Reddit v1

- subreddit posts ingest successfully
- normalized Reddit records are created
- perfume/note mentions are extracted from titles and selftext
- resolved entities flow into analytics
- unresolved entities flow into discovery
- Reddit becomes available as an input to client-facing reports

---

## Phase 4C — Multi-Source Client Report v1

The system must produce a richer client-facing report that combines TikTok, YouTube, Reddit, and Notes / accords intelligence.

The goal is to move from source-specific outputs to a **cross-source market narrative**.

---

### Purpose of Multi-Source Report

The report should answer:
- which perfumes are trending
- which notes are rising or declining
- which platforms are driving the trend
- whether the signal is creator-driven, community-driven, or mixed
- what this means commercially

This report is intended for: perfume brands, retail buyers, content strategists, internal market research.

---

### Required Sections (v1)

**1. Executive Summary**
High-level market summary for the reporting window.

**2. Top Trending Perfumes**
Cross-source ranking with trend direction.

**3. Top Notes This Period**
- note, score, direction, brief drivers if available

**4. Source Breakdown**
Relative contribution from TikTok, YouTube, Reddit.

**5. Community vs Creator Signal**
Differentiate: creator-led hype, community-led validation, mixed signals.

**6. Emerging Entities**
Unresolved/promoted candidates that may become important.

**7. Opportunity / Risk Summary**
Commercial interpretation: launch opportunities, oversaturation risks, declining profiles.

---

### Multi-Source Aggregation Rules

The report must not simply concatenate source outputs — it must aggregate signals across sources by canonical entity.

**Rules:**
- perfume-level aggregation must use resolved canonical entity IDs
- note-level aggregation must combine extracted note mentions with enrichment notes
- source attribution must remain visible
- report should distinguish: high-volume signal, high-engagement signal, high-credibility/community signal

---

### Report Output Formats

Required output formats:
- **Markdown** — source-of-truth report format
- **PDF** — client-facing presentation format
- **CSV** — analyst workflow export

---

### Report Design Principle

The report must be useful to a client without requiring access to the raw system.

This means: concise executive narrative, visible trend direction, source-aware interpretation, commercial implications.

---

### Success Criteria for Multi-Source Report

- one report combines TikTok + YouTube + Reddit + Notes
- trend direction is visible
- source contribution is visible
- note momentum is visible
- report reads like market intelligence, not raw logs

---

## Infrastructure Decision Gate — PostgreSQL + docker-compose

After Reddit v1 and the multi-source client report are complete, the project must explicitly evaluate whether it should move beyond the current local + lightweight setup.

**This is a decision gate, not an automatic migration.**

---

### Decision Criteria

Move toward PostgreSQL and optionally docker-compose if at least several of these conditions are true:

**PostgreSQL criteria:**
- multiple scheduled jobs run regularly
- concurrent reads/writes begin to matter
- history volume grows significantly
- analyst UI or client UI needs stable query performance
- SQLite becomes operationally fragile

**docker-compose criteria:**
- local and VPS environments need reproducible parity
- project now includes multiple services
- PostgreSQL is introduced
- report/UI/API stack needs one-command startup
- environment setup is becoming error-prone

**Rules:**
- PostgreSQL is not mandatory before it is operationally needed
- docker-compose is not mandatory before multi-service complexity exists
- avoid premature infrastructure complexity
- infrastructure changes must follow product and operational needs, not precede them

---

### Preferred Transition Order

1. Complete Reddit v1 locally
2. Generate multi-source client report
3. Review operational pain points
4. Decide on PostgreSQL
5. Decide on docker-compose
6. Then prepare VPS production contour accordingly

---

### Evaluation Output

When this decision gate is reached, the system/project should produce a brief architecture review covering:
- current bottlenecks
- current storage limitations
- current deployment pain points
- recommendation: stay on SQLite + venv / move to PostgreSQL only / move to PostgreSQL + docker-compose

---

## Resolver Extension — Knowledge Base Integration

Resolver must prioritize fragrance_master before any dynamic logic.

### Resolution Order (UPDATED)
1. Pre-normalization
2. Exact alias match (from fragrance_master)
3. Fuzzy match (against fragrance_master)
4. Optional AI arbitration
5. Unresolved → Discovery Layer

### Rules
- Resolver must NOT create new canonical entities directly
- All new entities must go through Discovery Layer
- fragrance_master remains the only source of canonical truth

---

## Signal Attribution Rule

All signals (mentions, engagement, trends) must be attached to resolved canonical entities.

### Rules
- Do NOT score raw text mentions directly
- All analytics must operate on `fragrance_id` and `brand_id`

### Example
Input: `"best delina perfume 2025"` → fragrance_id → Parfums de Marly Delina

### Impact
- Prevents duplication
- Ensures accurate aggregation
- Enables reliable trend scoring

---

## Static vs Dynamic Data Separation

The system must strictly separate:

### Static Layer
- `fragrance_master`
- `aliases`

### Dynamic Layer
- `mentions`
- `signals`
- `trends`
- engagement data

### Rules
- Static data must not be mutated by runtime signals
- Dynamic signals must not redefine canonical entities
- Updates to static layer must be explicit and controlled

---

### Canonical data model
The project should maintain canonical entity tables:
- `brands`
- `perfumes`
- `aliases`

Recommended minimum fields:

#### brands
- `id`
- `canonical_name`
- `normalized_name`

#### perfumes
- `id`
- `brand_id`
- `canonical_name`
- `normalized_name`
- `default_concentration` (optional)

#### aliases
- `id`
- `alias_text`
- `normalized_alias_text`
- `entity_type` (`brand`, `perfume`)
- `entity_id`
- `match_type` (`manual`, `exact`, `fuzzy`, `ai_confirmed`)
- `confidence`
- `created_at`
- `updated_at`

### Mention and resolution storage
Never store only the final canonical ID.
Each resolved mention must preserve:
- raw text
- normalized text
- extracted candidate
- resolved entity id
- resolved entity type
- resolution method
- resolution confidence
- source
- timestamp
- weight / score if available

This is required so the system can re-resolve history later if matching logic improves.

### Unknown / unresolved handling
If no reliable match is found:
- do not discard the mention
- store it in an unresolved queue for later review

Suggested unresolved fields:
- `id`
- `raw_text`
- `normalized_text`
- `candidate_text`
- `source`
- `mention_id`
- `reason`
- `created_at`

### Fuzzy matching policy
- Use RapidFuzz for fuzzy matching.
- Do not run fuzzy search blindly across everything if candidate narrowing is available.
- Initial thresholds:
  - `>= 92`: auto-accept
  - `80-91`: review or optional AI validation
  - `< 80`: unresolved

Thresholds can be tuned later using real data.

### LLM usage policy
Use LLMs only when:
- exact match failed
- fuzzy score is in the ambiguous middle range
- the mention is high-value enough to justify cost
- the alias is not already known

LLM outputs must be structured JSON when used for validation.

Example shape:
```json
{
  "is_match": true,
  "canonical_name": "Baccarat Rouge 540",
  "entity_type": "perfume",
  "confidence": 0.88,
  "reason": "BR540 is a common shorthand for Baccarat Rouge 540"
}
```

---

## Project Identity

**Working title:** Perfume Trend Intelligence SDK (PTI SDK)
**Internal aliases:** PTI SDK, Perfume Signals Engine, Fragrance Trend OS

**Mission:** Build a modular platform for collecting, normalizing, analyzing, and packaging perfume trend signals from the US market (social platforms, retail sources, commercial data) — reusable across media, app, B2B analytics, affiliate models, and future data APIs.

---

## Technology Stack

| Concern | Choice |
|---------|--------|
| Language | Python 3.11+ |
| Data validation | Pydantic v2 |
| HTTP client | requests / httpx |
| Browser automation | Playwright (when needed) |
| Storage (dev) | SQLite with PostgreSQL-ready abstractions |
| File formats | JSONL, CSV, Markdown |
| Scheduling | cron / GitHub Actions / lightweight task runner |
| Testing | pytest |
| Logging | Structured JSON logs |

---

## AI Layer Rules (NEVER VIOLATE)

- AI extractors must be model-agnostic — logic lives in engine, not pipeline
- All AI engines must return the same unified output schema
- AI is an optional layer — pipeline must work without it
- Rule-based extractor remains the fallback
- Always route through `get_extractor(provider)` — never instantiate engines directly in pipeline
- Source intelligence is a first-class signal — not metadata decoration

---

## Architecture Principles (NEVER VIOLATE)

1. **Interfaces first, then implementation** — define contracts before writing logic
2. **No source dictates the data model** — connectors adapt to canonical schema, not the other way around
3. **No analytics inside connectors** — connectors return raw data only
4. **Each layer stores its own result separately** — raw ≠ normalized ≠ signals ≠ enriched
5. **Every block must have a clear replacement point** — weak coupling everywhere
6. **Historical data must be reprocessable** — never overwrite raw with interpreted data
7. **Loose coupling** — connector knows nothing about scoring; scoring doesn't depend on collection method

---

## Architecture Layers

| Layer | Name | Responsibility |
|-------|------|----------------|
| 1 | Core | Config loading, module registry, pipeline routing, error handling, logging, versioning |
| 2 | Connectors | Fetch raw data from external sources, maintain cursors, return raw payload |
| 3 | Normalization | Convert raw source into canonical CanonicalContentItem |
| 4 | Extraction | Extract perfume/brand/note/price/retailer mentions, classify signal type |
| 5 | Resolution | Deduplicate entities, build alias mapping, identity layer |
| 6 | Enrichment | Add official notes, prices, retailer list, discount signals |
| 7 | Scoring & Analytics | Compute trend score, creator influence, note momentum, rising perfumes |
| 8 | Output / Delivery | Publish to CSV, JSON, Google Sheets, markdown report, API |
| 9 | SDK Layer | Module interfaces, developer docs, config templates, test fixtures |

---

## Project Structure

```
perfume_trend_sdk/
  pyproject.toml
  README.md
  .env.example
  configs/
    app.yaml
    sources/
      youtube.yaml
      tiktok_watchlist.yaml
      instagram_watchlist.yaml
      retail_prices.yaml
    watchlists/
      creators_us.yaml
      brands_us.yaml
      retailers_us.yaml
    scoring/
      trend_score.yaml
  core/
    config/
    registry/
    pipeline/
    logging/
    errors/
    models/
    types/
    utils/
  connectors/
    youtube/
    tiktok_watchlist/
    instagram_watchlist/
    retail_prices/
    brand_sites/
  normalizers/
    social_content/
    commerce_snapshot/
  extractors/
    perfume_mentions/
    brand_mentions/
    note_mentions/
    price_mentions/
    retailer_mentions/
    recommendation_signals/
  resolvers/
    perfume_identity/
    brand_identity/
  enrichers/
    perfume_metadata/
    pricing/
    discounts/
  scorers/
    trend_score/
    creator_weight/
    note_momentum/
  storage/
    interfaces/
    raw/
    normalized/
    signals/
    entities/
    analytics/
  publishers/
    json/
    csv/
    markdown/
    sheets/
  workflows/
    ingest_social_content.py
    enrich_market_data.py
    build_weekly_report.py
  tests/
    unit/
    integration/
    fixtures/
  docs/
    schemas/
    module_contracts/
```

---

## Base Types (Core)

```python
class PipelineContext(BaseModel):
    run_id: str
    workflow_name: str
    started_at: datetime
    environment: str
    schema_version: str
    extractor_version: str | None = None
    scoring_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class FetchCursor(BaseModel):
    source_name: str
    cursor_type: str
    cursor_value: str | None = None
    updated_at: datetime

class FetchSessionResult(BaseModel):
    source_name: str
    fetched_count: int
    success_count: int
    failed_count: int
    next_cursor: FetchCursor | None = None
    raw_items: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

---

## SDK Module Contracts (Python Protocols)

```python
class SourceConnector(Protocol):
    name: str
    version: str
    def validate_config(self, config: dict[str, Any]) -> None: ...
    def healthcheck(self) -> bool: ...
    def get_cursor(self) -> FetchCursor | None: ...
    def set_cursor(self, cursor: FetchCursor) -> None: ...
    def fetch(self, context: PipelineContext, limit: int | None = None) -> FetchSessionResult: ...

class Normalizer(Protocol):
    name: str
    version: str
    def normalize(self, raw_item: dict[str, Any], context: PipelineContext) -> CanonicalContentItem: ...

class Extractor(Protocol):
    name: str
    version: str
    def extract(self, content_item: CanonicalContentItem, context: PipelineContext) -> ExtractedSignals: ...

class Resolver(Protocol):
    name: str
    version: str
    def resolve(self, signals: ExtractedSignals, context: PipelineContext) -> ResolvedSignals: ...

class Enricher(Protocol):
    name: str
    version: str
    def enrich(self, entity: dict[str, Any], context: PipelineContext) -> dict[str, Any]: ...

class Scorer(Protocol):
    name: str
    version: str
    def score(self, entity: dict[str, Any], context: PipelineContext) -> dict[str, Any]: ...

class Publisher(Protocol):
    name: str
    version: str
    def publish(self, payload: dict[str, Any], destination: dict[str, Any], context: PipelineContext) -> None: ...

class ModuleRegistry(Protocol):
    def register_connector(self, connector: SourceConnector) -> None: ...
    def register_normalizer(self, normalizer: Normalizer) -> None: ...
    def register_extractor(self, extractor: Extractor) -> None: ...
    def register_resolver(self, resolver: Resolver) -> None: ...
    def register_enricher(self, enricher: Enricher) -> None: ...
    def register_scorer(self, scorer: Scorer) -> None: ...
    def register_publisher(self, publisher: Publisher) -> None: ...
    def get_connector(self, name: str) -> SourceConnector: ...
    def get_normalizer(self, name: str) -> Normalizer: ...
    def get_extractor(self, name: str) -> Extractor: ...
    def get_resolver(self, name: str) -> Resolver: ...
    def get_enricher(self, name: str) -> Enricher: ...
    def get_scorer(self, name: str) -> Scorer: ...
    def get_publisher(self, name: str) -> Publisher: ...
```

**Contract rules:**
- `fetch()` returns raw records only — no analytics, no alias resolution
- `normalize()` must not discard reference to raw payload; must be deterministic
- `extract()` must record confidence where applicable; must not call publishers
- Extractor/Scorer/Publisher output must be versioned

---

## Canonical Schemas (Pydantic v2)

```python
class EngagementMetrics(BaseModel):
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None

class CanonicalContentItem(BaseModel):
    id: str
    schema_version: str
    source_platform: Literal["youtube", "tiktok", "instagram", "other"]
    source_account_id: str | None = None
    source_account_handle: str | None = None
    source_account_type: Literal["creator", "brand", "retailer", "other"] | None = None
    source_url: str
    external_content_id: str | None = None
    published_at: datetime
    collected_at: datetime
    content_type: Literal["video", "short", "reel", "post", "other"]
    title: str | None = None
    caption: str | None = None
    text_content: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions_raw: list[str] = Field(default_factory=list)
    media_metadata: dict[str, Any] = Field(default_factory=dict)
    engagement: EngagementMetrics = Field(default_factory=EngagementMetrics)
    language: str | None = None
    region: str = "US"
    raw_payload_ref: str
    normalizer_version: str

class EntityMention(BaseModel):
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = None
    start_char: int | None = None
    end_char: int | None = None

class PriceMention(BaseModel):
    raw_text: str
    currency: str | None = None
    amount: float | None = None
    confidence: float | None = None

class ExtractedSignals(BaseModel):
    content_item_id: str
    schema_version: str
    extractor_version: str
    perfume_mentions: list[EntityMention] = Field(default_factory=list)
    brand_mentions: list[EntityMention] = Field(default_factory=list)
    note_mentions: list[EntityMention] = Field(default_factory=list)
    retailer_mentions: list[EntityMention] = Field(default_factory=list)
    price_mentions: list[PriceMention] = Field(default_factory=list)
    discount_mentions: list[EntityMention] = Field(default_factory=list)
    recommendation_tags: list[str] = Field(default_factory=list)
    sentiment_hints: list[str] = Field(default_factory=list)
    usage_context_tags: list[str] = Field(default_factory=list)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)

class ResolvedEntityLink(BaseModel):
    entity_type: Literal["perfume", "brand", "retailer", "note"]
    entity_id: str
    canonical_name: str
    matched_from: str
    confidence: float | None = None

class ResolvedSignals(BaseModel):
    content_item_id: str
    resolver_version: str
    resolved_entities: list[ResolvedEntityLink] = Field(default_factory=list)
    unresolved_mentions: list[str] = Field(default_factory=list)
    alias_candidates: list[dict[str, Any]] = Field(default_factory=list)

class PerfumeEntity(BaseModel):
    perfume_id: str
    brand_id: str | None = None
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    concentration: str | None = None
    official_notes: list[str] = Field(default_factory=list)
    family: str | None = None
    status: Literal["active", "discontinued", "unknown"] = "unknown"
    metadata_sources: list[str] = Field(default_factory=list)
    entity_version: str

class PriceSnapshot(BaseModel):
    id: str
    perfume_id: str
    retailer_id: str
    captured_at: datetime
    currency: str = "USD"
    price: float | None = None
    list_price: float | None = None
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    product_url: str
    source_name: str

class DiscountSnapshot(BaseModel):
    id: str
    perfume_id: str
    retailer_id: str
    captured_at: datetime
    discount_type: str | None = None
    discount_value: float | None = None
    promo_text: str | None = None
    product_url: str
    source_name: str

class TrendSignal(BaseModel):
    perfume_id: str
    window: Literal["7d", "30d"]
    mention_count: int
    engagement_weighted_mentions: float
    creator_weighted_mentions: float
    recency_score: float
    novelty_score: float
    trend_score: float
    top_context_tags: list[str] = Field(default_factory=list)
    top_note_mentions: list[str] = Field(default_factory=list)
    scoring_version: str
```

---

## Storage Interfaces

```python
class RawStorage(Protocol):
    def save_raw_batch(self, source_name: str, run_id: str, items: list[dict[str, Any]]) -> list[str]: ...

class NormalizedStorage(Protocol):
    def save_content_items(self, items: list[CanonicalContentItem]) -> None: ...
    def get_content_items(self, ids: list[str]) -> list[CanonicalContentItem]: ...

class SignalStorage(Protocol):
    def save_extracted_signals(self, items: list[ExtractedSignals]) -> None: ...
    def save_resolved_signals(self, items: list[ResolvedSignals]) -> None: ...

class EntityStorage(Protocol):
    def upsert_perfumes(self, items: list[PerfumeEntity]) -> None: ...
    def get_perfume_by_alias(self, alias: str) -> PerfumeEntity | None: ...

class AnalyticsStorage(Protocol):
    def save_trend_signals(self, items: list[TrendSignal]) -> None: ...
    def get_trend_signals(self, window: str) -> list[TrendSignal]: ...
```

**Storage rules:**
- Raw payloads must be persisted **before** normalization results are committed
- Normalized items must reference raw payload location (`raw_payload_ref`)
- Storage must support replay workflows
- Failed items must be traceable to source and run_id

---

## Configuration Structure

### configs/app.yaml
```yaml
app_name: perfume_trend_sdk
environment: dev
schema_version: "1.0"
default_region: US
logging:
  level: INFO
  format: json
storage:
  raw_backend: filesystem
  normalized_backend: sqlite
  signals_backend: sqlite
  entities_backend: sqlite
  analytics_backend: sqlite
workflows:
  ingest_social_content:
    enabled: true
  enrich_market_data:
    enabled: true
  build_weekly_report:
    enabled: true
```

### configs/sources/youtube.yaml (example)
```yaml
name: youtube_watchlist
enabled: true
connector: youtube_connector
normalizer: social_content_normalizer
cursor_strategy: published_after
fetch_limit: 50
watchlist_file: configs/watchlists/creators_us.yaml
rate_limits:
  requests_per_minute: 30
retry:
  max_attempts: 3
  backoff_seconds: 5
```

### configs/watchlists/creators_us.yaml (example)
```yaml
accounts:
  - platform: youtube
    account_handle: "example_creator"
    account_type: creator
    priority: high
    region: US
    active: true
```

### configs/scoring/trend_score.yaml (example)
```yaml
trend_score:
  mention_weight: 1.0
  engagement_weight: 0.5
  creator_weight: 0.8
  recency_weight: 0.7
  novelty_weight: 0.3
creator_weights:
  high: 1.5
  medium: 1.0
  low: 0.7
```

**Lives in config:** active sources, watchlists, fetch params, schedules, scoring weights, output routes, feature flags, account priorities

**Does NOT live in config:** business-critical computations requiring code, complex entity matching algorithms

---

## Workflows

### Workflow A: ingest_social_content
1. Load pipeline context
2. For each enabled social connector:
   - validate config → healthcheck → fetch raw batch → persist raw
   - normalize items → persist canonical content
   - run extractors → persist extracted signals
   - run resolvers → persist resolved signals
   - update cursor
3. Emit workflow summary

### Workflow B: enrich_market_data
1. Load recently resolved perfume entities
2. For each entity: run metadata enricher → price enricher → discount enricher
3. Persist entity updates, price snapshots, discount snapshots
4. Emit enrichment summary

### Workflow C: build_weekly_report
1. Load last 7 days of resolved and enriched data
2. Run scoring modules
3. Aggregate: top perfumes, notes, creators, retailers, discount signals
4. Persist trend signals
5. Publish: JSON + CSV + markdown report + optional Sheets sync

---

## First End-to-End Path (required before multi-source)

```
YouTube watchlist → normalization → extraction → resolution → storage → weekly markdown export
```

Acceptance conditions:
- Source fetch succeeds with cursor support
- Canonical content records are created
- Perfume mentions are extracted from normalized items
- Resolved entities are stored
- Weekly markdown output is generated from stored results

---

## Logging Specification

All runtime logs must be structured JSON with these fields:

```json
{
  "timestamp": "ISO8601",
  "level": "INFO|WARNING|ERROR",
  "run_id": "string",
  "workflow_name": "string",
  "module_type": "connector|normalizer|extractor|...",
  "module_name": "string",
  "event_name": "string",
  "source_name": "string",
  "entity_id": "string (if applicable)",
  "message": "string",
  "error_type": "string (if applicable)"
}
```

---

## Error Handling

### Error Classes
```
ConfigValidationError
ConnectorHealthcheckError
FetchError
NormalizationError
ExtractionError
ResolutionError
EnrichmentError
PublishError
StorageError
```

### Rules
- Connector failure must NOT crash unrelated source workflows
- Item-level normalization errors: log and skip when safe
- Extraction errors: preserve failed content item identifiers
- Publisher failures: must NOT delete analytics results
- Retry only where idempotence is acceptable

### Retry Policy
| Operation | Retry |
|-----------|-------|
| Network fetch | Yes |
| Storage write (idempotent) | Yes |
| Normalization logic bug | No — fail and log |
| Extraction parsing error | No — log for inspection |

---

## Scoring Formula

```
trend_score =
  (mention_count × mention_weight) +
  (engagement_weighted_mentions × engagement_weight) +
  (creator_weighted_mentions × creator_weight) +
  (recency_score × recency_weight) +
  (novelty_score × novelty_weight)
```

- All weights loaded from `configs/scoring/trend_score.yaml`
- Creator tier comes from watchlist metadata (`priority: high/medium/low`)
- Formula must be isolated in scorer module
- Report must display which `scoring_version` was used

---

## Versioning

Required version fields:
- `schema_version` — canonical schema
- `normalizer_version` — normalizer logic
- `extractor_version` — extraction logic
- `resolver_version` — resolution logic
- `scoring_version` — scoring formulas
- `entity_version` — entity shape

**Rule:** Whenever output shape or logic materially changes, the corresponding version must change.
**Replay requirement:** Historical raw data must be replayable through newer versions of normalization, extraction, or scoring.

---

## Security Rules

- Secrets must NOT be hardcoded anywhere in the codebase
- Credentials must come from environment variables or secret manager
- Source configs may reference secret keys by name only
- Logs must NOT expose tokens or session secrets
- Browser automation settings must remain source-isolated

---

## Testing Requirements

### Unit tests (required)
- Config loading
- Connector validation
- Normalizer mapping behavior
- Extractor output shape
- Resolver alias matching
- Scorer formula behavior
- Publisher payload formatting

### Integration tests (required)
- One connector end-to-end through normalization and extraction
- Replay from raw storage
- Weekly report generation from stored data
- Module replacement without breaking registry

### Fixtures (required)
- Raw YouTube-like content item
- Raw Instagram-like content item
- Raw TikTok-like content item
- Ambiguous perfume alias examples
- Price and discount page samples

---

## Module Development Workflow

For every new module, follow this sequence:
1. Define the contract (interface)
2. Create skeleton implementation
3. Create example config
4. Create test cases
5. Register module in registry
6. Run integration
7. Document the interface

---

## Implementation Milestones

| Milestone | Scope |
|-----------|-------|
| 1 | Core skeleton + config loader + registry + logging |
| 2 | YouTube connector + social normalizer + raw/normalized storage |
| 3 | Perfume mention extractor + brand extractor + basic resolver |
| 4 | Weekly markdown report |
| 5 | TikTok and Instagram watchlist connectors |
| 6 | Market enrichment for price and discount signals |
| 7 | Trend scoring + CSV/JSON outputs |
| 8 | SDK cleanup + examples + fixture set |

---

## Implementation Roadmap (Stages)

| Stage | Goal | Status |
|-------|------|--------|
| 0 | Project Charter | Done |
| 1 | Domain Modeling | Done |
| 2 | Core Framework Skeleton | Next → Milestone 1 |
| 3 | First end-to-end pipeline (YouTube) | Milestones 2–4 |
| 4 | Social Source Expansion (TikTok, Instagram) | Milestone 5 |
| 5 | Extraction Engine v1 | Milestone 3 |
| 6 | Identity Resolution Layer | Milestone 3 |
| 7 | Market Enrichment Layer | Milestone 6 |
| 8 | Trend Scoring Engine | Milestone 7 |
| 9 | Reporting & Delivery | Milestones 4, 7 |
| 10 | SDK Packaging | Milestone 8 |
| 11 | Monetization Adapters | Post-v1 |

---

## Definition of Done — v1

- [ ] Minimum 3 sources running
- [ ] Single canonical schema for all v1 sources
- [ ] Perfume mentions extracted and aggregated
- [ ] Notes, prices, and retailers added for at least a subset of entities
- [ ] Weekly report assembled automatically
- [ ] One module can be disabled without breaking the core
- [ ] New connector can be added via template

---

## Scope — v1

**In scope:**
- US market, perfume category
- Watchlist monitoring of known US players
- Level 1: TikTok, Instagram, YouTube watchlists
- Level 2: brand sites, retail pages, price/availability/discount pages
- Normalization, extraction, basic enrichment, trend score, weekly report

**Out of scope for v1:**
- Full TikTok/Instagram/YouTube scan
- Real-time tracking
- Full comment analysis
- Multi-language / multi-region
- Complex recommendation models
- Public SDK for third-party developers

---

## Key Business Questions System Must Answer

1. Which perfumes are currently being promoted in the US by key accounts?
2. Who exactly is promoting them?
3. What exactly are they saying about them?
4. Which notes repeat most often?
5. What price range is being discussed?
6. Where are they sold?
7. Are there signs of discounts, promotions, or commercial pressure?

---

## Implementation Plan v1 — Sprint Breakdown

### Build Philosophy

Build as a sequence of thin, testable vertical slices. Each slice must:
- implement one clear responsibility
- fit the contracts defined in Tech Spec v1
- remain replaceable
- be usable in the next sprint

For each module: define interface → skeleton → minimum logic → tests → integration → document.

---

### Sprint Overview

| Sprint | Goal | Status |
|--------|------|--------|
| 0 | Project bootstrap — repo skeleton, package structure, configs | Done |
| 1 | Core framework — config, registry, logging, models, storage interfaces | Done |
| 2 | First end-to-end source — YouTube → raw → normalize → extract → resolve → markdown | Done |
| 3 | Hybrid AI Intelligence — pre-filter, multi-engine AI extractor, router | Next |
| 3.5 | Source Intelligence — who drives trends, influence scoring, UnifiedSignal extension | Pending |
| 4 | Social expansion — TikTok + Instagram connectors under same contracts | Pending |
| 5 | Intelligence layer — full extraction, resolution, enrichment, scoring | Pending |
| 6 | Output + SDK packaging — CSV/JSON/Sheets publishers, replay, docs, fixtures | Pending |
| 7 | Stabilization — modular review, contract freeze, v1 readiness check | Pending |

---

### Sprint 0 — Project Bootstrap

Exit criteria:
- package structure exists and imports work
- configs load from filesystem path
- pytest runs (even with placeholders)

Files:
```
pyproject.toml, README.md, .env.example
configs/app.yaml, configs/sources/, configs/watchlists/, configs/scoring/
perfume_trend_sdk/__init__.py + all top-level package dirs
tests/ + fixtures/ structure
```

---

### Sprint 1 — Core Framework

Exit criteria:
- foundation modules compile
- config + registry operational
- all core schemas exist
- storage interfaces defined
- core unit tests pass

Modules: `core/config`, `core/registry`, `core/logging`, `core/errors`, `core/models`, `storage/interfaces`

Key files:
```
core/config/models.py          ← AppConfig, LoggingConfig, StorageConfig
core/config/loader.py          ← load_yaml, load_app_config
core/errors/base.py + typed errors
core/logging/logger.py         ← log_event (structured JSON)
core/models/context.py         ← PipelineContext
core/models/fetch.py           ← FetchCursor, FetchSessionResult
core/models/content.py         ← CanonicalContentItem
core/models/signals.py         ← ExtractedSignals, ResolvedSignals
core/models/entities.py        ← PerfumeEntity, PriceSnapshot, DiscountSnapshot
core/models/analytics.py       ← TrendSignal
core/types/contracts.py        ← Protocol interfaces for all module types
core/registry/module_registry.py
storage/interfaces/raw.py + normalized.py + signals.py + entities.py + analytics.py
```

---

### Sprint 2 — First End-to-End Source (YouTube)

Required path before multi-source expansion:
```
YouTube watchlist → raw storage → normalization → extraction → resolution → markdown output
```

Exit criteria:
- fetch returns FetchSessionResult with cursor support
- raw, normalized, extracted, resolved layers all exist in storage
- markdown weekly report generated
- replay from raw manually possible

Key files:
```
connectors/youtube/connector.py + client.py + mappers.py
storage/raw/filesystem.py
normalizers/social_content/normalizer.py
storage/normalized/sqlite_store.py
extractors/perfume_mentions/extractor.py
extractors/brand_mentions/extractor.py
storage/signals/sqlite_store.py
resolvers/perfume_identity/resolver.py + alias_store.py
publishers/markdown/weekly_report.py
workflows/ingest_social_content.py
workflows/build_weekly_report.py
```

---

### Sprint 3 — Hybrid AI Intelligence Layer

**Goal:** Upgrade extraction from rule-based to hybrid AI + multi-engine + source intelligence.

**Architecture:**
```
Fetch → Pre-filter → AI Extractor (via router) → Resolver → Unified Signals → Scoring → Reports
```

**Pipeline rules:**
- Rule-based extractor = fallback (always works without AI)
- AI layer = optional, plugged via router only
- Pipeline must work without AI
- Do NOT hardcode AI logic in pipeline
- All AI engines must return same unified output schema

**Phase A — Pre-filter**
```
extractors/pre_filter/filter.py
```
- Skip non-perfume content before AI call
- Reduce API cost and noise

**Phase B — Multi-Engine AI Extraction**
```
extractors/ai_engines/
    base.py          ← AIExtractor Protocol
    router.py        ← get_extractor(provider: str) -> AIExtractor
    openai_extractor.py
    claude_extractor.py   (placeholder)
    gemini_extractor.py   (placeholder)
```

AI interface:
```python
class AIExtractor(Protocol):
    def extract(self, text: str) -> dict: ...
```

Required unified output schema (ALL engines must return this):
```json
{
  "perfumes": [
    {"brand": "Dior", "product": "Sauvage Elixir", "confidence": 0.95, "sentiment": "positive"}
  ],
  "brands": ["Dior"],
  "notes": ["vanilla", "oud"],
  "sentiment": "positive",
  "confidence": 0.92
}
```

**Phase C — AI Config**
```yaml
ai:
  provider: "openai"
  model: "gpt-4o-mini"
  temperature: 0
  enabled: true
```

**Phase D — Pipeline Integration**
Update: `workflows/test_pipeline.py`, `workflows/ingest_social_content.py`

**Phase E — Cost & Control**
- `max_tokens` config
- Fallback to rule-based extractor on AI failure

**Exit criteria:**
- Pre-filter implemented
- AIExtractor interface defined
- OpenAI extractor working
- Router routes by config provider
- Pipeline works with AI disabled
- Fallback to rule-based confirmed

---

### Sprint 3.5 — Source Intelligence Layer

**Goal:** Identify WHO drives trends and weight their influence.

**Modules:**
```
analysis/source_intelligence/
    analyzer.py
    scoring.py
```

**Output schema:**
```json
{
  "source_type": "influencer | brand | user | bot",
  "influence_score": 0,
  "credibility_score": 0.0,
  "engagement_level": "low | medium | high"
}
```

**UnifiedSignal extension** (`core/models/unified_signal.py`):
- `source_type: str | None`
- `influence_score: float | None`
- `credibility_score: float | None`

**Business value:** System sells influence-weighted intelligence, not raw mention counts.
Example: "80% of Dior hype driven by 3 influencers with >500k audience"

**Exit criteria:**
- Source analyzer classifies source type
- Influence scoring works from metadata
- UnifiedSignal extended with source fields

---

### Sprint 4 — Social Expansion (previously Sprint 3)

Exit criteria:
- TikTok + Instagram connectors conform to same SourceConnector contract
- registry activates source modules by config
- core contracts unchanged

Key files:
```
connectors/tiktok_watchlist/connector.py + client.py + config.py
connectors/instagram_watchlist/connector.py + client.py + config.py
core/config/watchlist_loader.py
configs/watchlists/creators_us.yaml (finalized schema)
```

---

### Sprint 4 — Intelligence Layer

Exit criteria:
- notes, prices, retailers, discounts enter the data model
- brand and perfume aliases resolve from fixtures
- trend scores generated and stored

Key files:
```
extractors/note_mentions/extractor.py
extractors/price_mentions/extractor.py
extractors/retailer_mentions/extractor.py
extractors/recommendation_signals/extractor.py
resolvers/brand_identity/resolver.py
storage/entities/sqlite_store.py
enrichers/perfume_metadata/enricher.py
enrichers/pricing/enricher.py
enrichers/discounts/enricher.py
storage/analytics/sqlite_store.py
scorers/trend_score/scorer.py
scorers/creator_weight/scorer.py
scorers/note_momentum/scorer.py
workflows/enrich_market_data.py
```

---

### Sprint 5 — Output + SDK Packaging

Exit criteria:
- JSON, CSV, optional Sheets outputs available
- replay workflow works
- module template docs exist
- project resembles SDK-ready constructor

Key files:
```
publishers/json/publisher.py
publishers/csv/publisher.py
publishers/sheets/publisher.py (optional)
workflows/replay_from_raw.py
docs/module_contracts/source_connector.md + normalizer.md + extractor.md
sdk/examples/sample_connector.py + sample_extractor.py + sample_publisher.py
tests/fixtures/ (hardened: social, commerce, entities, edge cases)
```

---

### Sprint 6 — Stabilization

Required review checklist:
- YouTube connector swappable without changing extractor logic?
- TikTok connector disableable while report still builds from other sources?
- Raw payloads replayable through newer normalizer versions?
- Scoring weights entirely config-driven?
- Outputs decoupled from internal storage shape?
- New publisher addable without editing connector code?

Exit criteria: all critical integration tests pass, contracts frozen, known limitations documented.

---

### File Build Order Summary

| Phase | Files |
|-------|-------|
| A — Foundation | pyproject.toml, core/config/*, core/errors/*, core/logging/*, core/models/*, core/types/contracts.py, core/registry/module_registry.py, storage/interfaces/* |
| B — First vertical slice | connectors/youtube/*, storage/raw/filesystem.py, normalizers/social_content/normalizer.py, storage/normalized/sqlite_store.py, extractors/perfume_mentions/*, extractors/brand_mentions/*, storage/signals/sqlite_store.py, resolvers/perfume_identity/*, workflows/ingest_social_content.py, publishers/markdown/weekly_report.py, workflows/build_weekly_report.py |
| C — Source expansion | connectors/tiktok_watchlist/*, connectors/instagram_watchlist/*, core/config/watchlist_loader.py |
| D — Intelligence | extractors/note_mentions→recommendation_signals/*, resolvers/brand_identity/*, storage/entities/*, enrichers/*/*, storage/analytics/*, scorers/*/*, workflows/enrich_market_data.py |
| E — Packaging | publishers/json→sheets/*, workflows/replay_from_raw.py, docs/module_contracts/*, sdk/examples/*, tests/fixtures/* |

---

## Perfume Trend Intelligence Engine v1

### 1. Product Definition

Perfume Trend Intelligence Engine is a market terminal for fragrance trends.

**This is NOT:**
- a static dashboard
- a reporting tool
- a simple analytics panel

**This IS:**
- a real-time trend intelligence system
- a decision engine
- a market-like environment, where perfumes, brands, notes, and accords behave like tradable entities (similar to stocks/assets)

The system must allow users to:
- detect rising trends early
- monitor momentum
- compare entities
- identify breakouts and reversals
- understand WHY something is moving

---

### 2. Core Product Metaphor

All tracked entities behave like market instruments.

Each entity has:
- score (like price)
- momentum
- volume
- volatility
- signals

UI and backend must follow this model strictly.

---

### 3. Core Entities

**Primary**
- Brand
- Perfume
- Note
- Accord

**Secondary**
- Creator (TikTok / YouTube / etc.)
- Channel (TikTok, YouTube, Google Trends, etc.)
- Retailer (Amazon, etc.)
- Signal Event

---

### 4. Existing Data (DO NOT REMOVE)

The system already includes:
- `mention_count` (weighted float)
- `influence_score` weighting
- sentiment multiplier: positive → ×1.2, negative → ×0.5
- `ai_confidence` multiplier
- `trend_score`
- `mentions_last_24h`
- `mentions_prev_24h`
- `growth`

These must remain intact. All new layers must build on top of this, not replace it.

---

### 5. Required Backend Architecture (Market Engine)

**Layer A — Ingestion**

Collect data from:
- YouTube (metadata)
- Google Trends
- Reddit
- News / blogs
- Fragrance datasets (GitHub / Kaggle)
- Keepa API (Amazon proxy)

**Layer B — Entity Resolution**
- detect brands, perfumes, notes, accords
- resolve aliases and misspellings
- map mentions → entities

**Layer C — Enrichment**
- sentiment
- confidence
- influence score
- engagement normalization
- channel attribution
- region attribution

**Layer D — Aggregation**

Store time-bucketed data:
- hourly (short-term)
- daily (core)
- weekly/monthly (long-term)

**Layer E — Derived Metrics**

Compute:
- `composite_market_score`
- momentum
- acceleration
- volatility
- source_diversity
- creator_velocity
- saturation_risk
- forecast_score

**Layer F — Signal Engine**

Detect:
- breakout
- acceleration spike
- reversal
- divergence
- creator-driven spike
- cross-channel confirmation
- note fatigue

**Layer G — Serving Layer**

Expose API endpoints for UI:
- dashboard
- screener
- entity page
- charts
- signals
- watchlists
- alerts

---

### 6. Data Model Requirements

**Required new fields**

Each entity must have:
- `entity_id`
- `entity_type`
- `ticker` (short symbol)

Time series must include:
- `timestamp`
- `mention_count`
- `unique_authors`
- `engagement_sum`
- `sentiment_avg`
- `search_index`
- `retailer_score`
- `composite_market_score`
- `acceleration`
- `volatility`
- `forecast_score`

---

### 7. UI Principles (MANDATORY)

UI must follow financial terminal logic, not ecommerce.

**Required characteristics:**
- dark theme
- data-dense layout
- real-time feel
- chart-first design
- comparison-friendly
- sortable tables
- filters everywhere

**Avoid:**
- "beauty brand" UI
- decorative layouts
- large empty spaces
- marketing-style pages

The UI must feel like TradingView or a simplified Bloomberg terminal.

---

### 8. API Design Principles

APIs must return:
- precomputed data
- chart-ready time series
- screener-ready rows

Frontend must NOT:
- compute metrics from raw mentions
- aggregate heavy datasets

All heavy computation belongs to backend.

---

### 9. Data Source Policy

**Allowed sources:**
- Google Trends
- YouTube metadata
- Reddit
- News / blogs
- Fragrance datasets (GitHub / Kaggle)
- Keepa API (Amazon data proxy)

**Amazon Policy:**
- Use Keepa API for: price history, rank proxy, stock proxy
- DO NOT use Amazon Seller / SP-API
- DO NOT require seller account authentication

---

### 10. Development Rules

- DO NOT delete existing pipeline
- ALWAYS extend current system
- EACH feature must map to: entity, metric, signal, workflow

**Prefer:**
- precomputation
- normalized data
- reusable metrics

**Avoid:**
- one-off scripts
- UI-specific logic in backend
- raw data exposure

---

### 11. V1 Scope (STRICT PRIORITY)

Build in this order:
1. Entity master tables (brands, perfumes, notes, accords)
2. Time-series storage
3. Composite market score
4. Dashboard API
5. Top movers table
6. Screener API
7. Entity page (summary + chart)
8. Signal detection v1
9. Watchlists

---

### 12. V2 Scope

After V1:
- Notes & accords rotation engine
- Relationship graph
- Channel attribution layer
- Creator influence system
- Saturation detection
- Forecast engine

---

### 13. Product Goal

The system must allow users to feel:
- they are watching a live market
- they can discover trends early
- data is actionable
- movement is visible and explainable

This is NOT about data display. This is about decision advantage.

---

### 14. Golden Rule

If a feature does not:
- improve trend detection
- improve decision speed
- improve signal clarity

→ it should NOT be implemented.

---

## 15. Frontend Terminal Architecture (V1)

The frontend for Perfume Trend Intelligence Engine must be implemented as a **desktop-first market terminal**, not as a marketing site or ecommerce storefront.

### Frontend goals

The frontend must:

* render dense market intelligence clearly
* support fast scanning of movers, signals, and entities
* prioritize dashboard, screener, and entity workflows
* remain compatible with future watchlists, alerts, and compare features

### Core frontend stack

Preferred stack:

* Next.js
* React
* TypeScript
* Tailwind CSS
* TanStack Query
* Zustand
* TanStack Table
* Recharts for V1 charts

The stack may be adapted to the existing repo if needed, but the architecture and interaction model must remain consistent.

### Frontend page structure

Required V1 routes:

* `/dashboard`
* `/screener`
* `/entities/[entityId]`
* `/watchlists` (placeholder allowed in V1)
* `/alerts` (placeholder allowed in V1)

The root route may redirect to `/dashboard`.

### App shell rules

The app must use a shared terminal shell with:

* left sidebar
* top navigation/header
* main content region

Sidebar items:

* Dashboard
* Screener
* Watchlists
* Alerts

The shell must be:

* dark-first
* compact
* desktop-first
* route-aware with active state highlighting

### Primary UI pages

#### Dashboard

The dashboard must include:

* top control bar
* KPI strip
* top movers table
* main chart panel
* signal feed panel

The dashboard is the market overview screen and should answer:

* what is moving?
* how strongly is it moving?
* what just triggered?

#### Entity page

The entity page must include:

* entity header
* main chart
* metrics rail
* signal timeline
* recent mentions

The entity page should answer:

* what is happening?
* how strong is it?
* why is it happening?
* what should the user watch next?

#### Screener

The screener must include:

* quick controls
* advanced filters
* sortable results table
* pagination footer

The screener is the discovery workflow and should allow users to hunt for opportunities quickly.

### Watchlists and alerts

In V1:

* watchlists and alerts may exist as scaffold or placeholder routes
* do not build full workflow unless explicitly requested
* preserve route structure so the product can expand cleanly later

### Shared design system requirements

All frontend work must use a consistent terminal-style design system.

Required shared primitives:

* TerminalPanel
* SectionHeader
* KpiCard
* MetricBadge
* DeltaBadge
* SignalBadge
* EmptyState
* ErrorState
* LoadingSkeleton
* ControlBar
* SearchInput
* FilterChip
* ChartContainer

Design principles:

* information first
* dense but readable
* semantic color only
* consistent formatting across all pages

### Table rules

Tables are core UI infrastructure.

Use a reusable table system for:

* top movers
* screener
* watchlists later
* alerts later

Tables must support:

* compact density
* sortable headers
* row click
* loading state
* empty state

### Chart rules

Charts must be used as analytical tools, not decoration.

V1 charts should:

* use line charts
* support time range switching where practical
* use real backend timeseries
* prioritize clarity over animation

### API integration rules

Frontend must consume real backend APIs where available.

Do:

* centralize API calls in a dedicated API layer
* use typed response models
* use TanStack Query for server-state
* keep server data out of local UI stores

Do not:

* fetch directly in deeply nested presentational components
* scatter formatting logic across pages
* hardcode fake market data when real endpoints exist

### State management rules

Use:

* TanStack Query for server state
* Zustand only for local UI state

Examples of local UI state:

* selected dashboard entity
* modal open/close
* screener panel open/close
* active watchlist id later
* chart mode toggle

Do not use a large global store for backend responses.

### URL and filter behavior

Screener filters should be URL-friendly where practical.

Examples:

* entity type
* signal type
* min score
* min confidence
* min mentions
* sort_by
* order
* offset

This ensures shareable and reproducible views.

### Formatting rules

Use a shared adapter/formatter layer for:

* score formatting
* growth formatting
* confidence formatting
* signal labels
* timestamps

Do not duplicate formatting logic across components.

### Frontend build order

When implementing the frontend, build in this order:

1. app shell
2. shared primitives
3. dashboard page
4. entity page
5. screener page
6. watchlists placeholder
7. alerts placeholder

### Frontend non-goals for V1

Do not prioritize:

* landing page
* auth system
* ecommerce-style branding
* animation-heavy UI
* full compare mode
* full watchlist workflow
* full alerts workflow

### Golden frontend rule

If a frontend change does not improve:

* market readability
* decision speed
* signal clarity
* workflow efficiency

then it should not be prioritized.

---

## 16. Frontend/Backend Contract Rules

The frontend must treat the backend as the source of truth for:

* market scores
* growth rates
* confidence
* signals
* timeseries
* screener filtering results

### Rules

* do not recompute backend market metrics in the frontend
* do not derive alternative signal logic in the frontend
* only format and present backend values
* keep frontend adapters lightweight and presentation-focused

### Page-to-endpoint mapping

* Dashboard → `/api/v1/dashboard`
* Screener → `/api/v1/screener`
* Entity Page → `/api/v1/entities/{id}`
* Signals feed → `/api/v1/signals`

### Contract principle

If payload shape mismatches UI needs:

* prefer lightweight frontend adapters first
* only change backend when the mismatch is structural or repeated

---

## 17. Current Product Stage

The project is currently in the transition from backend foundation to frontend terminal implementation.

This means:

* backend market engine is already functional
* API payloads are terminal-ready for V1
* frontend work should now focus on dashboard, entity page, and screener
* watchlists and alerts remain secondary in the first frontend build pass

---

## 18. Watchlists and Alerts (V1)

The next product layer after the core terminal is a personal monitoring workflow built around watchlists and alerts.

### Watchlists goals

Watchlists allow users to:

* save important entities
* group them into named lists
* return quickly to a curated set of perfumes and brands
* monitor signal activity without re-running searches

### Alerts goals

Alerts allow users to:

* be notified when meaningful entity changes happen
* react to breakouts, acceleration, and threshold changes
* reduce the need to manually check the terminal repeatedly

### V1 watchlists scope

Implement only:

* manual watchlists
* add/remove entities
* watchlist detail view with enriched market fields
* watchlist activity based on signals affecting watched entities

Do not implement yet:

* team/shared watchlists
* dynamic screener-based watchlists
* folders/tags
* complex notes system

### V1 alerts scope

Implement only:

* entity-based alerts
* in-app delivery only
* active/paused state
* trigger history
* cooldown support
* simple condition types

Do not implement yet:

* email/slack delivery
* team notification routing
* screener-wide alerts
* boolean rule builders
* AI-generated alert conditions

### V1 alert condition types

Allowed V1 conditions:

* breakout_detected
* acceleration_detected
* any_new_signal
* score_above
* growth_above
* confidence_below

### Watchlist and alert principle

This layer must transform the terminal from a place users visit occasionally into a place they can rely on continuously.

---

## 19. Alerting Rules

Alerts must be low-noise and meaningful.

### Rules

* the backend is the source of truth for alert evaluation
* the frontend must never independently evaluate alert conditions
* alerts should only trigger on explicit backend-supported conditions
* every alert type must map to clear stored logic
* repeated alerts require cooldown protection

### Cooldown

Every alert must support a cooldown window.
Default V1 behavior should use a 24-hour cooldown unless explicitly configured otherwise.

If a condition remains true during the cooldown period:

* do not generate a fresh active alert event
* optionally record a suppressed event for diagnostics later

### Alert quality principle

It is better to deliver fewer, more meaningful alerts than many repetitive alerts.
A noisy alert system reduces trust in the product.

---

## 20. Current Product Direction

The project has now moved from:

* backend market engine foundation
* terminal frontend foundation
  into:
* monitoring and retention workflow

Current product priority:

1. core terminal stability
2. watchlists
3. alerts
4. later deployment and live ingestion hardening

The next implementation work should focus on turning analytics into persistent user workflows.

---

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

**As of 2026-04-20**

| Layer | Status |
|-------|--------|
| Knowledge Base (seed) | OPERATIONAL — Kaggle + curated, ~2,240 perfumes |
| Live ingestion | OPERATIONAL — YouTube + Reddit, 2× daily |
| Fragrantica enrichment | DEPLOY COMPLETE · PRODUCTION BLOCKED (Fragrantica 403 from Railway IPs) |
| Notes / accords layer | DEPLOY COMPLETE · schema in production · awaiting real data |
| Discovery loop | MISSING — fragrance_candidates table not created |
| Coverage maintenance service | NOT IMPLEMENTED |
| Historical backfill layer | NOT IMPLEMENTED |
| Backup policy | NOT YET IMPLEMENTED |

### Current Priority Order

1. ~~Stabilize KB production seeding~~ — **DONE (Phase 0)**
2. ~~Activate Fragrantica enrichment (DB tables + pipeline integration)~~ — **CODE COMPLETE · PRODUCTION BLOCKED** — unblock fetch layer (Playwright / cookie injection), then deploy + verify
3. Add notes / accords tables + populate from Fragrantica — **CODE COMPLETE · awaiting real data**
4. Build discovery loop (fragrance_candidates table + promotion flow)
5. Build coverage maintenance service
6. Implement backup policy

---

## Phase 1 — Fragrantica Enrichment Activation

### Status
- Code complete
- Deploy complete
- Production DB path verified
- Production blocked by Fragrantica HTTP 403

### Verified in production
- Alembic migration 008 applied successfully
- Production PostgreSQL contains:
  - fragrantica_records
  - notes
  - accords
  - perfume_notes
  - perfume_accords
- identity map lookup works
- DB persistence path works
- notes_summary update path works

### External blocker
Live Fragrantica fetch from Railway IPs returns HTTP 403.
This is an external access constraint, not a schema or persistence bug.

### Rule
Phase 1 is not considered fully source-operational until the fetch layer is upgraded
to a Playwright-based or cookie-backed client and a real enrichment batch succeeds.

---

## Phase 1b — Fragrantica Access Layer (Fetch Unblock)

### Purpose

Unblock real Fragrantica data ingestion by replacing the HTTP fetch layer.

### Context

Direct HTTP requests from Railway IPs return HTTP 403 due to bot protection.

The enrichment pipeline, DB schema, and persistence layer are fully operational.
Only the fetch layer is blocked.

### Requirement

`FragranticaClient.fetch_page(url)` must be upgraded to a browser-based or
authenticated request mechanism.

### Accepted Solutions

- Playwright-based headless browser (preferred)
- Cookie-injected HTTP client (if stable)
- Hybrid (browser fetch → cached HTML → parser)

### Rules

- The fetch layer must be isolated behind a single interface:
  `fetch_page(url) → html string`

- The rest of the pipeline (parser, normalizer, store) MUST NOT change

- Raw HTML must still be stored for replay/debug

- Failures must be per-entity, not global

### Completion Criteria

Phase 1b is complete when:

1. At least 50 perfumes are successfully fetched from live Fragrantica pages
2. `parsed > 0`, `enriched > 0`
3. DB rows inserted into:
   - `fragrantica_records`
   - `perfume_notes`
   - `perfume_accords`
4. `notes_summary` updated for those perfumes

### Status

Pending implementation

---

## Phase 0 — KB Stabilization (COMPLETED)

### Status

Phase 0 (Knowledge Base stabilization and seeding) is complete.

### Achievements

- Restored Postgres-compatible fragrance master store (`pg_fragrance_master_store.py`, SQLAlchemy-based)
- Unified seeding entrypoint (`scripts/seed_kb.py`)
- Verified repeatable seed load for:
  - fragrance_master
  - aliases
  - brands
  - perfumes
- Identity mapping between resolver (`data/resolver/pti.db`) and market DB is stable
- brands: 260/260 linked, perfumes: 2246/2247 linked

### Known Behaviors (NOT bugs)

#### Alias Count Variance

Alias count differences across environments are expected.

Cause:
- Different CSV load order (seed_master vs seed_placeholder)
- ID assignment differences in resolver DB

Impact:
- No duplicate entities created
- Resolver behavior remains correct
- Some aliases intentionally map to multiple entities (e.g. base vs concentration variants)

This behavior is accepted and should NOT be "fixed".

#### Alias Collisions

Examples like:
- `"aventus"` → base entity (`Creed Aventus`, pid=27) + EDP variant (`Creed Aventus Eau de Parfum`)

Are expected and beneficial.

Resolver prioritizes:
- base entity (lower ID)

This is consistent with concentration-stripping aggregation logic.

### Known Edge Case

**"Les Bains Guerbois Eau de Cologne"**

Issue:
- Name contains `"Eau de Cologne"` as part of the actual product name (not a concentration qualifier)
- `seed_market_catalog.py` strips standalone `Cologne` → produces malformed entry `name='Eau de'`, `slug='les-bains-guerbois-eau-de'`
- `sync_identity_map.py` strips full `"Eau de Cologne"` → expects slug `'les-bains-guerbois'` → no match → 1 unlinked perfume

Status:
- Known issue, documented
- Low impact — brand is not in tracked watchlist, has not appeared in any ingestion data
- Deferred fix — do not modify normalization rules globally for this case

### Rule

Do NOT rework seeding logic unless:
- data integrity is broken
- resolver produces incorrect matches

---

## Execution Rule — Phase Completion

A phase is NOT considered complete when code is only implemented locally.

Each phase must pass 3 gates:

**1. Code Complete**
- implementation finished
- local tests pass
- local DB state verified

**2. Deploy Complete**
- changes pushed to main
- Railway deployment completed
- Alembic migrations applied successfully

**3. Production Verified**
- target workflow executed in Railway
- expected DB/state changes confirmed
- smoke-check passed

### Rule

CLAUDE.md may record a phase as fully complete only after all 3 gates pass.

If code is complete but production is blocked by an external constraint
(e.g. third-party 403, missing credentials, infra limitation),
the phase must be marked as:

- **code-complete**
- **production-blocked**

not fully complete.
