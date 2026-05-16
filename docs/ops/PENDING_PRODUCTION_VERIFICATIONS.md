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
| **Trigger event** | Tonight's 23:00 UTC evening pipeline (2026-05-16) |
| **Blocking severity** | High — P3.1 has been marked COMPLETE — PRODUCTION VERIFIED in CLAUDE.md incorrectly since 2026-05-12. Cannot restore that status until persistence is confirmed. |

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
| **Current status** | `READY TO VERIFY` |
| **Immediate verification considered?** | Yes — this is the immediate verification. Does not require waiting for any pipeline. |
| **Why deferred** | Not deferred — added to ledger as READY TO VERIFY because it cannot be closed without production SQL evidence. DB access required (Railway production). |
| **Trigger event** | None — can run now. |
| **Blocking severity** | Medium — incident cannot be formally closed without confirming or refuting the backfill artifact explanation. |

**Hypothesis to confirm or refute:**
> entity_mentions=17 on May 16 morning was caused by YouTube first-poll backfill:
> 362 canonical_content_items were collected with `collected_at = 2026-05-16`,
> but most had `published_at` from earlier dates.
> Health check counts `entity_mentions WHERE DATE(occurred_at) = '2026-05-16'`
> and `occurred_at = published_at`, so only items published today counted.

**Exact verification SQL:**
```sql
-- Q1: Distribution of published_at for YouTube items collected on 2026-05-16
-- CONFIRM: most items were published before May 16
SELECT
    DATE(published_at::timestamptz) AS published_day,
    COUNT(*) AS items_count
FROM canonical_content_items
WHERE source_platform = 'youtube'
  AND DATE(collected_at::timestamptz) = '2026-05-16'
GROUP BY published_day
ORDER BY published_day DESC;

-- Q2: Distribution of occurred_at in entity_mentions around the incident
-- CONFIRM: only ~17 mentions land on 2026-05-16
SELECT
    DATE(occurred_at) AS mention_day,
    COUNT(*) AS mentions
FROM entity_mentions
WHERE DATE(occurred_at) >= '2026-05-13'
GROUP BY mention_day
ORDER BY mention_day DESC;

-- Q3: May 15 vs May 16 side-by-side item counts (baseline comparison)
SELECT
    DATE(collected_at::timestamptz) AS collection_day,
    source_platform,
    COUNT(*) AS items_collected
FROM canonical_content_items
WHERE DATE(collected_at::timestamptz) IN ('2026-05-15', '2026-05-16')
GROUP BY collection_day, source_platform
ORDER BY collection_day DESC, source_platform;

-- Q4: Reddit items on May 16 (confirm truly zero, not a date issue)
SELECT COUNT(*) AS reddit_items_may16
FROM canonical_content_items
WHERE source_platform = 'reddit'
  AND collected_at::timestamptz >= '2026-05-16T00:00:00Z'
  AND collected_at::timestamptz < '2026-05-17T00:00:00Z';
```

**Pass criteria (hypothesis CONFIRMED if all pass):**
- Q1: `published_day = '2026-05-16'` row shows significantly fewer items than older dates (e.g., fewer than 30 items published today out of 362 collected)
- Q2: `mention_day = '2026-05-16'` shows approximately 17 mentions; prior days show normal volume (150–250)
- Q3: May 16 shows higher YouTube collection volume than May 15 (confirming active channel polling), with reddit=0 on May 16
- Q4: `reddit_items_may16 = 0` (confirms Reddit truly produced nothing, not a date-bucketing issue)

**If hypothesis is REFUTED (Q1 shows most items published today):**
- The collapse was NOT a backfill artifact
- Resolver failure or ingestion quality issue must be investigated separately
- Update the incident notes in CLAUDE.md accordingly

**CLAUDE.md update after resolution:**
- Update the May 16 incident OPS NOTE with confirmed or refuted root cause and evidence
- Close this ledger entry

---

## Closed Entries

*(none yet)*

---

## Ledger Status Summary

| ID | Phase | Status | Trigger |
|----|-------|--------|---------|
| PV-001 | P3.1 Health Log persistence | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` | Tonight 23:00 UTC |
| PV-002 | FTG-5 / SN1-A snapshots | `IMPLEMENTED — AWAITING PIPELINE VERIFICATION` | Next healthy pipeline (signals > 10) |
| PV-003 | May 16 incident root-cause | `READY TO VERIFY` | Now — requires production SQL |
