FROM python:3.11-slim

WORKDIR /app

# Copy only what the backend needs — deliberately exclude frontend/
COPY pyproject.toml .
COPY perfume_trend_sdk/ perfume_trend_sdk/
COPY alembic/ alembic/
COPY alembic.ini .

# Install the package and all declared dependencies
RUN pip install --no-cache-dir .

# Non-root user
RUN useradd -m -u 1000 pti
USER pti

EXPOSE 8000

# Railway injects $PORT at runtime. The CMD is the fallback when
# railway.toml startCommand is not set (e.g. local docker run).
CMD ["sh", "-c", "alembic upgrade head 2>&1 || true && uvicorn perfume_trend_sdk.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
