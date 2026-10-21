"""soa_query_generation_jobs.archived_at: archive a study

Revision ID: a2c4e6f8b1d3
Revises: f7c2a9e4b1d6
Create Date: 2026-10-21

2L-1 (B3). Decision (Elton, Oct 21): "New study" stays the only way to change
a study's questions (an in-place edit would break week-over-week), and the
study list gets an archive. There is no soa_studies table: a study is its
generation job row (see the model), so the column lives there.

One nullable column, additive. No row is written: every study reads as not
archived until an operator archives it. Downgrade drops the column, which
loses only which studies were archived.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2c4e6f8b1d3"
down_revision: Union[str, None] = "f7c2a9e4b1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_query_generation_jobs",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True,
                  comment="When an operator archived the study (2L-1). NULL: not archived."),
    )


def downgrade() -> None:
    op.drop_column("soa_query_generation_jobs", "archived_at")
