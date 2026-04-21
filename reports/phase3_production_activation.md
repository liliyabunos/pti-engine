# Phase 3 Production Activation Check

**Date:** 2026-04-21  
**Scope:** Verify Phase 3 (candidate collection + aggregation + validation) is active in production  
**Status:** COMPLETE — Phase 3 fully active after pipeline fix

---

## A. Schema Check

**Production PostgreSQL — `fragrance_candidates` table**

| Check | Result |
|-------|--------|
| Table exists | ✅ EXISTS |
| Row count | **2,300** (as of 2026-04-21 morning pipeline) |

### Columns present

| Column | Type | Phase |
|--------|------|-------|
| raw_text | text | Phase 3A |
| normalized_text | text | Phase 3A |
| source_platform | text | Phase 3A |
| occurrences | integer | Phase 3A |
| distinct_sources_count | integer | Phase 3A |
| first_seen | text | Phase 3A |
| last_seen | text | Phase 3A |
| confidence_score | double precision | Phase 3A/agg |
| status | text | Phase 3A |
| candidate_type | text | Phase 3B |
| validation_status | text | Phase 3B |
| rejection_reason | text | Phase 3B |
| token_count | integer | Phase 3B |
| contains_brand_keyword | integer | Phase 3B |
| contains_perfume_keyword | integer | Phase 3B |
| review_status | text | Phase 4a |
| normalized_candidate_text | text | Phase 4a |
| reviewed_at | text | Phase 4a |
| review_notes | text | Phase 4a |
| approved_entity_type | text | Phase 4a |
| promotion_decision | text | Phase 4b |
| promoted_at | text | Phase 4b |
| promoted_canonical_name | text | Phase 4b |
| promoted_as | text | Phase 4b |
| promotion_rejection_reason | text | Phase 4b |

All Phase 3, 3B, and 4a/4b columns present. Schema: ✅ COMPLETE

---

## B. Ingestion Hook Check

**Hook: PRESENT in both ingest scripts**

Both `scripts/ingest_youtube.py` and `scripts/ingest_reddit.py` correctly call `batch_upsert_candidates()` after the resolver runs:

```python
# ingest_youtube.py:192
# Save unresolved mentions to discovery candidates table
with session_scope() as db:
    batch_upsert_candidates(db, resolved_items, source_platform="youtube")

# ingest_reddit.py:216
with session_scope() as db:
    batch_upsert_candidates(db, resolved_items, source_platform="reddit")
```

Unresolved entities are NOT dropped. They are upserted into `fragrance_candidates` immediately after each ingestion batch. Hook: ✅ PRESENT

---

## C. Pipeline Integration Check

**Before fix:**

| Step | Morning pipeline | Evening pipeline |
|------|-----------------|-----------------|
| aggregate_candidates | ❌ MISSING | ❌ MISSING |
| validate_candidates | ❌ MISSING | ❌ MISSING |

Both `aggregate_candidates` and `validate_candidates` existed as working jobs but were never added to the pipeline scripts. This is the core gap: candidates were being collected (Phase 3A active) but never aggregated or validated (Phase 3B inactive).

**After fix (commit 0d76907):**

Both pipeline scripts now include Steps 1b and 1c between ingestion and market aggregation:

```sh
# Step 1b: Aggregate and classify discovery candidates (Phase 3A → 3B)
echo "[pipeline] Step 1b — Aggregate candidates"
timeout 600 python3 -m perfume_trend_sdk.jobs.aggregate_candidates || \
  echo "[pipeline] WARNING: aggregate_candidates failed — continuing"
echo "[pipeline] Step 1c — Validate candidates (Phase 3B)"
timeout 600 python3 -m perfume_trend_sdk.jobs.validate_candidates || \
  echo "[pipeline] WARNING: validate_candidates failed — continuing"
```

Both use `||` (non-blocking) — a failure does not abort the market aggregation steps.

Pipeline integration: ✅ FIXED

---

## D. Live Data Flow Verification

**Production PostgreSQL — final state (2026-04-21)**

| Metric | Before fix | After fix |
|--------|-----------|----------|
| Row count | 2,300 | 2,300 |
| status='aggregated' | 0 | **2,300** |
| confidence_score > 0 | 0 | **2,300** |
| validation_status='accepted_rule_based' | 0 | **312** |
| validation_status='review' | 0 | **1,758** |
| validation_status='rejected_noise' | 0 | **230** |
| candidate_type populated | 0 | **2,300** |

### Candidate type breakdown

| Type | Count |
|------|-------|
| unknown | 1,727 |
| perfume | 282 |
| noise | 230 |
| brand | 58 |
| note | 3 |

### Top accepted_rule_based candidates (by occurrences)

| Candidate | Type | Occurrences |
|-----------|------|-------------|
| rouge 540 | brand | 6 |
| baccarat rouge 540 | perfume | 6 |
| aventus | brand | 3 |
| baccarat rouge 540 dupe | perfume | 3 |
| by creed | brand | 3 |
| xerjoff | brand | 3 |

Phase 3 is producing real signal from live ingestion data. ✅

---

## E. DB Target Check

**Phase 3 DB target: ✅ CORRECT — production PostgreSQL**

All Phase 3 writes use `session_scope()` from `perfume_trend_sdk.storage.postgres.db`, which resolves in this order:

1. `DATABASE_URL` → Railway PostgreSQL (production)
2. `PTI_DB_PATH` → SQLite file (dev/test)
3. Default → `outputs/pti.db` (legacy)

In production (`PTI_ENV=production`, `DATABASE_URL` set): writes go to **PostgreSQL** only. SQLite fallback is blocked (`RuntimeError` if `DATABASE_URL` is missing in production mode).

| Component | Actual DB target | Expected |
|-----------|-----------------|----------|
| `batch_upsert_candidates` (ingestion) | Production PostgreSQL | ✅ Correct |
| `aggregate_candidates` | Production PostgreSQL | ✅ Correct |
| `validate_candidates` | Production PostgreSQL | ✅ Correct |

No SQLite writes. No data going to `outputs/*.db` in production.

---

## F. Fixes Applied

**One fix only (minimal):**

Added Steps 1b + 1c to `start_pipeline.sh` and `start_pipeline_evening.sh`.

```
start_pipeline.sh
start_pipeline_evening.sh
```

Commit: `0d76907` — `feat: add Phase 3 candidate aggregation + validation to production pipeline`

No changes to:
- Phase 3 / 3B logic
- ingestion hooks
- candidate_store
- resolver
- promotion pipeline
- architecture

---

## G. Post-Fix Verification

First execution of both jobs against production PostgreSQL (2026-04-21):

| Job | Result |
|-----|--------|
| `aggregate_candidates` | ✅ 2,300 rows updated — confidence_score computed |
| `validate_candidates` | ✅ 2,300 rows classified — validation_status + candidate_type set |

Classification output from `validate_candidates`:
- `accepted_rule_based`: 312 (13.6%)
- `rejected_noise`: 230 (10.0%)
- `review`: 1,758 (76.4%)

Brand tokens loaded: 362. Note names loaded: 109.

Both jobs confirmed working against production PostgreSQL. ✅

**Note on concurrent execution:** Running both jobs simultaneously against the same table causes deadlocks (both lock `fragrance_candidates` rows during UPDATE). The pipeline scripts run them strictly sequentially — this is correct and prevents deadlocks.

---

## H. Classification

**Phase 3 classification: PARTIALLY ACTIVE → FULLY ACTIVE (after fix)**

| Sub-phase | Before fix | After fix |
|-----------|-----------|----------|
| Phase 3A — Candidate collection | ✅ Active | ✅ Active |
| Phase 3B — Aggregation (confidence_score) | ❌ Inactive | ✅ Active |
| Phase 3B — Validation (candidate_type) | ❌ Inactive | ✅ Active |

**Before fix classification:** Phase 3 partially active — ingestion connected, aggregation/validation missing from pipeline.

**After fix classification:** Phase 3 fully active in production.

---

## I. CLAUDE.md Status Text

Update Phase 3 block to:

```
## Phase 3 — Discovery / Self-Improving System

### Status
- Phase 3A (collection layer): COMPLETE and ACTIVE in production
- Phase 3B (validation/filtering): COMPLETE and ACTIVE in production

### Production evidence (as of 2026-04-21)
- fragrance_candidates: 2,300 rows in production PostgreSQL
- all rows classified by validate_candidates (accepted/review/noise)
- confidence_score computed by aggregate_candidates
- both jobs run in every pipeline cycle (Steps 1b + 1c)
```

---

## J. Summary

| Check | Result |
|-------|--------|
| A. Schema — fragrance_candidates exists | ✅ EXISTS, 25 columns, 2300 rows |
| A. Phase 3/3B fields present | ✅ ALL present |
| B. Ingestion hook (batch_upsert_candidates) | ✅ PRESENT in youtube + reddit |
| C. aggregate_candidates in pipeline | ❌ MISSING → ✅ ADDED (0d76907) |
| C. validate_candidates in pipeline | ❌ MISSING → ✅ ADDED (0d76907) |
| D. Live data verified (validate ran) | ✅ 312 accepted / 1758 review / 230 noise |
| E. DB target — production PostgreSQL | ✅ CORRECT |
| F. Minimal fix only | ✅ Only pipeline scripts modified |
| G. Post-fix verification | ✅ Both jobs confirmed working |

**Root cause:** `aggregate_candidates` and `validate_candidates` jobs existed and worked correctly but were never added to the production pipeline scripts. Candidates were being collected (Phase 3A) but never processed (Phase 3B). Fixed by adding Steps 1b + 1c to both `start_pipeline.sh` and `start_pipeline_evening.sh`.

---

*Verification date: 2026-04-21. Production PostgreSQL. 2300 candidates from morning pipeline run.*
