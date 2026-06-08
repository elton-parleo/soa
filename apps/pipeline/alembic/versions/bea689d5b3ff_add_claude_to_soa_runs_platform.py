"""add_claude_to_soa_runs_platform

Revision ID: bea689d5b3ff
Revises: 2173cb184e80
Create Date: 2026-05-06 11:09:33.081432

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bea689d5b3ff'
down_revision: Union[str, None] = '2173cb184e80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing constraint (chatgpt, perplexity, gemini)
    op.drop_constraint('ck_soa_runs_platform', 'soa_runs', type_='check')
    # Re-create with claude added
    op.create_check_constraint(
        'ck_soa_runs_platform',
        'soa_runs',
        "platform IN ('chatgpt', 'perplexity', 'gemini', 'claude')",
    )


def downgrade() -> None:
    # Remove the updated constraint
    op.drop_constraint('ck_soa_runs_platform', 'soa_runs', type_='check')
    # Restore original constraint without claude
    op.create_check_constraint(
        'ck_soa_runs_platform',
        'soa_runs',
        "platform IN ('chatgpt', 'perplexity', 'gemini')",
    )
