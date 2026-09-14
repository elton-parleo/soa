"""add_lead_notified_at_to_soa_lite_requests

Revision ID: a9f3c2d81b47
Revises: 3f8e2a91c7d4
Create Date: 2026-09-14 00:00:00.000000

Adds a nullable lead_notified_at timestamptz to soa_lite_requests —
set once the internal "new lead" notification has been sent for the
address currently on the row (apps/api/app/services/
lead_notification_email.py, wired into set_lite_email).

This is the dedupe key: PATCH /email is idempotent from the widget's
point of view and a visitor can retry it, so without a stamp every
retry would send another copy of the same notification. The send is
gated on the email having actually CHANGED (NULL -> something, or a
different address), and this column records that the resulting send
succeeded — a failed send leaves it NULL, which simply means the next
genuine email change gets another attempt rather than the failure
being silently swallowed.

Purely additive and nullable, so existing rows (every lead captured
before this migration) read as "never notified" without a backfill —
correct, since those notifications were never going to be sent
retroactively anyway.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a9f3c2d81b47"
down_revision: Union[str, None] = "3f8e2a91c7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_lite_requests",
        sa.Column("lead_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soa_lite_requests", "lead_notified_at")
