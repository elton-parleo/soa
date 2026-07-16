"""add_missing_observation_grain_indexes

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-15 00:00:00.000000

Two columns added by the observation-grain migrations declare
index=True on their ORM Column but the migrations that added them
never created the index, caught by `alembic check` against a
from-scratch DB:

  - soa_price_observations.run_id (added in e1f2a3b4c5d6) — that
    migration only created the composite (run_id, entity_id) index,
    never a standalone one.
  - soa_incentive_scores.price_observation_id (added in
    a3b4c5d6e7f8) — that migration added the column with no index at
    all.

Purely additive; makes the DB match what the models already declare.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_soa_price_observations_run_id", "soa_price_observations", ["run_id"])
    op.create_index("ix_soa_incentive_scores_price_observation_id", "soa_incentive_scores", ["price_observation_id"])


def downgrade() -> None:
    op.drop_index("ix_soa_incentive_scores_price_observation_id", table_name="soa_incentive_scores")
    op.drop_index("ix_soa_price_observations_run_id", table_name="soa_price_observations")
