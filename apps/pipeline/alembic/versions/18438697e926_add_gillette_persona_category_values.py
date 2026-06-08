"""add_gillette_persona_category_values

Revision ID: 18438697e926
Revises: 86e7d3e85de5
Create Date: 2026-05-18

Expands soa_queries CheckConstraints to support Gillette grooming queries:
  - persona: adds 'Problem-Skin Sufferer' and 'Eco-Conscious / Minimalist'
  - category: adds 'Grooming'
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "18438697e926"
down_revision: Union[str, None] = "86e7d3e85de5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CHANGE A — Expand persona constraint
    op.drop_constraint("ck_soa_queries_persona", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_persona",
        "soa_queries",
        (
            "persona IN ("
            "'Casual / Gift Buyer',"
            "'Value-Conscious',"
            "'Beauty Enthusiast',"
            "'Problem-Skin Sufferer',"
            "'Eco-Conscious / Minimalist'"
            ")"
        ),
    )

    # CHANGE B — Expand category constraint to include Grooming
    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        (
            "category IN ("
            "'Skincare',"
            "'Makeup',"
            "'Fragrance',"
            "'Haircare',"
            "'Cross-Category',"
            "'Grooming'"
            ")"
        ),
    )


def downgrade() -> None:
    # Restore category constraint without Grooming
    op.drop_constraint("ck_soa_queries_category", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_category",
        "soa_queries",
        (
            "category IN ("
            "'Skincare',"
            "'Makeup',"
            "'Fragrance',"
            "'Haircare',"
            "'Cross-Category'"
            ")"
        ),
    )

    # Restore persona constraint to original three values
    op.drop_constraint("ck_soa_queries_persona", "soa_queries", type_="check")
    op.create_check_constraint(
        "ck_soa_queries_persona",
        "soa_queries",
        (
            "persona IN ("
            "'Casual / Gift Buyer',"
            "'Value-Conscious',"
            "'Beauty Enthusiast'"
            ")"
        ),
    )
