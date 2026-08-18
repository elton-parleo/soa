"""add_soa_cycle_shares

Revision ID: a1b2c3d4e5f6
Revises: 8c31844a4171
Create Date: 2026-08-18 00:00:00.000000

Shareable Full Analysis reports: a share link is an owner-initiated,
revocable, optionally-expiring token scoped to exactly one cycle — a
dedicated table rather than nullable columns on soa_cycles so a cycle
can support more than one link (rotation) without a future migration,
and so a revoke never has to guess which of several links it's
revoking. token uses the exact same scheme as soa_lite_requests.token
(uuid4 hex, generated app-side, unique, unguessable) — see
app/services/share_tokens.py, the one helper both paths call.

soa_public_share_views is a pure append-only read log for the public
endpoint's own per-IP rate limit (mirrors soa_lite_requests doubling as
its own rate-limit log in public_lite.py::_enforce_rate_limits) — no
domain meaning beyond "this ip_hash read this share at this time".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '8c31844a4171'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_cycle_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=False),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_soa_cycle_shares_cycle_id", "soa_cycle_shares", ["cycle_id"])
    op.create_index("ix_soa_cycle_shares_token", "soa_cycle_shares", ["token"], unique=True)

    op.create_table(
        "soa_public_share_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("share_id", sa.Integer(), sa.ForeignKey("soa_cycle_shares.id"), nullable=False),
        sa.Column("ip_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_soa_public_share_views_ip_hash_created_at", "soa_public_share_views", ["ip_hash", "created_at"])
    op.create_index("ix_soa_public_share_views_share_id", "soa_public_share_views", ["share_id"])


def downgrade() -> None:
    op.drop_index("ix_soa_public_share_views_share_id", table_name="soa_public_share_views")
    op.drop_index("ix_soa_public_share_views_ip_hash_created_at", table_name="soa_public_share_views")
    op.drop_table("soa_public_share_views")

    op.drop_index("ix_soa_cycle_shares_token", table_name="soa_cycle_shares")
    op.drop_index("ix_soa_cycle_shares_cycle_id", table_name="soa_cycle_shares")
    op.drop_table("soa_cycle_shares")
