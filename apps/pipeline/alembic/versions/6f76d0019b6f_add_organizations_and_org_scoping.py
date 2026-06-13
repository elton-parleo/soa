"""add_organizations_and_org_scoping

Revision ID: 6f76d0019b6f
Revises: c18179fc952d
Create Date: 2026-06-12 18:39:59.992195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6f76d0019b6f'
down_revision: Union[str, None] = 'c18179fc952d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. Create organization_members table
    op.create_table(
        'organization_members',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='member'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_check_constraint(
        'ck_org_members_role',
        'organization_members',
        "role IN ('owner', 'member')",
    )

    op.create_unique_constraint(
        'uq_org_members_org_user',
        'organization_members',
        ['organization_id', 'user_id'],
    )

    op.create_index(
        'ix_org_members_user_id',
        'organization_members',
        ['user_id'],
    )

    # 3. Seed the default "Parleo" organization
    op.execute("""
        INSERT INTO organizations (name, created_at)
        VALUES ('Parleo', NOW())
    """)

    # 4. Add organization_id + created_by to work-product tables.
    # soa_entities is intentionally NOT scoped — it remains a shared catalog.
    for table in [
        'soa_cycles',
        'soa_queries',
        'soa_query_generation_jobs',
    ]:
        op.add_column(
            table,
            sa.Column(
                'organization_id',
                sa.Integer(),
                sa.ForeignKey('organizations.id'),
                nullable=True,  # nullable during backfill, tightened below
            ),
        )
        op.add_column(
            table,
            sa.Column(
                'created_by',
                sa.String(),
                nullable=True,
                # audit-only, Supabase user_id, not enforced anywhere yet
            ),
        )

    # 5. Backfill all existing rows to the "Parleo" organization
    op.execute("""
        UPDATE soa_cycles
        SET organization_id = (
            SELECT id FROM organizations WHERE name = 'Parleo'
        )
        WHERE organization_id IS NULL
    """)
    op.execute("""
        UPDATE soa_queries
        SET organization_id = (
            SELECT id FROM organizations WHERE name = 'Parleo'
        )
        WHERE organization_id IS NULL
    """)
    op.execute("""
        UPDATE soa_query_generation_jobs
        SET organization_id = (
            SELECT id FROM organizations WHERE name = 'Parleo'
        )
        WHERE organization_id IS NULL
    """)

    # 6. Now that all rows are backfilled, enforce NOT NULL on organization_id
    for table in [
        'soa_cycles',
        'soa_queries',
        'soa_query_generation_jobs',
    ]:
        op.alter_column(
            table,
            'organization_id',
            nullable=False,
        )

    # 7. Add indexes for WHERE organization_id = ... filters
    for table in [
        'soa_cycles',
        'soa_queries',
        'soa_query_generation_jobs',
    ]:
        op.create_index(
            f'ix_{table}_organization_id',
            table,
            ['organization_id'],
        )


def downgrade() -> None:
    for table in [
        'soa_cycles',
        'soa_queries',
        'soa_query_generation_jobs',
    ]:
        op.drop_index(
            f'ix_{table}_organization_id',
            table_name=table,
        )
        op.drop_column(table, 'created_by')
        op.drop_column(table, 'organization_id')

    op.drop_index(
        'ix_org_members_user_id',
        table_name='organization_members',
    )
    op.drop_constraint(
        'uq_org_members_org_user',
        'organization_members',
        type_='unique',
    )
    op.drop_constraint(
        'ck_org_members_role',
        'organization_members',
        type_='check',
    )
    op.drop_table('organization_members')
    op.drop_table('organizations')
