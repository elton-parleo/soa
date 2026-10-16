"""soa_cycles.domain_checks: the Audit's domain checks, run for the cycle

Revision ID: b4e8f1c3a9d2
Revises: a7d2c9e4b1f6
Create Date: 2026-10-15

2E: the worker runs the Audit's Protocol & Feed Presence and Value
Protocols checks (scan/scorer.py, called through scoring/domain_checks.py)
and the signed-agent probe against the cycle's merchant's own domains, and
stores the raw record here: per domain, each fetch, the protocol files'
bodies, the hints, the site type, both dimension scores and the probe's
two outcomes, versioned by the scan module's SCORER_VERSION. The console's
score of record reads it; scoring/domain_checks.score_entry re-scores it.

Additive and nullable: safe to apply ahead of the deploy. Not mapped on
SoaCycle; scoring/domain_checks.store writes it only when the column
exists, and the console reads it inside a try, so both run before this is
applied (the two dimensions then read "not measured", as before 2E).
Existing rows are not backfilled: scripts/run_domain_checks.py does that
for one cycle at a time.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8f1c3a9d2"
down_revision: Union[str, None] = "a7d2c9e4b1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("soa_cycles", sa.Column("domain_checks", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("soa_cycles", "domain_checks")
