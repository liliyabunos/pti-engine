from __future__ import annotations

"""
SQLAlchemy engine + session factory for the Market Engine.

URL resolution order:
  1. DATABASE_URL environment variable  (PostgreSQL in production)
  2. PTI_DB_PATH environment variable   (SQLite file path, dev/test)
  3. Default: sqlite:///outputs/pti.db
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _build_url(url_or_path: str) -> str:
    """Normalise a path or URL into a SQLAlchemy connection string."""
    if "://" in url_or_path:
        return url_or_path
    return f"sqlite:///{url_or_path}"


def _make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def get_database_url() -> str:
    """Return the active database URL from environment variables.

    URL resolution order:
      1. DATABASE_URL env var  → Postgres in production (Railway / Render / Fly)
      2. PTI_DB_PATH env var   → SQLite file path for local dev
      3. Default               → sqlite:///outputs/pti.db (local dev fallback)

    Railway quirk: the Postgres plugin exports DATABASE_URL with the legacy
    ``postgres://`` scheme prefix. SQLAlchemy 1.4+ requires ``postgresql://``.
    This function normalises the prefix so the engine is always created correctly.
    """
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        # Normalise Railway's legacy postgres:// → postgresql://
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://"):]
        return db_url
    path = os.environ.get("PTI_DB_PATH", "outputs/pti.db")
    return _build_url(path)


def make_session_factory(url_or_path: str) -> sessionmaker:
    engine = _make_engine(_build_url(url_or_path))
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session_factory() -> sessionmaker:
    """Return a session factory bound to the configured database."""
    engine = _make_engine(get_database_url())
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a managed SQLAlchemy session."""
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
