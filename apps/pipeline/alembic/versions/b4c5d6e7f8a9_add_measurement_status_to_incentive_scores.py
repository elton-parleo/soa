"""add_measurement_status_to_incentive_scores

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-15 00:00:00.000000

Adds the validity gate: ground_truth_available_deals (the not-applied
candidate deals — together with ground_truth_applied_deals, a complete
partition of every deal the engine evaluated) and measurement_status
('measured' | 'unmeasured' | null). When the Deal Engine has no deal
data for a merchant/category at all, it echoes the input price back as
true_cost, which looks like a perfect 0% price gap but isn't an actual
measurement — this column lets Net Price Accuracy / Offer Completeness
and TVD-01/TVD-03 tell the difference. Additive only; existing rows get
measurement_status=NULL (never computed for them) rather than a guess.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_incentive_scores", sa.Column("ground_truth_available_deals", sa.JSON(), nullable=True))
    op.add_column("soa_incentive_scores", sa.Column("measurement_status", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_soa_incentive_scores_measurement_status",
        "soa_incentive_scores",
        "measurement_status IS NULL OR measurement_status IN ('measured','unmeasured')",
    )
    op.create_index("ix_soa_incentive_scores_measurement_status", "soa_incentive_scores", ["measurement_status"])


def downgrade() -> None:
    op.drop_index("ix_soa_incentive_scores_measurement_status", table_name="soa_incentive_scores")
    op.drop_constraint("ck_soa_incentive_scores_measurement_status", "soa_incentive_scores", type_="check")
    op.drop_column("soa_incentive_scores", "measurement_status")
    op.drop_column("soa_incentive_scores", "ground_truth_available_deals")
