"""add_observation_grain_to_incentive_scores

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-03 00:00:00.000000

Adds observation-grain columns to soa_incentive_scores: merchant_slug
(the real resolved retailer, vs. merchant_id which mirrored the always-
null soa_entities.merchant_id), price_observation_id (traces back to the
coding-stage soa_price_observations row), and scoring_grain
('legacy' | 'observation'). The 485 pre-existing rows get
scoring_grain='legacy' via the column default — never deleted, never
altered otherwise. See scoring/observation_scorer.py.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_incentive_scores", sa.Column("merchant_slug", sa.Text(), nullable=True))
    op.add_column(
        "soa_incentive_scores",
        sa.Column("price_observation_id", sa.Integer(), sa.ForeignKey("soa_price_observations.id"), nullable=True),
    )
    op.add_column(
        "soa_incentive_scores",
        sa.Column("scoring_grain", sa.Text(), nullable=False, server_default="legacy"),
    )
    op.create_check_constraint(
        "ck_soa_incentive_scores_scoring_grain",
        "soa_incentive_scores",
        "scoring_grain IN ('legacy','observation')",
    )
    op.create_index("ix_soa_incentive_scores_scoring_grain", "soa_incentive_scores", ["scoring_grain"])


def downgrade() -> None:
    op.drop_index("ix_soa_incentive_scores_scoring_grain", table_name="soa_incentive_scores")
    op.drop_constraint("ck_soa_incentive_scores_scoring_grain", "soa_incentive_scores", type_="check")
    op.drop_column("soa_incentive_scores", "scoring_grain")
    op.drop_column("soa_incentive_scores", "price_observation_id")
    op.drop_column("soa_incentive_scores", "merchant_slug")
