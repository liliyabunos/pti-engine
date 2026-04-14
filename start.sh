#!/bin/sh
set -x
echo "START SCRIPT"
pwd
if [ -n "$DATABASE_URL" ]; then echo "DATABASE_URL is set"; else echo "DATABASE_URL is MISSING"; fi
alembic upgrade head 2>&1
echo "ALEMBIC_EXIT=$?"
exec uvicorn perfume_trend_sdk.api.main:app --host 0.0.0.0 --port ${PORT:-8000} 2>&1
