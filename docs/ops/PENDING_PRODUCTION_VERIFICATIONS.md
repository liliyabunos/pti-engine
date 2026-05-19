# Pending Production Verifications Ledger

**OPS-PV1 — established 2026-05-16**

This ledger tracks all implementation tasks where production verification was deferred
and has not yet been confirmed with real evidence. It is the authoritative source of
truth for "things that must not be treated as COMPLETE — PRODUCTION VERIFIED."

---

## Operating Policy

### Primary Rule: Prefer Immediate Verification

Before deferring any verification, ask explicitly:

> Can this be verified NOW via direct production SQL, API/route smoke test,
> targeted job execution, bounded write-mode test, or safe manual UI check?

If yes: verify immediately. Do not create a ledger entry. Close with real evidence.

If no: create a ledger entry BEFORE moving on to new work.

### Status Vocabulary

| Status | Meaning |
|--------|---------|
| `IMPLEMENTED — PRODUCTION VERIFICATION PENDING` | Shipped. Immediate verification not possible. Deferred reason recorded. |
| `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` | Specifically waiting on a scheduled morning or evening pipeline run. |
| `READY TO VERIFY` | Trigger event has occurred or verification can now be run immediately. |
| `COMPLETE — PRODUCTION VERIFIED` | Confirmed with real production evidence. Entry closed with date + evidence. |
| `FAILED PRODUCTION VERIFICATION — FOLLOW-UP REQUIRED` | Verification ran; checks did not pass. Requires investigation and re-fix. |

### Blocking Rule

**No phase or task may be marked `COMPLETE — PRODUCTION VERIFIED` in CLAUDE.md
while it has an open unresolved entry in this ledger.**

### Repair-Complete Rule

**A data repair phase may not be marked `COMPLETE — PRODUCTION VERIFIED` unless all data layers that could recreate the false data have also been cleaned.**

Specifically: if downstream rows (`entity_mentions`, `entity_timeseries_daily`, `signals`) are deleted or repaired, but the upstream source layer that can recreate them (e.g. `resolved_signals.resolved_entities_json`) still contains the removed false entities, the phase must remain in status `IMPLEMENTED — FINAL SOURCE STRIP PENDING` until the upstream strip/cleanup is executed and verified at 0.

**Delivery Report Rule:** A delivery report may not contain `COMPLETE — PRODUCTION VERIFIED` together with any "remaining open item" that is structurally required to preserve the repair.

**Status to use when downstream is clean but upstream strip is pending:**
```
IMPLEMENTED — FINAL SOURCE STRIP PENDING
```

### Repair Scope Compatibility Rule

**The RS strip window (date cutoff) must cover the full date range of any aggregation recompute that runs after the repair — including retroactive recomputes triggered by unrelated data corrections.**

Root cause documented (RES-AMB1 Phase 2 regression, 2026-05-17):
- `res_amb1_targeted_repair.py` stripped RS with `--days 30` (cutoff: 2026-04-17)
- DATA4-D later ran aggregation recompute for 43 dates starting 2026-04-04
- `_load_resolved_signals()` reads ALL resolved_signals with no date filter
- 17 RS rows from 2026-04-11/13 (before the 30-day cutoff) were never stripped
- The recompute found those unstripped RS rows and recreated false entity_mentions

**Rule:** Any RS strip for an ambiguous false-positive entity must strip ALL historical RS rows for that entity — no `--days` window. Use `LIKE '%canonical_name%'` without a date condition to catch pre-cutoff accumulations.

### Required Delivery Line

Every task report that includes deferred verification must end with one of:

```
Production verification mode: IMMEDIATE — VERIFIED
```
or
```
Production verification mode: DEFERRED — LEDGER ENTRY CREATED: PV-XXX
```

### Session Opening Checklist

At the start of any new Claude session, before beginning new implementation work:

1. Read this file in full.
2. Identify any entries with status `READY TO VERIFY` or `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` where the trigger event has already occurred.
3. Resolve those entries first, unless the founder explicitly prioritizes otherwise.
4. Only then proceed to new implementation work.

---

## Ledger Entries

---

### PV-001 — P3.1 Pipeline Health Log Persistence Fix

| Field | Value |
|-------|-------|
| **Verification ID** | PV-001 |
| **Phase / task** | P3.1 — Pipeline Health Log DB persistence |
| **Related commits** | `8b49fd2` (implementation) · `ffab2ac` (SQL bug fix) |
| **Implementation shipped** | 2026-05-12 (migration 041) |
| **Fix shipped** | 2026-05-16 (`ffab2ac` pushed to main, Railway auto-deploy) |
| **Current status** | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` |
| **Immediate verification considered?** | No — `pipeline_health_log` is only written by the health check at the end of a pipeline run. Cannot be triggered safely outside the scheduled pipeline without running the full pipeline manually. |
| **Why deferred** | Requires a successful evening or morning pipeline run to produce a row. Fix deployed before 23:00 UTC 2026-05-16. |
| **Trigger event** | Tonight's 23:00 UTC evening pipeline (2026-05-16) — recovered manually same night after cron interruption |
| **Blocking severity** | High — P3.1 has been marked COMPLETE — PRODUCTION VERIFIED in CLAUDE.md incorrectly since 2026-05-12. Cannot restore that status until persistence is confirmed. |
| **2026-05-16 evening run outcome** | Pipeline started 23:00 UTC (Reddit 195 items, YouTube 497 items collected at 23:02). Code deploy `8a9c7ac` at ~23:09 UTC killed the cron container before Step 2 (aggregation). `updated_at` on entity_timeseries_daily never exceeded 22:57 UTC. pipeline_health_log still 0 rows. Same incident pattern as 2026-05-06 OPS NOTE. Recovered manually same night via `railway ssh --service generous-prosperity` — all remaining steps executed with `--date 2026-05-16`. |
| **Production verification evidence (2026-05-16)** | `pipeline_health_log`: run_date=2026-05-16, run_label='evening', overall_level='OK', reddit_items=195, reddit_mentions=217, issue_count=0, pipeline_service='generous-prosperity', recorded_at=2026-05-17T00:11:51Z ✓ · COUNT(*)=1 ✓ |

**Pass criteria — ALL MET:**
- `COUNT(*) > 0` ✓ (1 row)
- Row exists for `run_date = '2026-05-16'` and `run_label = 'evening'` ✓
- `overall_level = 'OK'` ✓
- `issues` is a valid non-null JSONB array (issue_count=0) ✓
- `pipeline_service = 'generous-prosperity'` ✓

**CLOSED — 2026-05-16**

---

### PV-002 — FTG-5 / SN1-A Signal Intelligence Snapshots

| Field | Value |
|-------|-------|
| **Verification ID** | PV-002 |
| **Phase / task** | FTG-5 / SN1-A — Signal Intelligence Snapshots |
| **Related commits** | `79d72c8` (implementation) · migration 050 |
| **Implementation shipped** | 2026-05-16 |
| **Current status** | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` |
| **Immediate verification considered?** | Partial — migration 050 can be verified immediately (table exists, alembic version). But snapshot rows require a healthy pipeline run that produces signals. May 16 morning was anomalous (signals=3); not acceptable evidence. |
| **Why deferred** | Row-level verification requires a healthy pipeline run with normal signal volume. May 16 morning run had only 3 signals — insufficient to confirm the snapshot write path. Verify against the next run where `signals_detected > 10`. |
| **Trigger event** | Tonight's 23:00 UTC evening pipeline (2026-05-16) — recovered manually same night after cron interruption; signals=134 >> 10 threshold |
| **Blocking severity** | Medium — SN1-A is not in a user-facing path. But CLAUDE.md must not show COMPLETE — PRODUCTION VERIFIED until rows are confirmed. |
| **Production verification evidence (2026-05-16)** | COUNT(*)=134 ✓ · earliest=2026-05-16, latest=2026-05-16 ✓ · market_score_at_detection IS NOT NULL ✓ (e.g. Creed Aventus reversal: score=24.9041, mentions=3.40) · snapshot_schema_version=1 on all rows ✓ · pipeline_run_date=2026-05-16 on all rows ✓ · Sample: Creed Aventus reversal, Diptyque L'eau acceleration_spike, Very Well breakout + acceleration_spike, MFK Baccarat Rouge 540 reversal |

**Pass criteria — ALL MET:**
- `signal_intelligence_snapshots COUNT(*) = 134` ✓
- `pipeline_run_date = 2026-05-16` on all rows ✓
- `market_score_at_detection IS NOT NULL` ✓
- `snapshot_schema_version = 1` ✓

**CLOSED — 2026-05-16**

---

### PV-003 — May 16 Morning signals=3 Root-Cause Verification

| Field | Value |
|-------|-------|
| **Verification ID** | PV-003 |
| **Phase / task** | Incident verification — not an implementation phase |
| **Related commits** | N/A |
| **Incident date** | 2026-05-16 morning |
| **Current status** | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` |
| **Verified** | 2026-05-16 via `railway ssh --service generous-prosperity` production SQL |

**SQL evidence (production, 2026-05-16):**
```
Q1 — YouTube published_at for items collected 2026-05-16:
  2026-05-16: 41 items   (11% — published same day)
  2026-05-15: 164 items
  2026-05-14: 127 items
  2026-05-13: 30 items
  Total collected: 362 items; 321 (89%) had pre-May-16 published_at

Q2 — entity_mentions occurred_at:
  2026-05-16: 17 mentions  ← matches health check exactly
  2026-05-15: 268 mentions
  2026-05-14: 65 mentions
  2026-05-13: 242 mentions

Q3 — platform breakdown:
  2026-05-16: youtube=362, reddit=0
  2026-05-15: reddit=204, youtube=956

Q4 — reddit_may16_count: 0 (confirmed true zero)
```

**Hypothesis verdict: CONFIRMED — with one correction.**

The `occurred_at = published_at` artifact is confirmed: 362 YouTube items collected on May 16, but 321 (89%) had `published_at` from May 13–15. Health check counts `WHERE DATE(occurred_at) = '2026-05-16'` → only 17 entity_mentions landed on May 16 → signals=3.

**Correction vs. original hypothesis:** This was NOT a first-poll (30-day) backfill. The published_at span covers only 3 days (May 13–16), consistent with the standard `--lookback-days 2` YouTube search ingest window running at 11:00 UTC. This is the normal "morning collection lag" artifact — items published on May 14–15 are always re-collected in the morning window and contribute to `entity_mentions` dated those prior days, not today.

**Structural conclusion:** The `entity_mentions` health check metric is **inherently unreliable for morning-only YouTube runs** because it counts by `occurred_at = published_at`, not by ingestion time. A pipeline that runs at 11:00 UTC will always have most "today's" YouTube items with yesterday's or earlier `published_at`. The metric is reliable for Reddit (where `occurred_at = collected_at`) but structurally understates YouTube-only pipeline runs.

**No follow-up required.** Root cause confirmed. Reddit=0 confirmed as a separate independent failure.

---

## Closed Entries

### PV-001 — CLOSED 2026-05-16
`pipeline_health_log` persistence confirmed after manual recovery of interrupted evening pipeline. Fix `ffab2ac` (`CAST(:issues AS JSONB)`) verified working: run_date=2026-05-16, run_label='evening', overall_level='OK', pipeline_service='generous-prosperity', COUNT(*)=1. Recovery via `railway ssh --service generous-prosperity` — all remaining steps executed with `--date 2026-05-16` after cron was killed by code deploy `8a9c7ac` at 23:09 UTC.

### PV-002 — CLOSED 2026-05-16
Signal intelligence snapshots confirmed after manual recovery of interrupted evening pipeline. 134 snapshots written for pipeline_run_date=2026-05-16. All pass criteria met: metrics populated (market_score_at_detection IS NOT NULL), snapshot_schema_version=1, pipeline_run_date matches detected_at::date. Recovery via `railway ssh --service generous-prosperity` — signals=134 far exceeded the >10 threshold.

### PV-003 — CLOSED 2026-05-16
Hypothesis confirmed via production SQL (`railway ssh --service generous-prosperity`). Root cause: `occurred_at = published_at` means morning YouTube ingest always produces entity_mentions dated prior days. Reddit=0 confirmed as independent failure. See entry above for full evidence.

---

---

### PV-004 — DATA4-B Brand Promotion Guard + Ghost Brand Repair

| Field | Value |
|-------|-------|
| **Verification ID** | PV-004 |
| **Phase / task** | DATA4-B — Brand promotion guard + ghost brand repair script |
| **Related commits** | `48784ed` (implementation) |
| **Implementation shipped** | 2026-05-16 |
| **Current status** | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` |
| **Immediate verification considered?** | Yes — repair script can be run immediately via Railway SSH. Guard verification requires running `aggregate_daily_market_metrics` after deploy. |
| **Why deferred** | Requires Railway auto-deploy of `48784ed` to complete, then run repair script + aggregation rerun via Railway SSH. Cannot verify guard effectiveness until at least one pipeline run post-deploy. |
| **Trigger event** | Railway deploy of `48784ed` completes (Railway auto-deploys on push to main) |
| **Blocking severity** | High — guard prevents future ghost brand pollution; repair removes existing ghosts. Both must be verified before DATA4-B can be marked COMPLETE. |

**Verification steps:**

```bash
# Step 1: Confirm Railway deployed 48784ed
railway deployment list --limit 5 --json | grep -A5 "48784ed"

# Step 2: Run repair script dry-run
DATABASE_URL=<prod-url> python3 scripts/data4b_ghost_brand_repair.py

# Step 3: Run repair script --apply
DATABASE_URL=<prod-url> python3 scripts/data4b_ghost_brand_repair.py --apply

# Step 4: Verify ghost brands gone (via Railway SSH)
# SQL:
SELECT em.canonical_name, COUNT(etd.id) AS ts_rows
FROM entity_market em
LEFT JOIN entity_timeseries_daily etd ON etd.entity_id = em.id
WHERE em.entity_type = 'brand'
  AND NOT EXISTS (SELECT 1 FROM resolver_brands rb WHERE LOWER(rb.canonical_name) = LOWER(em.canonical_name))
  AND NOT EXISTS (SELECT 1 FROM brand_profiles bp WHERE LOWER(bp.brand_name_normalized) = LOWER(em.canonical_name))
GROUP BY em.canonical_name HAVING COUNT(etd.id) > 0 ORDER BY ts_rows DESC;
-- Expect: 0 rows (TOM FORD Private Blend and encoding-mismatch brands exempt)

# Step 5: Re-run aggregation for last 7 days
for D in $(seq 0 6); do
  DATE=$(date -u -d "-$D days" +%Y-%m-%d 2>/dev/null || date -u -v-${D}d +%Y-%m-%d)
  python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date $DATE
done

# Step 6: Confirm guard fires for known ghost brand in WARNING logs
# (Check railway logs for "brand_promotion_blocked" warnings — should appear if any
# entity_market.perfume rows still have ghost brand_names after repair)
```

**Pass criteria:**
- Ghost brand query returns 0 rows with `ts_rows > 0` (excluding TOM FORD Private Blend and encoding variants)
- `brand_promotion_blocked` warnings appear in aggregation logs for any residual ghost brands
- Dashboard and screener load correctly after aggregation rerun (no P0 regressions)

**Production verification evidence (2026-05-16):**
- Ghost brands with ts_rows > 0 after repair: 5 (all DATA4-D encoding variants — correctly excluded) ✓
- Known-deleted ghost entity_ids still in entity_market: 0 ✓
- Upstream brand_name spot-check: Angels' Share → Kilian, Creed Green Irish Tweed → Creed, Molecule 01 + Ginger → Escentric Molecules, Vanilla | 28 → Kayali, Oud & Bergamot → Jo Malone, Musk | 12 → Kayali — all correct ✓
- TOM FORD Private Blend (DATA4-C exclusion): INTACT ts=59 ✓
- Total brand entities: 572 (down from 660 pre-repair) ✓
- Total ghost brands remaining: 5 (exactly the DATA4-D encoding variants) ✓
- Guard firing in aggregation reruns: `brand_promotion_blocked` warnings for structural fragments and non-canonical brands ✓
- Aggregation rerun 7 days: 0 errors, brand_rollup_written counts normal ✓
- Idempotency: second dry-run after apply shows Ghost brands found: 5 / entities deleted: 0 ✓

**CLOSED — 2026-05-16**

---

---

### PV-005 — RES-AMB4 Brand Recompute Verification (5 Mixed Brands)

| Field | Value |
|-------|-------|
| **Verification ID** | PV-005 |
| **Phase / task** | RES-AMB4 — brand-level timeseries/signals restoration for 5 mixed brands |
| **Related commits** | `1f63429` (repair script) |
| **Repair applied** | 2026-05-17 |
| **Current status** | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` |
| **Blocking severity** | Medium — UI/API currently shows no score/trend for 5 brands that have legitimate tracked perfumes. Product gap, not data integrity issue. RS source is clean. |

**Context:**

The RES-AMB4 brand cleanup deleted brand-level `entity_timeseries_daily` + `signals` for all 8 affected brands using OPS-EE1 (delete all → let pipeline recompute). Post-deletion analysis confirmed:

**3 brands were 100% false-positive-derived (deletion was fully correct):**
- **Femascu** — "I will" was the only tracked perfume. All ts=48, sig=22 were FP-derived.
- **Smell Bent** — "Day One" was the only tracked perfume. All ts=23, sig=1 were FP-derived.
- **Puig** — "You & You" was the only tracked perfume. All ts=26, sig=0 were FP-derived.

**5 brands were mixed — legitimate brand state was also deleted:**
- **Michael Kors** — brand ts=35 deleted; "Very Pretty" had ts=6. ~29 rows likely from other MK tracked perfumes.
- **Fiorucci** — brand ts=30 deleted; "So Sexy!" had ts=13. ~17 rows likely from other Fiorucci tracked perfumes.
- **Helena Rubinstein** — brand ts=39 deleted; "Best Man" had ts=12. ~27 rows likely from other HR tracked perfumes.
- **Primark** — brand ts=41 deleted; "Jasmine & Rose" had ts=18. ~23 rows likely from other Primark tracked perfumes.
- **Monotheme** — brand ts=14 deleted; "Cedar Wood" had ts=1. ~13 rows likely from other Monotheme tracked perfumes.

The RS strip was correctly applied full-history for all 8 FP perfume entities. The pipeline's next aggregation recompute will re-derive legitimate brand state from the now-clean RS rows. No FP canonical names will be recreated because the guard is live in `perfume_resolver.py`.

**Trigger event:** Next scheduled morning pipeline (11:00 UTC 2026-05-18) or evening pipeline (23:00 UTC 2026-05-17).

**Verification SQL (run after pipeline):**

```sql
-- Check all 5 mixed brands have non-zero ts rows restored
SELECT em.canonical_name, COUNT(etd.id) AS ts_rows, MAX(etd.date) AS latest_date
FROM entity_market em
LEFT JOIN entity_timeseries_daily etd ON etd.entity_id = em.id
WHERE em.entity_type = 'brand'
  AND em.canonical_name IN ('Michael Kors', 'Fiorucci', 'Helena Rubinstein', 'Primark', 'Monotheme')
GROUP BY em.canonical_name
ORDER BY em.canonical_name;
-- Expect: ts_rows > 0 for all 5 brands (exact counts depend on which perfumes they have tracked)

-- Confirm no FP canonical names re-appear in RS rows
SELECT COUNT(*) FROM resolved_signals
WHERE resolved_entities_json::jsonb @> jsonb_build_array(jsonb_build_object('canonical_name', 'Very Pretty'))
   OR resolved_entities_json::jsonb @> jsonb_build_array(jsonb_build_object('canonical_name', 'So Sexy!'))
   OR resolved_entities_json::jsonb @> jsonb_build_array(jsonb_build_object('canonical_name', 'Best Man'))
   OR resolved_entities_json::jsonb @> jsonb_build_array(jsonb_build_object('canonical_name', 'You & You'))
   OR resolved_entities_json::jsonb @> jsonb_build_array(jsonb_build_object('canonical_name', 'Jasmine & Rose'))
   OR resolved_entities_json::jsonb @> jsonb_build_array(jsonb_build_object('canonical_name', 'Cedar Wood'));
-- Expect: 0 (all newly ingested RS rows pass through the updated guard)
```

**Pass criteria (ALL must pass):**
- Michael Kors: `ts_rows > 0` ✓
- Fiorucci: `ts_rows > 0` ✓
- Helena Rubinstein: `ts_rows > 0` ✓
- Primark: `ts_rows > 0` ✓
- Monotheme: `ts_rows > 0` ✓
- FP re-appearance check: `COUNT(*) = 0` ✓

**On pass:** Update RES-AMB4 status in CLAUDE.md to `COMPLETE — PRODUCTION VERIFIED`. Close this entry.

**Important note:** If any of the 5 brands shows `ts_rows = 0` after the pipeline runs, this means they have no other tracked perfumes generating mentions in the current pipeline window. That would still be a legitimate state (not a failure of the repair) — but confirm by checking `entity_market` for other tracked perfumes under that brand.

---

---

### PV-006 — SIG-QA1-REPAIR Production UI/API Verification

| Field | Value |
|-------|-------|
| **Verification ID** | PV-006 |
| **Phase / task** | SIG-QA1-REPAIR — 5 confirmed unsupported entities; guard + RS strip + downstream cleanup + brand rollup repair |
| **Related commits** | `b765377` (guards + tests + repair script) |
| **Repair applied** | 2026-05-17 (direct DB via public proxy) |
| **Current status** | `IMPLEMENTED — AWAITING UI VERIFICATION` |
| **Blocking severity** | High — RS strip + downstream cleanup verified at DB layer; UI/API smoke test required to confirm no stale signals or entity scores are served to users. |

**Repair summary (applied 2026-05-17):**

| Layer | Count |
|-------|-------|
| RS rows updated (resolved_entities_json stripped) | 80 total (PL=9, OTR=19, ETD=1, OB=49, CTR=2) |
| entity_mentions deleted | 80 |
| entity_timeseries_daily deleted (perfume) | 131 |
| signals deleted (perfume) | 26 |
| signal_intelligence_snapshots deleted | 2 |
| Brand ts deleted (Wolken=46, AF=49, CT=8) | 103 |
| Brand signals deleted (Wolken=5, AF=19, CT=1) | 25 |
| Angela Flanders brand recomputed | 1 row (2026-04-16, score=30.1682, mentions=1.0, from Precious One) |

**DB-layer verification evidence (2026-05-17 — ALL PASS):**
- Pure Luxury (c08867ea): mentions=0, ts=0, signals=0, snaps=0 ✓
- On the Rocks (d22eea5f): mentions=0, ts=0, signals=0, snaps=0 ✓
- Enjoy the Day (411ebef2): mentions=0, ts=0, signals=0, snaps=0 ✓
- Orange Blossom (7277f176): mentions=0, ts=0, signals=0, snaps=0 ✓
- Cire Trudon Revolution (0c5f5215): mentions=0, ts=0, signals=0, snaps=0 ✓
- RS residual (exact jsonb canonical_name check): ALL 5 = 0 ✓
- Wolken Parfums brand: ts=0, signals=0 ✓
- Angela Flanders brand: ts=1 (2026-04-16, score=30.1682, mentions=1.0) ✓
- Cire Trudon brand: ts=0, signals=0 ✓

**Trigger event:** Railway deploy of `b765377` completes + UI/API smoke test run by operator.

**UI/API verification checklist (operator runs after Railway deploy):**

```
[ ] Wolken Parfums brand page (/entities/brand/brand-wolken-parfums):
    - Pure Luxury NOT in top movers or active entities
    - On the Rocks NOT in top movers or active entities
    - Enjoy the Day NOT in top movers or active entities
    - Brand score = None or 0 (no tracked perfumes remaining)

[ ] Angela Flanders brand page (/entities/brand/brand-angela-flanders):
    - Orange Blossom: entity score removed or shows Precious One contribution only
    - Brand shows only Precious One as tracked perfume

[ ] Cire Trudon Revolution entity page (/entities/perfume/cire-trudon-revolution):
    - score = None (no data) OR entity not in active search results
    - No active signals visible

[ ] Dashboard Top Movers:
    - None of the 5 FP entity names appear (Pure Luxury, On the Rocks, Enjoy the Day,
      Orange Blossom [Angela Flanders], Cire Trudon Revolution)

[ ] Positive regression — Jaguar Vision:
    - /entities/perfume/jaguar-vision still shows score (SIG-QA1 verdict: CONFIRMED SUPPORTED)

[ ] Positive regression — Kilian Apple Brandy on the Rocks:
    - Resolver smoke test: "kilian apple brandy on the rocks" resolves correctly
    - "On the Rocks" (Wolken) is NOT attributed in that content

[ ] Guard smoke test (resolver):
    - resolve_text("apple brandy on the rocks is incredible") → On the Rocks NOT in results
    - resolve_text("wolken on the rocks is great") → On the Rocks IN results
```

**Pass criteria:** All 7 checklist items pass.

**On pass:** Update SIG-QA1-REPAIR status in CLAUDE.md to `COMPLETE — PRODUCTION VERIFIED`. Close this entry.

---

---

### PV-007 — SIG-ID1 Production Deploy Verification

| Field | Value |
|-------|-------|
| **Verification ID** | PV-007 |
| **Phase / task** | SIG-ID1 — Cross-Brand Attribution Correction: migration 051 + Amber Elixir repair + harvest backfill |
| **Related commits** | SIG-ID1 implementation (this session 2026-05-18) |
| **Current status** | `COMPLETE — PRODUCTION VERIFIED (2026-05-18)` |
| **Blocking severity** | CLOSED |

**What was implemented (SIG-ID1):**
- `perfume_resolver.py`: bare-alias conflicting-brand suppression + 7 new `_AMBIGUOUS_PHRASE_GUARD` entries for cross-brand collision pairs
- `pg_resolver_store.py`: `brand_name` added to alias cache; `get_brand_token_map()` method
- `alembic/versions/051_sig_id1_unresolved_signal_candidates.py`: new `unresolved_signal_candidates` table
- `scripts/harvest_unresolved_brand_signals.py`: daily harvest of brand-qualified unresolved phrases
- `scripts/sig_id1_amber_elixir_repair.py`: targeted repair for Oriflame Amber Elixir false attributions
- Admin API: `GET /api/v1/admin/signal-candidates`, `POST /{id}/dismiss`
- Admin UI: `/admin/signal-candidates` (Signal Candidates nav item in sidebar)
- Pipeline: `harvest_unresolved_brand_signals.py --apply --days 2` added to morning + evening pipelines
- Tests: `tests/unit/test_sig_id1_brand_proximity_suppression.py` — 43/43 pass

**Production deploy steps (operator):**

```bash
# 1. Deploy commit to main → Railway auto-deploys

# 2. Apply migration 051
railway run --service generous-prosperity alembic upgrade head
# Expect: alembic_version = 051

# 3. Run Amber Elixir repair (dry-run first)
DATABASE_URL=<prod-url> python3 scripts/sig_id1_amber_elixir_repair.py
# Then apply:
DATABASE_URL=<prod-url> python3 scripts/sig_id1_amber_elixir_repair.py --apply

# 4. Run initial harvest backfill (--days 90 to surface historical unresolved phrases)
DATABASE_URL=<prod-url> python3 scripts/harvest_unresolved_brand_signals.py --days 90 --apply
```

**Production verification evidence (2026-05-18) — ALL PASS:**

```
[x] alembic_version = 051 ✓
[x] unresolved_signal_candidates table: 7851 rows ✓ (COUNT > 0 ✓)
[x] Amber Elixir repair:
    - Oriflame Amber Elixir entity_mentions = 0 ✓
    - entity_timeseries_daily = 0 ✓
    - signals = 0 ✓
    - RS residual (exact jsonb canonical_name check) = 0 ✓
[x] Admin API: 401 without X-Pti-Admin-User; 200 + total=7851 with header ✓
[x] Resolver smoke tests:
    - _is_bare_alias("amber elixir", "Oriflame") = True ✓
    - _is_bare_alias("oriflame amber elixir", "Oriflame") = False ✓
    - _conflicting_brand_in_window(["vertus","amber","elixir",...], 1, 3, "Oriflame", map) = "Vertus" ✓
    - _AMBIGUOUS_PHRASE_GUARD["amber elixir"] = [frozenset({"oriflame"})] ✓
[x] 49/49 unit tests pass ✓
```

**Note — "vertus amber elixir" candidate:** The 2 repaired RS rows had "Oriflame Amber Elixir" stripped from
resolved_entities_json. The phrase "amber elixir" was originally resolved (not unresolved), so it was not added
to unresolved_mentions_json by the repair. Future Vertus Amber Elixir content will produce unresolved candidates.
This is correct behavior — the guard prevents future misattribution; historical repair was complete.

**Frontend deploy incident (2026-05-18) — included in this verification:**
- Root cause: `signal-candidates/[[...path]]/route.ts` (optional catch-all) conflicted with sibling `route.ts`
  — Next.js "cannot define route with same specificity" build failure
- Fix: renamed to `[...path]/route.ts` (required catch-all, commit `08048af`)
- pti-frontend Railway deploy `38465449` = SUCCESS ✓

**CLOSED — 2026-05-18**

---

---

### PV-008 — SIG-QA2 Shadow Mode Observation

| Field | Value |
|-------|-------|
| **Verification ID** | PV-008 |
| **Phase / task** | SIG-QA2 — Evidence-Aware Mention Promotion Gate v1 (shadow mode) |
| **Related commits** | `35120fa` SIG-QA2 impl · `2181ff5` alias_used fix · `2203d61` migration 053 + SAVEPOINT · `fa50e55` score-before-dedup reorder |
| **Migrations** | 052 — `evidence_confidence` + `weak_evidence_log` (UUID type, broken); 053 — `content_item_id` UUID→TEXT (fix) |
| **Implementation shipped** | 2026-05-18 |
| **Corrective patch deployed** | 2026-05-19 08:09:50 UTC — Railway SUCCESS |
| **Current status** | `IMPLEMENTED — SHADOW MODE PENDING PRODUCTION OBSERVATION` |
| **Gate active?** | NO — `SIG_QA2_GATE_ACTIVE=false` (Railway env default). Shadow-only: scores, logs, stamps evidence_confidence, never suppresses. |
| **Blocking severity** | High — gate must not be activated without completing all three prerequisites below. |

**Clean observation start: 2026-05-19 08:09:50 UTC (corrective patch deploy confirmed SUCCESS)**

- `alias_used` corrective patch (`2181ff5`) deployed and active.
- Migration 053 applied 2026-05-19 — `content_item_id` column changed UUID→TEXT. All RS rows have YouTube video IDs as content_item_id (non-UUID); migration 052 defined the column as UUID causing every INSERT to fail. Migration 053 fixes this.
- SAVEPOINT fix (`2203d61`): `_upsert_weak_evidence_log` now uses `SAVEPOINT weak_log_sp` to isolate upsert failures from the outer transaction (prevents `InFailedSqlTransaction` on EntityMention writes).
- Score-before-dedup reorder (`fa50e55`): evidence scoring and `_upsert_weak_evidence_log` now execute BEFORE the EntityMention dedup check (`if exists: continue`). This ensures `weak_evidence_log` is populated on every aggregation run, including idempotent reruns on dates with existing entity_mentions.
- **All `weak_evidence_log` rows are valid for PV-008 evaluation** (0 rows existed before migration 053 was applied).

**Observation run 1 — 2026-05-19 (aggregation run for 2026-05-18 data) — DIAGNOSTIC ONLY (pre-B1-fix scorer):**

```
Total rows: 182
would_suppress=False (pass):  53
would_suppress=True (suppress): 129

Score distribution:
  ≥0.8:  1   (1 row: Jo Malone — highest confidence, brand+context present)
  0.6-0.8: 43
  0.5-0.6:  9
  0.3-0.5: 62
  <0.3:    67

avg=0.4172  min=0.04  max=0.84
would_suppress rate: 70.9% (129/182)

Top True Positive suppressions (note/ingredient names — d3_raw=0.8, correct):
  Black Tea (Demeter)         score=0.04  d1=0.0 d2=0.0 d3=0.8
  Egyptian Musk (Kuumba Made) score=0.04  d1=0.0 d2=0.0 d3=0.8
  Golden Amber (Floris)       score=0.04  d1=0.0 d2=0.0 d3=0.8
  Cotton Flower (Giardino B.) score=0.04  d1=0.0 d2=0.0 d3=0.8
  Dark Patchouli (Scent BTHS) score=0.09  d1=0.0 d2=0.2 d3=0.8
  Frankincense & Myrrh        score=0.13  d1=0.0 d2=0.0 d3=0.8
  Black Pepper (Demeter)      score=0.20  d1=0.0 d2=0.0 d3=0.0
  Earl Grey (Teone Reinthal)  score=0.20  d1=0.0 d2=0.0 d3=0.0

Top passing entities:
  Jo Malone (Jo Malone)       score=0.84  (brand in alias + fragrance context)
  Killer Queen (Katy Perry)   score=0.74
  Rasasi Hawas (Rasasi)       score=0.74
  Paco Rabanne 1 Million      score=0.70
```

**Cool Water watchlist observation (run 1, pre-B1 fix):**
- `Cool Water Parfum` scored 0.29 → would_suppress=True (false suppression — concentration-suffix failure, logged as PV-008-B1)
- `Cool Water` (Davidoff main entity) not present in this run's data — no RS rows for 2026-05-18 content

**False suppression pattern (PV-008-B1 — documented, now RESOLVED):**
- `Creed Aventus Eau de Parfum`: score=0.29 (2 rows), 0.34 (2 rows), all would_suppress=True → fixed in `f067364`
- Root cause: full concentration-suffix phrase not found in source text → D1=0.0 → score≈0.29
- Fixed by suffix-strip fallback in `_find_alias_position()`. See PV-008-B1 section below for full before/after.

---

### PV-008 Supplemental: 2026-05-18 Evening Pipeline Failure Audit

**Audit date:** 2026-05-19 · **Verdict: REPAIR-COMPLETE**

**Root cause of evening failure:**
1. Migration 052 defined `weak_evidence_log.content_item_id` as UUID type.
2. All `resolved_signals.content_item_id` values are YouTube video IDs (11-char strings, e.g. "kh8zbwoRHN0") — not UUIDs.
3. On 2026-05-18 evening, `_write_mentions()` called `_upsert_weak_evidence_log()` → INSERT hit `InvalidTextRepresentation` error.
4. Without SAVEPOINT isolation (fix not yet deployed), psycopg2 connection entered `InFailedSqlTransaction` state.
5. All subsequent EntityMention INSERTs in the session aborted — 0 entity_mentions written by the evening pipeline.
6. No entity_timeseries_daily rows written for 2026-05-18 by the evening pipeline.
7. Pipeline health check either not reached or failed to persist (lingering failed transaction state); no `run_label='evening'` row in `pipeline_health_log` for 2026-05-18.

**Repair path:**
- 2026-05-19: Migration 053 applied (UUID→TEXT), SAVEPOINT fix (`2203d61`) deployed, score-before-dedup reorder (`fa50e55`) deployed.
- Manual aggregation rerun for 2026-05-18 — all data layers written correctly.
- Signal detection ran on next pipeline cycle — signals for 2026-05-18 written.

**SQL-backed verification table (all queried 2026-05-19 from production):**

| Layer | Value | Status |
|-------|-------|--------|
| Content ingested — YouTube | 694 items | ✓ |
| Content ingested — Reddit | 194 items | ✓ |
| RS rows for 2026-05-18 content | 888 rows | ✓ |
| entity_mentions (occurred_at=2026-05-18, perfume) | 183 rows | ✓ written by manual rerun |
| entity_timeseries_daily (2026-05-18, perfume active>0) | 137 rows | ✓ |
| entity_timeseries_daily (2026-05-18, brand active>0) | 98 rows | ✓ |
| signals (2026-05-18) | 4 (breakout:2, acceleration_spike:2) | ✓ |
| weak_evidence_log (first clean snapshot) | 182 rows, 70.9% would_suppress | ✓ |
| pipeline_health_log (evening, 2026-05-18) | ABSENT | ops log gap only — not a data gap |

**Ops log gap (pipeline_health_log evening entry):** This is the only missing artifact. No entity scores, timeseries, signals, or public API output is affected. The morning entry exists (`run_label='morning', level='CRITICAL', em=7, reddit=0, 2026-05-18 11:24 UTC`). The missing evening entry is an observability gap only — does not affect any downstream data or user-facing output.

**VERDICT: REPAIR-COMPLETE — 2026-05-18 evening failure left no remaining data/reporting gap.**

---

### PV-008-B1 — Concentration-Suffix False Suppression Risk (Active-Mode Blocker)

**Status: RESOLVED — fix-verification confirmed 2026-05-19 (commit f067364)**

**Problem:** Entities with a concentration suffix in their canonical name (e.g. "Creed Aventus Eau de Parfum", "Cool Water Parfum") are systematically false-suppressed by the evidence gate in shadow mode. If the gate were activated, these resolutions would be suppressed despite being legitimate product mentions.

**Root cause (technical):**
- All production `resolved_signals` rows have `alias_used=""` (empty string) — the resolver does not write the matched alias back to RS JSON.
- The D4 corrective patch (`2181ff5`) sets `alias_norm_for_d4 = _normalize(alias_used)` → empty string → D4=0.0.
- For position finding (D1/D2/D3), the fallback `position_alias_norm = _normalize(alias_used or canonical_name)` resolves to the full canonical name with suffix, e.g. `"creed aventus eau de parfum"`.
- `_find_alias_position()` searches for this full phrase in source `matched_from` text (e.g. `"creed aventus review"`). The suffix is absent in the source text → `match_pos=None`.
- With `match_pos=None`: D1=0.0 (no brand proximity window to evaluate), D2 scores the whole text but often finds 0 fragrance tokens in a short `matched_from` field, score ≈ D5 contribution only = 0.29.

**Observed instances in run 1 (2026-05-18 data):**
| Entity | Rows | Score range | would_suppress |
|--------|------|-------------|----------------|
| Creed Aventus Eau de Parfum | 4 | 0.29–0.34 | True (all 4) |
| Cool Water Parfum | 1 | 0.29 | True |

**Why this blocks active activation:** Activating the gate at current threshold=0.5 would suppress legitimate mentions for Creed Aventus Eau de Parfum and other EDP/Extrait variants in every pipeline run. These are unambiguously real product resolutions; suppressing them would cause systematic under-counting of mention-volume entities with concentration-specific tracking.

**Three repair directions (design note — no code):**

**Direction 1 — Suffix-strip fallback in `_find_alias_position()` (recommended first step)**
After the primary lookup fails, attempt a second lookup using `_base_name(canonical_name)` (strip concentration suffixes identically to how aggregation normalizes entity names). If the stripped form is found, use that position for D1/D2/D3 window calculation.
- Risk: low — invoked only when primary fails; uses existing suffix-list already in `aggregate_daily_market_metrics.py`
- Accuracy: D1/D2/D3 would score against "creed aventus" position → brand token "creed" within window → D1≈0.8
- Preserves D4=0 (no alias credit) — still conservative on alias quality
- No RS format change required; no migration

**Direction 2 — Populate `alias_used` in resolver output (correct long-term fix)**
The resolver has the matched alias at resolution time (it's in `_resolve_phrase()`). Pass the matched alias through to `resolved_signals.resolved_entities_json` as the `alias_used` field. This would fix both D4 and position finding for all entities, not just concentration variants.
- Risk: medium — requires resolver output format change + re-resolving historical RS rows (or accepting blank D4 for historical rows)
- Accuracy: best-quality fix, eliminates all alias_used=None false suppression systematically
- Requires RS JSON schema addition + resolver change + downstream consumers updated

**Direction 3 — Base-name lookup in entity_mentions dedup check (targeted hedge)**
When `_find_alias_position()` returns None and the canonical name contains a suffix, try resolving the position using the base-name form. If successful, mark the entity as `evidence_confidence='medium'` (new tier between high/low) and exempt from suppression.
- Risk: low — purely additive; introduces a third evidence tier
- Accuracy: conservative — doesn't inflate score, just prevents false suppression for a specific failure mode
- Requires schema change: add `'medium'` as a valid `evidence_confidence` value; update aggregation logic

**Required before active-mode activation: Direction 1 must be implemented and verified in shadow mode.**

**PV-008-B1-FIX1 IMPLEMENTED — fix-verification complete (2026-05-19):**
- Commit: `f067364` — `fix: PV-008-B1-FIX1 — concentration-suffix fallback in _find_alias_position`
- Tests: 74/74 pass (11 new `TestB1Fix` tests: S1–S5 unit, I1–I2 integration)
- Fix-verification rerun: manual aggregation for 2026-05-18 after deploy

**Pre-fix baseline (run 1, 2026-05-19, diagnostic only):**
```
total=182  pass=53   suppress=129  avg=0.4172  min=0.04  max=0.84
bands: <0.3:67  0.3-0.5:62  0.5-0.6:9  0.6-0.8:43  >=0.8:1
Creed Aventus Eau de Parfum (4 rows): score 0.29–0.34, all would_suppress=True, all D1=0.0
Cool Water Parfum (1 row): score=0.29, would_suppress=True, D1=0.0
```

**Post-fix results (fix-verification rerun for 2026-05-18):**
```
total=182  pass=79   suppress=103  avg=0.4647  min=0.04  max=0.84
bands: <0.3:58  0.3-0.5:45  0.5-0.6:5  0.6-0.8:73  >=0.8:1
Creed Aventus Eau de Parfum (4 rows): score 0.64–0.69, all would_suppress=False ✓ D1=1.0
Cool Water Parfum (1 row): score=0.64, would_suppress=False ✓ D1=1.0
```

- Creed Aventus EDP: "creed aventus" found via suffix-strip → D1=1.000 ("creed" within ±15 tokens) ✓
- Cool Water Parfum: "cool water" found via suffix-strip → D1=1.000 ("davidoff" in source proximity for this content item) ✓
- Net change: 26 fewer false suppressions; avg score +0.047; 0.6–0.8 band: 43 → 73 rows

**Activation-evaluation window note:**
- Observation run 1 (2026-05-19, 2026-05-18 data): diagnostic only — pre-B1-fix scorer
- Fix-verification rerun (2026-05-19, 2026-05-18 date): post-fix correction, not a clean observation run
- **First clean activation-evaluation run** = first normal pipeline run AFTER Railway deploy of `f067364` completes
- Activation-evaluation window: ≥7 consecutive clean runs from that point

---

**Four prerequisites for active-mode activation (ALL must be complete first):**

1. **PV-008-B1 resolved — Concentration-Suffix False Suppression** (see above):
   - Direction 1 (suffix-strip fallback) implemented and verified in shadow mode ✓ **RESOLVED 2026-05-19**
   - Creed Aventus Eau de Parfum: would_suppress=False, score=0.64–0.69 ✓
   - Cool Water Parfum: would_suppress=False, score=0.64 ✓

2. **Men's Cologne guard + repair** (separate task — RES-AMB5 / SIG-QA1-REPAIR-2):
   - Entity: Men's Cologne (Coty) — entity_id prefix `c6b0eee2` — Type G category descriptor
   - Confirmed: 17 mentions, 41 ts rows, 9 signals; 0% RS brand context
   - Required: add `"men s cologne"` to `_AMBIGUOUS_PHRASE_GUARD` requiring `{"coty"}` proximity; full-history RS strip; delete entity_mentions/ts/signals
   - **Do NOT activate gate before this repair is complete.** The gate would write evidence_confidence=low for Men's Cologne mentions but they would still be written in shadow mode. Once active, they'd be suppressed — but Men's Cologne existing data in entity_mentions would remain until repair runs.

3. **Shadow observation (≥7 pipeline runs)**:
   - Monitor `weak_evidence_log` distribution: would_suppress rate by entity, brand, score band
   - Specifically monitor: Cool Water (Davidoff) — standalone fragrance that may score below threshold if "davidoff" is absent in review text. Legitimate passes are expected; consistent fails require guard tuning.
   - Check: no well-established entities (≥50 mentions, score ≥60 on dashboard) consistently scoring below 0.5 without brand context

4. **Founder review and explicit active-mode approval**:
   - Review shadow log report (to be produced by Claude after ≥7 runs)
   - Confirm threshold calibration acceptable
   - Explicit approval via session instruction

**Shadow observation SQL (run after ≥7 pipeline runs):**

```sql
-- Overall shadow summary
SELECT
    would_suppress,
    COUNT(*) AS count,
    AVG(score::numeric) AS avg_score,
    MIN(score::numeric) AS min_score,
    MAX(score::numeric) AS max_score
FROM weak_evidence_log
GROUP BY would_suppress
ORDER BY would_suppress;

-- Top suppressed entities by count
SELECT entity_canonical_name, entity_brand_name, COUNT(*) AS suppress_count, AVG(score::numeric) AS avg_score
FROM weak_evidence_log
WHERE would_suppress = true
GROUP BY entity_canonical_name, entity_brand_name
ORDER BY suppress_count DESC LIMIT 30;

-- Cool Water / Davidoff watchlist (check score distribution)
SELECT pipeline_run_date, score, would_suppress, features_json
FROM weak_evidence_log
WHERE entity_canonical_name = 'Cool Water'
ORDER BY pipeline_run_date DESC;

-- Score distribution bands
SELECT
    CASE
        WHEN score < 0.3 THEN 'very_low'
        WHEN score < 0.5 THEN 'low'
        WHEN score < 0.7 THEN 'medium'
        ELSE 'high'
    END AS band,
    COUNT(*) AS count
FROM weak_evidence_log
GROUP BY band ORDER BY band;
```

**Pass criteria for shadow review (ALL must hold before active-mode activation):**
- `would_suppress=true` rate is within expected range (10–25% of perfume entity resolutions)
- Cool Water / Davidoff: majority of rows have `would_suppress=false` OR score distribution is stable and not trending toward false suppression
- No well-established entity (dashboard score ≥60, ts_rows ≥30) shows consistent `would_suppress=true` across multiple runs
- Men's Cologne repair is complete (RS=0, entity_mentions=0, ts=0)
- Founder review complete

**On completion:** Update SIG-QA2 status in CLAUDE.md to `COMPLETE — PRODUCTION VERIFIED`. Close this entry.

---

### PV-008 Supplemental — RES-AMB-FIVE Shadow-Confirmed FP Catch (2026-05-19)

**Bruno Fazzolari Five false breakout — founder-confirmed Class 1 False Identity.**

**Classification:** PRE-GATE LEGACY POLLUTION. SIG-QA2 was NOT deployed when these 26 entity_mentions were written (all evidence_confidence=legacy_unscored). The gate would catch new resolutions today (score ≈0.29–0.35 < threshold=0.5 → would_suppress=True) — this is a shadow-confirmed FP catch. It is NOT a gate scoring failure.

**Root cause:** Bare alias `'five'` (resolver_aliases id=12495, entity_id=2971, exact match) stored for "Bruno Fazzolari Five Eau de Parfum". Matched generic counting/ordinal language.

**Confirmed RS evidence (26 rows, 0% brand context):**
- "my stepfather came in when i was five years old" (wedding Reddit)
- "Five summer colognes under 50$!" (counting fragrances)
- "FIVE DOLLARS at 5 below" (price)
- "five in the morning and five later in the day" (spray cadence — MFK content)
- "it doesn't make me look like i'm five years older" (hair dye video — not fragrance)
- "Five Star Fragrances" (star-rating expression)

**Repair applied (2026-05-19) — COMPLETE:**

| Layer | Count |
|-------|-------|
| RS rows stripped | 26 |
| entity_mentions deleted | 26 |
| entity_timeseries_daily (perfume) deleted | 41 |
| signals (perfume) deleted | 12 |
| signal_intelligence_snapshots deleted | 0 |
| brand ts deleted | 49 |
| brand signals deleted | 12 |

- RS residual (`resolved_entities_json LIKE '%Bruno Fazzolari Five%'`): **0** ✓
- Single brand entity: "Bruno Fazzolari" — only tracked perfume was "Five" → all brand rows were 100% false → deleted.
- Bare alias deleted from `resolver_aliases` (id=12495) ✓
- `"five"` added to `_BLOCKED_SINGLE_WORD_ALIASES` (commit `1678158`) ✓
- 5 new tests (F1-F5) in `TestRESAMBFive` — 52/52 pass ✓

**Resolver protection:** `"five"` is now in `_BLOCKED_SINGLE_WORD_ALIASES` — unconditional block. Branded multi-token alias `"bruno fazzolari five"` resolves correctly (multi-token, unaffected by blocklist).

**OPS-PV1 Repair-Complete Rule status:** RS stripped (0 residual) + all downstream deleted. No aggregation recompute needed — dates affected have no RS rows and will produce no new mentions.

**UI verification (2026-05-19):**
- Bruno Fazzolari Five: absent from Dashboard Top Movers ✓
- Bruno Fazzolari brand: absent as false breakout brand ✓
- Dashboard movers count: 2769 → 2767 (2 polluted market entries removed, consistent with perfume + brand entity cleanup) ✓

**Production verification mode: IMMEDIATE — VERIFIED (2026-05-19)**
**Operational verdict: RES-AMB-FIVE — REPAIR-COMPLETE — PRODUCTION/UI VERIFIED**

---

## Ledger Status Summary

| ID | Phase | Status | Trigger |
|----|-------|--------|---------|
| PV-001 | P3.1 Health Log persistence | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` | CLOSED — manually recovered same night |
| PV-002 | FTG-5 / SN1-A snapshots | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` | CLOSED — 134 snapshots written in manual recovery |
| PV-003 | May 16 incident root-cause | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` | CLOSED |
| PV-004 | DATA4-B brand promotion guard + repair | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` | CLOSED |
| PV-005 | RES-AMB4 brand recompute — 5 mixed brands | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` | Next morning/evening pipeline run |
| PV-006 | SIG-QA1-REPAIR UI/API verification — 5 FP entities + brand cleanup | `IMPLEMENTED — AWAITING UI VERIFICATION` | Railway deploy of `b765377` + operator UI smoke test |
| PV-007 | SIG-ID1 production deploy — migration 051, Amber Elixir repair, harvest backfill | `COMPLETE — PRODUCTION VERIFIED (2026-05-18)` | CLOSED |
| PV-008 | SIG-QA2 shadow mode observation — migrations 052+053, evidence gate, weak_evidence_log | `IMPLEMENTED — SHADOW MODE PENDING PRODUCTION OBSERVATION` | PV-008-B1 RESOLVED (f067364, 2026-05-19). RES-AMB-FIVE shadow-confirmed catch documented (legacy pollution, not gate failure). Activation-evaluation window: ≥7 clean runs from next pipeline after B1-fix deploy. Remaining prerequisites: Men's Cologne guard+repair + shadow review + founder approval. Post-fix: pass=79, suppress=103, avg=0.4647. |
