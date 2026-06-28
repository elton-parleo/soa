"""add_soa_truecost_snapshots

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-28 00:00:01.000000

Adds soa_truecost_snapshots — one row per (scope SKU x tier) captured by a
'truecost' cycle's Deal Engine sweep (apps/pipeline/sweep/truecost_sweep.py).
Additive only; never populated by the existing query/coding pipeline.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_truecost_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=False),
        sa.Column("scope_sku_id", sa.Integer(), sa.ForeignKey("soa_scope_skus.id"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=True),
        sa.Column("dealengine_listing_id", sa.Integer(), nullable=True),
        sa.Column("merchant_slug", sa.Text(), nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("user_tier_name", sa.Text(), nullable=True),
        sa.Column("listed_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("true_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_savings", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_points_earned", sa.Integer(), nullable=True),
        sa.Column("applied_deals", sa.JSON(), nullable=True),
        sa.Column("available_deals", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("price_was_refreshed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("price_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="captured"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('captured', 'ground_truth_unavailable')",
            name="ck_soa_truecost_snapshots_status",
        ),
    )
    op.create_index("ix_soa_truecost_snapshots_cycle_id", "soa_truecost_snapshots", ["cycle_id"])
    op.create_index("ix_soa_truecost_snapshots_scope_sku_id", "soa_truecost_snapshots", ["scope_sku_id"])
    op.create_index(
        "ix_soa_truecost_snapshots_dealengine_listing_id",
        "soa_truecost_snapshots",
        ["dealengine_listing_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_soa_truecost_snapshots_dealengine_listing_id", table_name="soa_truecost_snapshots")
    op.drop_index("ix_soa_truecost_snapshots_scope_sku_id", table_name="soa_truecost_snapshots")
    op.drop_index("ix_soa_truecost_snapshots_cycle_id", table_name="soa_truecost_snapshots")
    op.drop_table("soa_truecost_snapshots")
