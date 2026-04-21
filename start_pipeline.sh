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

# ── Resolver volume init + catalog bootstrap ─────────────────────────────────
# RESOLVER_DB_PATH points to a Railway Volume mount (persistent across deploys).
# On first run the volume is empty — copy the git-tracked seed (2,245 perfumes)
# then bootstrap the kaggle_v1 catalog (53k perfumes).
# Subsequent runs SKIP the bootstrap instantly (guard: kaggle_v1 rows > 0).
if [ -n "${RESOLVER_DB_PATH:-}" ]; then
  mkdir -p /app/resolver-vol
  chmod -R 777 /app/resolver-vol
  if [ ! -f "$RESOLVER_DB_PATH" ]; then
    echo "[pipeline] Resolver volume empty — copying seed DB from repo..."
    cp data/resolver/pti.db "$RESOLVER_DB_PATH"
    echo "[pipeline] Seed copied"
  fi
  echo "[pipeline] Resolver bootstrap — catalog check"
  timeout 1800 python3 scripts/bootstrap_resolver_catalog.py || \
    echo "[pipeline] WARNING: bootstrap_resolver_catalog failed — continuing with existing resolver"
else
  echo "[pipeline] RESOLVER_DB_PATH not set — using git-tracked data/resolver/pti.db"
fi

# Step 0: Reset resolved_signals sequence to prevent pkey conflicts on rerun
echo "[pipeline] Step 0 — Reset sequence"
timeout "$STEP_TIMEOUT" python3 scripts/reset_sequence.py

# Step 1: Ingest all sources (YouTube + Reddit)
echo "[pipeline] Step 1 — Ingestion"
timeout "$STEP_TIMEOUT" python3 -m perfume_trend_sdk.jobs.run_ingestion \
  --max-results "${INGEST_YT_MAX_RESULTS:-50}" \
  --lookback-days "${INGEST_YT_LOOKBACK_DAYS:-2}"

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

echo "[pipeline] Pipeline complete for date=$TODAY"
