"""migrate_soa_metrics_results_to_entity_id

Revision ID: e90651a008de
Revises: d0da6d0716bf
Create Date: 2026-05-19 15:00:00.000000

soa_metrics_results.merchant_id was an FK to merchants.id, but brand
study cycles (e.g. brand_gillette, brand_oral_b) have entities with no
supply-app merchant row. Writing metrics for these cycles would fire an
FK violation.

Rename merchant_id → entity_id and point the FK at soa_entities.id.
Backfill existing retailer-study rows via soa_entities.merchant_id lookup.
Recreate the soa_dashboard_summary materialized view to join soa_entities
directly instead of routing through merchants.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e90651a008de"
down_revision: Union[str, None] = "d0da6d0716bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop materialized view — it joins on merchant_id, must be rebuilt.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS soa_dashboard_summary")

    # 2. Drop FK and dependent constraints/indexes on merchant_id.
    op.drop_constraint(
        "soa_metrics_results_merchant_id_fkey",
        "soa_metrics_results",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_soa_metrics_results_slice",
        "soa_metrics_results",
        type_="unique",
    )
    op.drop_index(
        "ix_soa_metrics_results_cycle_merchant_slice_type",
        table_name="soa_metrics_results",
    )
    op.drop_index(
        "ix_soa_metrics_results_merchant_id",
        table_name="soa_metrics_results",
    )
    op.drop_index(
        "ix_soa_metrics_results_merchant_slice_type_value",
        table_name="soa_metrics_results",
    )

    # 3. Rename the column.
    op.alter_column("soa_metrics_results", "merchant_id", new_column_name="entity_id")

    # 4. Backfill: existing rows contain merchant_id values in the renamed column.
    #    Map them to the correct soa_entities.id via the merchant_id FK on soa_entities.
    op.execute("""
        UPDATE soa_metrics_results mr
        SET entity_id = e.id
        FROM soa_entities e
        WHERE e.merchant_id = mr.entity_id
    """)

    # 5. Add FK to soa_entities.
    op.create_foreign_key(
        "soa_metrics_results_entity_id_fkey",
        "soa_metrics_results",
        "soa_entities",
        ["entity_id"],
        ["id"],
    )

    # 6. Recreate UniqueConstraint and indexes with entity_id names.
    op.create_unique_constraint(
        "uq_soa_metrics_results_slice",
        "soa_metrics_results",
        ["cycle_id", "entity_id", "slice_type", "slice_value"],
    )
    op.create_index(
        "ix_soa_metrics_results_entity_id",
        "soa_metrics_results",
        ["entity_id"],
    )
    op.create_index(
        "ix_soa_metrics_results_cycle_entity_slice_type",
        "soa_metrics_results",
        ["cycle_id", "entity_id", "slice_type"],
    )
    op.create_index(
        "ix_soa_metrics_results_entity_slice_type_value",
        "soa_metrics_results",
        ["entity_id", "slice_type", "slice_value"],
    )

    # 7. Recreate materialized view joining soa_entities directly.
    op.execute("""
        CREATE MATERIALIZED VIEW soa_dashboard_summary AS
        SELECT
            c.cycle_code,
            e.name  AS merchant_name,
            e.slug  AS merchant_slug,
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
        JOIN soa_cycles   c ON c.id = mr.cycle_id
        JOIN soa_entities e ON e.id = mr.entity_id
        ORDER BY c.cycle_code DESC, mr.slice_type, mr.slice_value,
                 mr.soa_pct DESC NULLS LAST
    """)
    op.execute("""
        CREATE UNIQUE INDEX uix_soa_dashboard_summary_key
        ON soa_dashboard_summary (cycle_code, merchant_slug, slice_type, slice_value)
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS soa_dashboard_summary")

    op.drop_index(
        "ix_soa_metrics_results_entity_slice_type_value",
        table_name="soa_metrics_results",
    )
    op.drop_index(
        "ix_soa_metrics_results_cycle_entity_slice_type",
        table_name="soa_metrics_results",
    )
    op.drop_index(
        "ix_soa_metrics_results_entity_id",
        table_name="soa_metrics_results",
    )
    op.drop_constraint(
        "uq_soa_metrics_results_slice",
        "soa_metrics_results",
        type_="unique",
    )
    op.drop_constraint(
        "soa_metrics_results_entity_id_fkey",
        "soa_metrics_results",
        type_="foreignkey",
    )

    # Reverse backfill: restore merchant_id values from soa_entities.merchant_id.
    op.execute("""
        UPDATE soa_metrics_results mr
        SET entity_id = e.merchant_id
        FROM soa_entities e
        WHERE e.id = mr.entity_id
    """)

    op.alter_column("soa_metrics_results", "entity_id", new_column_name="merchant_id")

    op.create_foreign_key(
        "soa_metrics_results_merchant_id_fkey",
        "soa_metrics_results",
        "merchants",
        ["merchant_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_soa_metrics_results_slice",
        "soa_metrics_results",
        ["cycle_id", "merchant_id", "slice_type", "slice_value"],
    )
    op.create_index(
        "ix_soa_metrics_results_merchant_id",
        "soa_metrics_results",
        ["merchant_id"],
    )
    op.create_index(
        "ix_soa_metrics_results_cycle_merchant_slice_type",
        "soa_metrics_results",
        ["cycle_id", "merchant_id", "slice_type"],
    )
    op.create_index(
        "ix_soa_metrics_results_merchant_slice_type_value",
        "soa_metrics_results",
        ["merchant_id", "slice_type", "slice_value"],
    )

    op.execute("""
        CREATE MATERIALIZED VIEW soa_dashboard_summary AS
        SELECT
            c.cycle_code,
            m.name AS merchant_name,
            m.slug AS merchant_slug,
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
        JOIN soa_cycles  c ON c.id = mr.cycle_id
        JOIN merchants   m ON m.id = mr.merchant_id
        ORDER BY c.cycle_code DESC, mr.slice_type, mr.slice_value,
                 mr.soa_pct DESC NULLS LAST
    """)
    op.execute("""
        CREATE UNIQUE INDEX uix_soa_dashboard_summary_key
        ON soa_dashboard_summary (cycle_code, merchant_slug, slice_type, slice_value)
    """)
