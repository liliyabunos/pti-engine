"""Fix missing SERIAL sequences on resolver_aliases and resolver_fragrance_master.

Revision ID: 015
Revises: 014
Create Date: 2026-04-21

Migration 014 created resolver_aliases and resolver_fragrance_master with
INTEGER NOT NULL id columns but did not wire a sequence as the DEFAULT value
(unlike resolver_brands and resolver_perfumes which had explicit CREATE
SEQUENCE + ALTER TABLE steps). This migration patches those two columns.
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS resolver_aliases_id_seq "
        "START 1 OWNED BY resolver_aliases.id"
    )
    op.execute(
        "ALTER TABLE resolver_aliases ALTER COLUMN id "
        "SET DEFAULT nextval('resolver_aliases_id_seq')"
    )

    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS resolver_fragrance_master_id_seq "
        "START 1 OWNED BY resolver_fragrance_master.id"
    )
    op.execute(
        "ALTER TABLE resolver_fragrance_master ALTER COLUMN id "
        "SET DEFAULT nextval('resolver_fragrance_master_id_seq')"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE resolver_fragrance_master ALTER COLUMN id DROP DEFAULT"
    )
    op.execute("DROP SEQUENCE IF EXISTS resolver_fragrance_master_id_seq")

    op.execute(
        "ALTER TABLE resolver_aliases ALTER COLUMN id DROP DEFAULT"
    )
    op.execute("DROP SEQUENCE IF EXISTS resolver_aliases_id_seq")
