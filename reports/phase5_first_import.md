# Phase 5 — First Safe Import Run

**Date:** 2026-04-21  
**Scope:** Bounded 500-row catalog import from Parfumo/TidyTuesday dataset into resolver KB  
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

## D. Bounded Real Run (500 rows)

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

## E. Post-Run Verification

| Check | Result |
|-------|--------|
| brands: 260 → 364 (+104) | ✅ |
| perfumes: 2,245 → 2,720 (+475) | ✅ |
| fragrance_master: 2,245 → 2,720 (+475) | ✅ |
| aliases unchanged (12,884) | ✅ |
| perfume normalized_name duplicates | 0 ✅ |
| brand normalized_name duplicates | 0 ✅ |
| FK integrity: invalid brand_id | 0 ✅ |
| FK integrity: invalid perfume_id in FM | 0 ✅ |
| FK integrity: invalid brand_id in FM | 0 ✅ |
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
| Parfums de Marly Delina |
| Maison Francis Kurkdjian Baccarat Rouge 540 |
| Byredo Gypsy Water |
| Yves Saint Laurent Libre |
| Xerjoff Erba Pura |

---

## F. Rollback Test

**First rollback attempt:** Used fragrance_master reference after FM deletion — caught 7 pre-existing orphan perfumes as side effect. Root cause: orphan perfumes (existed in `perfumes` with no FM row) were indistinguishable from newly inserted ones after FM rows were deleted.

**Fix applied:** Collect kaggle_v1 `perfume_id` and `brand_id` from FM table *before* deleting it. Delete only the exact IDs that were inserted.

**Second rollback (fixed):**

| Action | Count |
|--------|-------|
| FM rows deleted | 475 |
| Perfumes deleted | 475 |
| Brands deleted | 104 |

| Table | Before | After | Match baseline |
|-------|--------|-------|----------------|
| brands | 364 | 260 | ✅ |
| perfumes | 2,720 | 2,245 | ✅ |
| fragrance_master | 2,720 | 2,245 | ✅ |
| aliases | 12,884 | 12,884 | ✅ |
| perfume dups | 0 | 0 | ✅ |

**Rollback result: PASS** — baseline restored exactly, no side effects.

---

## G. Alias Integrity

Aliases count before import: **12,884**  
Aliases count after import: **12,884**  
Aliases count after rollback: **12,884**

No alias pollution at any stage. ✅

---

## H. Rollback Command

```bash
python3 scripts/import_kaggle_v1.py --rollback
```

Safe to run at any time. Removes all `source='kaggle_v1'` rows with exact ID tracking.

---

## I. Script Location

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

## J. Notes & Known Behaviors

**`Brands inserted: -1`** in script output: SQLite `cur.rowcount` returns `-1` after `executemany` with `OR IGNORE`. Cosmetic only — brands ARE correctly inserted (verified by count delta).

**Pre-existing orphan perfumes:** 7 perfumes existed in the `perfumes` table with no corresponding `fragrance_master` row before this import. These are Phase 4c discovery entities and similar KB entries that exist in `perfumes` only. The first rollback incorrectly removed them. Fixed in the `--rollback` command by precise ID tracking.

**`source` column in `perfumes`:** The `perfumes` table has no `source` column. Rollback uses FM-collected IDs rather than a source tag on `perfumes` directly.

---

## K. Classification

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

The import pipeline is validated. The bounded run inserted 475 new perfumes and 104 new brands cleanly with zero errors, zero duplicates, zero alias pollution, and a verified rollback path.

**Estimated full-run output (59,273 valid rows):**
- ~1,348 new brands
- ~53,822 new perfumes
- ~53,822 fragrance_master rows
- aliases: unchanged (0 new)

Ready for full dataset import upon confirmation.

---

*Run date: 2026-04-21. Target: `data/resolver/pti.db`. Current state: 500-row kaggle_v1 import active in resolver.*
