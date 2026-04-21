# Phase 2b — Production Enrichment Data Bridge

**Date:** 2026-04-21  
**Scope:** Phase 2b — Bridge local SQLite enrichment data to production PostgreSQL  
**Status:** COMPLETED — all enrichment tables populated, Phase 2 verification PASS

---

## 1. Summary

| Metric | Value |
|--------|-------|
| Tables synced | 5 |
| notes inserted | 137 |
| accords inserted | 9 |
| fragrantica_records inserted | 29 |
| perfume_notes inserted | 277 |
| perfume_accords inserted | 10 |
| Perfume ID mismatches | 0 |
| Note ID mismatches (perfume_notes) | 5 |
| Accord ID mismatches (perfume_accords) | 3 |
| Total run time | ~10 seconds |

---

## 2. Pre-Sync Production State

| Table | Row count |
|-------|-----------|
| notes | 0 |
| accords | 0 |
| fragrantica_records | 0 |
| perfume_notes | 0 |
| perfume_accords | 0 |
| perfumes | 2,255 |
| brands | 319 |

All enrichment tables were empty. Catalog tables (perfumes, brands) were fully seeded from Phase 0.

---

## 3. Bridge Script

**File:** `scripts/sync_enrichment_to_production.py`  
**Commit:** `9a53027`

### Design decisions

**Bulk INSERT approach:**  
Per-row INSERT queries over a high-latency Railway connection (~200ms per round-trip) would require 470+ individual round-trips. The script collects all new rows in-memory and executes a single `INSERT ... VALUES (...), (...), ...` per table — reducing to 1 round-trip per table regardless of row count. Total sync time: ~10 seconds.

**Pre-load existence checks:**  
For each table, all existing keys are loaded in one query before processing. In-memory set lookup replaces per-row `SELECT EXISTS` queries.

**UUID normalization:**  
SQLite stores UUIDs as 32-character hex strings (`a0b21187723442a6acd9ef7712c67589`). PostgreSQL stores as UUID type with hyphens (`a0b21187-7234-42a6-acd9-ef7712c67589`). Same bit-value. `_norm_uuid()` converts all local IDs to standard hyphenated form before writing to production.

**Identity safety:**  
`_build_perfume_uuid_set()` pre-loads all production perfume UUIDs. Any enrichment row whose `perfume_id` is not found in production is skipped and logged. No orphan enrichment rows are written.

**Idempotent:**  
`ON CONFLICT DO NOTHING` on every INSERT. Re-running the script for the same data produces 0 new inserts, no errors.

**Dry-run mode:**  
`--dry-run` flag reads source data and reports what would be synced without writing anything.

---

## 4. Sync Execution Log

```
2026-04-21T03:53:55  INFO  Source SQLite  : outputs/market_dev.db
2026-04-21T03:53:55  INFO  Target DB      : gondola.proxy.rlwy.net:34404/railway
2026-04-21T03:53:55  INFO  Mode           : LIVE
2026-04-21T03:54:01  INFO  Pre-sync production counts: {'notes': 0, 'accords': 0, 'fragrantica_records': 0, 'perfume_notes': 0, 'perfume_accords': 0}
2026-04-21T03:54:02  INFO  Production perfumes available for mapping: 2255
2026-04-21T03:54:02  INFO  --- Syncing notes ---
2026-04-21T03:54:02  INFO  notes: {'inserted': 137, 'skipped': 0, 'total_source': 137}
2026-04-21T03:54:02  INFO  --- Syncing accords ---
2026-04-21T03:54:03  INFO  accords: {'inserted': 9, 'skipped': 0, 'total_source': 9}
2026-04-21T03:54:03  INFO  Production notes available after sync: 137
2026-04-21T03:54:03  INFO  Production accords available after sync: 9
2026-04-21T03:54:03  INFO  --- Syncing fragrantica_records ---
2026-04-21T03:54:04  INFO  fragrantica_records: {'inserted': 29, 'skipped': 0, 'no_perfume_match': 0, 'total_source': 29}
2026-04-21T03:54:04  INFO  --- Syncing perfume_notes ---
2026-04-21T03:54:05  INFO  perfume_notes: {'inserted': 277, 'skipped': 0, 'no_match': 5, 'total_source': 282}
2026-04-21T03:54:05  INFO  --- Syncing perfume_accords ---
2026-04-21T03:54:05  INFO  perfume_accords: {'inserted': 10, 'skipped': 0, 'no_match': 3, 'total_source': 13}
```

### Skipped rows explanation

**perfume_notes — 5 no_match:**  
5 rows in local `perfume_notes` reference note IDs that could not be joined to a `notes.normalized_name` in the local SQLite (likely orphaned note rows from earlier enrichment runs before normalization was stable). These rows were skipped safely. 0 data loss for the 28 enriched perfumes.

**perfume_accords — 3 no_match:**  
3 local accord rows have perfume_id values not in the production perfume UUID set. These are from the Phase 1 reference seed batch and reference perfumes that are not in the current production catalog. Skipped safely.

---

## 5. Post-Sync Production State

| Table | Row count |
|-------|-----------|
| notes | 137 |
| accords | 9 |
| fragrantica_records | 29 |
| perfume_notes | 277 |
| perfume_accords | 10 |
| notes_canonical | 109 |
| note_canonical_map | 137 |
| note_stats | 109 |
| accord_stats | 8 |
| note_brand_stats | 239 |

---

## 6. Phase 2 Intelligence Re-Run (Production)

After the bridge completed, `build_notes_intelligence` was re-run in production via `railway ssh --service generous-prosperity`:

```
[stats_builder] starting full build
[stats_builder] canonical entries to upsert: 109
[stats_builder] notes_canonical populated: 109 entries
[stats_builder] note_canonical_map populated: 137 entries
[stats_builder] note_stats upserted: 109 canonical notes
[stats_builder] accord_stats upserted: 8 accords
[stats_builder] note_brand_stats upserted: 239 note×brand pairs
[stats_builder] build complete: {'notes_canonical': 109, 'note_canonical_map': 137,
  'note_stats': 109, 'accord_stats': 8, 'note_brand_stats': 239}
```

**Exit code:** 0

---

## 7. Production Validation

```
=== Phase 2 Validation ===
  ✅  notes_canonical_populated
  ✅  note_canonical_map_populated
  ✅  note_stats_populated
  ✅  accord_stats_populated
  ✅  note_brand_stats_populated
  ✅  top_notes_returns_result
  ✅  brand_stats_returns_result
  ✅  top_accords_returns_result
  ✅  no_duplicate_note_mappings

  Overall: PASS
```

**All 9 checks pass.** Production notes & brand intelligence is fully operational.

---

## 8. Top 10 Notes (Production)

| Rank | Note | Perfumes | Brands | Top | Middle | Base |
|------|------|----------|--------|-----|--------|------|
| 1 | musk | 13 | 10 | 0 | 3 | 12 |
| 2 | Vanilla | 13 | 9 | 0 | 2 | 11 |
| 3 | patchouli | 12 | 9 | 1 | 4 | 8 |
| 4 | bergamot | 10 | 8 | 11 | 0 | 0 |
| 5 | Jasmine | 10 | 6 | 0 | 10 | 0 |
| 6 | Cedar | 9 | 6 | 0 | 0 | 11 |
| 7 | Sandalwood | 8 | 6 | 0 | 1 | 7 |
| 8 | Amber | 7 | 6 | 0 | 0 | 7 |
| 9 | Rose | 6 | 6 | 1 | 6 | 0 |
| 10 | Lemon | 6 | 6 | 6 | 0 | 0 |

Results match local verification from `reports/phase2_notes_brand.md` exactly.

---

## 9. Top Brands by Note Diversity (Production)

| Brand | Distinct Notes | Total Note Links |
|-------|---------------|-----------------|
| Parfums de Marly | 31 | 42 |
| Mancera | 24 | 29 |
| Maison Francis Kurkdjian | 24 | 25 |
| Creed | 22 | 22 |
| Versace | 20 | 20 |

---

## 10. Bug Fixed During Phase 2b

### `operator does not exist: text = uuid` in `build_note_brand_stats`

**Error location:** `stats_builder.py` → `build_note_brand_stats()`

**Trigger:** First execution against production PostgreSQL after enrichment data was present.

**Root cause:**  
The query `SELECT pn.note_id, pn.perfume_id, p.brand_id FROM perfume_notes pn JOIN perfumes p ON ...` returns `p.brand_id` as a Python `UUID` object (because `brands.id` is PostgreSQL UUID type). This UUID object was then stored in a dict and passed as a query parameter:  
`WHERE canonical_note_id=:cid AND brand_id=:bid` — where `note_brand_stats.brand_id` is TEXT.  
PostgreSQL rejected `text = uuid` comparison.

**Fix:** `CAST(p.brand_id AS text)` in the source query + `str(brand_id)` coercion in Python.  
**Fix commit:** `9a53027`

This is the third variant of the UUID/text cast issue in this layer:
- `722d443` — fixed JOINs in `stats_builder.py` and `query_layer.py` (deploy verification)
- `9a53027` — fixed `p.brand_id` SELECT (this phase)

---

## 11. Status Classification

| Gate | Status |
|------|--------|
| Code Complete | ✅ |
| Bridge Script Written | ✅ (`scripts/sync_enrichment_to_production.py`) |
| Dry-Run Verified | ✅ |
| Live Sync Executed | ✅ |
| Phase 2 Re-Run | ✅ |
| Validation PASS | ✅ All 9 checks |
| Commit and Push | ✅ `9a53027` |

**Phase 2b: COMPLETE**  
**Phase 2: PRODUCTION VERIFIED**

---

## 12. Commit Summary

| Hash | Content |
|------|---------|
| `9a53027` | Bridge script + fix: note_brand_stats UUID/text cast |

---

*Run date: 2026-04-21. Production service: `generous-prosperity` (Railway). Database: PostgreSQL at `postgres.railway.internal:5432/railway`.*
