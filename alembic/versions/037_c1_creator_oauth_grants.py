"""C1 — creator_oauth_grants scaffold

Revision ID: 037
Revises: 036
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_oauth_grants",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("platform_user_id", sa.Text(), nullable=False),
        # Nullable — future bridge to FragranceIndex creator profiles
        sa.Column("creator_id", sa.Text(), nullable=True),
        # Tokens encrypted at rest — NEVER plaintext
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "scopes_granted",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "grant_status",
            sa.Text(),
            nullable=False,
            server_default="active",
        ),
        # Timestamps
        sa.Column(
            "connected_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("last_refreshed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("disconnect_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "grant_status IN ('active', 'revoked', 'expired', 'failed')",
            name="ck_creator_oauth_grants_status",
        ),
    )

    # One active grant per user+platform+platform_user_id (allows multiple accounts)
    op.create_index(
        "uq_creator_oauth_grants_active_account",
        "creator_oauth_grants",
        ["user_id", "platform", "platform_user_id"],
        unique=True,
        postgresql_where=sa.text("grant_status = 'active'"),
    )

    op.create_index(
        "ix_creator_oauth_grants_user",
        "creator_oauth_grants",
        ["user_id"],
    )

    op.create_index(
        "ix_creator_oauth_grants_creator",
        "creator_oauth_grants",
        ["creator_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_creator_oauth_grants_creator", table_name="creator_oauth_grants")
    op.drop_index("ix_creator_oauth_grants_user", table_name="creator_oauth_grants")
    op.drop_index("uq_creator_oauth_grants_active_account", table_name="creator_oauth_grants")
    op.drop_table("creator_oauth_grants")
