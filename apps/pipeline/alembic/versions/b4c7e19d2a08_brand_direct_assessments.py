"""Brand-direct assessments, and the near-miss flag

Revision ID: b4c7e19d2a08
Revises: a9f3c21b7e40
Create Date: 2026-09-15

Two additive changes to soa_expectation_outcomes, both driven by cycle
20260915-113207-wiggle-snug-full.

The outcome CHECK admitted five values, all of which describe an answer
compared against a published NUMBER. Brand-direct questions have no
number, so they were scored on whether the brand was named at all — and
63 of 66 runs scored `exact` on a brand two of them had actually read.
The constraint now admits the brand vocabulary alongside the value one;
which of the two applies is decided by the row's tier, in
soa_shared.expected_answers.outcomes_for_tier.

near_miss records the right promotion code with the wrong terms. It stays
a flag rather than a sixth outcome on purpose: the answer is wrong, it
belongs in the wrong count, and moving it out would change the accuracy
denominator to make a number look better.

Nothing here rewrites a stored row. Every existing outcome is still a
legal value, so catalog-accuracy and value-incentives rows are untouched
by this migration and by the re-score that follows it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c7e19d2a08"
down_revision: Union[str, None] = "a9f3c21b7e40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_soa_expectation_outcomes_outcome"
TABLE = "soa_expectation_outcomes"

# Literal, not interpolated from the vocabulary module. A constraint that
# reads its own values from application code changes silently when that
# code changes, and a migration is supposed to be the record of what the
# database was asked to accept on a given day.
OLD = "outcome IN ('exact', 'stale', 'wrong', 'absent', 'unscoreable')"
NEW = (
    "outcome IN ('exact', 'stale', 'wrong', 'absent', 'unscoreable', "
    "'grounded', 'echoed', 'misattributed', 'fabricated', "
    "'acknowledged_unknown')"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, NEW)
    op.add_column(
        TABLE,
        sa.Column("near_miss", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    # The column goes first: a row carrying a brand assessment would fail
    # the narrowed constraint, and dropping near_miss afterwards would
    # leave the table half-migrated behind a failed statement.
    op.drop_column(TABLE, "near_miss")
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, OLD)
