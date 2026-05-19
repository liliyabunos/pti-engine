"""Fix weak_evidence_log.content_item_id column type UUID → TEXT

Revision ID: 053
Revises: 052
Create Date: 2026-05-19

Root cause:
    Migration 052 defined weak_evidence_log.content_item_id as UUID type.
    However, resolved_signals.content_item_id stores YouTube video IDs
    (11-character strings like "kh8zbwoRHN0"), not UUIDs. This caused
    every _upsert_weak_evidence_log INSERT to fail with:
        InvalidTextRepresentation: invalid input syntax for type uuid: "kh8zbwoRHN0"

    All 16,802 resolved_signals rows confirmed to be non-UUID format.
    Zero rows were ever successfully written to weak_evidence_log.

Fix:
    Change content_item_id from UUID to TEXT. The UNIQUE constraint on
    (content_item_id, entity_canonical_name, pipeline_run_date) still holds —
    TEXT uniqueness is sufficient for idempotent upsert semantics.

    Also drop and recreate the UniqueConstraint and indexes because
    ALTER COLUMN TYPE on a constrained column requires dropping constraints
    that reference it first.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The table was created in 052 and has 0 rows (all inserts failed due to
    # type mismatch). Drop indexes and unique constraint first, then alter type.

    op.drop_index("ix_weak_evidence_log_would_suppress", table_name="weak_evidence_log")
    op.drop_index("ix_weak_evidence_log_canonical", table_name="weak_evidence_log")
    op.drop_index("ix_weak_evidence_log_run_date", table_name="weak_evidence_log")
    op.drop_constraint(
        "uq_weak_evidence_log_item_entity_date",
        "weak_evidence_log",
        type_="unique",
    )

    # Change content_item_id from UUID to TEXT
    op.alter_column(
        "weak_evidence_log",
        "content_item_id",
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="content_item_id::text",
    )

    # Recreate unique constraint and indexes
    op.create_unique_constraint(
        "uq_weak_evidence_log_item_entity_date",
        "weak_evidence_log",
        ["content_item_id", "entity_canonical_name", "pipeline_run_date"],
    )
    op.create_index(
        "ix_weak_evidence_log_run_date",
        "weak_evidence_log",
        ["pipeline_run_date"],
    )
    op.create_index(
        "ix_weak_evidence_log_canonical",
        "weak_evidence_log",
        ["entity_canonical_name"],
    )
    op.create_index(
        "ix_weak_evidence_log_would_suppress",
        "weak_evidence_log",
        ["would_suppress"],
    )


def downgrade() -> None:
    op.drop_index("ix_weak_evidence_log_would_suppress", table_name="weak_evidence_log")
    op.drop_index("ix_weak_evidence_log_canonical", table_name="weak_evidence_log")
    op.drop_index("ix_weak_evidence_log_run_date", table_name="weak_evidence_log")
    op.drop_constraint(
        "uq_weak_evidence_log_item_entity_date",
        "weak_evidence_log",
        type_="unique",
    )
    op.alter_column(
        "weak_evidence_log",
        "content_item_id",
        type_=sa.dialects.postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        postgresql_using="content_item_id::uuid",
    )
    op.create_unique_constraint(
        "uq_weak_evidence_log_item_entity_date",
        "weak_evidence_log",
        ["content_item_id", "entity_canonical_name", "pipeline_run_date"],
    )
    op.create_index(
        "ix_weak_evidence_log_run_date",
        "weak_evidence_log",
        ["pipeline_run_date"],
    )
    op.create_index(
        "ix_weak_evidence_log_canonical",
        "weak_evidence_log",
        ["entity_canonical_name"],
    )
    op.create_index(
        "ix_weak_evidence_log_would_suppress",
        "weak_evidence_log",
        ["would_suppress"],
    )
