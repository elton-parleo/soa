"""add_baby_care_category_personas_awareness_stage

Revision ID: 8d154bad5968
Revises: b8c9d0e1f2a3
Create Date: 2026-06-30 22:15:39.996417

Adds 'Baby Care' to ck_soa_queries_category,
'Awareness' (top-of-funnel) to ck_soa_queries_stage, and
five Baby Care personas to ck_soa_queries_persona
to support the first non-beauty vertical (Pampers).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "8d154bad5968"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        "category = ANY (ARRAY["
        "'Skincare', 'Makeup', 'Fragrance', 'Haircare', "
        "'Cross-Category', 'Grooming', 'Oral Care', 'Baby Care'"
        "])",
    )

    op.drop_constraint("ck_soa_queries_stage", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_stage",
        "soa_queries",
        "stage = ANY (ARRAY["
        "'Awareness', 'Research', 'Comparison', 'Ready to Buy'"
        "])",
    )

    op.drop_constraint("ck_soa_queries_persona", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_persona",
        "soa_queries",
        "persona = ANY (ARRAY["
        "'Casual / Gift Buyer', 'Value-Conscious', 'Beauty Enthusiast', "
        "'Problem-Skin Sufferer', 'Eco-Conscious / Minimalist', "
        "'Oral Health Symptom Sufferer', "
        "'New / First-Time Parent', 'Value-Conscious Parent', "
        "'Sensitive-Skin Baby Parent', 'Subscription / Replenishment Parent', "
        "'Eco-Conscious Parent'"
        "])",
    )


def downgrade() -> None:
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

    op.drop_constraint("ck_soa_queries_stage", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_stage",
        "soa_queries",
        "stage = ANY (ARRAY["
        "'Research', 'Comparison', 'Ready to Buy'"
        "])",
    )

    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        "category = ANY (ARRAY["
        "'Skincare', 'Makeup', 'Fragrance', 'Haircare', "
        "'Cross-Category', 'Grooming', 'Oral Care'"
        "])",
    )
