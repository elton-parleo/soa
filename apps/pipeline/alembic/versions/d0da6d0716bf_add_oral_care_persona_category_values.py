"""add_oral_care_persona_category_values

Revision ID: d0da6d0716bf
Revises: 4daf78023c67
Create Date: 2026-05-19 14:00:00.000000

Adds 'Oral Care' to ck_soa_queries_category and
'Oral Health Symptom Sufferer' to ck_soa_queries_persona
to support brand_oral_b study queries.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d0da6d0716bf"
down_revision: Union[str, None] = "4daf78023c67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        "category = ANY (ARRAY["
        "'Skincare', 'Makeup', 'Fragrance', 'Haircare', "
        "'Cross-Category', 'Grooming', 'Oral Care'"
        "])",
    )

    op.drop_constraint("ck_soa_queries_persona", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_persona",
        "soa_queries",
        "persona = ANY (ARRAY["
        "'Casual / Gift Buyer', 'Value-Conscious', 'Beauty Enthusiast', "
        "'Problem-Skin Sufferer', 'Eco-Conscious / Minimalist', "
        "'Oral Health Symptom Sufferer'"
        "])",
    )


def downgrade() -> None:
    op.drop_constraint("ck_soa_queries_persona", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_persona",
        "soa_queries",
        "persona = ANY (ARRAY["
        "'Casual / Gift Buyer', 'Value-Conscious', 'Beauty Enthusiast', "
        "'Problem-Skin Sufferer', 'Eco-Conscious / Minimalist'"
        "])",
    )

    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        "category = ANY (ARRAY["
        "'Skincare', 'Makeup', 'Fragrance', 'Haircare', "
        "'Cross-Category', 'Grooming'"
        "])",
    )
