# Phase 5 — First Safe Import Run (Step 5 + Step 5b)

**Date:** 2026-04-21  
**Scope:** Pilot (500-row) + medium batch (5,000-row) catalog import from Parfumo/TidyTuesday dataset into resolver KB  
**Status:** SAFE TO SCALE

---

## A. Baseline Counts (pre-import)

| Table | Count |
|-------|-------|
| brands | 260 |
| perfumes | 2,245 |
| fragrance_master | 2,245 |
| aliases | 12,884 |

Pre-existing duplicates (normalized_name): **0 brands, 0 perfumes** ✅

---

## B. Dataset

| Property | Value |
|----------|-------|
| Source | Parfumo via TidyTuesday (2024-12-10) |
| URL | `https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2024/2024-12-10/parfumo_data_clean.csv` |
| Total rows | 59,325 |
| Null brand rows | 1 |
| Null name rows | 0 |
| Noise (too short / garbage) | 51 |
| **Valid rows** | **59,273** |

Columns used: `Brand` → `brand_name`, `Name` → `perfume_name`  
Optional columns present but deferred: `Release_Year`, `Concentration`, `Rating_Value`, `Rating_Count`, `Main_Accords`, `Top_Notes`, `Middle_Notes`, `Base_Notes`

---

## C. Dry-Run Summary (full dataset, no writes)

| Metric | Count |
|--------|-------|
| New brands (would insert) | 1,348 |
| New perfumes (would insert) | 53,822 |
| Skip — perfume normalized_name dup | 5,413 |
| Skip — fragrance_master dup | 38 |
| Aliases (must stay 12,884) | 12,884 ✅ |
| Errors | 0 |

**Dry-run result: PASS** — no errors, counts look reasonable, aliases untouched.

---

## D. Bounded Real Run (500 rows) — Pilot

| Metric | Count |
|--------|-------|
| Rows loaded from CSV | 500 |
| New brands inserted | 104 |
| New perfumes inserted | 475 |
| Skipped (perfume dup) | 24 |
| Skipped (FM dup) | 1 |
| fragrance_master rows inserted | 475 |
| Errors | 0 |

All rows tagged `source='kaggle_v1'`.

---

## E. Bug Found & Fixed: fragrance_id Collision

During the medium batch run (5,000 rows after the active pilot), a bug was discovered:

**Root cause:** `fragrance_id` was generated as `fm_kaggle_v1_{batch_index}_{fm_batch_len}` — a positional counter that restarts at 0 on every script invocation. On the second run, the first 475 FM rows got IDs already occupied by the pilot batch. `OR IGNORE` silently dropped them → 475 perfumes in `perfumes` table with no `fragrance_master` row (orphans).

**Impact:** Resolver still functional (uses `perfumes` + `aliases`, not `fragrance_master` for lookups). But FM integrity was broken.

**Fix applied:** fragrance_id now uses `sha1(normalized_name)[:12]` — content-addressed, stable across runs, collision-safe.

```python
fid_hash = hashlib.sha1(normalized_fm.encode()).hexdigest()[:12]
fragrance_id = f"fm_{SOURCE_TAG}_{fid_hash}"
```

All data was rolled back, orphans cleaned up, and the medium batch re-run with the fixed script.

---

## F. Medium Batch Run (5,000 rows) — Post-fix

| Metric | Count |
|--------|-------|
| Rows loaded | 5,000 |
| New brands inserted | 787 |
| New perfumes inserted | 4,456 |
| Skipped (perfume dup, incl. pilot) | 537 |
| Skipped (FM dup) | 7 |
| FM rows inserted | 4,456 |
| Orphan perfumes | 0 |
| Errors | 0 |

Final counts: brands=1,047 (+787) / perfumes=6,701 (+4,456) / FM=6,701 (+4,456) / aliases=12,884 (unchanged)

### Verification

| Check | Result |
|-------|--------|
| aliases unchanged (12,884) | ✅ |
| perfume normalized_name duplicates | 0 ✅ |
| brand normalized_name duplicates | 0 ✅ |
| orphan perfumes (no FM row) | 0 ✅ |
| FK perfumes.brand_id invalid | 0 ✅ |
| FK fm.perfume_id invalid | 0 ✅ |
| FK fm.brand_id invalid | 0 ✅ |
| Errors during run | 0 ✅ |

### New perfume spot-check (5 samples)

| Brand | Perfume |
|-------|---------|
| Le Ré Noir | Tabac Écarlate |
| CB I Hate Perfume | Tidal Pool |
| CB I Hate Perfume | Pumpkin Pie |
| CB I Hate Perfume | Wet Stone |
| CB I Hate Perfume | Chocolate Box |

### Old perfume spot-check (still present after import)

| Perfume |
|---------|
| Indult Tihota Eau de Parfum |
| Di Ser Sola Parfum |
| Parfums de Marly Delina |
| Maison Francis Kurkdjian Baccarat Rouge 540 |
| Byredo Gypsy Water |
| Yves Saint Laurent Libre |
| Xerjoff Erba Pura |

---

## G. Rollback Test (post-fix)

Rollback tested against the full 5,000-row active state:

| Action | Count |
|--------|-------|
| FM rows deleted | 4,456 |
| Perfumes deleted | 4,456 |
| Brands deleted | 787 |

| Table | Before | After | Baseline |
|-------|--------|-------|----------|
| brands | 1,047 | 260 | ✅ |
| perfumes | 6,701 | 2,245 | ✅ |
| fragrance_master | 6,701 | 2,245 | ✅ |
| aliases | 12,884 | 12,884 | ✅ |
| perfume dups | 0 | 0 | ✅ |

**Rollback result: PASS** — baseline restored exactly, no side effects, no orphan perfumes.

---

## H. Alias Integrity

Aliases count before import: **12,884**  
Aliases count after 5k import: **12,884**  
Aliases count after rollback: **12,884**

No alias pollution at any stage. ✅

---

## I. Rollback Command

```bash
python3 scripts/import_kaggle_v1.py --rollback
```

Safe to run at any time. Removes all `source='kaggle_v1'` rows with exact ID tracking.

---

## J. Script Location

```
scripts/import_kaggle_v1.py
```

Usage:
```bash
# Dry-run (full dataset, no writes)
python3 scripts/import_kaggle_v1.py --csv /path/to/parfumo_data_clean.csv --dry-run

# Bounded run (500 rows)
python3 scripts/import_kaggle_v1.py --csv /path/to/parfumo_data_clean.csv --limit 500

# Full run
python3 scripts/import_kaggle_v1.py --csv /path/to/parfumo_data_clean.csv

# Rollback
python3 scripts/import_kaggle_v1.py --rollback
```

---

## K. Notes & Known Behaviors

**`Brands inserted: -1`** in script output: SQLite `cur.rowcount` returns `-1` after `executemany` with `OR IGNORE`. Cosmetic only — brands ARE correctly inserted (verified by count delta).

**fragrance_id collision bug (fixed):** The initial positional fragrance_id scheme (`fm_kaggle_v1_{i}_{seq}`) restarted at 0 on each invocation, causing silent FM row drops via `OR IGNORE` when a prior run had used the same IDs. Fixed by switching to content-addressed SHA1 hash: `fm_kaggle_v1_{sha1(normalized_name)[:12]}`. Stable across runs and idempotent.

**`source` column in `perfumes`:** The `perfumes` table has no `source` column. Rollback uses FM-collected IDs (collected before FM deletion) for precise, side-effect-free cleanup.

---

## L. Classification

| Gate | Status |
|------|--------|
| Dry-run clean | ✅ |
| 500-row bounded run clean | ✅ |
| Zero duplicates | ✅ |
| Aliases unchanged | ✅ |
| FK integrity | ✅ |
| Old perfumes unaffected | ✅ |
| Rollback tested and working | ✅ |
| Rollback restores baseline exactly | ✅ |

---

## **CLASSIFICATION: SAFE TO SCALE**

The import pipeline is validated through two stages — pilot (500 rows) and medium batch (5,000 rows):

| Metric | Pilot | Medium batch |
|--------|-------|-------------|
| New perfumes | 475 | 4,456 |
| New brands | 104 | 787 |
| Duplicates | 0 | 0 |
| Alias pollution | 0 | 0 |
| FK violations | 0 | 0 |
| Orphan perfumes | 0 | 0 |
| Rollback precision | ✅ | ✅ |

**One bug found and fixed:** fragrance_id positional collision → switched to SHA1 content-hash. Script is now idempotent and multi-run safe.

**Estimated full-run output (59,273 valid rows):**
- ~1,348 new brands
- ~53,822 new perfumes
- ~53,822 fragrance_master rows
- aliases: unchanged (0 new)

Ready for full dataset import upon confirmation.

---

*Run date: 2026-04-21. Target: `data/resolver/pti.db`. Current state: 5,000-row kaggle_v1 import active (4,456 new perfumes, 787 new brands).*
