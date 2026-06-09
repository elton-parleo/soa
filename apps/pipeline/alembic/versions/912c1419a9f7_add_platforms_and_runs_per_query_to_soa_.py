"""add_platforms_and_runs_per_query_to_soa_cycles

Revision ID: 912c1419a9f7
Revises: e90651a008de
Create Date: 2026-06-08 22:58:49.717319

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '912c1419a9f7'
down_revision: Union[str, None] = 'e90651a008de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'soa_cycles',
        sa.Column(
            'platforms',
            sa.JSON(),
            nullable=True,
            comment='List of platform ids e.g. ["chatgpt","gemini"]',
        ),
    )
    op.add_column(
        'soa_cycles',
        sa.Column(
            'runs_per_query',
            sa.Integer(),
            nullable=True,
            server_default='5',
            comment='Number of runs per query per platform',
        ),
    )


def downgrade() -> None:
    op.drop_column('soa_cycles', 'runs_per_query')
    op.drop_column('soa_cycles', 'platforms')
