from __future__ import annotations

"""
Central database engine / session management.

This is the single authoritative source for engine creation used by
jobs, scripts, and the postgres store layer.

URL resolution order (same as db/market/session.py):
  1. DATABASE_URL env var  — PostgreSQL in production (required when PTI_ENV=production)
  2. PTI_DB_PATH env var   — SQLite file path, converted to sqlite:///
  3. Default              — sqlite:///outputs/pti.db  (legacy, no market rows)

Production safety rules enforced here:
  - If PTI_ENV=production and DATABASE_URL is unset → RuntimeError (fail fast)
  - create_all_tables() raises RuntimeError in production (use Alembic migrations instead)

Usage in scripts / jobs::

    from perfume_trend_sdk.storage.postgres.db import get_engine, session_scope

    with session_scope() as session:
        session.execute(text("SELECT 1"))

Usage for schema creation (dev only)::

    from perfume_trend_sdk.storage.postgres.db import create_all_tables
    create_all_tables()  # raises in production — use alembic upgrade head instead
"""

import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from perfume_trend_sdk.db.market.session import _make_engine, get_database_url

logger = logging.getLogger(__name__)


def _get_env() -> str:
    """Return the normalized PTI_ENV value (default: 'dev')."""
    return os.environ.get("PTI_ENV", "dev").strip().lower()


def _is_production() -> bool:
    return _get_env() == "production"


def _resolve_database_url() -> str:
    """Resolve and validate the database URL.

    In production: DATABASE_URL is mandatory. If absent, raises RuntimeError
    immediately rather than silently falling back to SQLite.
    """
    url = get_database_url()  # applies the standard priority chain

    if _is_production():
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL is required when PTI_ENV=production. "
                "Set it to a PostgreSQL connection string, e.g.: "
                "postgresql://user:password@host:5432/pti"
            )
        if url.startswith("sqlite"):
            # Shouldn't happen given the check above, but guard explicitly.
            raise RuntimeError(
                "SQLite is not allowed in production. "
                "DATABASE_URL must be a PostgreSQL connection string."
            )

    return url


def get_engine() -> Engine:
    """Return the SQLAlchemy engine for the configured database.

    Logs the active database type at INFO level so the environment is always
    visible in process logs — prevents 'surprise SQLite' in production.
    """
    url = _resolve_database_url()
    engine = _make_engine(url)

    dialect = engine.dialect.name  # 'sqlite' | 'postgresql'
    if dialect == "postgresql":
        # Mask credentials in logs
        safe_url = url.split("@")[-1] if "@" in url else url
        logger.info("Database: PostgreSQL at %s (env=%s)", safe_url, _get_env())
    else:
        db_path = url.replace("sqlite:///", "")
        logger.info("Database: SQLite at %s (env=%s)", db_path, _get_env())

    return engine


def get_session_factory() -> sessionmaker:
    """Return a session factory bound to the configured database."""
    engine = get_engine()
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def create_all_tables() -> None:
    """Create all ORM-managed tables.

    DEVELOPMENT ONLY. Raises RuntimeError in production — use
    ``alembic upgrade head`` for controlled schema migration.
    """
    if _is_production():
        raise RuntimeError(
            "create_all_tables() is disabled in production (PTI_ENV=production). "
            "Run 'alembic upgrade head' to apply schema migrations."
        )

    from perfume_trend_sdk.db.market.models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Schema created via create_all_tables() (dev mode)")


def probe_connection() -> None:
    """Verify the database is reachable. Raises on failure.

    Call once at process startup for fail-fast behaviour.
    """
    from sqlalchemy import text

    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            f"Database connection failed ({engine.dialect.name}): {exc}"
        ) from exc


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager that yields a managed SQLAlchemy session.

    Commits on clean exit, rolls back on exception, always closes.

    Example::

        with session_scope() as db:
            db.add(entity)
    """
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
