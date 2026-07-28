"""add_member_value_cited_to_soa_coded_mentions

Revision ID: fc9738f67127
Revises: 2dff84f7861c
Create Date: 2026-07-28 00:00:00.000000

Stage 16 (Part 5): adds a non-nullable member_value_cited boolean
column (default false) to soa_coded_mentions — true whenever the
response indicates ANY member-exclusive/loyalty-program value for this
entity, concrete or not. Broader and separate from deal_cited/
deal_types, which deliberately exclude vague program-existence
mentions (see the MEMBER VALUE CITATION RULES section added to
apps/pipeline/parser/prompts.py's SYSTEM_PROMPT). Coded by the same
pass-1 LLM call and persisted by parser/response_coder.py. Feeds
apps/api/app/services/lite_pillars.py::score_member_value_said as an
additional citation signal alongside primary_member_price_claimed and
LOYALTY_DEAL_TYPES. Purely additive; existing rows backfill to false
via the column default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "fc9738f67127"
down_revision: Union[str, None] = "2dff84f7861c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_coded_mentions",
        sa.Column("member_value_cited", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("soa_coded_mentions", "member_value_cited")
