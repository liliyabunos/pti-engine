"""add brand_name to entity_market

Revision ID: 005
Revises: 004
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entity_market",
        sa.Column("brand_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_market", "brand_name")
