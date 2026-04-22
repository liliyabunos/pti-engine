FROM python:3.11-slim

WORKDIR /app

# curl-cffi requires libcurl + SSL libs (available in slim already for most)
# Keep this minimal — curl_cffi wheels bundle libcurl statically for Linux
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
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
