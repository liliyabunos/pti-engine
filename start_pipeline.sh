#!/bin/sh
# Full pipeline run: ingest → aggregate → detect signals
# Designed to be called by Railway cron services or manually.
#
# Environment variables required:
#   DATABASE_URL       Railway Postgres connection string
#   YOUTUBE_API_KEY    YouTube Data API v3 key
#
# Optional overrides:
#   INGEST_YT_MAX_RESULTS      (default: 50)
#   INGEST_YT_LOOKBACK_DAYS    (default: 2)
#   INGEST_REDDIT_LOOKBACK_DAYS (default: 1)

set -e

# Hard timeout: if any step hangs beyond its limit, kill it and exit non-zero.
# Railway will mark the execution as failed and not leave it stuck forever.
STEP_TIMEOUT=3600  # 1 hour per step (ingestion is the longest)

TODAY=$(date -u +%Y-%m-%d)
echo "[pipeline] Starting full pipeline run for date=$TODAY"
echo "[pipeline] DATABASE_URL backend: ${DATABASE_URL:+postgres (set)} ${DATABASE_URL:-MISSING - will fallback to SQLite}"
echo "[pipeline] Step timeout: ${STEP_TIMEOUT}s per step"

# Step 0: Reset resolved_signals sequence to prevent pkey conflicts on rerun
echo "[pipeline] Step 0 — Reset sequence"
timeout "$STEP_TIMEOUT" python3 scripts/reset_sequence.py

# Step 1: Ingest all sources (YouTube + Reddit)
echo "[pipeline] Step 1 — Ingestion"
timeout "$STEP_TIMEOUT" python3 -m perfume_trend_sdk.jobs.run_ingestion \
  --max-results "${INGEST_YT_MAX_RESULTS:-50}" \
  --lookback-days "${INGEST_YT_LOOKBACK_DAYS:-2}"

# Step 1a: Channel polling — poll due YouTube channels (adaptive gating via next_poll_after)
echo "[pipeline] Step 1a — YouTube channel polling"
timeout 600 python3 scripts/ingest_youtube_channels.py --limit 50 || \
  echo "[pipeline] WARNING: ingest_youtube_channels failed or timed out — continuing"

# Step 1b: Aggregate and classify discovery candidates (Phase 3A → 3B)
echo "[pipeline] Step 1b — Aggregate candidates"
timeout 600 python3 -m perfume_trend_sdk.jobs.aggregate_candidates || \
  echo "[pipeline] WARNING: aggregate_candidates failed — continuing"
echo "[pipeline] Step 1c — Validate candidates (Phase 3B)"
timeout 600 python3 -m perfume_trend_sdk.jobs.validate_candidates || \
  echo "[pipeline] WARNING: validate_candidates failed — continuing"

# Step 2: Aggregate daily metrics for today
echo "[pipeline] Step 2 — Aggregation for date=$TODAY"
timeout "$STEP_TIMEOUT" python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date "$TODAY"

# Step 3: Detect signals
echo "[pipeline] Step 3 — Signal detection for date=$TODAY"
timeout "$STEP_TIMEOUT" python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date "$TODAY"

# Step 4: Verify state (non-blocking — log failures but don't abort)
echo "[pipeline] Step 4 — Market state verification"
timeout 300 python3 -m perfume_trend_sdk.jobs.verify_market_state || \
  echo "[pipeline] WARNING: verify_market_state reported issues — check logs"

# Step 4b: Topic/Query Intelligence (Phase I5/I6) — extract new topics, rebuild links
echo "[pipeline] Step 4b — Topic extraction + entity link rebuild (Phase I5/I6)"
timeout 600 python3 -m perfume_trend_sdk.jobs.extract_entity_topics --rebuild-links || \
  echo "[pipeline] WARNING: extract_entity_topics failed — continuing"

# Step 4c: Emerging signals extraction (Phase E3-E) — refresh channel-aware emerging candidates
echo "[pipeline] Step 4c — Emerging signals extraction (Phase E3-E)"
timeout 300 python3 -m perfume_trend_sdk.jobs.extract_emerging_signals --days 7 || \
  echo "[pipeline] WARNING: extract_emerging_signals failed or timed out — continuing"

# Step 5: Coverage maintenance (Phase 5) — runs morning-only, non-blocking
echo "[pipeline] Step 5 — Coverage maintenance (stale + metadata detection + runner)"
timeout 300 python3 -m perfume_trend_sdk.jobs.detect_stale_entities --stale-days 14 || \
  echo "[pipeline] WARNING: detect_stale_entities failed — continuing"
timeout 300 python3 -m perfume_trend_sdk.jobs.detect_metadata_gaps || \
  echo "[pipeline] WARNING: detect_metadata_gaps failed — continuing"
timeout 300 python3 -m perfume_trend_sdk.jobs.run_maintenance --limit 20 || \
  echo "[pipeline] WARNING: run_maintenance failed — continuing"

# Step 5b: YouTube channel auto-discovery (Phase G3-C) — promote new channels from content history
echo "[pipeline] Step 5b — YouTube channel auto-discovery (Phase G3-C)"
timeout 180 python3 scripts/discover_youtube_channels.py --apply --limit 100 \
  --min-avg-views 1000 --min-videos 2 || \
  echo "[pipeline] WARNING: discover_youtube_channels failed — continuing"

echo "[pipeline] Pipeline complete for date=$TODAY"
