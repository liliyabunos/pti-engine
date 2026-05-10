"""SOURCE-INTAKE-V1A — source_intake_batches, source_intake_candidates, source_intake_audit_log

Revision ID: 038
Revises: 037
Create Date: 2026-05-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None

_CANDIDATE_STATUSES = (
    "PENDING_VERIFICATION",
    "VERIFIED_ADD_READY",
    "SKIP_DUPLICATE",
    "SKIP_INACTIVE",
    "NEEDS_OPERATOR_REVIEW",
    "OPERATOR_APPROVED",
    "OPERATOR_REJECTED",
    "DEFERRED",
    "BLOCKED_BY_API_PERMISSION",
    "APPLIED",
    "APPLY_FAILED",
    "PRODUCTION_VERIFIED",
)

_BATCH_STATUSES = ("open", "closed", "applied", "production_verified")


def upgrade() -> None:
    # ── source_intake_batches ─────────────────────────────────────────────────
    op.create_table(
        "source_intake_batches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("batch_label", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("applied_by", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _BATCH_STATUSES)})",
            name="ck_source_intake_batches_status",
        ),
    )

    # ── source_intake_candidates ──────────────────────────────────────────────
    op.create_table(
        "source_intake_candidates",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("candidate_name", sa.Text(), nullable=False),
        sa.Column("input_url", sa.Text(), nullable=False),
        sa.Column("resolved_platform_id", sa.Text(), nullable=True),
        sa.Column("resolved_title", sa.Text(), nullable=True),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("total_content_count", sa.Integer(), nullable=True),
        sa.Column("recent_content_count", sa.Integer(), nullable=True),
        sa.Column("recent_titles_sample", sa.Text(), nullable=True),  # JSON array
        sa.Column("resolve_method", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING_VERIFICATION"),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("operator_override_url", sa.Text(), nullable=True),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("quality_tier", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("apply_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["source_intake_batches.id"],
            name="fk_source_intake_candidates_batch",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _CANDIDATE_STATUSES)})",
            name="ck_source_intake_candidates_status",
        ),
    )
    op.create_index(
        "ix_source_intake_candidates_batch_id",
        "source_intake_candidates",
        ["batch_id"],
    )
    op.create_index(
        "ix_source_intake_candidates_status",
        "source_intake_candidates",
        ["status"],
    )

    # ── source_intake_audit_log ───────────────────────────────────────────────
    op.create_table(
        "source_intake_audit_log",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("candidate_id", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("old_status", sa.Text(), nullable=True),
        sa.Column("new_status", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["source_intake_candidates.id"],
            name="fk_source_intake_audit_candidate",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_source_intake_audit_candidate_id",
        "source_intake_audit_log",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_table("source_intake_audit_log")
    op.drop_table("source_intake_candidates")
    op.drop_table("source_intake_batches")
