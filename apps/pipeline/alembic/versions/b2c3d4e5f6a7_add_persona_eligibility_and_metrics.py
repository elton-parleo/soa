"""add_persona_eligibility_and_metrics

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-20 00:00:00.000000

Adds persona eligibility state to soa_queries (membership_program,
tier_name, subscription_state, new_customer — all nullable, default null =
"no eligibility constraint" = today's behavior) and a new
soa_eligibility_metrics table for the eligibility-conditioned Rung-0
metrics (M1, M3). Does not touch soa_coded_mentions, soa_metrics_results,
or any existing column/table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Persona eligibility columns on soa_queries — all nullable.
    op.add_column("soa_queries", sa.Column("membership_program", sa.Text(), nullable=True))
    op.add_column("soa_queries", sa.Column("tier_name", sa.Text(), nullable=True))
    op.add_column("soa_queries", sa.Column("subscription_state", sa.Text(), nullable=True))
    op.add_column("soa_queries", sa.Column("new_customer", sa.Boolean(), nullable=True))

    op.create_check_constraint(
        "ck_soa_queries_subscription_state",
        "soa_queries",
        "subscription_state IS NULL OR subscription_state IN ('subscribed', 'not_subscribed')",
    )

    # 2. New table for eligibility-conditioned metrics.
    op.create_table(
        "soa_eligibility_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=False),
        sa.Column("slice_type", sa.Text(), nullable=False),
        sa.Column("slice_value", sa.Text(), nullable=False),
        sa.Column("total_eligible_runs", sa.Integer(), nullable=False),
        sa.Column("surfaced_eligible_count", sa.Integer(), nullable=False),
        sa.Column("considered_eligible_count", sa.Integer(), nullable=False),
        sa.Column("eligible_surfacing_rate", sa.Float(), nullable=True),
        sa.Column("incentive_consideration_rate", sa.Float(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "slice_type IN ('overall','category','stage','specificity','persona','platform')",
            name="ck_soa_eligibility_metrics_slice_type",
        ),
        sa.UniqueConstraint(
            "cycle_id", "entity_id", "slice_type", "slice_value",
            name="uq_soa_eligibility_metrics_slice",
        ),
    )
    op.create_index(
        "ix_soa_eligibility_metrics_cycle_id", "soa_eligibility_metrics", ["cycle_id"],
    )
    op.create_index(
        "ix_soa_eligibility_metrics_entity_id", "soa_eligibility_metrics", ["entity_id"],
    )
    op.create_index(
        "ix_soa_eligibility_metrics_cycle_entity_slice_type",
        "soa_eligibility_metrics",
        ["cycle_id", "entity_id", "slice_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_soa_eligibility_metrics_cycle_entity_slice_type",
        table_name="soa_eligibility_metrics",
    )
    op.drop_index("ix_soa_eligibility_metrics_entity_id", table_name="soa_eligibility_metrics")
    op.drop_index("ix_soa_eligibility_metrics_cycle_id", table_name="soa_eligibility_metrics")
    op.drop_table("soa_eligibility_metrics")

    op.drop_constraint("ck_soa_queries_subscription_state", "soa_queries", type_="check")
    op.drop_column("soa_queries", "new_customer")
    op.drop_column("soa_queries", "subscription_state")
    op.drop_column("soa_queries", "tier_name")
    op.drop_column("soa_queries", "membership_program")
