"""add_soa_scope_skus

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-20 00:00:00.000000

Adds soa_scope_skus — an optional SKU-level measurement scope nested under
entities. cycle_id and entity_id are both nullable so a SKU can exist
before being attached to a cycle/brand. Deal-Engine-reference columns
mirror the merchant_ref.py by-value pattern (no cross-DB FK) and are all
nullable.

Also adds two nullable columns to soa_incentive_scores — scope_sku_id (FK
to soa_scope_skus) and dealengine_listing_id — so a score row can be keyed
to a specific SKU instead of the existing brand x category path. Both
default to NULL; existing rows and the existing brand-level scoring path
are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_scope_skus",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=True),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=True),
        sa.Column("role", sa.Text(), nullable=False, server_default="target"),
        sa.Column("dealengine_listing_id", sa.Integer(), nullable=True),
        sa.Column("dealengine_catalog_product_id", sa.Integer(), nullable=True),
        sa.Column("merchant_slug", sa.Text(), nullable=True),
        sa.Column("merchant_sku", sa.Text(), nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("product_url", sa.Text(), nullable=True),
        sa.Column("listed_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('target', 'competitor')",
            name="ck_soa_scope_skus_role",
        ),
    )
    op.create_index("ix_soa_scope_skus_cycle_id", "soa_scope_skus", ["cycle_id"])
    op.create_index("ix_soa_scope_skus_entity_id", "soa_scope_skus", ["entity_id"])
    op.create_index(
        "ix_soa_scope_skus_dealengine_listing_id", "soa_scope_skus", ["dealengine_listing_id"],
    )

    op.add_column(
        "soa_incentive_scores",
        sa.Column("scope_sku_id", sa.Integer(), sa.ForeignKey("soa_scope_skus.id"), nullable=True),
    )
    op.add_column(
        "soa_incentive_scores",
        sa.Column("dealengine_listing_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_soa_incentive_scores_scope_sku_id", "soa_incentive_scores", ["scope_sku_id"],
    )
    op.create_index(
        "ix_soa_incentive_scores_dealengine_listing_id",
        "soa_incentive_scores",
        ["dealengine_listing_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_soa_incentive_scores_dealengine_listing_id", table_name="soa_incentive_scores")
    op.drop_index("ix_soa_incentive_scores_scope_sku_id", table_name="soa_incentive_scores")
    op.drop_column("soa_incentive_scores", "dealengine_listing_id")
    op.drop_column("soa_incentive_scores", "scope_sku_id")

    op.drop_index("ix_soa_scope_skus_dealengine_listing_id", table_name="soa_scope_skus")
    op.drop_index("ix_soa_scope_skus_entity_id", table_name="soa_scope_skus")
    op.drop_index("ix_soa_scope_skus_cycle_id", table_name="soa_scope_skus")
    op.drop_table("soa_scope_skus")
