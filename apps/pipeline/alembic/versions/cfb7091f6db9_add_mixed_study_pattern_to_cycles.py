"""add_mixed_study_pattern_to_cycles

Revision ID: cfb7091f6db9
Revises: 18438697e926
Create Date: 2026-05-19 07:09:59.648459

Adds 'mixed' as a valid value for soa_cycles.study_pattern so that a
single cycle can span queries with multiple study_pattern values
(e.g. brand_vs_brand + brand_at_retail).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cfb7091f6db9"
down_revision: Union[str, None] = "18438697e926"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safety: normalise any rows that somehow have an unrecognised value
    op.execute("""
        UPDATE soa_cycles
        SET study_pattern = 'brand_vs_brand'
        WHERE study_pattern NOT IN (
            'retailer',
            'brand_at_retail',
            'brand_vs_brand'
        )
        AND study_pattern IS NOT NULL
    """)

    op.drop_constraint("ck_soa_cycles_study_pattern", "soa_cycles", type_="check")

    op.create_check_constraint(
        "ck_soa_cycles_study_pattern",
        "soa_cycles",
        (
            "study_pattern IN ("
            "'retailer',"
            "'brand_at_retail',"
            "'brand_vs_brand',"
            "'mixed'"
            ")"
        ),
    )


def downgrade() -> None:
    # Move any 'mixed' rows to a safe value before restoring the old constraint
    op.execute("""
        UPDATE soa_cycles
        SET study_pattern = 'brand_vs_brand'
        WHERE study_pattern = 'mixed'
    """)

    op.drop_constraint("ck_soa_cycles_study_pattern", "soa_cycles", type_="check")

    op.create_check_constraint(
        "ck_soa_cycles_study_pattern",
        "soa_cycles",
        (
            "study_pattern IN ("
            "'retailer',"
            "'brand_at_retail',"
            "'brand_vs_brand'"
            ")"
        ),
    )
