"""026 — Unique index on entity_mentions(entity_id, source_url)

Adds:
  UNIQUE INDEX uq_entity_mentions_entity_source
    ON entity_mentions(entity_id, source_url)

Purpose:
  Prevents duplicate (entity_id, source_url) rows that were caused by a
  dedup-check mismatch in _write_mentions(): the check used the bare
  content_item_id (e.g. "abc123xyz") while the INSERT wrote the full URL
  (e.g. "https://youtube.com/watch?v=abc123xyz"). The mismatch meant the
  check never matched existing rows, so every re-aggregation inserted a
  fresh duplicate.

  After FIX-1B cleanup (2026-05-02) there are zero duplicate
  (entity_id, source_url) pairs, so the index can be created without
  CONCURRENTLY or dedup pre-steps.

  source_url has 0 NULL values in production — a full (non-partial)
  unique index is correct.

Also enables ON CONFLICT DO NOTHING in _write_mentions() as a DB-level
safety net in addition to the Python dedup check.

Revision ID: 026
Revises: 025
"""

from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_entity_mentions_entity_source",
        "entity_mentions",
        ["entity_id", "source_url"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_entity_mentions_entity_source", table_name="entity_mentions")
