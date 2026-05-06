"""Add source_submissions table (Submit a Source MVP).

Revision ID: 033
Revises: 032
Create Date: 2026-05-06

Stores community-submitted source URLs for manual review. No automatic
ingestion. No direct market score manipulation.
"""

from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_submissions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("raw_url", sa.Text, nullable=False),
        sa.Column("normalized_url", sa.Text, nullable=False),
        sa.Column("platform", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("submitted_by_user_id", sa.Text, nullable=True),
        sa.Column("submitted_by_email", sa.Text, nullable=True),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
    )
    # Duplicate protection: one submission per normalized URL
    op.create_index(
        "uq_source_submissions_normalized_url",
        "source_submissions",
        ["normalized_url"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_source_submissions_normalized_url", table_name="source_submissions")
    op.drop_table("source_submissions")
