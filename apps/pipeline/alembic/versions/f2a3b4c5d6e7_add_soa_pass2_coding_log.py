"""add_soa_pass2_coding_log

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-03 00:00:00.000000

Adds soa_pass2_coding_log — a sentinel marking a run as pass-2-processed
regardless of whether it produced any soa_price_observations /
soa_citations rows, so ResponseCoderV2's idempotency check doesn't
re-query the API for runs that legitimately found nothing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_pass2_coding_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("soa_runs.id"), nullable=False),
        sa.Column("coding_pass_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("observations_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("citations_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "coding_pass_version", name="uq_soa_pass2_coding_log_run_version"),
    )
    op.create_index("ix_soa_pass2_coding_log_run_id", "soa_pass2_coding_log", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_soa_pass2_coding_log_run_id", table_name="soa_pass2_coding_log")
    op.drop_table("soa_pass2_coding_log")
