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

TODAY=$(date -u +%Y-%m-%d)
echo "[pipeline-evening] Starting for date=$TODAY"
echo "[pipeline-evening] DATABASE_URL: ${DATABASE_URL:+postgres (set)} ${DATABASE_URL:-MISSING - will fallback to SQLite}"

# Step 0: Reset resolved_signals sequence to prevent pkey conflicts on rerun
echo "[pipeline-evening] Step 0 — Reset sequence"
python3 scripts/reset_sequence.py

# Step 1: Ingest all sources (YouTube + Reddit)
echo "[pipeline-evening] Step 1 — Ingestion"
python3 -m perfume_trend_sdk.jobs.run_ingestion \
  --max-results "${INGEST_YT_MAX_RESULTS:-50}" \
  --lookback-days "${INGEST_YT_LOOKBACK_DAYS:-2}"

# Step 2: Aggregate daily metrics for today
echo "[pipeline-evening] Step 2 — Aggregation for date=$TODAY"
python3 -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics --date "$TODAY"

# Step 3: Detect signals
echo "[pipeline-evening] Step 3 — Signal detection for date=$TODAY"
python3 -m perfume_trend_sdk.jobs.detect_breakout_signals --date "$TODAY"

echo "[pipeline-evening] Complete for date=$TODAY"
