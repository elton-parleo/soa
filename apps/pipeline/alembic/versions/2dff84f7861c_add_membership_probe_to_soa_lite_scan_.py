"""add_membership_probe_to_soa_lite_scan_results

Revision ID: 2dff84f7861c
Revises: b7c9c235bf62
Create Date: 2026-07-28 00:00:00.000000

Stage 16 (Part 4): adds a nullable membership_probe JSON column to
soa_lite_scan_results — {result: 'yes'|'no'|'unknown', raw_evidence:
str|null} from a single out-of-band OpenAI call
(apps/pipeline/generation/membership_probe.py). Metrically invisible —
not one of the 12 tracked queries, excluded from every mention/citation
denominator. Feeds P3's member_value applicability decision only
(apps/api/app/services/lite_pillars.py::member_value_applicable).
Purely additive; nothing existing reads or writes this column until
this stage wires it in (apps/pipeline/worker.py::process_lite_requests).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2dff84f7861c"
down_revision: Union[str, None] = "b7c9c235bf62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_lite_scan_results",
        sa.Column("membership_probe", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soa_lite_scan_results", "membership_probe")
