"""soa_merchant_revenue_inputs: the revenue model's inputs per org x merchant

Revision ID: e5b1d7f3a8c2
Revises: d2f6b8a4c1e9
Create Date: 2026-10-20

2I-9: the console's Impact screen models what wrong and missing answers cost
a merchant a year (sales in scope x AI share x measured shares x conversion
effect). The merchant enters its sales in scope there and may change the three
public parameters and the share of Lost the record can win back. One row per
org x merchant; a null field reads the public default (soa_shared/revenue.py),
a null scope reads as not entered. No row until someone saves on Impact.

Sales in scope is a customer's financial figure: served only on that
merchant's console reads, never on an operator-wide list.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b1d7f3a8c2"
down_revision: Union[str, None] = "d2f6b8a4c1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "soa_merchant_revenue_inputs",
        sa.Column("org_id", sa.Integer(), primary_key=True),
        sa.Column("merchant_slug", sa.Text(), primary_key=True),
        sa.Column("scope_value", sa.Numeric(), nullable=True),
        sa.Column("scope_display", sa.Text(), nullable=True),
        sa.Column("scope_source", sa.Text(), nullable=True),
        sa.Column("influence", sa.Float(), nullable=True),
        sa.Column("horizon", sa.Float(), nullable=True),
        sa.Column("penalty", sa.Float(), nullable=True),
        sa.Column("lost_gainable", sa.Float(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("soa_merchant_revenue_inputs")
