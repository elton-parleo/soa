"""add_pet_care_category_personas

Revision ID: d439b7309af4
Revises: b4c7e19d2a08
Create Date: 2026-09-29

Adds 'Pet Care' to ck_soa_queries_category and five Pet Care personas
to ck_soa_queries_persona so the pet care study seed can import.
Additive only: every existing value is preserved.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d439b7309af4"
down_revision: Union[str, None] = "b4c7e19d2a08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        "category = ANY (ARRAY["
        "'Skincare', 'Makeup', 'Fragrance', 'Haircare', "
        "'Cross-Category', 'Grooming', 'Oral Care', 'Baby Care', 'General', "
        "'Pet Care'"
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
        "'Eco-Conscious Parent', "
        "'New Pet Parent', 'Value-Conscious Pet Parent', "
        "'Health-Focused Pet Parent', 'Subscription / Replenishment Pet Parent', "
        "'Premium / Quality-First Pet Parent'"
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
        "'Oral Health Symptom Sufferer', "
        "'New / First-Time Parent', 'Value-Conscious Parent', "
        "'Sensitive-Skin Baby Parent', 'Subscription / Replenishment Parent', "
        "'Eco-Conscious Parent'"
        "])",
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
