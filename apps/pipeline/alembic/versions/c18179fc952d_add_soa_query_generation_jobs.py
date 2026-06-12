"""add_soa_query_generation_jobs

Revision ID: c18179fc952d
Revises: 912c1419a9f7
Create Date: 2026-06-12 10:28:09.783031

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c18179fc952d'
down_revision: Union[str, None] = '912c1419a9f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'soa_query_generation_jobs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('study_type', sa.String(), nullable=False, unique=True),
        sa.Column('study_name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_count', sa.Integer(), nullable=False),
        sa.Column('created_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        'ck_generation_jobs_status',
        'soa_query_generation_jobs',
        "status IN ('pending', 'running', 'complete', 'failed')",
    )

    op.create_index(
        'ix_generation_jobs_status',
        'soa_query_generation_jobs',
        ['status'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_generation_jobs_status',
        table_name='soa_query_generation_jobs',
    )
    op.drop_constraint(
        'ck_generation_jobs_status',
        'soa_query_generation_jobs',
        type_='check',
    )
    op.drop_table('soa_query_generation_jobs')
