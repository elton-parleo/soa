"""fix_ck_soa_lite_requests_status

Revision ID: b7c9c235bf62
Revises: b7f61bed6b64
Create Date: 2026-07-26 00:00:00.000000

Stage 14 (M1): incident fix. Stage 13 added the 'identifying_competitors'
status write (apps/pipeline/worker.py::process_lite_requests, on pickup,
ahead of query generation) without updating ck_soa_lite_requests_status
to allow it — the constraint still only permitted ('pending','generating',
'running','complete','failed'). Every attempt to write
'identifying_competitors' violated the constraint and raised before the
row could advance past 'pending'; since process_lite_requests always
selects the SINGLE oldest pending row (ORDER BY created_at ASC LIMIT 1),
the same poisoned row was re-picked and re-failed on every poll,
permanently blocking every request submitted after it.

Recreates the constraint from LITE_STATUSES (soa_shared/models/
soa_models.py), the new single source of truth for this column's valid
values, so the DB and the code can no longer drift apart silently — see
also the Stage 14 status-parity test (tests/test_lite_status_parity.py)
that now fails CI if they do.

Drop-and-recreate rather than ALTER: Postgres has no ALTER CHECK
CONSTRAINT; the table is tiny (public lead-gen submissions only) so the
brief validation-scan lock this takes is a non-issue.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b7c9c235bf62"
down_revision: Union[str, None] = "b7f61bed6b64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_soa_lite_requests_status"

# Mirrors LITE_STATUSES in soa_shared/models/soa_models.py exactly.
NEW_STATUSES = (
    "pending",
    "identifying_competitors",
    "generating",
    "running",
    "complete",
    "failed",
)

# The constraint as it exists in prod today (verbatim from the
# traceback) — restored by downgrade().
OLD_STATUSES = (
    "pending",
    "generating",
    "running",
    "complete",
    "failed",
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "soa_lite_requests", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "soa_lite_requests",
        "status IN (" + ", ".join(f"'{s}'" for s in NEW_STATUSES) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "soa_lite_requests", type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "soa_lite_requests",
        "status IN (" + ", ".join(f"'{s}'" for s in OLD_STATUSES) + ")",
    )
