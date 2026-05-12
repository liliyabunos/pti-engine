# Data Retention Policy — FragranceIndex.ai / FTI Market Terminal

**Version:** 1.0 — DATA0 Foundation
**Date:** 2026-05-12
**Phase:** DATA0 — Historical Integrity & Metric Versioning

---

## 1. Purpose

This document defines what data is kept, for how long, and why — grounded in:

- **Methodology integrity:** Future premium reports must be able to cite which formula version produced a historical score, which thresholds produced a historical signal, and what the topic/intent distribution looked like at a given point in time.
- **Report-grade history:** The Perfume Deep Dive and other REPORT1 artifacts require up to 24 months of historical data with clean methodology provenance. Premature trimming destroys this permanently.
- **Compliance discipline:** Retention decisions must be intentional. Raw source data retention is bounded by platform agreements and policy (see section 3.3).
- **Accidental cleanup prevention:** No retention job should remove data from a "keep indefinitely" table. Trimming jobs only target tables explicitly marked with a retention window below.

Any change to this policy requires explicit review and documentation. Methodology-affecting changes must be versioned (see section 4).

---

## 2. Keep Indefinitely

The following tables are **never trimmed by automated jobs.** All data in these tables is considered permanent intelligence history.

### 2.1 Core Entity Intelligence

| Table | Purpose | Why Keep |
|-------|---------|----------|
| `entity_market` | Entity identity, canonical name, brand, ticker | The permanent registry of tracked entities |
| `entity_timeseries_daily` | Daily market score, mention count, growth, trend state, formula version | The historical intelligence record; required for all report sections showing score trend |
| `signals` | Breakout, acceleration, and sustained signals with threshold version | Required for Signal Timeline section of Deep Dive; historical signals are the evidence record |
| `entity_mentions` | Raw attribution links from content items to entities | Required for Driver Attribution and Creator Concentration report sections |
| `entity_topic_snapshots` | Dated aggregate of topic/intent distribution per entity (DATA0) | Required for Intent Breakdown (IL1 section 6) and topic trend-over-time analysis |

### 2.2 Source Intelligence

| Table | Purpose | Why Keep |
|-------|---------|----------|
| `canonical_content_items` | All ingested content items (YouTube videos, Reddit posts) | Source evidence for all mentions and signals; needed for re-resolution and report evidence refs |
| `resolved_signals` | Resolver output linking content items to entities | Allows re-aggregation from raw if formula changes |
| `mention_sources` | Per-mention engagement metrics (views, likes, comments, source_score) | Required for Driver Attribution and Creator Intelligence; historical engagement is not re-fetchable |
| `source_profiles` | Creator/channel source registry | Attribution provenance for content items |
| `content_topics` | Extracted topic labels per content item | The extraction input for entity_topic_links; required for topic re-linking |
| `entity_topic_links` | Current live topic-entity associations | Active state for API/UI — rebuilt each cycle but always reflects latest complete picture |

### 2.3 Creator Intelligence

| Table | Purpose | Why Keep |
|-------|---------|----------|
| `creator_entity_relationships` | Per-creator, per-entity aggregated metrics | Required for Creator Concentration section of reports |
| `creator_scores` | Creator influence scores and tier classifications | Attribution intelligence |
| `youtube_channels` | YouTube channel registry with metadata | Source identity for creator attribution |

### 2.4 Audit and Compliance

| Table | Purpose | Why Keep |
|-------|---------|----------|
| `creator_profile_claims` | Creator claim history and verification status | Legal/compliance audit trail |
| `source_intake_audit_log` | Source intake operator actions | Operator audit trail |
| `creator_watchlist_audit_log` | Watchlist operator actions | Operator audit trail |

---

## 3. Retention Windows

The following tables have known bounded retention. Automated trim behavior is documented here.

### 3.1 Platform Operations (90 days)

| Table | Retention | Trim Mechanism |
|-------|-----------|---------------|
| `pipeline_health_log` | 90 days | Trimmed inline by `pipeline_health_check.py` on each run. Rows older than 90 days are deleted at persist time. No separate cron. |
| `emerging_signals` | 90 days rolling | `detect_emerging_signals.py` with `--days` parameter. Older rows beyond the analysis window are not explicitly trimmed — this should be reviewed and formalized before REPORT1. |

### 3.2 User-Controlled Data

| Table | Retention | Notes |
|-------|-----------|-------|
| `watchlists` / `watchlist_items` | User-lifetime | No automated trim. User delete is the only removal path. |
| `alerts` / `alert_events` | User-lifetime | No automated trim. Alert history is user-controlled. |
| `source_submissions` | Indefinite | Operator-reviewed. No automated trim. |

### 3.3 Platform Raw Data

`canonical_content_items` retains all ingested items indefinitely. This is intentional for report grade evidence. However:

- **YouTube:** The YouTube Data API v3 Terms of Service require that stored video metadata not be used beyond its stated purposes. Raw body text of comments is NOT ingested (compliance boundary v1). Video title and metadata are public record and retained for intelligence purposes.
- **Reddit:** Reddit-derived data is subject to Reddit's Data API Terms. Before commercial monetization of Reddit-derived outputs, Reddit commercial approval must be confirmed (P1 track). This does not affect the retention of already-ingested data for internal intelligence purposes.
- **Instagram (future IG1):** Retain metadata per Instagram Platform Policy. No raw comment text. Review API terms at IG1 implementation time.

---

## 4. Versioning Policy

**Rule: every derived / scored intelligence object introduced after DATA0 must carry a formula_version or equivalent field from day one.** This policy is non-negotiable for any object that may appear in premium reports.

### 4.1 Current Version Constants

| Object | Table | Version Field | Current Version | Version Source |
|--------|-------|---------------|-----------------|----------------|
| Daily market score | `entity_timeseries_daily` | `score_formula_version` | 1 | `SCORE_FORMULA_VERSION` constant in `aggregate_daily_market_metrics.py` |
| Breakout signal | `signals` | `signal_threshold_version` | 1 | `SIGNAL_THRESHOLD_VERSION` constant in `detect_breakout_signals.py` |
| Topic distribution snapshot | `entity_topic_snapshots` | `formula_version` | 1 | `TOPIC_DISTRIBUTION_VERSION` constant in `extract_entity_topics.py` |

### 4.2 Provenance Note for Existing Historical Rows

Rows in `entity_timeseries_daily` and `signals` that were written before migration 043 (DATA0) have been assigned version 1 via `server_default` in the migration. This is the baseline version. These rows predate explicit version tracking but are assigned version 1 for continuity. Future reports citing these rows should note: "Historical rows prior to 2026-05-12 are assigned baseline formula version 1."

### 4.3 When to Bump a Version

A version must be bumped when:
- The score formula changes in a way that makes old and new scores **incomparable** (e.g., a new component added, weights changed, normalization changed)
- Signal detection thresholds are tuned in a way that would produce materially different signal sets on the same data
- Topic extraction logic changes in a way that reclassifies topic_text values across large portions of the entity catalog

A version should NOT be bumped for:
- Bug fixes that make the formula more correct (document the fix; note the historical gap in methodology docs)
- Performance improvements that produce numerically identical outputs
- New entity types being added (version applies per formula, not per entity)

### 4.4 Bumping Procedure

1. Update the relevant Python constant (e.g., `SCORE_FORMULA_VERSION = 2`)
2. Write a new Alembic migration if the column definition changes
3. Document the version change in this file (section 4.1) and in the relevant architecture doc
4. Do NOT retroactively update historical rows to the new version — historical rows retain their original version to preserve comparability

### 4.5 Future Derived Objects

The following planned intelligence objects must carry `formula_version` from day one when implemented:

| Future Object | Phase | Formula Version Field |
|---------------|-------|-----------------------|
| `entity_opportunities` | IL1 | `formula_version` (specified in MONETIZATION_ARCHITECTURE.md section 9) |
| Mention-level intent classification | IL1 | `classifier_version` (to be named at IL1 time) |
| Any future aggregate or scored table | As introduced | Must include `formula_version` or equivalent |

---

## 5. Change Control

**No destructive retention change — trimming a "keep indefinitely" table, reducing a retention window, or dropping historical version data — may be introduced without:**

1. Explicit documentation of what is being removed and why
2. Update to this policy document
3. Founder-level approval if the change affects report-grade data or methodology provenance

**Schema changes that affect versioned fields (score_formula_version, signal_threshold_version, formula_version) require:**

1. Alembic migration
2. Corresponding Python constant bump
3. Update to section 4.1 of this document
4. Notation in CLAUDE.md migration table

---

*End of DATA_RETENTION_POLICY.md*
*Phase: DATA0 — Historical Integrity & Metric Versioning*
*Next phase: SEO0 — SEO Infrastructure Foundation*
