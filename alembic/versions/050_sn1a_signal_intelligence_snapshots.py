"""FTG-5 / SN1-A — Signal Intelligence Snapshots

Revision ID: 050
Revises: 049
Create Date: 2026-05-16

Creates the signal_intelligence_snapshots table — the first layer of the
Intelligence Snapshot Layer (FTG-5 / SN1).

Purpose:
  Persist an immutable historical record of market intelligence at the moment
  a market signal was first detected by the pipeline. This allows future
  Deep Dive Reports and trend analyses to answer:
    - Which entity was signaled?
    - When was the signal detected?
    - What type of signal was it?
    - What market metrics supported it at that time?
    - What pipeline version / threshold version produced the snapshot?

Snapshot semantics (Option A — first-capture immutable):
  ON CONFLICT (entity_id, entity_type, signal_type, detected_at) DO NOTHING.
  The detect_breakout_signals job deletes and recreates signal rows on reruns,
  but signal_intelligence_snapshots rows are never overwritten. The snapshot
  captures the intelligence state at the moment of first detection.

No FK to signals table — signals are deleted/recreated on pipeline reruns;
a FK would cascade-delete historical snapshots. Natural composite key is used.

No FK to entity_market — resilience against entity deletion.

Schema version: 1 (snapshot_schema_version column). Bump when field semantics
change. Historical rows remain queryable by version for report methodology footnotes.

Fields:
  id                         UUID PK
  entity_id                  UUID (entity_market.id, no FK)
  entity_type                VARCHAR(32) — 'perfume' | 'brand'
  entity_canonical_name      TEXT — denormalized at capture time
  entity_brand_name          TEXT NULL — denormalized at capture time
  signal_type                VARCHAR(64) — 'breakout' | 'new_entry' | 'acceleration_spike' | 'reversal'
  detected_at                TIMESTAMPTZ — matches signals.detected_at
  pipeline_run_date          DATE — = detected_at::date
  market_score_at_detection  NUMERIC(10,4) NULL — composite_market_score
  growth_rate_at_detection   NUMERIC(10,4) NULL — growth_rate
  momentum_at_detection      NUMERIC(10,4) NULL — momentum
  acceleration_at_detection  NUMERIC(10,4) NULL — acceleration
  mention_count_at_detection NUMERIC(10,2) NULL — mention_count
  signal_strength            FLOAT NOT NULL — strength from signal dict
  signal_metadata            JSONB NULL — sanitized metadata_json from signal
  signal_threshold_version   INTEGER NOT NULL DEFAULT 1 — DATA0 lineage
  snapshot_schema_version    INTEGER NOT NULL DEFAULT 1 — schema provenance
  first_captured_at          TIMESTAMPTZ NOT NULL DEFAULT now()

Indexes:
  ix_sig_snap_entity_id       (entity_id)
  ix_sig_snap_entity_type     (entity_type)
  ix_sig_snap_signal_type     (signal_type)
  ix_sig_snap_detected_at     (detected_at)
  ix_sig_snap_pipeline_date   (pipeline_run_date)
  UNIQUE uq_sig_snapshot_entity_signal_detected (entity_id, entity_type, signal_type, detected_at)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_intelligence_snapshots",

        # --- Identity ---
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),

        # --- Entity ---
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False,
                  comment="entity_market.id — no FK for resilience against entity deletion"),
        sa.Column("entity_type", sa.String(32), nullable=False,
                  comment="perfume | brand — denormalized from entity_market"),
        sa.Column("entity_canonical_name", sa.Text(), nullable=False,
                  comment="Canonical name from entity_market, captured at snapshot time"),
        sa.Column("entity_brand_name", sa.Text(), nullable=True,
                  comment="Brand name from entity_market, captured at snapshot time (nullable)"),

        # --- Signal identity ---
        sa.Column("signal_type", sa.String(64), nullable=False,
                  comment="breakout | new_entry | acceleration_spike | reversal"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False,
                  comment="Matches signals.detected_at — the pipeline run timestamp for the date"),
        sa.Column("pipeline_run_date", sa.Date(), nullable=False,
                  comment="= detected_at::date — the date being processed"),

        # --- Market metrics at detection time (from entity_timeseries_daily) ---
        sa.Column("market_score_at_detection", sa.Numeric(10, 4), nullable=True,
                  comment="composite_market_score on the day of detection"),
        sa.Column("growth_rate_at_detection", sa.Numeric(10, 4), nullable=True,
                  comment="growth_rate on the day of detection (None for new_entry)"),
        sa.Column("momentum_at_detection", sa.Numeric(10, 4), nullable=True,
                  comment="momentum on the day of detection"),
        sa.Column("acceleration_at_detection", sa.Numeric(10, 4), nullable=True,
                  comment="acceleration on the day of detection"),
        sa.Column("mention_count_at_detection", sa.Numeric(10, 2), nullable=True,
                  comment="raw mention volume on the day of detection"),

        # --- Signal data ---
        sa.Column("signal_strength", sa.Float(), nullable=False, server_default="0.0",
                  comment="Detector strength score"),
        sa.Column("signal_metadata", JSONB(), nullable=True,
                  comment="Sanitized metadata_json from signal dict (growth_pct, momentum, etc.)"),

        # --- Versioning (DATA0 lineage) ---
        sa.Column("signal_threshold_version", sa.Integer(), nullable=False, server_default="1",
                  comment="DATA0 — version of the breakout detection threshold set"),
        sa.Column("snapshot_schema_version", sa.Integer(), nullable=False, server_default="1",
                  comment="SN1 — version of this snapshot schema; bump on semantic changes"),

        # --- Timestamps ---
        sa.Column("first_captured_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()"),
                  comment="When this snapshot was first written; immutable thereafter"),

        # --- Uniqueness (idempotency key) ---
        sa.UniqueConstraint(
            "entity_id", "entity_type", "signal_type", "detected_at",
            name="uq_sig_snapshot_entity_signal_detected",
        ),
    )

    # --- Indexes ---
    op.create_index("ix_sig_snap_entity_id",     "signal_intelligence_snapshots", ["entity_id"])
    op.create_index("ix_sig_snap_entity_type",   "signal_intelligence_snapshots", ["entity_type"])
    op.create_index("ix_sig_snap_signal_type",   "signal_intelligence_snapshots", ["signal_type"])
    op.create_index("ix_sig_snap_detected_at",   "signal_intelligence_snapshots", ["detected_at"])
    op.create_index("ix_sig_snap_pipeline_date", "signal_intelligence_snapshots", ["pipeline_run_date"])


def downgrade() -> None:
    op.drop_index("ix_sig_snap_pipeline_date", table_name="signal_intelligence_snapshots")
    op.drop_index("ix_sig_snap_detected_at",   table_name="signal_intelligence_snapshots")
    op.drop_index("ix_sig_snap_signal_type",   table_name="signal_intelligence_snapshots")
    op.drop_index("ix_sig_snap_entity_type",   table_name="signal_intelligence_snapshots")
    op.drop_index("ix_sig_snap_entity_id",     table_name="signal_intelligence_snapshots")
    op.drop_table("signal_intelligence_snapshots")
