"""add_customer_accounts

Revision ID: a7c3e9f1b2d4
Revises: d439b7309af4
Create Date: 2026-10-04

Step 1C: soa orgs become supply tenants.

  * organizations: truesync_tenant_slug (unique), truesync_token_sealed
    (Fernet ciphertext, soa_shared/secret_box.py), truesync_token_id.
  * organization_members.is_operator — a Parleo operator may select any
    customer org. Defaults false; nothing here sets it.
  * soa_query_generation_jobs.customer_organization_id — the org whose
    tenant a grounded study's catalog is read from.

Additive only, and no data: linking Wiggle & Snug and marking operators
needs a token and a list of people, neither of which belongs in a
migration. scripts/backfill_customer_accounts.py does both, after this.

Downgrade drops the columns, and with them every stored token and
operator flag. It refuses while any org holds a sealed token, so a
downgrade can't silently discard a customer's only copy of its token.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9f1b2d4"
down_revision: Union[str, None] = "d439b7309af4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("truesync_tenant_slug", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("truesync_token_sealed", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("truesync_token_id", sa.String(), nullable=True))
    op.create_unique_constraint(
        "uq_organizations_truesync_tenant_slug", "organizations", ["truesync_tenant_slug"]
    )

    op.add_column(
        "organization_members",
        sa.Column("is_operator", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        "soa_query_generation_jobs",
        sa.Column("customer_organization_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_soa_query_generation_jobs_customer_org",
        "soa_query_generation_jobs", "organizations",
        ["customer_organization_id"], ["id"],
    )


def downgrade() -> None:
    sealed = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM organizations WHERE truesync_token_sealed IS NOT NULL")
    ).scalar()
    if sealed:
        raise RuntimeError(
            f"refusing to downgrade: {sealed} org(s) hold a sealed TrueSync token that "
            f"this would destroy. Unlink them (or copy the tokens out) first."
        )

    op.drop_constraint(
        "fk_soa_query_generation_jobs_customer_org", "soa_query_generation_jobs",
        type_="foreignkey",
    )
    op.drop_column("soa_query_generation_jobs", "customer_organization_id")
    op.drop_column("organization_members", "is_operator")
    op.drop_constraint("uq_organizations_truesync_tenant_slug", "organizations", type_="unique")
    op.drop_column("organizations", "truesync_token_id")
    op.drop_column("organizations", "truesync_token_sealed")
    op.drop_column("organizations", "truesync_tenant_slug")
