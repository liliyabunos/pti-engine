# Phase 2 — Notes & Brand Intelligence Layer

**Date:** 2026-04-20  
**Scope:** Phase 2 — Notes normalization, canonical grouping, accord stats, brand intelligence  
**Status:** COMPLETE — all validation checks pass

---

## 1. Summary

| Metric | Value |
|--------|-------|
| Source notes (raw) | 137 |
| Canonical notes (after grouping) | 109 |
| Notes merged into groups | 28 (across 17 merge groups) |
| Accord entries | 9 |
| Accord stats computed | 8 |
| note_brand_stats pairs | 239 |
| Brands with enriched notes | 15 |
| Perfumes with note data | 28 |

---

## 2. Note Normalization & Canonical Grouping

### What changed

The raw `notes` table stores every distinct note string from Fragrantica (137 entries, already deduplicated by `normalized_name`). Phase 2 adds a **semantic grouping** layer that collapses variant spellings and regional subtypes into single canonical entities.

### New tables

| Table | Purpose |
|-------|---------|
| `notes_canonical` | 109 canonical note entities |
| `note_canonical_map` | Maps all 137 raw notes → canonical (one-to-one) |
| `note_stats` | Precomputed per-canonical stats |
| `accord_stats` | Precomputed per-accord stats |
| `note_brand_stats` | Note × brand relationship (239 pairs) |

### Canonical merge groups (17 groups, 28 notes merged)

| Canonical | Variants merged |
|-----------|----------------|
| pepper | Black Pepper, pepper, pink pepper, sichuan pepper |
| Cedar | Atlas Cedar, cedar, cedarwood, Virginian Cedar |
| Mandarin | Green Mandarin, Italian Mandarin, Mandarin Orange, Sicilian Mandarin |
| Orange | Blood Orange, Orange, Sicilian Orange |
| Blackcurrant | Black Currant, blackcurrant, Blackcurrant Syrup |
| Vanilla | Madagascar Vanilla, Vanilla, Vanilla Absolute |
| Rose | Damask Rose, rose, turkish rose |
| Jasmine | egyptian jasmine, jasmine, Water Jasmine |
| musk | musk, White Musk |
| Amber | Amber, Ambermax™ |
| bergamot | bergamot, Calabrian bergamot |
| Lemon | Lemon, Sicilian Lemon |
| labdanum | labdanum, Spanish Labdanum |
| patchouli | patchouli, Patchouli Leaf |
| Tobacco | Tobacco, Tobacco Leaf |
| Lychee | Litchi, lychee |
| Benzoin | Benzoin, Siam Benzoin |

All other 120 notes are self-canonical (each maps to itself).

---

## 3. Top 20 Notes by Perfume Coverage

| Rank | Note | Perfumes | Brands | Top | Middle | Base |
|------|------|----------|--------|-----|--------|------|
| 1 | musk | 13 | 10 | — | 3 | 12 |
| 2 | Vanilla | 13 | 9 | — | 2 | 11 |
| 3 | patchouli | 12 | 9 | 1 | 4 | 8 |
| 4 | bergamot | 10 | 8 | 11 | — | — |
| 5 | Jasmine | 10 | 6 | — | 10 | — |
| 6 | Cedar | 9 | 6 | — | — | 11 |
| 7 | Sandalwood | 8 | 6 | — | 1 | 7 |
| 8 | Amber | 7 | 6 | — | — | 7 |
| 9 | Lemon | 6 | 6 | 6 | — | — |
| 10 | Nutmeg | 6 | 6 | 5 | 1 | — |
| 11 | Rose | 6 | 6 | 1 | 6 | — |
| 12 | vetiver | 6 | 5 | — | 2 | 4 |
| 13 | Pepper | 6 | 5 | 5 | 2 | 1 |
| 14 | Mandarin | 5 | 5 | 5 | — | — |
| 15 | lavender | 5 | 4 | 2 | 3 | — |
| 16 | Incense | 4 | 4 | 1 | 1 | 2 |
| 17 | ambroxan | 4 | 4 | — | 1 | 3 |
| 18 | labdanum | 4 | 4 | 1 | — | 3 |
| 19 | Blackcurrant | 4 | 4 | 4 | — | 1 |
| 20 | Tonka Bean | 3 | 3 | — | 1 | 2 |

**Position patterns:**
- **Top notes:** bergamot, lemon, nutmeg, mandarin, pepper, blackcurrant — all brightness-first
- **Middle notes:** jasmine, rose — floral heart anchors
- **Base notes:** musk, vanilla, cedar, sandalwood, amber, patchouli — depth/fixative layer

---

## 4. Accord Statistics

| Accord | Perfumes | Brands |
|--------|----------|--------|
| fresh | 2 | 2 |
| woody | 2 | 2 |
| fruity | 1 | 1 |
| smoky | 1 | 1 |
| powdery | 1 | 1 |
| floral | 1 | 1 |
| sweet | 1 | 1 |
| aromatic | 1 | 1 |

> **Note:** Accord count is small because Fragrantica's current HTML does not render the accords section in the Vue.js DOM for most pages. The 9 accords present are from the Phase 1 reference seed batch. This limitation is tracked in the Phase 1b report.

---

## 5. Brand Intelligence

### Brands by note diversity (distinct canonical notes used)

| Brand | Distinct Notes | Total Note Links |
|-------|---------------|-----------------|
| Parfums de Marly | 31 | 46 |
| Mancera | 24 | 29 |
| Maison Francis Kurkdjian | 24 | 41 |
| Creed | 22 | 25 |
| Versace | 20 | 21 |
| Chanel | 18 | 23 |
| Lattafa | 18 | 13 |
| Dior | 16 | 26 |
| Gucci | 15 | 17 |
| Giorgio Armani | 15 | 18 |

### Example: Creed note profile

| Note | Perfumes | Share |
|------|----------|-------|
| patchouli | 1 | 1.00 |
| Jasmine | 1 | 1.00 |
| Sandalwood | 1 | 1.00 |
| apple | 1 | 1.00 |
| musk | 1 | 1.00 |
| Pepper | 1 | 1.00 |
| Amber | 1 | 1.00 |
| oakmoss | 1 | 1.00 |

*(1 Creed perfume enriched — Aventus)*

---

## 6. Note × Brand Example: patchouli

Brands using **patchouli** (canonical, includes Patchouli Leaf):

| Brand | Perfumes | Share |
|-------|----------|-------|
| Mancera | 2 | 1.00 |
| Giorgio Armani | 2 | 1.00 |
| Gucci | 2 | 1.00 |
| Creed | 1 | 1.00 |
| Initio | 1 | 1.00 |
| Parfums de Marly | 1 | 0.33 |
| Chanel | 1 | 0.50 |
| Dior | 1 | 0.50 |
| Maison Francis Kurkdjian | 1 | 0.50 |

---

## 7. Validation Results

All checks pass:

| Check | Result |
|-------|--------|
| notes_canonical populated | ✅ |
| note_canonical_map populated | ✅ |
| note_stats populated | ✅ |
| accord_stats populated | ✅ |
| note_brand_stats populated | ✅ |
| top_notes returns result | ✅ |
| brand_stats returns result | ✅ |
| top_accords returns result | ✅ |
| no duplicate note mappings | ✅ |

---

## 8. Query Layer Functions

| Function | Description |
|----------|-------------|
| `get_top_notes(session, limit)` | Top N canonical notes by perfume coverage |
| `get_top_accords(session, limit)` | Top N accords by perfume coverage |
| `get_notes_by_brand(session, brand_id, limit)` | Notes used by a brand |
| `get_brands_by_note(session, canonical_note_id, limit)` | Brands using a note |
| `get_brands_by_note_name(session, normalized_name, limit)` | Same, by name string |
| `get_perfumes_by_note(session, canonical_note_id, limit)` | Perfumes containing a note |
| `get_perfumes_by_note_name(session, normalized_name, limit)` | Same, by name string |
| `get_brand_note_profile(session, brand_id)` | Full note/accord profile for a brand |
| `get_brands_with_most_notes(session, limit)` | Brands ranked by note diversity |
| `validate(session)` | Run all validation checks |

All functions are in `perfume_trend_sdk/analysis/notes_intelligence/query_layer.py`.

---

## 9. Files Added

| File | Purpose |
|------|---------|
| `perfume_trend_sdk/db/market/notes_intelligence.py` | ORM models: NoteCanonical, NoteCanonicalMap, NoteStats, AccordStats, NoteBrandStats |
| `alembic/versions/009_add_notes_brand_intelligence.py` | Schema migration |
| `perfume_trend_sdk/analysis/notes_intelligence/canonicalizer.py` | Canonical group definitions + mapping logic |
| `perfume_trend_sdk/analysis/notes_intelligence/stats_builder.py` | Stats computation: populates all 5 tables |
| `perfume_trend_sdk/analysis/notes_intelligence/query_layer.py` | Read-only query API |
| `perfume_trend_sdk/jobs/build_notes_intelligence.py` | CLI job: `python3 -m perfume_trend_sdk.jobs.build_notes_intelligence` |

---

## 10. Known Limitations

| Limitation | Detail |
|------------|--------|
| Small dataset | Only 28 enriched perfumes — stats will improve as more Fragrantica data is ingested |
| Accords sparse | Fragrantica doesn't render accords in current Vue.js DOM; most accords data is from Phase 1 seed |
| Share calculation basis | Share = perfume_count / brand_enriched_perfume_count. With 1 enriched perfume per brand, all shares are 1.0 |
| No time dimension | Note stats are cross-sectional snapshots; no trending/velocity yet |

---

## 11. Next Steps

| Priority | Action |
|----------|--------|
| High | Expand Fragrantica enrichment (more perfumes → better note coverage) |
| Medium | Expose note/brand data in API endpoints (`/api/v1/notes`, `/api/v1/brands/{id}/notes`) |
| Medium | Add note momentum scoring (which notes are gaining coverage in new enrichments) |
| Low | Add note family grouping to dashboard filter layer |

---

*Build run against `outputs/market_dev.db`, 2026-04-20.*
