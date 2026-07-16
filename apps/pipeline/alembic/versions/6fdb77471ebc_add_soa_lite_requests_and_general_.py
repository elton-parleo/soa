"""add_soa_lite_requests_and_general_category

Revision ID: 6fdb77471ebc
Revises: c5d6e7f8a9b0
Create Date: 2026-07-15 00:00:00.000000

Adds soa_lite_requests — the orchestration state machine and lead-capture
record for "SoA Lite", the public unauthenticated lead-gen flow (visitor
enters a brand + up to 2 competitors, gets a token-gated report). Additive
only; never touched by the existing authenticated pipeline.

Also adds 'General' to ck_soa_queries_category, since Lite submissions can
be arbitrary brands outside the curated verticals — mirrors the pattern in
8d154bad5968 (Baby Care).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "6fdb77471ebc"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_lite_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("brand_name", sa.Text(), nullable=False),
        sa.Column("competitor_names", sa.JSON(), nullable=True),
        sa.Column("brand_entity_id", sa.Integer(), sa.ForeignKey("soa_entities.id"), nullable=True),
        sa.Column("competitor_entity_ids", sa.JSON(), nullable=True),
        sa.Column("study_type", sa.Text(), nullable=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'generating', 'running', 'complete', 'failed')",
            name="ck_soa_lite_requests_status",
        ),
    )
    op.create_index("ix_soa_lite_requests_status", "soa_lite_requests", ["status"])
    op.create_index(
        "ix_soa_lite_requests_ip_hash_created_at",
        "soa_lite_requests",
        ["ip_hash", "created_at"],
    )
    op.create_index(
        "ix_soa_lite_requests_organization_id",
        "soa_lite_requests",
        ["organization_id"],
    )

    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        "category = ANY (ARRAY["
        "'Skincare', 'Makeup', 'Fragrance', 'Haircare', "
        "'Cross-Category', 'Grooming', 'Oral Care', 'Baby Care', 'General'"
        "])",
    )


def downgrade() -> None:
    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        "category = ANY (ARRAY["
        "'Skincare', 'Makeup', 'Fragrance', 'Haircare', "
        "'Cross-Category', 'Grooming', 'Oral Care', 'Baby Care'"
        "])",
    )

    op.drop_index("ix_soa_lite_requests_organization_id", table_name="soa_lite_requests")
    op.drop_index("ix_soa_lite_requests_ip_hash_created_at", table_name="soa_lite_requests")
    op.drop_index("ix_soa_lite_requests_status", table_name="soa_lite_requests")
    op.drop_table("soa_lite_requests")
