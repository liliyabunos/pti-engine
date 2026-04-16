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

TODAY=$(date -u +%Y-%m-%d)
echo "[pipeline] Starting full pipeline run for date=$TODAY"
echo "[pipeline] DATABASE_URL backend: ${DATABASE_URL:+postgres (set)} ${DATABASE_URL:-MISSING - will fallback to SQLite}"

# Step 0: Reset resolved_signals sequence to prevent pkey conflicts on rerun
echo "[pipeline] Step 0 — Reset sequence"
python3 scripts/reset_sequence.py

# Step 1: Ingest all sources (YouTube + Reddit)
echo "[pipeline] Step 1 — Ingestion"
python3 -m perfume_trend_sdk.jobs.run_ingestion \
  --max-results "${INGEST_YT_MAX_RESULTS:-50}" \
  --lookback-days "${INGEST_YT_LOOKBACK_DAYS:-2}"

# Step 2: Aggregate daily metrics for today
echo "[pipeline] Step 2 — Aggregation for date=$TODAY"
python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date "$TODAY"

# Step 3: Detect signals
echo "[pipeline] Step 3 — Signal detection for date=$TODAY"
python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date "$TODAY"

# Step 4: Verify state (non-blocking — log failures but don't abort)
echo "[pipeline] Step 4 — Market state verification"
python3 -m perfume_trend_sdk.jobs.verify_market_state || \
  echo "[pipeline] WARNING: verify_market_state reported issues — check logs"

echo "[pipeline] Pipeline complete for date=$TODAY"
