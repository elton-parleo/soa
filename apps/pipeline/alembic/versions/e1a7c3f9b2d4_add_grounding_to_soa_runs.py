"""add grounding to soa_runs

Revision ID: e1a7c3f9b2d4
Revises: d8f1a3c5e7b9
Create Date: 2026-10-14

retrieved_sources holds source URLs only. For Gemini those are opaque
vertexaisearch redirects, and no platform's URL list says which part of
the answer a source backs. grounding keeps what each platform does say:
each source's title and domain, and the answer spans each one supports
(runners/grounding.py). The brand-direct classifier reads it to ground a
claim on a source the answer never named in its text.

Additive and nullable: safe to apply ahead of the deploy.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1a7c3f9b2d4"
down_revision: Union[str, None] = "d8f1a3c5e7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_runs", sa.Column("grounding", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("soa_runs", "grounding")
