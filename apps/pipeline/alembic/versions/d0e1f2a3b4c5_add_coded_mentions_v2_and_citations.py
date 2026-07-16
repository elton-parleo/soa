"""add_coded_mentions_v2_and_citations

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-02 00:00:00.000000

Adds soa_coded_mentions_v2 (pass-2 re-coding output, additive — pass 1's
soa_coded_mentions is never touched) and soa_citations (per-run cited
sources extracted from raw_response text). See
apps/pipeline/scripts/recode_cycle_pass2.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_coded_mentions_v2",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("soa_runs.id"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=True),
        sa.Column("mentioned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("strength", sa.Text(), nullable=True),
        sa.Column("deal_cited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deal_types", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("coded_by", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("stated_price", sa.Float(), nullable=True),
        sa.Column("claimed_net_price", sa.Float(), nullable=True),
        sa.Column("claimed_discount_value", sa.Float(), nullable=True),
        sa.Column("claimed_discount_pct", sa.Float(), nullable=True),
        sa.Column("claimed_terms", sa.JSON(), nullable=True),
        sa.Column("member_price_claimed", sa.Boolean(), nullable=True),
        sa.Column("subscription_offer_claimed", sa.Boolean(), nullable=True),
        sa.Column("merchant_name", sa.Text(), nullable=True),
        sa.Column("merchant_slug", sa.Text(), nullable=True),
        sa.Column("coding_pass_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "strength IS NULL OR strength IN ('Primary','Positive','Neutral','Negative')",
            name="ck_soa_coded_mentions_v2_strength",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_soa_coded_mentions_v2_confidence_range",
        ),
        sa.UniqueConstraint(
            "run_id", "entity_id", "coding_pass_version",
            name="uq_soa_coded_mentions_v2_run_entity_version",
        ),
    )
    op.create_index("ix_soa_coded_mentions_v2_run_entity", "soa_coded_mentions_v2", ["run_id", "entity_id"])
    op.create_index("ix_soa_coded_mentions_v2_entity_id", "soa_coded_mentions_v2", ["entity_id"])

    op.create_table(
        "soa_citations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("soa_runs.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("coding_pass_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_soa_citations_run_id", "soa_citations", ["run_id"])
    op.create_index("ix_soa_citations_domain", "soa_citations", ["domain"])


def downgrade() -> None:
    op.drop_index("ix_soa_citations_domain", table_name="soa_citations")
    op.drop_index("ix_soa_citations_run_id", table_name="soa_citations")
    op.drop_table("soa_citations")

    op.drop_index("ix_soa_coded_mentions_v2_entity_id", table_name="soa_coded_mentions_v2")
    op.drop_index("ix_soa_coded_mentions_v2_run_entity", table_name="soa_coded_mentions_v2")
    op.drop_table("soa_coded_mentions_v2")
