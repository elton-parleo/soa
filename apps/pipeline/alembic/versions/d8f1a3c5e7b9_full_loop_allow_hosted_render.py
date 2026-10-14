"""full loop: remember allow_hosted_render for the worker

Revision ID: d8f1a3c5e7b9
Revises: c4e2b7d9a1f3
Create Date: 2026-10-14

POST /api/full-loop no longer calls supply inside the request: it records
the press and the worker makes supply's POST (fullloop/coordinator.py). The
request's allow_hosted_render has to survive until then, so it is stored.

Additive, with a server default: safe to apply ahead of the deploy.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8f1a3c5e7b9"
down_revision: Union[str, None] = "c4e2b7d9a1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_full_loop_requests",
                  sa.Column("allow_hosted_render", sa.Boolean(), nullable=False,
                            server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("soa_full_loop_requests", "allow_hosted_render")
