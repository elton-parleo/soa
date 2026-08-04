"""add_events_to_soa_lite_requests

Revision ID: 8a7471e2aa94
Revises: 85fb82d3cd76
Create Date: 2026-08-04 00:00:00.000000

Run-manifest event contract (Part 1): adds a NOT NULL, server-defaulted
'[]' JSON events column to soa_lite_requests — an append-only log of
{seq, ts, kind: 'log'|'done'|'state', task, text, chips?} written
incrementally by worker.py/run_orchestrator.py/orchestrator/pipeline.py
as each stage of a run progresses (see apps/pipeline/lite_events.py).
Purely additive: the status endpoint (apps/api/app/routers/
public_lite.py) passes this straight through as an optional field, and
every row that predates this stage keeps its server-defaulted '[]' —
the status page's fallback view renders on an empty array exactly like
a pre-deploy run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8a7471e2aa94"
down_revision: Union[str, None] = "85fb82d3cd76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_lite_requests",
        sa.Column("events", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("soa_lite_requests", "events")
