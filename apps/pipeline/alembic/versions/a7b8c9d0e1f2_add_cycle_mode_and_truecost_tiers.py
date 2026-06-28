"""add_cycle_mode_and_truecost_tiers

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-28 00:00:00.000000

Adds cycle_mode (default 'query') and truecost_tiers (nullable JSON list of
tier names; a null entry means the non-member baseline) to soa_cycles.
Additive only — existing cycles default to cycle_mode='query' and behave
exactly as before. cycle_mode='truecost' is the new path consumed by
apps/pipeline/sweep/truecost_sweep.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_cycles",
        sa.Column("cycle_mode", sa.String(), nullable=False, server_default="query"),
    )
    op.add_column(
        "soa_cycles",
        sa.Column("truecost_tiers", sa.JSON(), nullable=True),
    )
    op.create_check_constraint(
        "ck_soa_cycles_cycle_mode",
        "soa_cycles",
        "cycle_mode IN ('query','truecost')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_soa_cycles_cycle_mode", "soa_cycles", type_="check")
    op.drop_column("soa_cycles", "truecost_tiers")
    op.drop_column("soa_cycles", "cycle_mode")
