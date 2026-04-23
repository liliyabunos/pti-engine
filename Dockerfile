FROM python:3.11-slim

WORKDIR /app

# System deps: minimal set needed before pip + playwright install-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Copy only what the backend needs — deliberately exclude frontend/
COPY pyproject.toml .
COPY perfume_trend_sdk/ perfume_trend_sdk/
COPY alembic/ alembic/
COPY alembic.ini .
COPY start.sh .
COPY start_pipeline.sh .
COPY start_pipeline_evening.sh .

# Ingestion scripts and config watchlists
COPY scripts/ scripts/
COPY configs/ configs/

# Install the package and all declared dependencies
RUN pip install --no-cache-dir .

# Install Playwright Chromium + its system deps (handles Bookworm package renames automatically).
# Use inline env var so Railway cannot blank it out via service env settings.
RUN PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 -m playwright install --with-deps chromium \
 && chmod -R o+rx /ms-playwright

# Make start scripts executable
RUN chmod +x start.sh start_pipeline.sh start_pipeline_evening.sh

# Runtime directories that jobs write into (raw payloads, unmapped log)
RUN mkdir -p data/raw outputs

# Non-root user — must own writable runtime directories
RUN useradd -m -u 1000 pti && \
    chown -R pti:pti data/ outputs/

USER pti

EXPOSE 8000

CMD ["sh", "start.sh"]
