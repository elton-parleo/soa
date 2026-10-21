"""soa_narratives: the console's one-line narratives

Revision ID: c8e2f4a6b1d3
Revises: a2c4e6f8b1d3
Create Date: 2026-10-21

2L-3. Decision (Elton, Oct 21): one model call per flagged answer and per
product row writes the line the console shows, from the facts the scorer
already has, checked before it is stored (soa_shared/narratives.py).

A side table, not a column: a product row is no stored row (True Value and
the Overview build it on read), so there is nothing to hang a column on. One
row per cycle and subject ('answer:run-<id>' or 'product:<key>') with the
facts digest it was written from, the model, the time, and each call's
answer and usage. The read serves a line only while its digest is the facts'
digest now.

Additive: a new table, no row written. The console serves `narrative: null`
until the worker or rescore_cycle.py --narratives writes a cycle's lines.
Downgrade drops the table, which loses only the lines (rescore rewrites them).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e2f4a6b1d3"
down_revision: Union[str, None] = "a2c4e6f8b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_narratives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False,
                  comment="'answer:run-<soa_runs.id>' or 'product:<True Value row key>'"),
        sa.Column("facts_digest", sa.Text(), nullable=False,
                  comment="sha256 of the facts the line was written from; served only while current"),
        sa.Column("line", sa.Text(), nullable=True, comment="The accepted line. NULL when dropped or null."),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True, comment="Why a line was dropped: the first failed check"),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("calls", sa.JSON(), nullable=True, comment="Each call's raw answer, usage and check"),
        sa.Column("written_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cycle_id", "subject", name="uq_soa_narratives_cycle_subject"),
        sa.CheckConstraint("status IN ('accepted','dropped','null')", name="ck_soa_narratives_status"),
    )
    op.create_index("ix_soa_narratives_cycle_id", "soa_narratives", ["cycle_id"])


def downgrade() -> None:
    op.drop_index("ix_soa_narratives_cycle_id", table_name="soa_narratives")
    op.drop_table("soa_narratives")
