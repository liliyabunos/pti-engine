"""028 — Add youtube_query_experiments table

Tracks temporary YouTube search queries generated from emerging_signals
and fragrance_candidates. Enables the G4-E Emerging → Targeted Queries
Feedback Loop.

Design principles:
  - Core perfume_queries.yaml is NEVER modified by this system
  - Experiments run in addition to, not instead of, core queries
  - Hard cap: max 5 active experiments to protect quota budget
  - Auto-expire after 14 days — no permanent leakage into pipeline
  - Promotion remains manual/approved

Lifecycle:
  pending   → active     (apply_temp_youtube_queries.py --apply)
  active    → expired    (auto, when expires_at <= NOW())
  active    → confirmed  (evaluate_temp_youtube_queries.py confirms signal)
  active    → suppressed (evaluate_temp_youtube_queries.py finds no signal)
  confirmed → promoted   (manual alias/entity seed via seed scripts)

Revision ID: 028
Revises: 027
"""

from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_query_experiments",
        # --- Identity ---
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        # --- Candidate provenance ---
        sa.Column("candidate_text", sa.Text(), nullable=False),
        sa.Column("normalized_candidate", sa.Text(), nullable=False),
        sa.Column("candidate_type", sa.String(32), nullable=False, server_default="perfume"),
        sa.Column("candidate_source", sa.String(64), nullable=False, server_default="emerging_signals"),
        sa.Column("candidate_id", sa.Integer(), nullable=True),   # emerging_signals.id or fragrance_candidates.id
        sa.Column("candidate_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("distinct_channels_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="medium"),
        # --- Query ---
        sa.Column("query_text", sa.Text(), nullable=False),       # actual YouTube search query
        # --- Lifecycle ---
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        # pending | active | paused | expired | confirmed | suppressed
        sa.Column("source", sa.String(64), nullable=False, server_default="g4e_emerging_feedback"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        # --- Execution tracking ---
        sa.Column("first_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("videos_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entity_mentions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fragrance_candidates_produced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_mentions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_json", sa.Text(), nullable=True),     # JSON: top entities, sample titles
        # --- Evaluation outcome ---
        sa.Column("recommendation", sa.String(16), nullable=True),
        # confirm | suppress | review | promote
        sa.Column("promoted_entity_id", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # --- PK / constraints ---
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_text", name="uq_yte_query_text"),
        sa.UniqueConstraint("normalized_candidate", name="uq_yte_normalized_candidate"),
    )

    op.create_index(
        "idx_yte_status",
        "youtube_query_experiments",
        ["status"],
    )
    op.create_index(
        "idx_yte_expires_at",
        "youtube_query_experiments",
        ["expires_at"],
    )
    op.create_index(
        "idx_yte_candidate_score",
        "youtube_query_experiments",
        [sa.text("candidate_score DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_yte_candidate_score", table_name="youtube_query_experiments")
    op.drop_index("idx_yte_expires_at", table_name="youtube_query_experiments")
    op.drop_index("idx_yte_status", table_name="youtube_query_experiments")
    op.drop_table("youtube_query_experiments")
