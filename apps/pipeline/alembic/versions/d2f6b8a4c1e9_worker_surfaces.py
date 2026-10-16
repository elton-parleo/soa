"""soa_worker_surfaces: which runners the worker has a key for

Revision ID: d2f6b8a4c1e9
Revises: c7a3e9d1f5b2
Create Date: 2026-10-16

2I: the worker writes one row per runner at boot, {surface_id, configured}
and when it said so. Booleans only, never a key value. The API refuses a
dispatch naming a surface reported `configured: false`
(surface_not_configured) and serves the rows in /api/console/surfaces, so
the console's run dialog checks every grounded surface the worker can run.

Empty until the worker restarts on this revision. An empty table refuses
nothing: a surface with no row is not known to be unconfigured.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2f6b8a4c1e9"
down_revision: Union[str, None] = "c7a3e9d1f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_worker_surfaces",
        sa.Column("surface_id", sa.Text(), primary_key=True),
        sa.Column("configured", sa.Boolean(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("soa_worker_surfaces")
