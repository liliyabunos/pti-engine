"""Add brands, perfumes, entity_mentions tables (original schema v1)

Revision ID: 002
Revises: 001
Create Date: 2026-04-10

Adds three tables to the Market Engine Core alongside the pipeline tables:

  brands          — canonical brand entities (Integer PK, canonical_name)
  perfumes        — canonical perfume entities linked to brands (Integer PK, Integer brand_id FK)
  entity_mentions — raw mention records, entity_id is String canonical name (not UUID)

NOTE: This is the ORIGINAL v1 additive schema. Migration 003 performs a breaking upgrade
to the v2 schema (UUID PKs, new columns, renamed tables, UUID entity_id references).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name", name="uq_brand_canonical_name"),
    )
    op.create_index("ix_brands_canonical_name", "brands", ["canonical_name"])

    op.create_table(
        "perfumes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=True),
        sa.Column("default_concentration", sa.String(64), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", name="uq_perfume_entity_id"),
    )
    op.create_index("ix_perfumes_canonical_name", "perfumes", ["canonical_name"])
    op.create_index("ix_perfumes_brand_id", "perfumes", ["brand_id"])

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("content_item_id", sa.String(255), nullable=True),
        sa.Column("mention_weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("sentiment", sa.String(32), nullable=True),
        sa.Column("published_at", sa.String(16), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_mentions_entity_id", "entity_mentions", ["entity_id"])
    op.create_index("ix_entity_mentions_entity_type", "entity_mentions", ["entity_type"])
    op.create_index("ix_entity_mentions_content_item_id", "entity_mentions", ["content_item_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_mentions_content_item_id", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_entity_type", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_entity_id", table_name="entity_mentions")
    op.drop_table("entity_mentions")

    op.drop_index("ix_perfumes_brand_id", table_name="perfumes")
    op.drop_index("ix_perfumes_canonical_name", table_name="perfumes")
    op.drop_table("perfumes")

    op.drop_index("ix_brands_canonical_name", table_name="brands")
    op.drop_table("brands")
