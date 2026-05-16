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
| **Current status** | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` |
| **Immediate verification considered?** | No — `pipeline_health_log` is only written by the health check at the end of a pipeline run. Cannot be triggered safely outside the scheduled pipeline without running the full pipeline manually. |
| **Why deferred** | Requires a successful evening or morning pipeline run to produce a row. Fix deployed before 23:00 UTC 2026-05-16. |
| **Trigger event** | Tomorrow 11:00 UTC morning pipeline (2026-05-17) |
| **Blocking severity** | High — P3.1 has been marked COMPLETE — PRODUCTION VERIFIED in CLAUDE.md incorrectly since 2026-05-12. Cannot restore that status until persistence is confirmed. |
| **2026-05-16 evening run outcome** | Pipeline started 23:00 UTC (Reddit 195 items, YouTube 497 items collected at 23:02). Code deploy `8a9c7ac` at ~23:09 UTC killed the cron container before Step 2 (aggregation). `updated_at` on entity_timeseries_daily never exceeded 22:57 UTC. pipeline_health_log still 0 rows. Same incident pattern as 2026-05-06 OPS NOTE. |

**Exact verification SQL:**
```sql
-- Confirm at least one row was written by tonight's run
SELECT run_date, run_label, overall_level, entity_mentions,
       reddit_items, reddit_mentions, signals_count,
       issues, pipeline_service, recorded_at
FROM pipeline_health_log
ORDER BY recorded_at DESC
LIMIT 5;

-- Confirm issues JSONB is populated (not null)
SELECT run_date, run_label, jsonb_array_length(issues) AS issue_count, issues
FROM pipeline_health_log
ORDER BY recorded_at DESC
LIMIT 3;

-- Confirm table is no longer empty
SELECT COUNT(*) FROM pipeline_health_log;
```

**Pass criteria:**
- `COUNT(*) > 0`
- Row exists for `run_date = '2026-05-16'` and `run_label = 'evening'`
- `overall_level` is one of: OK / WARNING / CRITICAL (not null)
- `issues` column is a valid non-null JSONB array
- `pipeline_service` reflects the Railway service name (or NULL if env var not set)

**CLAUDE.md update after pass:**
- Change P3.1 active roadmap status back to `COMPLETE — PRODUCTION VERIFIED (2026-05-16)`
- Update the phase status table row
- Close this ledger entry

---

### PV-002 — FTG-5 / SN1-A Signal Intelligence Snapshots

| Field | Value |
|-------|-------|
| **Verification ID** | PV-002 |
| **Phase / task** | FTG-5 / SN1-A — Signal Intelligence Snapshots |
| **Related commits** | `79d72c8` (implementation) · migration 050 |
| **Implementation shipped** | 2026-05-16 |
| **Current status** | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` |
| **Immediate verification considered?** | Partial — migration 050 can be verified immediately (table exists, alembic version). But snapshot rows require a healthy pipeline run that produces signals. May 16 morning was anomalous (signals=3); not acceptable evidence. |
| **Why deferred** | Row-level verification requires a healthy pipeline run with normal signal volume. May 16 morning run had only 3 signals — insufficient to confirm the snapshot write path. Verify against the next run where `signals_detected > 10`. |
| **Trigger event** | Next pipeline run where `signals_detected > 10` (expected: tonight's 23:00 UTC or tomorrow morning) |
| **Blocking severity** | Medium — SN1-A is not in a user-facing path. But CLAUDE.md must not show COMPLETE — PRODUCTION VERIFIED until rows are confirmed. |

**Exact verification SQL:**
```sql
-- Step 1: Confirm migration 050 applied
SELECT version_num FROM alembic_version;
-- Expect: 050

-- Step 2: Confirm table exists and received rows
SELECT COUNT(*),
       MIN(detected_at)::date AS earliest_date,
       MAX(detected_at)::date AS latest_date,
       MIN(first_captured_at) AS first_written,
       MAX(first_captured_at) AS last_written
FROM signal_intelligence_snapshots;

-- Step 3: Confirm metrics are populated (not all NULL)
SELECT entity_canonical_name, signal_type,
       market_score_at_detection, growth_rate_at_detection,
       mention_count_at_detection, signal_strength, snapshot_schema_version,
       pipeline_run_date, first_captured_at
FROM signal_intelligence_snapshots
ORDER BY first_captured_at DESC
LIMIT 10;

-- Step 4: Confirm idempotency — rerunning detect_breakout_signals for same date
-- should not increase row count (ON CONFLICT DO NOTHING)
SELECT pipeline_run_date, COUNT(*) AS snapshots
FROM signal_intelligence_snapshots
GROUP BY pipeline_run_date
ORDER BY pipeline_run_date DESC;
```

**Pass criteria:**
- `alembic_version = '050'`
- `signal_intelligence_snapshots COUNT(*) > 0`
- At least one row has `market_score_at_detection IS NOT NULL` (metrics populated)
- `snapshot_schema_version = 1` on all rows
- `pipeline_run_date` matches `detected_at::date` on all rows

**CLAUDE.md update after pass:**
- Change FTG-5 / SN1-A status to `COMPLETE — PRODUCTION VERIFIED (YYYY-MM-DD)`
- Close this ledger entry

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

## Ledger Status Summary

| ID | Phase | Status | Trigger |
|----|-------|--------|---------|
| PV-001 | P3.1 Health Log persistence | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` | Tomorrow 11:00 UTC morning pipeline (2026-05-17) — 23:00 UTC run interrupted by code deploy |
| PV-002 | FTG-5 / SN1-A snapshots | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` | Tomorrow 11:00 UTC morning pipeline (2026-05-17) — 23:00 UTC run interrupted by code deploy |
| PV-003 | May 16 incident root-cause | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` | CLOSED |
| PV-004 | DATA4-B brand promotion guard + repair | `COMPLETE — PRODUCTION VERIFIED (2026-05-16)` | CLOSED |
