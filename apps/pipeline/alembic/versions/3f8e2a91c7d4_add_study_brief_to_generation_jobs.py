"""add_study_brief_to_generation_jobs

Revision ID: 3f8e2a91c7d4
Revises: 467a91c32dd8
Create Date: 2026-09-02 00:00:00.000000

Carries the Create Study with AI brief across to the pipeline worker, and
carries a provenance record back.

Generation is asynchronous: POST /studies/generate writes one
soa_query_generation_jobs row and returns immediately, and the worker
picks the job up later. The two processes share nothing but this table,
so a structured input the API accepts and does not store is an input the
generator can never see. Before this migration the row held study_name,
description and target_count — so the modal could say how MANY questions
to write and nothing whatsoever about what they should be.

The eight brief columns are the fields the modal collects. provenance is
the return leg: what was generated, what was dropped automatically, and
what the advisory review passes flagged for a human. It lives here rather
than in the API response because rows never reach the client before
persistence — there is no response to attach it to — so
GET /studies/{study_type}/generation-status reads it back off this row.

Every column is nullable, and study_pattern doubles as the worker's path
discriminator: NULL means the job was queued before this migration (or by
a client that sends only the original three fields), and the worker runs
it exactly as it would have been run when it was queued. A job is
processed under the rules it was created under, never retroactively
under new ones.

No CHECK constraints on study_pattern, specificity_mode or the JSON
columns, deliberately. constants.py documents adding an allowed value as
"edit the list, write ONE migration for the CHECK, sync, redeploy", and
a CHECK here would quietly make that two migrations forever after. These
values are already validated by StudyGenerateRequest on the way in, and
study_pattern is validated again downstream by _validate_generated_row
when it is stamped onto rows — where soa_queries.study_pattern's own
CHECK constraint is the real enforcement. This table stores a request,
not a record of truth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3f8e2a91c7d4'
down_revision: Union[str, None] = '467a91c32dd8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, type) — kept as data so upgrade and downgrade cannot drift apart.
_BRIEF_COLUMNS = [
    ("study_pattern",         sa.String()),
    ("retailer_names",        sa.JSON()),
    ("allowed_categories",    sa.JSON()),
    ("stage_targets",         sa.JSON()),
    ("rotate_named_retailer", sa.Boolean()),
    ("naming_rule_enabled",   sa.Boolean()),
    ("personas",              sa.JSON()),
    ("specificity_mode",      sa.String()),
    ("provenance",            sa.JSON()),
]


def upgrade() -> None:
    for name, type_ in _BRIEF_COLUMNS:
        op.add_column(
            "soa_query_generation_jobs",
            sa.Column(name, type_, nullable=True),
        )


def downgrade() -> None:
    for name, _ in reversed(_BRIEF_COLUMNS):
        op.drop_column("soa_query_generation_jobs", name)
