"""soa_queries.tier admits comparison

Revision ID: f7c2a9e4b1d6
Revises: e5b1d7f3a8c2
Create Date: 2026-10-21

2K-1 (E29): the comparison tier. A study generated with the brand box on
tags its Comparison-stage questions `comparison` ("Pampers vs Huggies for
newborns"): they name the brand and a rival and ask which to choose, so they
are brand-choice questions, counted in Lost and the first-pick tiles.

`tier` is a text column, but ck_soa_queries_tier (a9f3c21b7e40) lists the
four tiers literally, so Postgres would refuse the new value. This replaces
the constraint with one that admits the five. No column, no row written.

Downgrade refuses while any question carries the tier, rather than leaving
the table half-migrated.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7c2a9e4b1d6"
down_revision: Union[str, None] = "e5b1d7f3a8c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Literal, not interpolated from application code: a migration records
# what the database was asked to accept on the day it ran.
OLD = ("tier IS NULL OR tier IN "
       "('brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control')")
NEW = ("tier IS NULL OR tier IN "
       "('brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control', 'comparison')")


def upgrade() -> None:
    op.drop_constraint("ck_soa_queries_tier", "soa_queries", type_="check")
    op.create_check_constraint("ck_soa_queries_tier", "soa_queries", NEW)


def downgrade() -> None:
    blocking = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM soa_queries WHERE tier = 'comparison'")).scalar()
    if blocking:
        raise RuntimeError(
            f"refusing to downgrade: {blocking} question(s) carry the comparison tier, which the "
            f"narrowed constraint would reject. Retag or remove them first.")
    op.drop_constraint("ck_soa_queries_tier", "soa_queries", type_="check")
    op.create_check_constraint("ck_soa_queries_tier", "soa_queries", OLD)
