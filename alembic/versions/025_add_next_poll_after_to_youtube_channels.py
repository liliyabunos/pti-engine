"""025 — Adaptive polling: next_poll_after column on youtube_channels

Adds:
  youtube_channels.next_poll_after TIMESTAMPTZ — computed due time for next poll;
    NULL = not yet polled (always eligible), set after each poll based on
    channel activity and quality tier.

Index on (next_poll_after, status) enables O(log n) due-channel lookup:
  WHERE status = 'active' AND (next_poll_after IS NULL OR next_poll_after <= NOW())

Revision ID: 025
Revises: 024
"""

from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "youtube_channels",
        sa.Column("next_poll_after", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_youtube_channels_next_poll",
        "youtube_channels",
        ["next_poll_after", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_youtube_channels_next_poll", table_name="youtube_channels")
    op.drop_column("youtube_channels", "next_poll_after")
