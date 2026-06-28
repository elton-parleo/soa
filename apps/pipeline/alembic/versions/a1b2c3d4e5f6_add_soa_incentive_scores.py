"""add_soa_incentive_scores

Revision ID: a1b2c3d4e5f6
Revises: 6f76d0019b6f
Create Date: 2026-06-20 00:00:00.000000

Adds soa_incentive_scores — Rung-0 fidelity scoring of agent-stated
incentives against Deal Engine ground truth. Does not touch
soa_coded_mentions or any other existing table. All columns nullable
except run_id/status so the table can be populated incrementally and
existing pipeline behavior is unaffected while INCENTIVE_SCORING_ENABLED
is false.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "6f76d0019b6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_incentive_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("soa_runs.id"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=True),
        sa.Column("merchant_id", sa.Integer(), nullable=True),
        sa.Column("stated_price", sa.Float(), nullable=True),
        sa.Column("claimed_net_price", sa.Float(), nullable=True),
        sa.Column("claimed_discount_value", sa.Float(), nullable=True),
        sa.Column("claimed_discount_pct", sa.Float(), nullable=True),
        sa.Column("claimed_terms", sa.JSON(), nullable=True),
        sa.Column("member_price_claimed", sa.Boolean(), nullable=True),
        sa.Column("subscription_offer_claimed", sa.Boolean(), nullable=True),
        sa.Column("ground_truth_true_cost", sa.Float(), nullable=True),
        sa.Column("ground_truth_applied_deals", sa.JSON(), nullable=True),
        sa.Column("ground_truth_confidence", sa.Float(), nullable=True),
        sa.Column("user_tier_name", sa.Text(), nullable=True),
        sa.Column("net_price_reflected", sa.Boolean(), nullable=True),
        sa.Column("net_price_accuracy", sa.Boolean(), nullable=True),
        sa.Column("term_fidelity", sa.Float(), nullable=True),
        sa.Column("member_price_reflected", sa.Boolean(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="scored"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('scored','ground_truth_unavailable','no_merchant_mapping','skipped')",
            name="ck_soa_incentive_scores_status",
        ),
    )
    op.create_index("ix_soa_incentive_scores_run_id", "soa_incentive_scores", ["run_id"])
    op.create_index("ix_soa_incentive_scores_entity_id", "soa_incentive_scores", ["entity_id"])
    op.create_index("ix_soa_incentive_scores_merchant_id", "soa_incentive_scores", ["merchant_id"])
    op.create_index("ix_soa_incentive_scores_status", "soa_incentive_scores", ["status"])


def downgrade() -> None:
    op.drop_index("ix_soa_incentive_scores_status", table_name="soa_incentive_scores")
    op.drop_index("ix_soa_incentive_scores_merchant_id", table_name="soa_incentive_scores")
    op.drop_index("ix_soa_incentive_scores_entity_id", table_name="soa_incentive_scores")
    op.drop_index("ix_soa_incentive_scores_run_id", table_name="soa_incentive_scores")
    op.drop_table("soa_incentive_scores")
