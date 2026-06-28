"""add_retrieved_sources_to_soa_runs

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-20 00:00:01.000000

Adds a nullable retrieved_sources JSON column to soa_runs to record
grounding/search source URLs (OpenAI web_search items, Gemini grounding
metadata, Perplexity citations) where the platform exposes them. NULL
elsewhere — existing rows and runners that do not populate it are
unaffected. Seeds source attribution (M26).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_runs", sa.Column("retrieved_sources", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("soa_runs", "retrieved_sources")
