"""add_search_triggered_to_soa_runs

Revision ID: 1fe6f03a1c1c
Revises: 0001
Create Date: 2026-05-05 11:29:00.036809

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1fe6f03a1c1c'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'soa_runs',
        sa.Column(
            'search_triggered',
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('soa_runs', 'search_triggered')
