"""Add subscriber_count_fetched_at to youtube_channels (C1.1)

Revision ID: 029
Revises: 028
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "youtube_channels",
        sa.Column("subscriber_count_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("youtube_channels", "subscriber_count_fetched_at")
