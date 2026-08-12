"""allow_standalone_cycle_scan_results

Revision ID: 8c31844a4171
Revises: 9fe17836f9d5
Create Date: 2026-08-10 00:00:00.000000

Full Analysis coexistence, Phase 2 follow-up to 9fe17836f9d5: a Full
Analysis cycle created WITHOUT a source_lite_request_id (a brand-new
paid cycle, not a continuation of an audit) still needs to launch its
own crawl — but soa_lite_scan_results.lite_request_id was NOT NULL,
which made a crawl row for such a cycle impossible to write at all.

Relaxes lite_request_id to nullable and adds a check constraint
guaranteeing every scan row is still owned by at least one of the two
FKs. The lite path is unaffected: every write it already performs sets
lite_request_id, so ck_soa_lite_scan_results_owned is satisfied
trivially for every existing and future lite-owned row. A
Full-Analysis-launched crawl (continuation or not) sets cycle_id with
lite_request_id NULL instead — see apps/pipeline/worker.py::
process_cycle_crawls.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8c31844a4171'
down_revision: Union[str, None] = '9fe17836f9d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "soa_lite_scan_results", "lite_request_id",
        existing_type=sa.Integer(), nullable=True,
    )
    op.create_check_constraint(
        "ck_soa_lite_scan_results_owned",
        "soa_lite_scan_results",
        "lite_request_id IS NOT NULL OR cycle_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_soa_lite_scan_results_owned", "soa_lite_scan_results", type_="check")
    op.alter_column(
        "soa_lite_scan_results", "lite_request_id",
        existing_type=sa.Integer(), nullable=False,
    )
