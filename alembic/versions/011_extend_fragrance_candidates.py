"""Extend fragrance_candidates with Phase 3B validation fields.

Revision ID: 011
Revises: 010
Create Date: 2026-04-21

Adds classification and validation columns to fragrance_candidates.
All new columns are nullable or carry a safe default so existing rows
remain valid after migration without running the validate_candidates job.

New columns:
  candidate_type         — noise | perfume | brand | note | unknown
  validation_status      — pending | accepted_rule_based | rejected_noise | review
  rejection_reason       — plain-text explanation for noise rows
  token_count            — number of whitespace-split tokens in normalized_text
  contains_brand_keyword — 1 if any token matches a known brand
  contains_perfume_keyword — 1 if any token matches a note / concentration word
  distinct_sources_count — number of distinct source_platforms that saw this phrase
                           (defaults to 1; updated by future ingestion instrumentation)
"""

from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fragrance_candidates",
        sa.Column("candidate_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column(
            "validation_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("token_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("contains_brand_keyword", sa.Integer(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column("contains_perfume_keyword", sa.Integer(), nullable=True),
    )
    op.add_column(
        "fragrance_candidates",
        sa.Column(
            "distinct_sources_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.create_index(
        "ix_fragrance_candidates_validation_status",
        "fragrance_candidates",
        ["validation_status"],
    )
    op.create_index(
        "ix_fragrance_candidates_candidate_type",
        "fragrance_candidates",
        ["candidate_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_fragrance_candidates_candidate_type", table_name="fragrance_candidates")
    op.drop_index("ix_fragrance_candidates_validation_status", table_name="fragrance_candidates")
    op.drop_column("fragrance_candidates", "distinct_sources_count")
    op.drop_column("fragrance_candidates", "contains_perfume_keyword")
    op.drop_column("fragrance_candidates", "contains_brand_keyword")
    op.drop_column("fragrance_candidates", "token_count")
    op.drop_column("fragrance_candidates", "rejection_reason")
    op.drop_column("fragrance_candidates", "validation_status")
    op.drop_column("fragrance_candidates", "candidate_type")
