"""soa_cycles: the console's stored Share of Algorithm score

Revision ID: f3b8d2a6c4e1
Revises: e1a7c3f9b2d4
Create Date: 2026-10-15

2C-3: GET /api/console/score computes the Audit's formula over a cycle's
loop data (app/services/console_score.py) and stores the result on the
cycle row with the scorer version it was computed under, so a read does
not recompute it. A row stored under an older version is recomputed on
its next read; a previous cycle stored under one reads "scored under vN,
re-score to compare".

Additive and nullable: safe to apply ahead of the deploy. The API reads
and writes the columns inside a try, so it also serves the score before
this is applied (recomputing on every read, storing nothing).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d2a6c4e1"
down_revision: Union[str, None] = "e1a7c3f9b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_cycles", sa.Column("share_of_algorithm", sa.JSON(), nullable=True))
    op.add_column("soa_cycles", sa.Column("share_of_algorithm_version", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("soa_cycles", "share_of_algorithm_version")
    op.drop_column("soa_cycles", "share_of_algorithm")
