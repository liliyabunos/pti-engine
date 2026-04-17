from __future__ import annotations

"""
FastAPI shared dependencies.

DATABASE_URL resolution order:
  1. DATABASE_URL env var  (PostgreSQL in production)
  2. PTI_DB_PATH env var   (SQLite file path, converted automatically)
  3. Default: sqlite:///outputs/pti.db
"""

from typing import Generator

from sqlalchemy.orm import Session

from perfume_trend_sdk.db.market.session import (
    get_database_url,
    make_session_factory,
)
from perfume_trend_sdk.storage.market.sqlite_store import MarketStore


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a managed SQLAlchemy session.

    Schema is managed exclusively by Alembic (run via start.sh before uvicorn).
    Commit on success, rollback on error, always close.
    """
    url = get_database_url()
    factory = make_session_factory(url)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_market_store() -> MarketStore:
    """Return a MarketStore bound to the configured database.

    Used by routes that still use the MarketStore abstraction. New routes
    should use get_db_session() + ORM queries directly.
    """
    store = MarketStore(get_database_url())
    store.init_schema()
    return store
