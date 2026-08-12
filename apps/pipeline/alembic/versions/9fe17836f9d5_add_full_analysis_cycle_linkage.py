"""add_full_analysis_cycle_linkage

Revision ID: 9fe17836f9d5
Revises: b3c9f1a2d4e6
Create Date: 2026-08-09 22:17:24.597137

Full Analysis coexistence, Phase 1: the schema linkage that lets a paid
soa_cycles row be created as the continuation of a free soa_lite_requests
audit, and lets any cycle (not just a lite one) carry an Agent Scan crawl.

Purely additive — every new column is nullable, nothing here is read or
written by the existing lite/cycle write paths until later phases wire
it in, and no existing row is touched except the one idempotent backfill
below. Old cycles are never retro-scored or migrated; see scan_dimensions.
py's version-gate philosophy, which the report-render discriminator
(Phase 4) extends rather than replaces.

  - soa_cycles.source_lite_request_id / prior_cycle_id / study_series_id:
    the time-dimension linkage — a cycle created from an audit points
    back at the audit's lite request and (once a first full cycle exists)
    at its own predecessor cycle, sharing one study_series_id across the
    series.
  - soa_lite_scan_results.cycle_id: re-keys crawl storage so ANY cycle
    can carry a crawl, not just a lite request's own. lite_request_id
    is untouched — the lite path keeps reading/writing exactly as it
    does today (uq_soa_lite_scan_results_lite_request_id still holds a
    scan to at most one lite request). The backfill below sets cycle_id
    on existing lite-owned scan rows via the same 1:1 lite_request ->
    cycle join public_lite.py already reads (soa_lite_requests.cycle_id)
    — trivial and idempotent, safe to run twice.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9fe17836f9d5'
down_revision: Union[str, None] = 'b3c9f1a2d4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_cycles",
        sa.Column(
            "source_lite_request_id",
            sa.Integer(),
            sa.ForeignKey("soa_lite_requests.id"),
            nullable=True,
            comment=(
                "Set when this cycle was created as the Full Analysis "
                "continuation of a SoA Lite audit run. Null for every "
                "cycle created the ordinary way (NewCycleWizard or the "
                "API directly) — never backfilled onto old cycles."
            ),
        ),
    )
    op.add_column(
        "soa_cycles",
        sa.Column(
            "study_series_id",
            sa.Text(),
            nullable=True,
            comment=(
                "Free-text id shared by every cycle in a recurring study "
                "series (e.g. an audit and the Full Analysis cycles run "
                "off it monthly/quarterly). Null means this cycle is not "
                "part of a tracked series."
            ),
        ),
    )
    op.add_column(
        "soa_cycles",
        sa.Column(
            "prior_cycle_id",
            sa.Integer(),
            sa.ForeignKey("soa_cycles.id"),
            nullable=True,
            comment=(
                "The cycle this one continues from in its study_series_id "
                "series — e.g. the audit's own cycle, for the first Full "
                "Analysis run off it. Null for a series' first cycle."
            ),
        ),
    )
    op.create_index(
        "ix_soa_cycles_source_lite_request_id",
        "soa_cycles",
        ["source_lite_request_id"],
    )
    op.create_index(
        "ix_soa_cycles_prior_cycle_id",
        "soa_cycles",
        ["prior_cycle_id"],
    )
    op.create_index(
        "ix_soa_cycles_study_series_id",
        "soa_cycles",
        ["study_series_id"],
    )
    op.create_check_constraint(
        "ck_soa_cycles_prior_cycle_not_self",
        "soa_cycles",
        "prior_cycle_id IS NULL OR prior_cycle_id != id",
    )

    op.add_column(
        "soa_lite_scan_results",
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("soa_cycles.id"),
            nullable=True,
            comment=(
                "The cycle this crawl is attached to — set for every scan "
                "going forward (both lite-owned and Full-Analysis-owned). "
                "lite_request_id remains the lite path's own FK, untouched; "
                "this column is what lets a paid cycle with no lite_request "
                "at all carry a crawl too."
            ),
        ),
    )
    op.create_index(
        "ix_soa_lite_scan_results_cycle_id",
        "soa_lite_scan_results",
        ["cycle_id"],
    )

    # Idempotent backfill: every existing scan row already belongs to
    # exactly one lite request (uq_soa_lite_scan_results_lite_request_id),
    # and that lite request already knows its own cycle_id once one was
    # created — the same join public_lite.py performs at read time. Rows
    # whose lite request has no cycle yet (cycle_id IS NULL) are left
    # alone; re-running this UPDATE is a no-op on rows it already set.
    op.execute(
        """
        UPDATE soa_lite_scan_results sr
        SET cycle_id = lr.cycle_id
        FROM soa_lite_requests lr
        WHERE sr.lite_request_id = lr.id
          AND lr.cycle_id IS NOT NULL
          AND sr.cycle_id IS DISTINCT FROM lr.cycle_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_soa_lite_scan_results_cycle_id", table_name="soa_lite_scan_results")
    op.drop_column("soa_lite_scan_results", "cycle_id")

    op.drop_constraint("ck_soa_cycles_prior_cycle_not_self", "soa_cycles", type_="check")
    op.drop_index("ix_soa_cycles_study_series_id", table_name="soa_cycles")
    op.drop_index("ix_soa_cycles_prior_cycle_id", table_name="soa_cycles")
    op.drop_index("ix_soa_cycles_source_lite_request_id", table_name="soa_cycles")
    op.drop_column("soa_cycles", "prior_cycle_id")
    op.drop_column("soa_cycles", "study_series_id")
    op.drop_column("soa_cycles", "source_lite_request_id")
