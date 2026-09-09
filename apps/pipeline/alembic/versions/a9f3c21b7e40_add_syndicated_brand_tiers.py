"""add_syndicated_brand_tiers

Revision ID: a9f3c21b7e40
Revises: 3f8e2a91c7d4
Create Date: 2026-09-09 10:45:00.000000

Purely additive. Every column added here is nullable with no server
default and no backfill, so an existing study, cycle or query is
byte-identical after this migration to what it was before it — which is
the point: a query written with no syndicated brand in view has no tier
it belongs to, and labelling it would make the report's tier
segmentation a fiction.

soa_queries gains the four grounding columns:
  tier             which of the four question tiers this belongs to
  expected_answer  the typed expectation (docs/expected-answer-vocabulary.md)
  provenance       catalog / ai_from_catalog / ai
  source_ref       merchant, listing, variant-or-offer, and the record's
                   published_at

soa_query_generation_jobs — the row that IS a study's definition, there
being no soa_studies table — gains syndicated_merchant and tier_config.

soa_cycles gains extraction_validation: the hand-checked agreement rate
for the Layer 2 extractor, NULL until a human records one.

soa_expectation_outcomes is new: one row per scored (question x surface x
sample), keyed on soa_runs so the answer text every rate traces back to
is the run's own stored raw_response rather than a second copy of it.

The CHECK constraints are written as literals rather than interpolated
from soa_shared.expected_answers. A migration has to mean the same thing
when it is replayed in two years, and a constraint whose text depends on
what a Python constant says at replay time does not.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9f3c21b7e40"
down_revision: Union[str, None] = "3f8e2a91c7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── soa_queries ──────────────────────────────────────────────────
    op.add_column("soa_queries", sa.Column("tier", sa.Text(), nullable=True))
    op.add_column("soa_queries", sa.Column("expected_answer", sa.JSON(), nullable=True))
    op.add_column("soa_queries", sa.Column("provenance", sa.Text(), nullable=True))
    op.add_column("soa_queries", sa.Column("source_ref", sa.JSON(), nullable=True))

    # `IS NULL OR` on both: NULL is the untouched state of every existing
    # row, not a violation to be migrated away from.
    op.create_check_constraint(
        "ck_soa_queries_tier",
        "soa_queries",
        "tier IS NULL OR tier IN "
        "('brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control')",
    )
    op.create_check_constraint(
        "ck_soa_queries_provenance",
        "soa_queries",
        "provenance IS NULL OR provenance IN ('catalog', 'ai_from_catalog', 'ai')",
    )
    op.create_index(
        "ix_soa_queries_study_type_tier", "soa_queries", ["study_type", "tier"],
    )

    # ─── soa_query_generation_jobs — the study's definition row ───────
    op.add_column(
        "soa_query_generation_jobs",
        sa.Column("syndicated_merchant", sa.String(), nullable=True),
    )
    op.add_column(
        "soa_query_generation_jobs",
        sa.Column("tier_config", sa.JSON(), nullable=True),
    )

    # ─── soa_cycles ───────────────────────────────────────────────────
    op.add_column(
        "soa_cycles",
        sa.Column("extraction_validation", sa.JSON(), nullable=True),
    )

    # ─── soa_expectation_outcomes ─────────────────────────────────────
    op.create_table(
        "soa_expectation_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("soa_runs.id"), nullable=False),
        sa.Column("query_id", sa.Integer(), sa.ForeignKey("soa_queries.id"), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("soa_cycles.id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=True),
        sa.Column("expected_answer", sa.JSON(), nullable=False),
        sa.Column("extraction", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("outcome_reason", sa.Text(), nullable=True),
        sa.Column("domain_cited", sa.Boolean(), nullable=True),
        sa.Column("source_attribution", sa.Text(), nullable=True),
        sa.Column("secondary_results", sa.JSON(), nullable=True),
        sa.Column("record_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_model", sa.Text(), nullable=True),
        sa.Column(
            "scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "outcome IN ('exact', 'stale', 'wrong', 'absent', 'unscoreable')",
            name="ck_soa_expectation_outcomes_outcome",
        ),
        # One verdict per run: a re-score replaces the row rather than
        # appending, so a rate cannot double-count a twice-scored run.
        sa.UniqueConstraint("run_id", name="uq_soa_expectation_outcomes_run"),
    )
    op.create_index(
        "ix_soa_expectation_outcomes_run_id", "soa_expectation_outcomes", ["run_id"],
    )
    op.create_index(
        "ix_soa_expectation_outcomes_query_id", "soa_expectation_outcomes", ["query_id"],
    )
    op.create_index(
        "ix_soa_expectation_outcomes_cycle_tier",
        "soa_expectation_outcomes",
        ["cycle_id", "tier"],
    )
    op.create_index(
        "ix_soa_expectation_outcomes_outcome", "soa_expectation_outcomes", ["outcome"],
    )


def downgrade() -> None:
    # Exact inverse, innermost first. The table goes before the columns
    # it has foreign keys into.
    op.drop_index("ix_soa_expectation_outcomes_outcome", table_name="soa_expectation_outcomes")
    op.drop_index("ix_soa_expectation_outcomes_cycle_tier", table_name="soa_expectation_outcomes")
    op.drop_index("ix_soa_expectation_outcomes_query_id", table_name="soa_expectation_outcomes")
    op.drop_index("ix_soa_expectation_outcomes_run_id", table_name="soa_expectation_outcomes")
    op.drop_table("soa_expectation_outcomes")

    op.drop_column("soa_cycles", "extraction_validation")

    op.drop_column("soa_query_generation_jobs", "tier_config")
    op.drop_column("soa_query_generation_jobs", "syndicated_merchant")

    op.drop_index("ix_soa_queries_study_type_tier", table_name="soa_queries")
    op.drop_constraint("ck_soa_queries_provenance", "soa_queries", type_="check")
    op.drop_constraint("ck_soa_queries_tier", "soa_queries", type_="check")
    op.drop_column("soa_queries", "source_ref")
    op.drop_column("soa_queries", "provenance")
    op.drop_column("soa_queries", "expected_answer")
    op.drop_column("soa_queries", "tier")
