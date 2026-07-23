"""add_soa_lite_scan_results_and_store_url

Revision ID: a6504712f219
Revises: 6fdb77471ebc
Create Date: 2026-07-22 00:00:00.000000

Adds soa_lite_scan_results — Agent Scan crawl output for a SoA Lite
request (score 0-100 across 8 dimensions, see apps/pipeline/scan/) — and
a nullable store_url column on soa_lite_requests to carry the visitor's
storefront URL into the scan. Both additive only; nothing here is read
or written by the existing Lite pipeline (apps/pipeline/worker.py,
apps/api/app/routers/public_lite.py) until a later stage wires it in.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a6504712f219"
down_revision: Union[str, None] = "6fdb77471ebc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_lite_requests", sa.Column("store_url", sa.Text(), nullable=True))

    op.create_table(
        "soa_lite_scan_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lite_request_id",
            sa.Integer(),
            sa.ForeignKey("soa_lite_requests.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("input_url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("total_score", sa.Integer(), nullable=True),
        sa.Column("integrity_capped", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("dimensions", sa.JSON(), nullable=True),
        sa.Column("pages_fetched", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'blocked', 'failed', 'skipped')",
            name="ck_soa_lite_scan_results_status",
        ),
    )
    op.create_index(
        "ix_soa_lite_scan_results_lite_request_id",
        "soa_lite_scan_results",
        ["lite_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_soa_lite_scan_results_lite_request_id", table_name="soa_lite_scan_results")
    op.drop_table("soa_lite_scan_results")
    op.drop_column("soa_lite_requests", "store_url")
