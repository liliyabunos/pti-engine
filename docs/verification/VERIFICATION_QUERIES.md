# Verification Queries

Extracted from CLAUDE.md on 2026-05-05.

## D4 — Market Reality Verification

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


---

## D5 — Aggregation Verification Queries

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


---

## Phase 5 — Import Verification

```sql
DELETE FROM fragrance_master WHERE source = 'kaggle_v1';
DELETE FROM perfumes WHERE source = 'kaggle_v1';
DELETE FROM brands WHERE source = 'kaggle_v1';
```

Three targeted deletes in FK order. No migration needed. Resolver returns to pre-import state exactly.

**Production PostgreSQL:** no rollback needed — Phase 5 writes nothing directly to PostgreSQL. Market-layer rows only appear after ingestion, so the rollback window exists.

### Verification

**After 500-row run:**

1. `SELECT COUNT(*) FROM brands WHERE source='kaggle_v1'` — must be > 0, must be < total brands in first 500 rows (some already existed)
2. `SELECT COUNT(*) FROM perfumes WHERE source='kaggle_v1'` — same logic
3. Spot-check 5 known perfumes from the 500-row slice: confirm they are NOT in `kaggle_v1` rows (correctly skipped by dedup)
4. Spot-check 3 expected-new perfumes: confirm they ARE present with correct brand_id links

**After full run:**

1. Count delta: brands, perfumes, fragrance_master — compare to pre-run baseline
2. Zero duplicates check: `SELECT normalized_name, COUNT(*) FROM perfumes GROUP BY normalized_name HAVING COUNT(*) > 1` — must return 0 rows
3. Resolver lookup: 5 newly imported perfumes must resolve correctly via existing resolver logic
4. Integrity check: all `perfumes.brand_id` must reference valid `brands.id` rows
5. Confirm `aliases` table was not touched (count must be unchanged)

### Success Criteria

| Criteria | Pass condition |
|----------|---------------|
| Dry-run clean | 0 errors, expected counts look reasonable |
| 500-row run clean | Counts correct, 0 duplicates, spot-checks pass |
| Full run clean | All verification queries pass |
| Zero alias pollution | `aliases` count unchanged from pre-import |
| Zero duplicate normalized_names | Duplicate query returns 0 rows |
| Resolver integrity | 5 new + 5 existing perfumes resolve correctly |
| Rollback tag confirmed | `source='kaggle_v1'` present on all new rows |
| Production run complete | Same verification passes against production DB |

**Import is NOT considered successful if:**
- any duplicate normalized_name exists
- any perfume row has a NULL or invalid brand_id
- aliases count changed (bulk generation must be 0)
- resolver spot-check fails for any imported entity

---


---

## G3-C Channel Registry Verification

expands its own channel coverage automatically:

```
YouTube search ingestion (Step 1)
  ↓ writes canonical_content_items with source_account_id = UC... channel ID
discover_youtube_channels.py (Step 5b)
  ↓ anti-joins canonical_content_items against youtube_channels
  ↓ promotes qualifying channels (avg_views ≥ 1,000, videos ≥ 2) into youtube_channels
  ↓ ON CONFLICT DO NOTHING — idempotent, safe every morning
youtube_channels registry (persistent)
  ↓ grows with every morning run as new channels appear in search-ingested content
ingest_youtube_channels.py (Step 1a)
  ↓ polls registered channels via playlistItems.list (1 unit/page vs 100 units/search)
  ↓ adaptive gating: due channels only (next_poll_after <= NOW())
more canonical_content_items (channel_poll ingestion_method)
  ↓ broader entity coverage, more resolved signals
aggregate + detect signals (Steps 2–3)
  ↓ more entities, more timeseries rows, more market intelligence
```

**Key properties of this loop:**
- **Self-seeding**: search-ingested content (Step 1) automatically feeds the discovery input
- **Zero extra quota for discovery**: anti-join runs against local DB, no API calls
- **Channel polling is cheaper than search**: 1 unit/page vs 100 units/search call
- **No cap on registry size**: the loop naturally converges as channels are promoted and polled
- **Automatic quality gating**: only channels seen in real content with real views enter
- **Daily cap**: `--limit 100` per morning cycle prevents unbounded growth spikes

**Invariant**: a channel that appears in `canonical_content_items` via search will,
within one morning pipeline cycle, be promoted to `youtube_channels` and begin
receiving dedicated channel polls in subsequent cycles.

---

### Non-Goals (G3-C)

- No migrations
- No schema changes
- No pipeline integration (G3-C is standalone only)
- No manual channel list insertion — all channels come from real `canonical_content_items` data
- No editorial tier assignment — auto-tier only (manual upgrade via `manage_channels.py --update-tier`)
- No handle validation via YouTube API — handle stored as-is from `source_account_handle`
- No subscriber count fetching — only what's available in local DB

---


---

## FIX-1 Verification

```sql
CREATE UNIQUE INDEX uq_entity_mentions_entity_source
  ON entity_mentions(entity_id, source_url);
```

Full (non-partial) index — `source_url` has 0 NULL values in production.
Acts as a DB-level safety net in addition to the Python dedup check.
Also enables `ON CONFLICT DO NOTHING` as a future hardening option.

---

### FIX-1D — Aggregator Dedup Fix

`_write_mentions()` now resolves the full source URL once and uses it consistently:

```python
# Resolve once — used for both check and INSERT
source_url_resolved = _resolve_source_url(item, cid)

exists = db.query(EntityMention).filter_by(
    entity_id=entity_uuid, source_url=source_url_resolved
).first()
if exists:
    continue

mention = EntityMention(
    ...
    source_url=source_url_resolved,
)
```

Regression tests: `tests/unit/test_write_mentions_dedup.py` — 10 tests covering URL resolution,
dedup consistency (check URL == insert URL for YouTube/Reddit), and multi-entity video dedup logic.

---

### FIX-1E/1F — Historical Re-aggregation + Signal Re-detection

All 33 dates re-aggregated and signal-detected:
- **Date range:** 2026-03-30 through 2026-05-01
- `aggregate_daily_market_metrics` run for all 33 dates (idempotent upserts)
- `detect_breakout_signals` run for all 33 dates (idempotent — clears stale signals before re-detecting)
- Re-aggregation confirmed `mentions_written=0` on all dates (dedup fix working, no new duplicates)

---

### Verification Results

| Metric | Value |
|--------|-------|
| `entity_mentions` after re-aggregation | **1,135** |
| `mention_sources` after re-aggregation | **1,277** |
| Duplicate `(entity_id, source_url)` groups | **0** |
| Unique index `uq_entity_mentions_entity_source` | **active, `indisunique=True`** |
| `alembic_version` | **026** |
| `entity_timeseries_daily` rows (Mar 30–May 1) | **5,000** |
| Signals across corrected 33-date window | **1,051** |
| Signal types | new_entry=436, breakout=297, acceleration_spike=261, reversal=57 |
| Repeated aggregation creates duplicates | **NO** |

**Key entity scores after correction (de-duplicated):**

| Entity | Latest date | Score | Trend state |
|--------|------------|-------|-------------|
| Creed Aventus | 2026-05-02 | 17.28 | declining |
| MFK Baccarat Rouge 540 | 2026-04-30 | 43.27 | rising |
| Dior Sauvage | 2026-05-02 | 14.85 | declining |
| Chanel Bleu de Chanel | 2026-05-02 | 27.73 | rising |
| Rasasi Hawas | 2026-05-02 | 20.87 | rising |
| Tom Ford Black Orchid | 2026-04-30 | 38.41 | breakout |

---

### UI Impact

- Scores and trend states are now computed from de-duplicated mention counts — no more compounding inflation
- Trend states for previously over-inflated entities corrected (e.g. declining entities now correctly show declining)
- Signal feed reflects real market activity — no phantom breakouts from duplicate-inflated scores
- Top movers ranking is based on actual ingested content volume

---

### Remaining Known Issue

**142 pre-existing orphan `mention_sources` rows** from the April 26 identity map cleanup
(`fix_stale_identity_map_mentions.py`) remain in the table. These were not introduced by FIX-1 and should be handled in a separate cleanup pass. They do not affect current scoring or signal detection.

---

### Pipeline Scripts

`start_pipeline.sh` and `start_pipeline_evening.sh` — **unchanged**.


---

