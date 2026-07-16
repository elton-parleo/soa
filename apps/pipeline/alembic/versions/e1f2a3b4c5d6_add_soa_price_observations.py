"""add_soa_price_observations

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-03 00:00:00.000000

Adds soa_price_observations — the corrected, observation-grain pass-2
table (one row per extracted price/offer observation, not one per
entity). Supersedes soa_coded_mentions_v2 from the immediately prior
migration, which used the wrong grain (one scalar price/merchant pair
per entity per run) and was never used to write cycle data the app
depends on. soa_coded_mentions_v2 is deliberately left in place rather
than dropped — see apps/pipeline/alembic/env.py's SOA_TABLES comment.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_price_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("soa_runs.id"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=False),
        sa.Column("stated_price", sa.Float(), nullable=True),
        sa.Column("claimed_net_price", sa.Float(), nullable=True),
        sa.Column("claimed_discount_value", sa.Float(), nullable=True),
        sa.Column("claimed_discount_pct", sa.Float(), nullable=True),
        sa.Column("claimed_terms", sa.JSON(), nullable=True),
        sa.Column("member_price_claimed", sa.Boolean(), nullable=True),
        sa.Column("subscription_offer_claimed", sa.Boolean(), nullable=True),
        sa.Column("merchant_name", sa.Text(), nullable=True),
        sa.Column("merchant_slug", sa.Text(), nullable=True),
        sa.Column("attribution_status", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("coding_pass_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "attribution_status IN ('mapped','unmapped','unattributed','brand_self_reference')",
            name="ck_soa_price_observations_attribution_status",
        ),
    )
    op.create_index("ix_soa_price_observations_run_entity", "soa_price_observations", ["run_id", "entity_id"])
    op.create_index("ix_soa_price_observations_entity_id", "soa_price_observations", ["entity_id"])
    op.create_index("ix_soa_price_observations_attribution_status", "soa_price_observations", ["attribution_status"])


def downgrade() -> None:
    op.drop_index("ix_soa_price_observations_attribution_status", table_name="soa_price_observations")
    op.drop_index("ix_soa_price_observations_entity_id", table_name="soa_price_observations")
    op.drop_index("ix_soa_price_observations_run_entity", table_name="soa_price_observations")
    op.drop_table("soa_price_observations")
