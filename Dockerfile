FROM python:3.11-slim

WORKDIR /app

# Copy only what the backend needs — deliberately exclude frontend/
COPY pyproject.toml .
COPY perfume_trend_sdk/ perfume_trend_sdk/
COPY alembic/ alembic/
COPY alembic.ini .
COPY start.sh .
COPY start_pipeline.sh .

# Ingestion scripts and config watchlists
COPY scripts/ scripts/
COPY configs/ configs/

# Resolver catalog (fragrance_master + aliases) — static prebuilt artifact
COPY data/resolver/pti.db data/resolver/pti.db

# Install the package and all declared dependencies
RUN pip install --no-cache-dir .

# Make start scripts executable
RUN chmod +x start.sh start_pipeline.sh

# Runtime directories that jobs write into (raw payloads, unmapped log)
RUN mkdir -p data/raw outputs

# Non-root user — must own writable runtime directories
RUN useradd -m -u 1000 pti && \
    chown -R pti:pti data/ outputs/

USER pti

EXPOSE 8000

CMD ["sh", "start.sh"]
