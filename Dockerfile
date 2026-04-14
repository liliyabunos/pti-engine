FROM python:3.11-slim

WORKDIR /app

# Copy only what the backend needs — deliberately exclude frontend/
COPY pyproject.toml .
COPY perfume_trend_sdk/ perfume_trend_sdk/
COPY alembic/ alembic/
COPY alembic.ini .
COPY start.sh .

# Install the package and all declared dependencies
RUN pip install --no-cache-dir .

# Make start script executable
RUN chmod +x start.sh

# Non-root user
RUN useradd -m -u 1000 pti
USER pti

EXPOSE 8000

CMD ["sh", "start.sh"]
