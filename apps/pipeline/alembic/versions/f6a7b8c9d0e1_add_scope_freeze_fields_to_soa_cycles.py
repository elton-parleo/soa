"""add_scope_freeze_fields_to_soa_cycles

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-21 00:00:00.000000

Adds scope_frozen_at (nullable DateTime) and scope_is_custom (Boolean,
default false) to soa_cycles, supporting the entity-template /
cycle-snapshot scope resolution rules in soa_shared/scope_resolution.py.
soa_scope_skus is unchanged. Additive only — existing cycles get
scope_frozen_at=NULL, scope_is_custom=false, which is exactly today's
behavior (materialized-at-creation / inherited-live per
PLANNED_CYCLE_SCOPE_RESYNC).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_cycles",
        sa.Column("scope_frozen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "soa_cycles",
        sa.Column("scope_is_custom", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("soa_cycles", "scope_is_custom")
    op.drop_column("soa_cycles", "scope_frozen_at")
