# Resolver Architecture

Extracted from CLAUDE.md on 2026-05-05.

## Architecture Guardrails

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


---

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


---

## O5 — Resolver DB Path Rule

## O5. Resolver DB Path Rule

Production resolver state must be updated in the production-path resolver database.

### Rule

For any KB-changing phase (Phase 4b, 4c, and future promotion phases):

- do NOT assume `outputs/pti.db` is the production resolver source
- the authoritative production-path resolver DB is `data/resolver/pti.db`

### Requirement

All promotion runs that mutate KB state must target the resolver DB actually used by deployment/runtime.

Run promotion jobs as:
```bash
RESOLVER_DB_PATH=data/resolver/pti.db PTI_DB_PATH=outputs/market_dev.db \
  python3 -m perfume_trend_sdk.jobs.<phase_job> ...
```

Or copy after a local run:
```bash
cp outputs/pti.db data/resolver/pti.db
```

### Verification

After any KB mutation phase, always verify both DBs:

```bash
sqlite3 data/resolver/pti.db "SELECT COUNT(*) FROM perfumes; SELECT COUNT(*) FROM aliases; SELECT COUNT(*) FROM fragrance_master;"
sqlite3 outputs/pti.db         "SELECT COUNT(*) FROM perfumes; SELECT COUNT(*) FROM aliases; SELECT COUNT(*) FROM fragrance_master;"
```

Counts must match. New entities and aliases must appear in `data/resolver/pti.db` before committing and pushing.

### Why this matters

`data/resolver/pti.db` is the file checked into git and deployed to Railway. `outputs/pti.db` is a local working copy only — it is gitignored in effect (large binary, not pushed routinely). A KB change applied only to `outputs/pti.db` is invisible to the production pipeline until `data/resolver/pti.db` is updated and pushed.

**Incident reference:** Phase 4b+4c (2026-04-21) — all KB changes were applied only to `outputs/pti.db`. Production resolver was stale for 5 days (April 16–21). Fixed by commit 3de63d1.

---


---

## Resolver Persistence Rule

> ⚠️ **SUPERSEDED by Phase R1 (2026-04-21).** The Railway Volume / RESOLVER_DB_PATH approach described below was rolled back. The active architecture is Phase R1: Postgres `resolver_*` tables. See `## ✅ Current Architecture` and `## 🚀 Migration Plan` below.

~~The production resolver catalog must not rely on ephemeral container filesystem state.~~

**Active rule:** Resolver catalog lives in Postgres `resolver_*` tables (migration 014). `PerfumeResolver` is constructed via `make_resolver()` which auto-selects `PgResolverStore` when `DATABASE_URL` is set, or `FragranceMasterStore(db_path)` for local SQLite fallback. No `RESOLVER_DB_PATH` env var. No Railway Volume.

---

## 🚫 Deprecated Architecture: Resolver Volume / SQLite

The project previously attempted to use a Railway volume mounted at `/app/resolver-vol`
to store a SQLite database (`pti.db`) for resolver/catalog logic.

This approach is **fully deprecated and must NOT be used**.

### ❌ Запрещено:
- Using SQLite (`pti.db`) as resolver storage
- Any filesystem-based DB under `/app/*`
- Railway volumes for KB / resolver state
- Copying seed DB files into containers
- mkdir/chmod/chown logic for resolver storage
- Any fallback to local DB

### Причина:
Railway volumes:
- cannot be shared across services reliably
- introduce permission issues (chmod/chown failures)
- break multi-service architecture
- are not needed because Postgres already exists

---

## ✅ Current Architecture: Postgres as Single Source of Truth

All resolver, catalog, and identity data MUST live in Postgres.

### Source of truth:
- `DATABASE_URL` (Postgres)

### Used by:
- `pipeline-daily`
- `pipeline-evening`
- resolver
- catalog import

### Expected tables:
- `brands`
- `perfumes`
- `aliases`
- `fragrance_master` (or equivalent KB table)

---

## 🧩 Resolver Rules

Resolver MUST:
- query Postgres directly
- NOT load any local files
- NOT depend on SQLite
- work identically across all services

---

## 🚀 Pipeline Rules

Pipelines MUST:
- read/write ONLY to Postgres
- NOT use local filesystem for state
- be stateless between runs

---

## 🧠 Resolver Architecture

Resolver and Market layers are separate systems.

Resolver uses:
- integer IDs
- `normalized_name`
- `aliases` table
- `fragrance_master` KB

Market uses:
- UUID IDs
- production entities

Resolver MUST NOT use market tables directly.

---

## 🚀 Migration Plan — Phase R1 (PRODUCTION-VERIFIED — 2026-04-21)

Resolver storage migrated from SQLite → Postgres.

### What was implemented

- **Alembic migration 014**: `resolver_brands`, `resolver_perfumes`, `resolver_aliases`, `resolver_fragrance_master` tables — INTEGER PKs, `resolver_` prefix (no collision with UUID market tables)
- **Alembic migration 015**: fixed missing SERIAL sequences for `resolver_aliases.id` and `resolver_fragrance_master.id` (migration 014 missed explicit `CREATE SEQUENCE` + `SET DEFAULT`)
- **`PgResolverStore`** (`perfume_trend_sdk/storage/entities/pg_resolver_store.py`): same interface as `FragranceMasterStore`, backed by Postgres `resolver_*` tables; includes `check_has_data()` fail-fast guard
- **`make_resolver(db_path)`** factory: auto-selects `PgResolverStore` (when `DATABASE_URL` set) or SQLite fallback; calls `check_has_data()` in production to fail fast if migration hasn't run
- **`PerfumeResolver.__init__(store=...)`**: accepts store object; `db_path` kept for backward compat
- **`scripts/migrate_resolver_to_postgres.py`**: idempotent batch migration using `psycopg2.extras.execute_values` (2,000-row batches; 56k rows in ~2 minutes)
- **`scripts/verify_resolver_shadow.py`**: shadow verification — row count parity + 16 resolver alias probes

### Production verification results (2026-04-21)

| Table | SQLite | Postgres | Match |
|-------|--------|----------|-------|
| resolver_brands | 1,608 | 1,608 | ✅ |
| resolver_perfumes | 56,067 | 56,067 | ✅ |
| resolver_aliases | 12,884 | 12,884 | ✅ |
| resolver_fragrance_master | 56,067 | 56,067 | ✅ |

Resolver output parity: 16/16 alias probes pass ✅

Shadow verification: **PASS** — "Production cutover is safe."

### Fail-fast guard (production)

If `resolver_aliases` has fewer than 5,000 rows and `PTI_ENV=production`, `make_resolver()` raises `RuntimeError` immediately. This prevents silent "no matches" when migration has not been run.

---

