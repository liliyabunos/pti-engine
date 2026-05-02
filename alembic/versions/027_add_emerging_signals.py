"""027 — Add emerging_signals table

Source-weighted, title-first, channel-aware emerging trend candidate table.
Separate from fragrance_candidates (Phase 3/4 promotion queue).
This table is intelligence-only — never used for KB promotion.

Columns:
  normalized_text          — lowercase normalized candidate phrase (UNIQUE)
  display_name             — title-cased for display
  candidate_type           — perfume | brand | clone_reference | unknown
  total_mentions           — count of channel_poll content items mentioning this phrase
  distinct_channels_count  — count of distinct youtube_channels that mentioned it
  weighted_channel_score   — sum of per-channel weights (tier1=3.0 tier2=2.0 tier3=1.0 unrated=0.5)
  top_channel_id           — channel_id of the highest-weighted contributing channel
  top_channel_title        — display title of that channel
  top_channel_tier         — quality_tier of that channel
  first_seen               — earliest published_at of contributing content
  last_seen                — most recent published_at of contributing content
  days_active              — days between first_seen and last_seen (min 1)
  is_in_resolver           — TRUE if normalized_text matches a resolver_aliases entry at write time
  is_in_entity_market      — TRUE if LOWER(canonical_name) matches in entity_market at write time
  review_status            — pending | rejected (human review gate, not auto-promotion)
  emerging_score           — weighted_channel_score × EXP(-0.1 × days_since_last_seen)
  created_at / updated_at

Revision ID: 027
Revises: 026
"""

from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emerging_signals",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("candidate_type", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("total_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_channels_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weighted_channel_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("top_channel_id", sa.Text(), nullable=True),
        sa.Column("top_channel_title", sa.Text(), nullable=True),
        sa.Column("top_channel_tier", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days_active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_in_resolver", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_in_entity_market", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("emerging_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_text", name="uq_emerging_signals_normalized_text"),
    )

    op.create_index(
        "idx_emerging_signals_score",
        "emerging_signals",
        [sa.text("emerging_score DESC")],
    )
    op.create_index(
        "idx_emerging_signals_last_seen",
        "emerging_signals",
        ["last_seen"],
    )
    op.create_index(
        "idx_emerging_signals_type",
        "emerging_signals",
        ["candidate_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_emerging_signals_type", table_name="emerging_signals")
    op.drop_index("idx_emerging_signals_last_seen", table_name="emerging_signals")
    op.drop_index("idx_emerging_signals_score", table_name="emerging_signals")
    op.drop_table("emerging_signals")
