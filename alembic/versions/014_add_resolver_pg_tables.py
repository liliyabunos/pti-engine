"""Add Postgres-native resolver/catalog tables (Phase R1).

Revision ID: 014
Revises: 013
Create Date: 2026-04-21

Creates four resolver tables that mirror the SQLite resolver schema
but live in Postgres. These are intentionally SEPARATE from the
market-layer tables (brands, perfumes — UUID PKs).

Naming convention: resolver_* prefix to avoid collision with market tables.

Tables:
  resolver_brands            — canonical brands (integer PK, normalized_name UNIQUE)
  resolver_perfumes          — canonical perfumes (integer PK, FK → resolver_brands)
  resolver_aliases           — alias lookup table (hot read path for resolver)
  resolver_fragrance_master  — full KB identity rows

Integer PKs are preserved to maintain continuity with the existing
SQLite resolver; aliases reference entity_id as integers.

Migration from SQLite:
  scripts/migrate_resolver_to_postgres.py (idempotent, ON CONFLICT DO NOTHING)
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resolver_brands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_resolver_brands_normalized"),
    )
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS resolver_brands_id_seq "
        "START 1 OWNED BY resolver_brands.id"
    )
    op.execute(
        "ALTER TABLE resolver_brands ALTER COLUMN id "
        "SET DEFAULT nextval('resolver_brands_id_seq')"
    )
    op.create_index(
        "ix_resolver_brands_normalized",
        "resolver_brands",
        ["normalized_name"],
    )

    op.create_table(
        "resolver_perfumes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("default_concentration", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"], ["resolver_brands.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_resolver_perfumes_normalized"),
    )
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS resolver_perfumes_id_seq "
        "START 1 OWNED BY resolver_perfumes.id"
    )
    op.execute(
        "ALTER TABLE resolver_perfumes ALTER COLUMN id "
        "SET DEFAULT nextval('resolver_perfumes_id_seq')"
    )
    op.create_index(
        "ix_resolver_perfumes_brand_id",
        "resolver_perfumes",
        ["brand_id"],
    )
    op.create_index(
        "ix_resolver_perfumes_normalized",
        "resolver_perfumes",
        ["normalized_name"],
    )

    op.create_table(
        "resolver_aliases",
        sa.Column("id", sa.Integer(), sa.Sequence("resolver_aliases_id_seq"), nullable=False),
        sa.Column("alias_text", sa.Text(), nullable=False),
        sa.Column("normalized_alias_text", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_alias_text",
            "entity_type",
            "entity_id",
            name="uq_resolver_aliases_lookup",
        ),
        sa.CheckConstraint(
            "entity_type IN ('brand', 'perfume')",
            name="ck_resolver_aliases_entity_type",
        ),
    )
    # Hot path: alias lookup by normalized text + entity type
    op.create_index(
        "ix_resolver_aliases_lookup",
        "resolver_aliases",
        ["normalized_alias_text", "entity_type"],
    )

    op.create_table(
        "resolver_fragrance_master",
        sa.Column("id", sa.Integer(), sa.Sequence("resolver_fragrance_master_id_seq"), nullable=False),
        sa.Column("fragrance_id", sa.Text(), nullable=False),
        sa.Column("brand_name", sa.Text(), nullable=False),
        sa.Column("perfume_name", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("gender", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("perfume_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["resolver_brands.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["perfume_id"], ["resolver_perfumes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fragrance_id", name="uq_resolver_fm_fragrance_id"),
        sa.UniqueConstraint("normalized_name", name="uq_resolver_fm_normalized"),
    )
    op.create_index(
        "ix_resolver_fm_source",
        "resolver_fragrance_master",
        ["source"],
    )


def downgrade() -> None:
    op.drop_table("resolver_fragrance_master")
    op.drop_table("resolver_aliases")
    op.drop_table("resolver_perfumes")
    op.drop_table("resolver_brands")
