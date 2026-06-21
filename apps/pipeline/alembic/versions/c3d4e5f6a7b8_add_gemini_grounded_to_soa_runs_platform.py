"""add_gemini_grounded_to_soa_runs_platform

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-20 00:00:00.000000

Adds 'gemini_grounded' to the soa_runs.platform CHECK constraint, mirroring
the pattern used in bea689d5b3ff_add_claude_to_soa_runs_platform.py. Keeps
all existing values — only additive.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing constraint (chatgpt, perplexity, gemini, claude)
    op.drop_constraint('ck_soa_runs_platform', 'soa_runs', type_='check')
    # Re-create with gemini_grounded added
    op.create_check_constraint(
        'ck_soa_runs_platform',
        'soa_runs',
        "platform IN ('chatgpt', 'perplexity', 'gemini', 'claude', 'gemini_grounded')",
    )


def downgrade() -> None:
    # Remove the updated constraint
    op.drop_constraint('ck_soa_runs_platform', 'soa_runs', type_='check')
    # Restore constraint without gemini_grounded
    op.create_check_constraint(
        'ck_soa_runs_platform',
        'soa_runs',
        "platform IN ('chatgpt', 'perplexity', 'gemini', 'claude')",
    )
