"""C1 — creator_profile_claims table

Revision ID: 036
Revises: 035
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_profile_claims",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("creator_id", sa.Text(), nullable=False),
        sa.Column(
            "claim_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "claim_method",
            sa.Text(),
            nullable=True,
        ),
        # Verification code stored as bcrypt hash — never plaintext
        sa.Column("verification_code_hash", sa.Text(), nullable=True),
        sa.Column("verification_code_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Evidence + review
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("claimed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # CHECK constraints
        sa.CheckConstraint(
            "claim_status IN ('pending', 'verified', 'rejected', 'revoked')",
            name="ck_creator_profile_claims_status",
        ),
        sa.CheckConstraint(
            "claim_method IN ('bio_code', 'screenshot', 'manual_review', 'domain_email', 'oauth')",
            name="ck_creator_profile_claims_method",
        ),
    )

    # Only one active (pending or verified) claim per user+platform+creator
    op.create_index(
        "uq_creator_profile_claims_active",
        "creator_profile_claims",
        ["platform", "creator_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("claim_status IN ('pending', 'verified')"),
    )

    op.create_index(
        "ix_creator_profile_claims_creator",
        "creator_profile_claims",
        ["platform", "creator_id"],
    )

    op.create_index(
        "ix_creator_profile_claims_user",
        "creator_profile_claims",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_creator_profile_claims_user", table_name="creator_profile_claims")
    op.drop_index("ix_creator_profile_claims_creator", table_name="creator_profile_claims")
    op.drop_index("uq_creator_profile_claims_active", table_name="creator_profile_claims")
    op.drop_table("creator_profile_claims")
