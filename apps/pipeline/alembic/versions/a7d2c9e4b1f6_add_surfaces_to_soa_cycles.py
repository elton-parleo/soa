"""soa_cycles.surfaces: the resolved surface of each platform the cycle runs

Revision ID: a7d2c9e4b1f6
Revises: f3b8d2a6c4e1
Create Date: 2026-10-15

2D: a cycle stores the surface ids it runs, resolved at creation
(soa_shared/surfaces.resolve), in `platforms`, and here {id: surface}
beside them, e.g. {"chatgpt": "grounded_api", "gemini_api": "api"}.
Before 2D an alias ("gemini") was stored and resolved only when the cycle
ran, which is how cycle 229 has "gemini" on the cycle and its runs on
grounded_api while the September cycle's "gemini" runs are on api.

Additive and nullable: safe to apply ahead of the deploy. Not mapped on
SoaCycle; soa_shared/cycle_creation.store_surfaces writes it only when the
column exists, so cycles are still created before this is applied. Existing
rows are not backfilled (scripts/report_surface_drift.py reports them).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2c9e4b1f6"
down_revision: Union[str, None] = "f3b8d2a6c4e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_cycles", sa.Column("surfaces", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("soa_cycles", "surfaces")
