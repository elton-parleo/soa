"""add_soa_dashboard_materialized_view

Revision ID: 2173cb184e80
Revises: 1fe6f03a1c1c
Create Date: 2026-05-05 21:15:09.407501

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2173cb184e80'
down_revision: Union[str, None] = '1fe6f03a1c1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the materialized view
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS soa_dashboard_summary AS
        SELECT
            c.cycle_code,
            m.name         AS merchant_name,
            m.slug         AS merchant_slug,
            mr.slice_type,
            mr.slice_value,
            mr.total_runs,
            mr.total_mentions,
            mr.mention_rate,
            mr.soa_pct,
            mr.position_index,
            mr.rsi_score,
            mr.deal_citation_rate,
            mr.platform_dist_index,
            mr.calculated_at
        FROM soa_metrics_results mr
        JOIN soa_cycles  c ON c.id  = mr.cycle_id
        JOIN merchants   m ON m.id  = mr.merchant_id
        ORDER BY
            c.cycle_code  DESC,
            mr.slice_type,
            mr.slice_value,
            mr.soa_pct    DESC NULLS LAST
    """)

    # Unique index — required for REFRESH MATERIALIZED VIEW CONCURRENTLY
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
            uix_soa_dashboard_summary_key
        ON soa_dashboard_summary
            (cycle_code, merchant_slug, slice_type, slice_value)
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS soa_dashboard_summary")
