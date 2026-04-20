from __future__ import annotations

"""DB persistence layer for Fragrantica enrichment results.

Handles all writes for a single enriched perfume:
  - Upsert fragrantica_records row
  - Upsert notes / accords into the canonical libraries
  - Upsert perfume_notes / perfume_accords junction rows
  - Update perfumes.notes_summary

Designed to be called once per enriched perfume inside a try/except block
so that a single failure never blocks the rest of the batch.

Uses raw SQLAlchemy text() for upsert patterns that are idempotent on
both SQLite (INSERT OR IGNORE + UPDATE) and PostgreSQL (ON CONFLICT DO UPDATE).
The dialect is detected at runtime from the engine URL.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from perfume_trend_sdk.normalizers.fragrantica.normalizer import FragranticaPerfumeRecord

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_term(term: str) -> str:
    """Simple lowercase + strip normalization for note/accord names."""
    return term.strip().lower()


def _build_notes_summary(record: "FragranticaPerfumeRecord") -> str | None:
    """Build a human-readable notes_summary text from top/middle/base/accords."""
    parts = []
    if record.notes_top:
        parts.append("Top: " + ", ".join(record.notes_top))
    if record.notes_middle:
        parts.append("Middle: " + ", ".join(record.notes_middle))
    if record.notes_base:
        parts.append("Base: " + ", ".join(record.notes_base))
    if record.accords:
        parts.append("Accords: " + ", ".join(record.accords))
    return " | ".join(parts) if parts else None


class FragranticaEnrichmentStore:
    """Persists Fragrantica enrichment data into the market engine DB.

    Parameters
    ----------
    database_url : str
        SQLAlchemy connection URL for the market engine DB.
        Accepts both SQLite paths (sqlite:///…) and PostgreSQL URLs.
    """

    def __init__(self, database_url: str) -> None:
        connect_args = (
            {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        )
        self._engine = create_engine(database_url, connect_args=connect_args, future=True)
        self._is_postgres = not database_url.startswith("sqlite")
        self._Session = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)

    # ------------------------------------------------------------------
    # Public API — one call per enriched perfume
    # ------------------------------------------------------------------

    def persist(
        self,
        *,
        fragrance_id: str,
        market_perfume_uuid: str | None,
        source_url: str,
        raw_payload_ref: str,
        brand_name: str | None,
        perfume_name: str | None,
        record: "FragranticaPerfumeRecord",
    ) -> None:
        """Write all enrichment data for one perfume. Idempotent."""
        with self._Session() as session:
            try:
                self._upsert_fragrantica_record(
                    session,
                    fragrance_id=fragrance_id,
                    market_perfume_uuid=market_perfume_uuid,
                    source_url=source_url,
                    raw_payload_ref=raw_payload_ref,
                    brand_name=brand_name,
                    perfume_name=perfume_name,
                    record=record,
                )

                if market_perfume_uuid:
                    self._upsert_notes(session, market_perfume_uuid, record)
                    self._upsert_accords(session, market_perfume_uuid, record)
                    self._update_notes_summary(session, market_perfume_uuid, record)

                session.commit()
                logger.debug(
                    "[FragranticaEnrichmentStore] persisted fragrance_id=%s uuid=%s",
                    fragrance_id, market_perfume_uuid,
                )
            except Exception:
                session.rollback()
                raise

    def lookup_market_uuid(self, resolver_perfume_id: int) -> str | None:
        """Look up the market UUID for a resolver integer perfume id.

        Queries perfume_identity_map.resolver_perfume_id → market_perfume_uuid.
        Returns None if no mapping exists.
        """
        with self._Session() as session:
            row = session.execute(
                text(
                    "SELECT market_perfume_uuid FROM perfume_identity_map "
                    "WHERE resolver_perfume_id = :pid LIMIT 1"
                ),
                {"pid": resolver_perfume_id},
            ).fetchone()
        return str(row[0]) if row else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert_fragrantica_record(
        self,
        session: Session,
        *,
        fragrance_id: str,
        market_perfume_uuid: str | None,
        source_url: str,
        raw_payload_ref: str,
        brand_name: str | None,
        perfume_name: str | None,
        record: "FragranticaPerfumeRecord",
    ) -> None:
        now = _now()
        params = {
            "id": str(uuid.uuid4()),
            "fragrance_id": fragrance_id,
            "perfume_id": market_perfume_uuid,
            "source_url": source_url,
            "raw_payload_ref": raw_payload_ref or "",
            "brand_name": brand_name,
            "perfume_name": perfume_name,
            "accords_json": json.dumps(record.accords, ensure_ascii=False),
            "notes_top_json": json.dumps(record.notes_top, ensure_ascii=False),
            "notes_middle_json": json.dumps(record.notes_middle, ensure_ascii=False),
            "notes_base_json": json.dumps(record.notes_base, ensure_ascii=False),
            "rating_value": record.rating_value,
            "rating_count": record.rating_count,
            "release_year": record.release_year,
            "perfumer": record.perfumer,
            "gender": record.gender,
            "similar_perfumes_json": json.dumps(record.similar_perfumes, ensure_ascii=False),
            "fetched_at": now,
            "created_at": now,
        }

        if self._is_postgres:
            session.execute(
                text("""
                    INSERT INTO fragrantica_records (
                        id, fragrance_id, perfume_id, source_url, raw_payload_ref,
                        brand_name, perfume_name, accords_json,
                        notes_top_json, notes_middle_json, notes_base_json,
                        rating_value, rating_count, release_year, perfumer, gender,
                        similar_perfumes_json, fetched_at, created_at
                    ) VALUES (
                        :id, :fragrance_id, :perfume_id, :source_url, :raw_payload_ref,
                        :brand_name, :perfume_name, :accords_json,
                        :notes_top_json, :notes_middle_json, :notes_base_json,
                        :rating_value, :rating_count, :release_year, :perfumer, :gender,
                        :similar_perfumes_json, :fetched_at, :created_at
                    )
                    ON CONFLICT (fragrance_id) DO UPDATE SET
                        perfume_id            = EXCLUDED.perfume_id,
                        source_url            = EXCLUDED.source_url,
                        raw_payload_ref       = EXCLUDED.raw_payload_ref,
                        accords_json          = EXCLUDED.accords_json,
                        notes_top_json        = EXCLUDED.notes_top_json,
                        notes_middle_json     = EXCLUDED.notes_middle_json,
                        notes_base_json       = EXCLUDED.notes_base_json,
                        rating_value          = EXCLUDED.rating_value,
                        rating_count          = EXCLUDED.rating_count,
                        release_year          = EXCLUDED.release_year,
                        perfumer              = EXCLUDED.perfumer,
                        gender                = EXCLUDED.gender,
                        similar_perfumes_json = EXCLUDED.similar_perfumes_json,
                        fetched_at            = EXCLUDED.fetched_at
                """),
                params,
            )
        else:
            # SQLite: INSERT OR IGNORE then UPDATE
            session.execute(
                text("""
                    INSERT OR IGNORE INTO fragrantica_records (
                        id, fragrance_id, perfume_id, source_url, raw_payload_ref,
                        brand_name, perfume_name, accords_json,
                        notes_top_json, notes_middle_json, notes_base_json,
                        rating_value, rating_count, release_year, perfumer, gender,
                        similar_perfumes_json, fetched_at, created_at
                    ) VALUES (
                        :id, :fragrance_id, :perfume_id, :source_url, :raw_payload_ref,
                        :brand_name, :perfume_name, :accords_json,
                        :notes_top_json, :notes_middle_json, :notes_base_json,
                        :rating_value, :rating_count, :release_year, :perfumer, :gender,
                        :similar_perfumes_json, :fetched_at, :created_at
                    )
                """),
                params,
            )
            session.execute(
                text("""
                    UPDATE fragrantica_records SET
                        perfume_id            = :perfume_id,
                        source_url            = :source_url,
                        raw_payload_ref       = :raw_payload_ref,
                        accords_json          = :accords_json,
                        notes_top_json        = :notes_top_json,
                        notes_middle_json     = :notes_middle_json,
                        notes_base_json       = :notes_base_json,
                        rating_value          = :rating_value,
                        rating_count          = :rating_count,
                        release_year          = :release_year,
                        perfumer              = :perfumer,
                        gender                = :gender,
                        similar_perfumes_json = :similar_perfumes_json,
                        fetched_at            = :fetched_at
                    WHERE fragrance_id = :fragrance_id
                """),
                params,
            )

    def _upsert_note(self, session: Session, name: str) -> str:
        """Upsert a note and return its UUID."""
        normalized = _normalize_term(name)
        now = _now()
        nid = str(uuid.uuid4())

        if self._is_postgres:
            session.execute(
                text("""
                    INSERT INTO notes (id, name, normalized_name, created_at)
                    VALUES (:id, :name, :normalized_name, :created_at)
                    ON CONFLICT (normalized_name) DO NOTHING
                """),
                {"id": nid, "name": name, "normalized_name": normalized, "created_at": now},
            )
        else:
            session.execute(
                text("""
                    INSERT OR IGNORE INTO notes (id, name, normalized_name, created_at)
                    VALUES (:id, :name, :normalized_name, :created_at)
                """),
                {"id": nid, "name": name, "normalized_name": normalized, "created_at": now},
            )

        row = session.execute(
            text("SELECT id FROM notes WHERE normalized_name = :n"),
            {"n": normalized},
        ).fetchone()
        return str(row[0])

    def _upsert_accord(self, session: Session, name: str) -> str:
        """Upsert an accord and return its UUID."""
        normalized = _normalize_term(name)
        now = _now()
        aid = str(uuid.uuid4())

        if self._is_postgres:
            session.execute(
                text("""
                    INSERT INTO accords (id, name, normalized_name, created_at)
                    VALUES (:id, :name, :normalized_name, :created_at)
                    ON CONFLICT (normalized_name) DO NOTHING
                """),
                {"id": aid, "name": name, "normalized_name": normalized, "created_at": now},
            )
        else:
            session.execute(
                text("""
                    INSERT OR IGNORE INTO accords (id, name, normalized_name, created_at)
                    VALUES (:id, :name, :normalized_name, :created_at)
                """),
                {"id": aid, "name": name, "normalized_name": normalized, "created_at": now},
            )

        row = session.execute(
            text("SELECT id FROM accords WHERE normalized_name = :n"),
            {"n": normalized},
        ).fetchone()
        return str(row[0])

    def _upsert_perfume_note(
        self, session: Session, perfume_id: str, note_id: str, position: str
    ) -> None:
        now = _now()
        row_id = str(uuid.uuid4())

        if self._is_postgres:
            session.execute(
                text("""
                    INSERT INTO perfume_notes (id, perfume_id, note_id, note_position, source, created_at)
                    VALUES (:id, :perfume_id, :note_id, :note_position, 'fragrantica', :created_at)
                    ON CONFLICT (perfume_id, note_id, note_position) DO NOTHING
                """),
                {"id": row_id, "perfume_id": perfume_id, "note_id": note_id,
                 "note_position": position, "created_at": now},
            )
        else:
            session.execute(
                text("""
                    INSERT OR IGNORE INTO perfume_notes
                        (id, perfume_id, note_id, note_position, source, created_at)
                    VALUES (:id, :perfume_id, :note_id, :note_position, 'fragrantica', :created_at)
                """),
                {"id": row_id, "perfume_id": perfume_id, "note_id": note_id,
                 "note_position": position, "created_at": now},
            )

    def _upsert_perfume_accord(
        self, session: Session, perfume_id: str, accord_id: str
    ) -> None:
        now = _now()
        row_id = str(uuid.uuid4())

        if self._is_postgres:
            session.execute(
                text("""
                    INSERT INTO perfume_accords (id, perfume_id, accord_id, source, created_at)
                    VALUES (:id, :perfume_id, :accord_id, 'fragrantica', :created_at)
                    ON CONFLICT (perfume_id, accord_id) DO NOTHING
                """),
                {"id": row_id, "perfume_id": perfume_id, "accord_id": accord_id,
                 "created_at": now},
            )
        else:
            session.execute(
                text("""
                    INSERT OR IGNORE INTO perfume_accords
                        (id, perfume_id, accord_id, source, created_at)
                    VALUES (:id, :perfume_id, :accord_id, 'fragrantica', :created_at)
                """),
                {"id": row_id, "perfume_id": perfume_id, "accord_id": accord_id,
                 "created_at": now},
            )

    def _upsert_notes(
        self,
        session: Session,
        perfume_id: str,
        record: "FragranticaPerfumeRecord",
    ) -> None:
        """Upsert notes in all positions for the given perfume."""
        for position, terms in (
            ("top", record.notes_top),
            ("middle", record.notes_middle),
            ("base", record.notes_base),
        ):
            for term in terms:
                if not term.strip():
                    continue
                try:
                    note_id = self._upsert_note(session, term)
                    self._upsert_perfume_note(session, perfume_id, note_id, position)
                except Exception as exc:
                    logger.warning(
                        "[FragranticaEnrichmentStore] note upsert failed: %s — %s", term, exc
                    )

    def _upsert_accords(
        self,
        session: Session,
        perfume_id: str,
        record: "FragranticaPerfumeRecord",
    ) -> None:
        """Upsert accords for the given perfume."""
        for term in record.accords:
            if not term.strip():
                continue
            try:
                accord_id = self._upsert_accord(session, term)
                self._upsert_perfume_accord(session, perfume_id, accord_id)
            except Exception as exc:
                logger.warning(
                    "[FragranticaEnrichmentStore] accord upsert failed: %s — %s", term, exc
                )

    def _update_notes_summary(
        self,
        session: Session,
        perfume_id: str,
        record: "FragranticaPerfumeRecord",
    ) -> None:
        """Write notes_summary text to the perfumes row if it has meaningful content."""
        summary = _build_notes_summary(record)
        if not summary:
            return
        session.execute(
            text("UPDATE perfumes SET notes_summary = :s WHERE id = :pid"),
            {"s": summary, "pid": perfume_id},
        )

    # ------------------------------------------------------------------
    # Count helpers (for reporting)
    # ------------------------------------------------------------------

    def count_rows(self, table_name: str) -> int:
        allowed = {"fragrantica_records", "notes", "accords", "perfume_notes", "perfume_accords"}
        if table_name not in allowed:
            raise ValueError(f"Unsupported table: {table_name!r}")
        with self._Session() as session:
            row = session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
        return int(row[0]) if row else 0

    def count_enriched_perfumes(self) -> int:
        """Count perfumes that now have a non-NULL notes_summary."""
        with self._Session() as session:
            row = session.execute(
                text("SELECT COUNT(*) FROM perfumes WHERE notes_summary IS NOT NULL")
            ).fetchone()
        return int(row[0]) if row else 0
