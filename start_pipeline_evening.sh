#!/bin/sh
# Evening pipeline: ingest → aggregate → detect signals
#
# Runs at 23:00 UTC via Railway cron (pipeline-evening service).
# Verify runs morning-only. Email digest runs separately at 00:00 UTC.
#
# Environment variables required:
#   DATABASE_URL       Railway Postgres connection string
#   YOUTUBE_API_KEY    YouTube Data API v3 key
#
# Optional overrides:
#   INGEST_YT_MAX_RESULTS       (default: 50)
#   INGEST_YT_LOOKBACK_DAYS     (default: 2)
#   INGEST_REDDIT_LOOKBACK_DAYS (default: 1)

set -e

# Hard timeout: if any step hangs beyond its limit, kill it and exit non-zero.
# Railway will mark the execution as failed and not leave it stuck forever.
STEP_TIMEOUT=3600  # 1 hour per step (ingestion is the longest)

TODAY=$(date -u +%Y-%m-%d)
echo "[pipeline-evening] Starting for date=$TODAY"
echo "[pipeline-evening] DATABASE_URL: ${DATABASE_URL:+postgres (set)} ${DATABASE_URL:-MISSING - will fallback to SQLite}"
echo "[pipeline-evening] Step timeout: ${STEP_TIMEOUT}s per step"

# Step 0: Reset resolved_signals sequence to prevent pkey conflicts on rerun
echo "[pipeline-evening] Step 0 — Reset sequence"
timeout "$STEP_TIMEOUT" python3 scripts/reset_sequence.py

# Step 1: Ingest all sources (YouTube + Reddit)
echo "[pipeline-evening] Step 1 — Ingestion"
timeout "$STEP_TIMEOUT" python3 -m perfume_trend_sdk.jobs.run_ingestion \
  --max-results "${INGEST_YT_MAX_RESULTS:-50}" \
  --lookback-days "${INGEST_YT_LOOKBACK_DAYS:-2}"

# Step 1a: Channel polling — poll due YouTube channels (adaptive gating via next_poll_after)
echo "[pipeline-evening] Step 1a — YouTube channel polling"
timeout 600 python3 scripts/ingest_youtube_channels.py --limit 50 || \
  echo "[pipeline-evening] WARNING: ingest_youtube_channels failed or timed out — continuing"

# Step 1b: Aggregate and classify discovery candidates (Phase 3A → 3B)
echo "[pipeline-evening] Step 1b — Aggregate candidates"
timeout 600 python3 -m perfume_trend_sdk.jobs.aggregate_candidates || \
  echo "[pipeline-evening] WARNING: aggregate_candidates failed — continuing"
echo "[pipeline-evening] Step 1c — Validate candidates (Phase 3B)"
timeout 600 python3 -m perfume_trend_sdk.jobs.validate_candidates || \
  echo "[pipeline-evening] WARNING: validate_candidates failed — continuing"

# Step 2: Aggregate daily metrics for today
echo "[pipeline-evening] Step 2 — Aggregation for date=$TODAY"
timeout "$STEP_TIMEOUT" python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date "$TODAY"

# Step 3: Detect signals
echo "[pipeline-evening] Step 3 — Signal detection for date=$TODAY"
timeout "$STEP_TIMEOUT" python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date "$TODAY"

# Step 3b: Topic/Query Intelligence (Phase I5/I6) — extract new topics, rebuild links
echo "[pipeline-evening] Step 3b — Topic extraction + entity link rebuild (Phase I5/I6)"
timeout 600 python3 -m perfume_trend_sdk.jobs.extract_entity_topics --rebuild-links || \
  echo "[pipeline-evening] WARNING: extract_entity_topics failed — continuing"

echo "[pipeline-evening] Complete for date=$TODAY"
