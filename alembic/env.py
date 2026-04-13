from __future__ import annotations

"""
Alembic environment — PTI SDK Market Engine migrations.

DATABASE_URL resolution order:
  1. DATABASE_URL environment variable  → used as-is (PostgreSQL in production)
  2. PTI_DB_PATH environment variable   → wrapped in sqlite:///
  3. Default: sqlite:///outputs/pti.db

Only the market engine tables (entity_market, entity_daily_snapshots,
market_signals) are managed by Alembic. Existing pipeline tables
(canonical_content_items, resolved_signals, etc.) are not touched.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the SDK importable from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import all models so Alembic autogenerate sees the full metadata.
from perfume_trend_sdk.db.market.models import (  # noqa: E402, F401
    Base,
    Brand,
    EntityMarket,
    EntityMention,
    EntityTimeSeriesDaily,
    Perfume,
    Signal,
)

# ---------------------------------------------------------------------------
# Alembic Config object
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for 'autogenerate' support — only market engine tables
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def _get_url() -> str:
    if db_url := os.environ.get("DATABASE_URL"):
        return db_url
    path = os.environ.get("PTI_DB_PATH", "outputs/pti.db")
    if "://" in path:
        return path
    return f"sqlite:///{path}"


# ---------------------------------------------------------------------------
# Offline mode (generate SQL without a live DB connection)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode (apply migrations against a live DB connection)
# ---------------------------------------------------------------------------

def run_migrations_online() -> None:
    url = _get_url()
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = url

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
