FROM python:3.11-slim

WORKDIR /app

# System dependencies for Playwright Chromium
# (installed as root before switching to non-root user)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
    libcairo2 libgdk-pixbuf2.0-0 libgtk-3-0 libx11-xcb1 libxcb-dri3-0 \
    fonts-liberation wget curl \
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

# Resolver catalog (fragrance_master + aliases) — static prebuilt artifact
COPY data/resolver/pti.db data/resolver/pti.db

# Install the package and all declared dependencies
RUN pip install --no-cache-dir .

# Install Playwright Chromium browser into a world-readable location.
# PLAYWRIGHT_BROWSERS_PATH must NOT be set here via ENV since Railway env
# overrides may blank it out — instead we install to /ms-playwright and
# set the path at runtime via the PLAYWRIGHT_BROWSERS_PATH env var in Railway,
# OR rely on the hardcoded default path below.
RUN PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 -m playwright install chromium \
 && chmod -R 755 /ms-playwright

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
