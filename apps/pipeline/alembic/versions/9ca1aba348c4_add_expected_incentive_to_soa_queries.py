"""add_expected_incentive_to_soa_queries

Revision ID: 9ca1aba348c4
Revises: 8d154bad5968
Create Date: 2026-06-30 23:08:18.466976

Adds nullable expected_incentive column (Low/Mixed/High) to soa_queries.
Records whether a consumer at a given stage/persona would expect price/promo
information in a good answer. Set by curation/seed; not by API or generation.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9ca1aba348c4"
down_revision: Union[str, None] = "8d154bad5968"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_queries",
        sa.Column("expected_incentive", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_soa_queries_expected_incentive",
        "soa_queries",
        "expected_incentive IN ('Low', 'Mixed', 'High')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_soa_queries_expected_incentive", "soa_queries", type_="check")
    op.drop_column("soa_queries", "expected_incentive")
