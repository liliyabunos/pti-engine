#!/bin/sh
set -e

echo "START SCRIPT"

if [ -n "$DATABASE_URL" ]; then
  echo "DATABASE_URL is set"
else
  echo "DATABASE_URL is MISSING — aborting"
  exit 1
fi

echo "Running alembic upgrade head"
alembic upgrade head
echo "ALEMBIC_EXIT=0"

echo "Starting uvicorn"
exec uvicorn perfume_trend_sdk.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
