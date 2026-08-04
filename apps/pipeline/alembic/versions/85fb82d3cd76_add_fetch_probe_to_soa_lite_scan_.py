"""add_fetch_probe_to_soa_lite_scan_results

Revision ID: 85fb82d3cd76
Revises: 1b5771574dfd
Create Date: 2026-08-02 00:00:00.000000

Part 2 (P1/P2): adds a nullable fetch_probe JSON column to
soa_lite_scan_results — {outcome: 'quoted_price'|'opened_no_price'|
'could_not_access'|'inconclusive', url: str, price: str|null,
quote: str|null, note: str|null} from a single out-of-band OpenAI
Responses-API call with the web_search tool (apps/pipeline/generation/
fetch_probe.py) — ChatGPT actually opening one sampled product URL.
Same never-throw pattern as membership_probe/revenue_probe, but ONE
call only, no retry. Metrically invisible — not one of the
LITE_QUERY_COUNT tracked queries, excluded from every mention/citation
denominator. Feeds Price Truth evidence and the blocked/degraded
banner (apps/api/app/services/lite_pillars.py, apps/api/app/routers/
public_lite.py); never affects any score.
Purely additive; nothing existing reads or writes this column until
this stage wires it in (apps/pipeline/worker.py::process_lite_requests).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "85fb82d3cd76"
down_revision: Union[str, None] = "1b5771574dfd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soa_lite_scan_results",
        sa.Column("fetch_probe", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("soa_lite_scan_results", "fetch_probe")
