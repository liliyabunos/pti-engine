"""024 — Transcript queue: status columns + content_transcripts table

Adds:
  canonical_content_items.transcript_status    — none | needed | fetched | unavailable | failed
  canonical_content_items.transcript_priority  — none | low | high
  content_transcripts                          — stores extracted transcript text

transcript_status and transcript_priority are lightweight queue markers on the
existing content_items row. The transcript text itself lives in content_transcripts
(separate table) to avoid bloating the main content query path.

Revision ID: 024
Revises: 023
"""

from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Lightweight queue status on canonical_content_items
    op.add_column(
        "canonical_content_items",
        sa.Column(
            "transcript_status",
            sa.String(20),
            nullable=True,
            server_default="none",
        ),
    )
    op.add_column(
        "canonical_content_items",
        sa.Column(
            "transcript_priority",
            sa.String(10),
            nullable=True,
            server_default="none",
        ),
    )

    op.create_index(
        "ix_cci_transcript_queue",
        "canonical_content_items",
        ["transcript_status", "transcript_priority"],
        postgresql_where=sa.text("transcript_status = 'needed'"),
    )

    # Transcript text storage — separate table to avoid bloating the main query path
    op.create_table(
        "content_transcripts",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "content_item_id",
            sa.String(255),
            sa.ForeignKey("canonical_content_items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("transcript_source", sa.String(64), nullable=False),  # youtube_captions | whisper | assemblyai
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_content_transcripts_content_item_id",
        "content_transcripts",
        ["content_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_transcripts_content_item_id", table_name="content_transcripts")
    op.drop_table("content_transcripts")
    op.drop_index("ix_cci_transcript_queue", table_name="canonical_content_items")
    op.drop_column("canonical_content_items", "transcript_priority")
    op.drop_column("canonical_content_items", "transcript_status")
