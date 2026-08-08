"""add_soa_demo_requests

Revision ID: b3c9f1a2d4e6
Revises: 8a7471e2aa94
Create Date: 2026-08-08 00:00:00.000000

Leadgen session: adds soa_demo_requests, the lead-capture table behind
the new RequestFormModal on the audit landing + report ("Book your
walkthrough" / "Talk to us about TrueSync"). Purely additive, never
touched by the existing pipeline. ip_hash mirrors soa_lite_requests'
column of the same name (sha256 of the client IP, never the raw
address) — needed so the API's per-IP rate limit can be DB-backed,
consistent with the existing public_lite.py guard, rather than relying
on in-process memory the Vercel deployment can't guarantee persists
between invocations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3c9f1a2d4e6"
down_revision: Union[str, None] = "8a7471e2aa94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_demo_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("brand_name", sa.Text(), nullable=True),
        sa.Column("report_token", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_soa_demo_requests_created_at", "soa_demo_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_soa_demo_requests_created_at", table_name="soa_demo_requests")
    op.drop_table("soa_demo_requests")
