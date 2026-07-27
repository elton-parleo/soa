"""add_report_email_sent_at_to_soa_lite_requests

Revision ID: e1d6eba13226
Revises: a6504712f219
Create Date: 2026-07-27 00:00:00.000000

Stage 12 (E3): adds a nullable report_email_sent_at timestamptz to
soa_lite_requests — set once the "your report is ready" email has been
sent, so apps/pipeline/worker.py::_sweep_lite_completions can check
(status='complete' AND email IS NOT NULL AND report_email_sent_at IS
NULL) on every sweep pass to send exactly once, retrying a transient
send failure on the next pass rather than losing it. Purely additive;
nothing existing reads or writes this column until this stage wires it
in (apps/pipeline/email_sender.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1d6eba13226"
down_revision: Union[str, None] = "a6504712f219"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_lite_requests",
        sa.Column("report_email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soa_lite_requests", "report_email_sent_at")
