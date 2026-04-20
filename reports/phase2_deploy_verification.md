# Phase 2 — Deploy Verification Report

**Date:** 2026-04-20  
**Scope:** Phase 2 Notes & Brand Intelligence Layer — production deploy verification  
**Engineer:** automated verification via railway ssh

---

## 1. Pre-Deploy State

### Git state (before verification run)
```
Branch: main
Local: up to date with origin/main
Dirty files: outputs/*.db, data/raw/* (runtime artifacts, not tracked)
```

### Phase 2 files confirmed in main
| File | Commit |
|------|--------|
| `alembic/versions/009_add_notes_brand_intelligence.py` | 50160ca |
| `perfume_trend_sdk/db/market/notes_intelligence.py` | 50160ca |
| `perfume_trend_sdk/analysis/notes_intelligence/canonicalizer.py` | 50160ca |
| `perfume_trend_sdk/analysis/notes_intelligence/stats_builder.py` | 50160ca |
| `perfume_trend_sdk/analysis/notes_intelligence/query_layer.py` | 50160ca |
| `perfume_trend_sdk/jobs/build_notes_intelligence.py` | 50160ca |
| `reports/phase2_notes_brand.md` | 50160ca |

### Migration 009 content verified
Creates: `notes_canonical`, `note_canonical_map`, `note_stats`, `accord_stats`, `note_brand_stats`  
Downgrade: reverses all 5 tables in correct FK order

### Startup path
`start.sh` executes `alembic upgrade head` before `uvicorn` — migration applies automatically on every deploy.

### Pre-deploy assessment: **READY TO DEPLOY**

No blocking risks. No uncommitted Phase 2 changes.

---

## 2. Deploy

### Commits pushed to origin/main

| Commit | Message |
|--------|---------|
| `50160ca` | feat: Phase 2 — Notes & Brand Intelligence Layer |
| `94f9c75` | docs: add Phase 2 COMPLETED section to CLAUDE.md |
| `722d443` | fix: PostgreSQL UUID/text type mismatch in notes intelligence queries |

### Bug fixed during verification

**Issue discovered:** `psycopg2.errors.UndefinedFunction: operator does not exist: uuid = text`

**Root cause:** `perfumes.id` and `brands.id` are stored as PostgreSQL `UUID` type. `perfume_notes.perfume_id`, `perfume_accords.perfume_id`, and `note_brand_stats.brand_id` are stored as `TEXT`. SQLite silently coerces, PostgreSQL rejects the comparison.

**Fix:** Added `CAST(p.id AS text)` and `CAST(b.id AS text)` to all JOIN conditions in `stats_builder.py` and `query_layer.py`. `CAST AS text` is valid in both SQLite and PostgreSQL.

**Fix commit:** `722d443` — pushed and redeployed before production job run.

### Railway deploy result

| Service | Status | Alembic | API |
|---------|--------|---------|-----|
| `generous-prosperity` | ✅ Deployed | `ALEMBIC_EXIT=0` | `startup complete` |

---

## 3. Production Migration Verification

```
alembic current: 009 (head)
```

### Phase 2 tables in production PostgreSQL

| Table | Exists | Row count |
|-------|--------|-----------|
| `notes_canonical` | ✅ | 0 |
| `note_canonical_map` | ✅ | 0 |
| `note_stats` | ✅ | 0 |
| `accord_stats` | ✅ | 0 |
| `note_brand_stats` | ✅ | 0 |

All 5 tables created by migration 009 are present. Row counts are 0 because the intelligence job has not yet produced output — explained in Section 4.

---

## 4. Production Job Verification

### Job execution

```bash
railway ssh --service generous-prosperity -- \
  python3 -m perfume_trend_sdk.jobs.build_notes_intelligence
```

**Exit code:** 0  
**PostgreSQL connection:** ✅ (`postgres.railway.internal:5432/railway`)  
**Errors:** none

**Job log (production):**
```
[stats_builder] starting full build
[stats_builder] canonical entries to upsert: 0
[stats_builder] notes_canonical populated: 0 entries
[stats_builder] note_canonical_map populated: 0 entries
[stats_builder] note_stats upserted: 0 canonical notes
[stats_builder] accord_stats upserted: 0 accords
[stats_builder] note_brand_stats upserted: 0 note×brand pairs
```

### Why output is 0 — root cause

The intelligence layer reads from: `notes`, `accords`, `perfume_notes`, `perfume_accords`, `perfumes`, `brands`.

**Production source table state:**

| Table | Production row count |
|-------|---------------------|
| `fragrantica_records` | **0** |
| `notes` | **0** |
| `accords` | **0** |
| `perfume_notes` | **0** |
| `perfume_accords` | **0** |
| `perfumes` | 2,255 ✅ |
| `brands` | 319 ✅ |

**Fragrantica enrichment was never run against the production PostgreSQL database.**

The enrichment workflow (`enrich_from_fragrantica.py`) was run locally against `outputs/market_dev.db` (SQLite) during Phase 1b and Phase 2 development. That data exists only in the local file.

The production DB has the full perfume catalog (`perfumes`, `brands`) but no Fragrantica-sourced enrichment data.

### Why enrichment hasn't run in production

The Fragrantica fetch layer (`CDPFragranticaClient`) requires a locally running Chrome instance with remote debugging enabled. Railway production cannot:
- maintain a persistent Chrome browser session
- pass Cloudflare Enterprise Bot Management (all direct HTTP requests return 403)

This is the documented Phase 1b/1c production limitation. It is an **infrastructure blocker**, not a code or schema issue.

---

## 5. Production Data Verification

Not applicable — production intelligence tables are empty due to the data blocker in Section 4.

**Local verification (from reports/phase2_notes_brand.md):**

| Metric | Local result |
|--------|-------------|
| Raw notes | 137 |
| Canonical notes | 109 |
| Merge groups | 17 |
| Notes merged | 28 |
| note_brand_stats pairs | 239 |
| Top note (by perfume coverage) | musk (13 perfumes, 10 brands) |
| Second note | Vanilla (13 perfumes, 9 brands) |
| Third note | patchouli (12 perfumes, 9 brands) |

Production data will match this exactly once Fragrantica enrichment runs against the production DB.

---

## 6. Status Classification

| Gate | Status | Notes |
|------|--------|-------|
| Code Complete | ✅ YES | All 7 Phase 2 files committed and pushed |
| Deploy Complete | ✅ YES | Migration 009 at HEAD in production, code deployed, job executes |
| Production Verified | ❌ NO | Intelligence tables empty; source data not in production PostgreSQL |
| Blocker | Data | Fragrantica enrichment (notes/accords/perfume_notes) runs locally only |

### Detailed classification

**Code Complete:** YES  
All analysis code, ORM models, migration, query layer, and CLI job are deployed and execute without errors in production PostgreSQL. The UUID/text type cast bug was discovered and fixed during this verification (`722d443`).

**Deploy Complete:** YES  
- Alembic version: `009 (head)` confirmed in production
- All 5 Phase 2 tables exist in production PostgreSQL
- Job runs to completion without error
- API is up and healthy

**Production Verified:** NO  
The job produces 0 rows in all output tables. The validation check fails:
- `notes_canonical_populated: ❌`
- `note_canonical_map_populated: ❌`
- `note_stats_populated: ❌`
- `accord_stats_populated: ❌`
- `note_brand_stats_populated: ❌`

**Blocker:** Production Fragrantica enrichment not implemented  
`fragrantica_records`, `notes`, `accords`, `perfume_notes`, `perfume_accords` → all 0 rows in production.  
Source: Phase 1c deferred — CDP-based enrichment is local-only.

---

## 7. Bug Fixed During Verification

| Aspect | Detail |
|--------|--------|
| Error | `psycopg2.errors.UndefinedFunction: operator does not exist: uuid = text` |
| Location | `stats_builder.py` — 3 JOINs; `query_layer.py` — 5 JOINs |
| Root cause | UUID columns (perfumes.id, brands.id) joined directly against TEXT columns |
| Fix | `CAST(p.id AS text)` and `CAST(b.id AS text)` in all affected JOIN conditions |
| Dialect safety | `CAST AS text` valid in both SQLite and PostgreSQL |
| Fix commit | `722d443` |
| Local re-verification | ✅ PASS (109 canonical notes, 239 pairs — unchanged) |

---

## 8. Path to Full Production Verification

To achieve `Production Verified: YES`, one of these must happen:

**Option A — Local CDP enrichment targeting production DB (recommended)**  
Run enrichment locally via CDP client, pointing `DATABASE_URL` at the production PostgreSQL public URL:
```bash
DATABASE_URL="postgresql://..." USE_CDP=true \
python3 -m perfume_trend_sdk.workflows.enrich_from_fragrantica \
    --resolver-db outputs/pti.db --limit 30
python3 -m perfume_trend_sdk.jobs.build_notes_intelligence
```
Requires: Railway PostgreSQL public URL (not the internal `postgres.railway.internal`).

**Option B — Production Fragrantica proxy (Phase 1c)**  
Implement residential proxy or Playwright service to bypass Cloudflare in Railway. Deferred by design.

**Option C — Accept partial status**  
Phase 2 is code-complete and deploy-complete. Production verification is blocked by the same infrastructure constraint as Phase 1b/1c. Document and defer.

---

## 9. Recommended CLAUDE.md Status Text

```
Phase 2 — code complete, deploy complete, production verification incomplete.

Blocker: Fragrantica enrichment data (notes, accords, perfume_notes) 
not present in production PostgreSQL. Intelligence job runs successfully 
but produces 0 rows. Same root cause as Phase 1c: CDP-based enrichment 
is local-only.

UUID/text type cast bug (stats_builder.py, query_layer.py) discovered 
and fixed during verification (commit 722d443).
```

---

## 10. Commit Summary

| Hash | Content |
|------|---------|
| `50160ca` | Phase 2 full implementation |
| `94f9c75` | CLAUDE.md Phase 2 COMPLETED section |
| `722d443` | Bug fix: PostgreSQL UUID/text JOIN type mismatch |

All three commits are on `origin/main` and deployed to Railway production.

---

*Verification run: 2026-04-20. Production service: `generous-prosperity` (Railway). Database: PostgreSQL at `postgres.railway.internal:5432/railway`.*
