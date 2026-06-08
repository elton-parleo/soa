"""make_merchant_id_nullable_in_coded_mentions

Revision ID: 4daf78023c67
Revises: cfb7091f6db9
Create Date: 2026-05-19 13:25:23.071348

The multi-study entity support migration (86e7d3e85de5) added entity_id
as the new FK column on soa_coded_mentions and dropped the FK constraint
on merchant_id, but did not remove the NOT NULL constraint from
merchant_id.

This caused a NotNullViolation when coding runs for brand studies (e.g.
brand_gillette) whose entities have no supply-app merchant counterpart —
soa_entities.merchant_id is NULL for CPG brands, so merchant_id was
written as NULL and the constraint fired.

merchant_id is retained for data lineage / backward compat with
calculator.py and writer.py, but must be nullable since entity_id is
now the authoritative FK.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4daf78023c67"
down_revision: Union[str, None] = "cfb7091f6db9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make merchant_id nullable — superseded by entity_id as the FK to
    # the entity registry. Retained for backward compat but no longer
    # guaranteed to be populated (CPG brand entities have no merchant row).
    op.alter_column(
        "soa_coded_mentions",
        "merchant_id",
        nullable=True,
        existing_type=sa.Integer(),
    )


def downgrade() -> None:
    # Before restoring NOT NULL, backfill any nulls via the entity registry
    op.execute("""
        UPDATE soa_coded_mentions
        SET merchant_id = (
            SELECT e.merchant_id
            FROM soa_entities e
            WHERE e.id = soa_coded_mentions.entity_id
        )
        WHERE merchant_id IS NULL
        AND entity_id IS NOT NULL
    """)
    op.alter_column(
        "soa_coded_mentions",
        "merchant_id",
        nullable=False,
        existing_type=sa.Integer(),
    )
