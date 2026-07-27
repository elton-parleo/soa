"""add_competitor_source_to_soa_lite_requests

Revision ID: b7f61bed6b64
Revises: e1d6eba13226
Create Date: 2026-07-26 00:00:00.000000

Stage 13 (F2): adds a nullable competitor_source text column to
soa_lite_requests — records the provenance of competitor_names once
worker-side competitor auto-generation runs (generated | manual | mixed
| none). competitor_names itself needs no migration: it's already a
JSON list column with no DB-level cap (the 0-2 limit was only a
Pydantic validator on the public POST endpoint), so it already
accommodates up to 5 entries. Purely additive; nothing existing reads
or writes this column until this stage wires it in
(apps/pipeline/generation/competitor_generator.py,
apps/pipeline/worker.py::process_lite_requests).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7f61bed6b64"
down_revision: Union[str, None] = "e1d6eba13226"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_lite_requests",
        sa.Column("competitor_source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soa_lite_requests", "competitor_source")
