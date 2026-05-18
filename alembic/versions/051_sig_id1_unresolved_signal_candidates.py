"""SIG-ID1 — Unresolved Signal Candidates Table

Revision ID: 051
Revises: 050
Create Date: 2026-05-18

Creates the unresolved_signal_candidates table — part of the SIG-ID1
Cross-Brand Attribution Correction phase.

Purpose:
    Previously, unresolved_mentions_json in resolved_signals captured
    n-gram phrases that the resolver could not match to any alias. This
    data was written but never read — operationally dead.

    This table surfaces brand-qualified unresolved phrases (phrases where
    a token matches a known brand name but the phrase as a whole has no
    alias) for operator visibility. It is populated by:
        scripts/harvest_unresolved_brand_signals.py

    The primary use case is detecting Class 2 (Wrong Identity) failures:
    content that names a real product not in the resolver catalog, where
    a bare alias from a different brand captures the signal instead.

    Example: "vertus amber elixir" appearing in content — Vertus Amber
    Elixir is not in the catalog, so "amber elixir" matched Oriflame.
    This table surfaces "vertus amber elixir" with brand_token="vertus"
    for operator review.

    ENTITY-DISC1 will extend this table with catalog-addition workflow
    (operator approve → resolver entry created → re-resolution triggered).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unresolved_signal_candidates",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # The normalized phrase from unresolved_mentions_json
        sa.Column("phrase", sa.Text(), nullable=False),
        # The single brand token (normalized) that qualifies this phrase
        sa.Column("brand_token", sa.Text(), nullable=False),
        # Canonical brand name resolved from brand_token
        sa.Column("brand_canonical_name", sa.Text(), nullable=False),
        # Cumulative occurrence count across all RS rows processed
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        # Number of distinct content items where this phrase appeared unresolved
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        # pending | dismissed | added_to_catalog
        # ENTITY-DISC1 will add: in_review | approved | rejected
        sa.Column(
            "candidate_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("phrase", "brand_token", name="uq_usc_phrase_brand_token"),
    )

    op.create_index(
        "ix_usc_status",
        "unresolved_signal_candidates",
        ["candidate_status"],
    )
    op.create_index(
        "ix_usc_brand_canonical",
        "unresolved_signal_candidates",
        ["brand_canonical_name"],
    )
    op.create_index(
        "ix_usc_last_seen",
        "unresolved_signal_candidates",
        ["last_seen"],
        postgresql_ops={"last_seen": "DESC"},
    )
    op.create_index(
        "ix_usc_occurrence_count",
        "unresolved_signal_candidates",
        ["occurrence_count"],
        postgresql_ops={"occurrence_count": "DESC"},
    )


def downgrade() -> None:
    op.drop_table("unresolved_signal_candidates")
