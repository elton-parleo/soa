"""add_soa_playbook_findings_recommendations

Revision ID: c9d0e1f2a3b4
Revises: 9ca1aba348c4
Create Date: 2026-07-02 00:00:00.000000

Adds the three tables backing the AC3 Actions feature (v1):
  - soa_playbook — curated remediation library, seeded from
    docs/playbook_v1.md (apps/pipeline/scripts/seed_playbook.py).
  - soa_findings — deterministic detector output for a completed cycle.
  - soa_recommendations — findings grouped and prioritized by play.
Additive only; never touches existing tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "9ca1aba348c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_playbook",
        sa.Column("play_id", sa.Text(), primary_key=True),
        sa.Column("pillar", sa.Text(), nullable=False),
        sa.Column("failure_mode", sa.Text(), nullable=False),
        sa.Column("detection_trigger", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("play_text", sa.Text(), nullable=False),
        sa.Column("mechanism_text", sa.Text(), nullable=False),
        sa.Column("effort", sa.Text(), nullable=False),
        sa.Column("expected_impact_text", sa.Text(), nullable=False),
        sa.Column("evidence_spec", sa.Text(), nullable=False),
        sa.Column("detector_status", sa.Text(), nullable=False, server_default="not_implemented"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("owner IN ('brand','retailer','joint')", name="ck_soa_playbook_owner"),
        sa.CheckConstraint("effort IN ('low','medium','high')", name="ck_soa_playbook_effort"),
        sa.CheckConstraint(
            "detector_status IN ('implemented','not_implemented')",
            name="ck_soa_playbook_detector_status",
        ),
    )
    op.create_index("ix_soa_playbook_pillar", "soa_playbook", ["pillar"])

    op.create_table(
        "soa_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=True),
        sa.Column("play_id", sa.Text(), sa.ForeignKey("soa_playbook.play_id"), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=True),
        sa.Column("persona", sa.Text(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("severity", sa.Float(), nullable=False),
        sa.Column("cells_affected", sa.Integer(), nullable=False),
        sa.Column("metric_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_run_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("severity >= 0.0 AND severity <= 1.0", name="ck_soa_findings_severity_range"),
    )
    op.create_index("ix_soa_findings_cycle_id", "soa_findings", ["cycle_id"])
    op.create_index("ix_soa_findings_cycle_play", "soa_findings", ["cycle_id", "play_id"])
    op.create_index("ix_soa_findings_entity_id", "soa_findings", ["entity_id"])

    op.create_table(
        "soa_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=False),
        sa.Column("play_id", sa.Text(), sa.ForeignKey("soa_playbook.play_id"), nullable=False),
        sa.Column("finding_ids", sa.JSON(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column("suppressed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('proposed','accepted','in_progress','done','dismissed')",
            name="ck_soa_recommendations_status",
        ),
        sa.UniqueConstraint("cycle_id", "play_id", name="uq_soa_recommendations_cycle_play"),
    )
    op.create_index("ix_soa_recommendations_cycle_id", "soa_recommendations", ["cycle_id"])


def downgrade() -> None:
    op.drop_index("ix_soa_recommendations_cycle_id", table_name="soa_recommendations")
    op.drop_table("soa_recommendations")

    op.drop_index("ix_soa_findings_entity_id", table_name="soa_findings")
    op.drop_index("ix_soa_findings_cycle_play", table_name="soa_findings")
    op.drop_index("ix_soa_findings_cycle_id", table_name="soa_findings")
    op.drop_table("soa_findings")

    op.drop_index("ix_soa_playbook_pillar", table_name="soa_playbook")
    op.drop_table("soa_playbook")
