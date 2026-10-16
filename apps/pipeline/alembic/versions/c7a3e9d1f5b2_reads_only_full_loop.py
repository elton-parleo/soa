"""soa_full_loop_requests: a reads-only request (no study)

Revision ID: c7a3e9d1f5b2
Revises: b4e8f1c3a9d2
Create Date: 2026-10-16

2I: "Run full loop" on a merchant with no study reads its pages only (the
access series and the reference reads, supply's stage one) and stops at
supply's reference_done. The request then has no study: `study_type` is
nullable, `platforms` defaults to [], and the status CHECK gains the
terminal `reads_done`.

Downgrade restores NOT NULL and the old CHECK only when no row needs the
new shape: it refuses, naming the count, while a reads-only row exists
(close or delete those first), rather than drop data to fit the old schema.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7a3e9d1f5b2"
down_revision: Union[str, None] = "b4e8f1c3a9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_CHECK = ("status IN ('reference_pending', 'reference_done', 'cycle_planned', "
             "'scoring', 'scored', 'failed')")
NEW_CHECK = ("status IN ('reference_pending', 'reference_done', 'cycle_planned', "
             "'scoring', 'scored', 'failed', 'reads_done')")


def upgrade() -> None:
    with op.batch_alter_table("soa_full_loop_requests") as batch:
        batch.alter_column("study_type", existing_type=sa.Text(), nullable=True)
        batch.alter_column("platforms", existing_type=sa.JSON(), server_default=sa.text("'[]'"))
        batch.drop_constraint("ck_soa_full_loop_requests_status", type_="check")
        batch.create_check_constraint("ck_soa_full_loop_requests_status", NEW_CHECK)


def downgrade() -> None:
    bind = op.get_bind()
    n = bind.execute(sa.text(
        "SELECT COUNT(*) FROM soa_full_loop_requests WHERE study_type IS NULL OR status = 'reads_done'")).scalar()
    if n:
        raise RuntimeError(
            f"refusing to downgrade c7a3e9d1f5b2: {n} reads-only full-loop request(s) have no study_type or "
            f"status reads_done, which the old schema cannot hold. Delete or close them first.")
    with op.batch_alter_table("soa_full_loop_requests") as batch:
        batch.drop_constraint("ck_soa_full_loop_requests_status", type_="check")
        batch.create_check_constraint("ck_soa_full_loop_requests_status", OLD_CHECK)
        batch.alter_column("platforms", existing_type=sa.JSON(), server_default=None)
        batch.alter_column("study_type", existing_type=sa.Text(), nullable=False)
