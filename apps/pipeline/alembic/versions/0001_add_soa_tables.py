"""Add SoA measurement tables

Revision ID: 0001
Revises:
Create Date: 2026-05-04

Adds six new tables for the Share of Algorithm (SoA) measurement system:
  soa_queries, soa_cycles, soa_runs, soa_coded_mentions,
  soa_other_mentions, soa_metrics_results

The merchants table is referenced via ForeignKey string only — this
migration NEVER creates, alters, or drops the merchants table. That
table is owned exclusively by the /supply app.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. soa_queries — no foreign keys to new tables
    # ------------------------------------------------------------------
    op.create_table(
        "soa_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query_code", sa.Text(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("specificity", sa.Text(), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("soa_focus", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("query_code", name="uq_soa_queries_query_code"),
        sa.CheckConstraint(
            "category IN ('Skincare','Makeup','Fragrance','Haircare','Cross-Category')",
            name="ck_soa_queries_category",
        ),
        sa.CheckConstraint(
            "stage IN ('Research','Comparison','Ready to Buy')",
            name="ck_soa_queries_stage",
        ),
        sa.CheckConstraint(
            "specificity IN ('Broad','Mid','Narrow')",
            name="ck_soa_queries_specificity",
        ),
        sa.CheckConstraint(
            "persona IN ('Casual / Gift Buyer','Value-Conscious','Beauty Enthusiast')",
            name="ck_soa_queries_persona",
        ),
        sa.CheckConstraint(
            "status IN ('Active','Paused','Retired')",
            name="ck_soa_queries_status",
        ),
    )
    op.create_index(
        "ix_soa_queries_category_stage_status",
        "soa_queries",
        ["category", "stage", "status"],
    )

    # ------------------------------------------------------------------
    # 2. soa_cycles — no foreign keys to new tables
    # ------------------------------------------------------------------
    op.create_table(
        "soa_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_code", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("total_runs_planned", sa.Integer(), nullable=True),
        sa.Column(
            "completed_runs",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("cycle_code", name="uq_soa_cycles_cycle_code"),
        sa.CheckConstraint(
            "status IN ('planned','running','complete','failed')",
            name="ck_soa_cycles_status",
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_soa_cycles_end_date_gte_start",
        ),
    )

    # ------------------------------------------------------------------
    # 3. soa_runs — FK → soa_queries, soa_cycles
    # ------------------------------------------------------------------
    op.create_table(
        "soa_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("soa_cycles.id"),
            nullable=False,
        ),
        sa.Column(
            "query_id",
            sa.Integer(),
            sa.ForeignKey("soa_queries.id"),
            nullable=False,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("response_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "platform IN ('chatgpt','perplexity','gemini')",
            name="ck_soa_runs_platform",
        ),
        sa.CheckConstraint(
            "status IN ('pending','success','error','timeout')",
            name="ck_soa_runs_status",
        ),
        sa.CheckConstraint(
            "run_number BETWEEN 1 AND 10",
            name="ck_soa_runs_run_number_range",
        ),
        sa.UniqueConstraint(
            "cycle_id", "query_id", "platform", "run_number",
            name="uq_soa_runs_slot",
        ),
    )
    op.create_index("ix_soa_runs_cycle_id", "soa_runs", ["cycle_id"])
    op.create_index("ix_soa_runs_query_id", "soa_runs", ["query_id"])
    op.create_index(
        "ix_soa_runs_cycle_platform_status",
        "soa_runs",
        ["cycle_id", "platform", "status"],
    )
    op.create_index(
        "ix_soa_runs_query_platform",
        "soa_runs",
        ["query_id", "platform"],
    )

    # ------------------------------------------------------------------
    # 4. soa_coded_mentions — FK → soa_runs, merchants (string ref only)
    # ------------------------------------------------------------------
    op.create_table(
        "soa_coded_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("soa_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "merchant_id",
            sa.Integer(),
            sa.ForeignKey("merchants.id"),
            nullable=False,
        ),
        sa.Column(
            "mentioned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("strength", sa.Text(), nullable=True),
        sa.Column(
            "deal_cited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("deal_types", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("coded_by", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "strength IS NULL OR "
            "strength IN ('Primary','Positive','Neutral','Negative')",
            name="ck_soa_coded_mentions_strength",
        ),
        sa.CheckConstraint(
            "mentioned = TRUE OR position IS NULL",
            name="ck_soa_coded_mentions_position_requires_mention",
        ),
        sa.CheckConstraint(
            "mentioned = TRUE OR strength IS NULL",
            name="ck_soa_coded_mentions_strength_requires_mention",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_soa_coded_mentions_confidence_range",
        ),
        sa.UniqueConstraint(
            "run_id", "merchant_id",
            name="uq_soa_coded_mentions_run_merchant",
        ),
    )
    op.create_index("ix_soa_coded_mentions_run_id", "soa_coded_mentions", ["run_id"])
    op.create_index(
        "ix_soa_coded_mentions_merchant_id", "soa_coded_mentions", ["merchant_id"]
    )
    op.create_index(
        "ix_soa_coded_mentions_run_merchant",
        "soa_coded_mentions",
        ["run_id", "merchant_id"],
    )
    op.create_index(
        "ix_soa_coded_mentions_merchant_mentioned",
        "soa_coded_mentions",
        ["merchant_id", "mentioned"],
    )
    op.create_index(
        "ix_soa_coded_mentions_needs_review",
        "soa_coded_mentions",
        ["needs_review"],
    )

    # ------------------------------------------------------------------
    # 5. soa_other_mentions — FK → soa_runs
    # ------------------------------------------------------------------
    op.create_table(
        "soa_other_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("soa_runs.id"),
            nullable=False,
        ),
        sa.Column("merchant_name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("strength", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_soa_other_mentions_run_id", "soa_other_mentions", ["run_id"]
    )

    # ------------------------------------------------------------------
    # 6. soa_metrics_results — FK → soa_cycles, merchants (string ref only)
    # ------------------------------------------------------------------
    op.create_table(
        "soa_metrics_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("soa_cycles.id"),
            nullable=False,
        ),
        sa.Column(
            "merchant_id",
            sa.Integer(),
            sa.ForeignKey("merchants.id"),
            nullable=False,
        ),
        sa.Column("slice_type", sa.Text(), nullable=False),
        sa.Column("slice_value", sa.Text(), nullable=False),
        sa.Column("total_runs", sa.Integer(), nullable=False),
        sa.Column("total_mentions", sa.Integer(), nullable=False),
        sa.Column("mention_rate", sa.Float(), nullable=True),
        sa.Column("soa_pct", sa.Float(), nullable=True),
        sa.Column("position_index", sa.Float(), nullable=True),
        sa.Column("rsi_score", sa.Float(), nullable=True),
        sa.Column("deal_citation_rate", sa.Float(), nullable=True),
        sa.Column("platform_dist_index", sa.Float(), nullable=True),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "slice_type IN "
            "('overall','category','stage','specificity','persona','platform')",
            name="ck_soa_metrics_results_slice_type",
        ),
        sa.UniqueConstraint(
            "cycle_id", "merchant_id", "slice_type", "slice_value",
            name="uq_soa_metrics_results_slice",
        ),
    )
    op.create_index(
        "ix_soa_metrics_results_cycle_id", "soa_metrics_results", ["cycle_id"]
    )
    op.create_index(
        "ix_soa_metrics_results_merchant_id", "soa_metrics_results", ["merchant_id"]
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


def downgrade() -> None:
    # Drop in reverse dependency order.
    # Indexes on dropped tables are removed automatically by PostgreSQL.
    op.drop_table("soa_metrics_results")
    op.drop_table("soa_other_mentions")
    op.drop_table("soa_coded_mentions")
    op.drop_table("soa_runs")
    op.drop_table("soa_cycles")
    op.drop_table("soa_queries")
