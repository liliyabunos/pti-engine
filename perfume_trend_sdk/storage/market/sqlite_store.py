from __future__ import annotations

"""
Market Engine Store — SQLAlchemy-backed, supports SQLite and PostgreSQL.

Used by legacy routes and tests that predate the per-route ORM refactor.
New routes should use get_db_session() + ORM queries directly.

Tables:
  entity_market           — tracked market entities (UUID PK)
  entity_timeseries_daily — daily time-series metrics (UUID entity_id)
  signals                 — detected signal events (UUID entity_id)
"""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from perfume_trend_sdk.db.market.models import (
    Base,
    EntityMarket,
    EntityTimeSeriesDaily,
    Signal,
)


def _build_url(url_or_path: str) -> str:
    if "://" in url_or_path:
        return url_or_path
    return f"sqlite:///{url_or_path}"


def _row_to_dict(obj) -> Dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


class MarketStore:
    """Manages market-engine tables via SQLAlchemy.

    Accepts a plain file path (converted to sqlite:///) or any
    SQLAlchemy-compatible URL.
    """

    def __init__(self, db_url_or_path: str) -> None:
        url = _build_url(db_url_or_path)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self._engine = create_engine(url, connect_args=connect_args)
        self._Session = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)

    def init_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # entity_market
    # ------------------------------------------------------------------

    def upsert_entity(
        self,
        *,
        entity_id: str,
        entity_type: str,
        ticker: str,
        canonical_name: str,
        created_at: Any,
    ) -> None:
        with self._Session() as session:
            if session.query(EntityMarket).filter_by(entity_id=entity_id).first() is None:
                session.add(EntityMarket(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    ticker=ticker,
                    canonical_name=canonical_name,
                    created_at=_to_datetime(created_at),
                ))
                session.commit()

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        with self._Session() as session:
            obj = session.query(EntityMarket).filter_by(entity_id=entity_id).first()
            return _row_to_dict(obj) if obj else None

    def list_entities(self) -> List[Dict[str, Any]]:
        with self._Session() as session:
            rows = session.query(EntityMarket).order_by(EntityMarket.canonical_name).all()
            return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # entity_timeseries_daily
    # ------------------------------------------------------------------

    def upsert_daily_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Insert or update a daily snapshot row.

        snapshot must include entity_id (string canonical name) — this method
        resolves it to the EntityMarket UUID before writing.
        """
        with self._Session() as session:
            em = session.query(EntityMarket).filter_by(
                entity_id=snapshot["entity_id"]
            ).first()
            if em is None:
                return  # entity must be registered first

            target_date = date.fromisoformat(str(snapshot["date"])[:10])
            entity_type = snapshot.get("entity_type", "perfume")
            existing = (
                session.query(EntityTimeSeriesDaily)
                .filter_by(entity_id=em.id, entity_type=entity_type, date=target_date)
                .first()
            )
            now = datetime.now(timezone.utc)
            cols = {c.name for c in EntityTimeSeriesDaily.__table__.columns}
            data = {
                k: v for k, v in snapshot.items()
                if k in cols and k not in ("id", "entity_id", "date", "entity_type")
            }
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
                existing.updated_at = now
            else:
                session.add(EntityTimeSeriesDaily(
                    entity_id=em.id,
                    entity_type=entity_type,
                    date=target_date,
                    created_at=now,
                    updated_at=now,
                    **data,
                ))
            session.commit()

    def get_latest_snapshot(self, entity_id: str) -> Optional[Dict[str, Any]]:
        with self._Session() as session:
            em = session.query(EntityMarket).filter_by(entity_id=entity_id).first()
            if em is None:
                return None
            obj = (
                session.query(EntityTimeSeriesDaily)
                .filter_by(entity_id=em.id)
                .order_by(EntityTimeSeriesDaily.date.desc())
                .first()
            )
            return _row_to_dict(obj) if obj else None

    def get_prev_snapshot(self, entity_id: str, before_date: str) -> Optional[Dict[str, Any]]:
        with self._Session() as session:
            em = session.query(EntityMarket).filter_by(entity_id=entity_id).first()
            if em is None:
                return None
            obj = (
                session.query(EntityTimeSeriesDaily)
                .filter(
                    EntityTimeSeriesDaily.entity_id == em.id,
                    EntityTimeSeriesDaily.date < before_date,
                )
                .order_by(EntityTimeSeriesDaily.date.desc())
                .first()
            )
            return _row_to_dict(obj) if obj else None

    def get_entity_history(self, entity_id: str, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        with self._Session() as session:
            em = session.query(EntityMarket).filter_by(entity_id=entity_id).first()
            if em is None:
                return []
            rows = (
                session.query(EntityTimeSeriesDaily)
                .filter(
                    EntityTimeSeriesDaily.entity_id == em.id,
                    EntityTimeSeriesDaily.date >= cutoff,
                )
                .order_by(EntityTimeSeriesDaily.date.asc())
                .all()
            )
            return [_row_to_dict(r) for r in rows]

    def list_latest_snapshots(self) -> List[Dict[str, Any]]:
        """Return the most recent snapshot per entity, joined with entity_market."""
        sql = text("""
            SELECT
                em.entity_id,
                em.entity_type,
                em.ticker,
                em.canonical_name,
                s.date,
                s.mention_count,
                s.engagement_sum,
                s.composite_market_score,
                s.momentum,
                s.acceleration,
                s.volatility,
                s.growth_rate
            FROM entity_market em
            LEFT JOIN entity_timeseries_daily s
                ON s.entity_id = em.id
                AND s.date = (
                    SELECT MAX(date) FROM entity_timeseries_daily
                    WHERE entity_id = em.id
                )
            ORDER BY
                CASE WHEN s.composite_market_score IS NULL THEN 1 ELSE 0 END,
                s.composite_market_score DESC
        """)
        with self._Session() as session:
            result = session.execute(sql)
            return [dict(row._mapping) for row in result]

    # ------------------------------------------------------------------
    # signals
    # ------------------------------------------------------------------

    def save_signals(self, signals: List[Dict[str, Any]]) -> None:
        """Write signal dicts.

        entity_id may be either:
          - a UUID object/string (from EntityMarket.id)
          - a canonical name string (resolved to UUID via entity_market lookup)

        detected_at may be a date string, date, or datetime — always stored
        as timezone-aware datetime.
        """
        with self._Session() as session:
            for sig in signals:
                raw_eid = sig["entity_id"]
                # Resolve string canonical name → UUID
                import uuid as _uuid
                try:
                    entity_uuid = _uuid.UUID(str(raw_eid))
                except (ValueError, AttributeError):
                    em = session.query(EntityMarket).filter_by(entity_id=str(raw_eid)).first()
                    if em is None:
                        continue
                    entity_uuid = em.id

                # Coerce detected_at to datetime
                raw_dt = sig["detected_at"]
                if isinstance(raw_dt, datetime):
                    detected_at = raw_dt if raw_dt.tzinfo else raw_dt.replace(tzinfo=timezone.utc)
                else:
                    d = date.fromisoformat(str(raw_dt)[:10])
                    detected_at = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

                entity_type = sig.get("entity_type", "perfume")
                existing = (
                    session.query(Signal)
                    .filter_by(
                        entity_id=entity_uuid,
                        entity_type=entity_type,
                        signal_type=sig["signal_type"],
                        detected_at=detected_at,
                    )
                    .first()
                )
                metadata = sig.get("metadata") or sig.get("details")
                strength = sig.get("strength", sig.get("score", 0.0))
                if existing:
                    existing.strength = strength
                    existing.metadata_json = metadata
                else:
                    session.add(Signal(
                        entity_id=entity_uuid,
                        entity_type=entity_type,
                        signal_type=sig["signal_type"],
                        strength=strength,
                        metadata_json=metadata,
                        detected_at=detected_at,
                        created_at=datetime.now(timezone.utc),
                    ))
            session.commit()

    def list_recent_signals(self, days: int = 7) -> List[Dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        sql = text("""
            SELECT
                s.entity_id, s.entity_type, s.signal_type, s.detected_at,
                s.strength, s.metadata_json,
                em.ticker, em.canonical_name, em.entity_id AS entity_slug
            FROM signals s
            JOIN entity_market em ON s.entity_id = em.id
            WHERE s.detected_at >= :cutoff
            ORDER BY s.detected_at DESC
        """)
        with self._Session() as session:
            result = session.execute(sql, {"cutoff": cutoff.isoformat()})
            return [dict(row._mapping) for row in result]

    def get_entity_signals(self, entity_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._Session() as session:
            em = session.query(EntityMarket).filter_by(entity_id=entity_id).first()
            if em is None:
                return []
            rows = (
                session.query(Signal)
                .filter_by(entity_id=em.id)
                .order_by(Signal.detected_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_dict(r) for r in rows]
