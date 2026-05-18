"""SIG-QA2 — Evidence-Aware Mention Promotion Gate v1 (Shadow Mode)

Revision ID: 052
Revises: 051
Create Date: 2026-05-18

Two schema additions:

1.  evidence_confidence column on entity_mentions
    Added as VARCHAR(32) NOT NULL DEFAULT 'legacy_unscored'.
    Historical rows are assigned 'legacy_unscored' — they predate SIG-QA2
    and were never evaluated by the gate. New rows scored by the gate receive
    'high' (score >= threshold) or 'low' (score < threshold). 'low' rows are
    still written in shadow mode but excluded when active mode is enabled.

2.  weak_evidence_log table
    Captures per-mention evidence scores from every pipeline run in shadow
    mode. Used for threshold calibration and shadow-mode observation before
    active-mode activation.

    UNIQUE on (content_item_id, entity_canonical_name, pipeline_run_date)
    — ON CONFLICT DO UPDATE for idempotent pipeline reruns.

Activation:
    Gate remains inactive (shadow mode only) after this migration.
    Set SIG_QA2_GATE_ACTIVE=true in Railway env to activate suppression.
    Activation requires shadow-mode observation review + Men's Cologne repair.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add evidence_confidence to entity_mentions
    # DEFAULT 'legacy_unscored' — historical rows predate SIG-QA2 scoring.
    # Valid values: legacy_unscored | high | low
    op.add_column(
        "entity_mentions",
        sa.Column(
            "evidence_confidence",
            sa.String(32),
            nullable=False,
            server_default="legacy_unscored",
        ),
    )

    # 2. Create weak_evidence_log
    op.create_table(
        "weak_evidence_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("content_item_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  nullable=False),
        sa.Column("entity_canonical_name", sa.Text, nullable=False),
        sa.Column("entity_brand_name", sa.Text, nullable=True),
        sa.Column("pipeline_run_date", sa.Date, nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("would_suppress", sa.Boolean, nullable=False),
        # features_json: {"d1": float, "d2": float, "d3_raw": float, "d4": float, "d5_density": float}
        sa.Column("features_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("shadow_mode", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Idempotent upsert key — reruns update existing row, never append
        sa.UniqueConstraint(
            "content_item_id", "entity_canonical_name", "pipeline_run_date",
            name="uq_weak_evidence_log_item_entity_date",
        ),
    )

    op.create_index(
        "ix_weak_evidence_log_run_date",
        "weak_evidence_log",
        ["pipeline_run_date"],
    )
    op.create_index(
        "ix_weak_evidence_log_canonical",
        "weak_evidence_log",
        ["entity_canonical_name"],
    )
    op.create_index(
        "ix_weak_evidence_log_would_suppress",
        "weak_evidence_log",
        ["would_suppress"],
    )


def downgrade() -> None:
    op.drop_index("ix_weak_evidence_log_would_suppress", table_name="weak_evidence_log")
    op.drop_index("ix_weak_evidence_log_canonical", table_name="weak_evidence_log")
    op.drop_index("ix_weak_evidence_log_run_date", table_name="weak_evidence_log")
    op.drop_table("weak_evidence_log")
    op.drop_column("entity_mentions", "evidence_confidence")
