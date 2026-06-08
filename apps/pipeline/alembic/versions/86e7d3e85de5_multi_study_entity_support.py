"""multi_study_entity_support

Revision ID: 86e7d3e85de5
Revises: bea689d5b3ff
Create Date: 2026-05-18

Implements multi-study support for the SoA measurement system:
  - Creates soa_entities as a named entity registry
  - Creates soa_cycle_entities to replace hardcoded MERCHANT_ID_TO_SLUG
  - Adds study_type and study_pattern to soa_queries and soa_cycles
  - Migrates soa_coded_mentions from merchant FK to entity FK
  - Backfills all existing data for retailer_sephora study

The merchants table is never modified by this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "86e7d3e85de5"
down_revision: Union[str, None] = "bea689d5b3ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ==================================================================
    # PART A — Create new tables
    # ==================================================================

    # 1. soa_entities
    op.create_table(
        "soa_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "entity_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'retailer'"),
        ),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column(
            "merchant_id",
            sa.Integer(),
            sa.ForeignKey("merchants.id"),
            nullable=True,
        ),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_soa_entities_slug"),
        sa.CheckConstraint(
            "entity_type IN ('retailer','brand','cpg','service','aggregate')",
            name="ck_soa_entities_entity_type",
        ),
    )
    op.create_index("ix_soa_entities_merchant_id", "soa_entities", ["merchant_id"])
    op.create_index("ix_soa_entities_entity_type", "soa_entities", ["entity_type"])
    op.create_index("ix_soa_entities_category", "soa_entities", ["category"])

    # 2. soa_cycle_entities
    op.create_table(
        "soa_cycle_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("soa_cycles.id"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("soa_entities.id"),
            nullable=False,
        ),
        sa.Column("comparison_code", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "role IN ('primary','competitor')",
            name="ck_soa_cycle_entities_role",
        ),
        sa.UniqueConstraint(
            "cycle_id", "comparison_code",
            name="uq_soa_cycle_entities_cycle_code",
        ),
        sa.UniqueConstraint(
            "cycle_id", "entity_id",
            name="uq_soa_cycle_entities_cycle_entity",
        ),
    )
    op.create_index("ix_soa_cycle_entities_cycle_id", "soa_cycle_entities", ["cycle_id"])
    op.create_index("ix_soa_cycle_entities_entity_id", "soa_cycle_entities", ["entity_id"])

    # ==================================================================
    # PART B — Add columns to existing tables
    # ==================================================================

    # 3. study_type on soa_queries
    op.add_column("soa_queries", sa.Column("study_type", sa.Text(), nullable=True))

    # 4. study_pattern on soa_queries
    op.add_column("soa_queries", sa.Column("study_pattern", sa.Text(), nullable=True))

    # 5. study_type on soa_cycles
    op.add_column("soa_cycles", sa.Column("study_type", sa.Text(), nullable=True))

    # 6. study_pattern on soa_cycles
    op.add_column("soa_cycles", sa.Column("study_pattern", sa.Text(), nullable=True))

    # ==================================================================
    # PART C — Backfill data for existing rows
    # ==================================================================

    # 7. Backfill existing soa_queries
    conn.execute(text("""
        UPDATE soa_queries
        SET study_type = 'retailer_sephora',
            study_pattern = 'retailer'
        WHERE study_type IS NULL
    """))

    # 8. Backfill existing soa_cycles
    conn.execute(text("""
        UPDATE soa_cycles
        SET study_type = 'retailer_sephora',
            study_pattern = 'retailer'
        WHERE study_type IS NULL
    """))

    # 9. Insert the four Sephora retailer entities into soa_entities.
    #    Nordstrom's merchant slug is 'nordstrom'; entity slug is 'nordstrom-beauty'.
    conn.execute(text("""
        INSERT INTO soa_entities
            (name, slug, entity_type, category, merchant_id, website_url, aliases)
        SELECT
            'Sephora', 'sephora', 'retailer', 'beauty',
            m.id, 'https://www.sephora.com',
            '["Sephora.com"]'::json
        FROM merchants m WHERE m.slug = 'sephora'
        ON CONFLICT (slug) DO NOTHING
    """))

    conn.execute(text("""
        INSERT INTO soa_entities
            (name, slug, entity_type, category, merchant_id, website_url, aliases)
        SELECT
            'Ulta Beauty', 'ulta-beauty', 'retailer', 'beauty',
            m.id, 'https://www.ulta.com',
            '["Ulta", "Ulta.com"]'::json
        FROM merchants m WHERE m.slug = 'ulta-beauty'
        ON CONFLICT (slug) DO NOTHING
    """))

    conn.execute(text("""
        INSERT INTO soa_entities
            (name, slug, entity_type, category, merchant_id, website_url, aliases)
        SELECT
            'Nordstrom Beauty', 'nordstrom-beauty', 'retailer', 'beauty',
            m.id, 'https://www.nordstrom.com/browse/beauty',
            '["Nordstrom"]'::json
        FROM merchants m WHERE m.slug = 'nordstrom'
        ON CONFLICT (slug) DO NOTHING
    """))

    conn.execute(text("""
        INSERT INTO soa_entities
            (name, slug, entity_type, category, merchant_id, website_url, aliases)
        SELECT
            'Brand Direct (Aggregate)', 'brand-direct', 'aggregate', 'beauty',
            m.id, NULL,
            '["brand''s own website", "brand website", "official website"]'::json
        FROM merchants m WHERE m.slug = 'brand-direct'
        ON CONFLICT (slug) DO NOTHING
    """))

    # 10. Populate soa_cycle_entities for all existing retailer_sephora cycles.
    conn.execute(text("""
        INSERT INTO soa_cycle_entities
            (cycle_id, entity_id, comparison_code, role)
        SELECT
            c.id AS cycle_id,
            e.id AS entity_id,
            mapping.code AS comparison_code,
            mapping.role
        FROM soa_cycles c
        CROSS JOIN (
            VALUES
              ('M001', 'sephora',          'primary'),
              ('M002', 'ulta-beauty',      'competitor'),
              ('M003', 'nordstrom-beauty', 'competitor'),
              ('M004', 'brand-direct',     'competitor')
        ) AS mapping(code, slug, role)
        JOIN soa_entities e ON e.slug = mapping.slug
        WHERE c.study_type = 'retailer_sephora'
        ON CONFLICT (cycle_id, comparison_code) DO NOTHING
    """))

    # ==================================================================
    # PART D — Handle soa_coded_mentions FK change
    # ==================================================================

    # Step 1: Add entity_id as nullable
    op.add_column(
        "soa_coded_mentions",
        sa.Column("entity_id", sa.Integer(), nullable=True),
    )

    # Step 2: Populate entity_id from merchant_id via soa_entities
    conn.execute(text("""
        UPDATE soa_coded_mentions cm
        SET entity_id = e.id
        FROM soa_entities e
        WHERE e.merchant_id = cm.merchant_id
    """))

    # Step 3: Verify no nulls remain
    null_count = conn.execute(text(
        "SELECT COUNT(*) FROM soa_coded_mentions WHERE entity_id IS NULL"
    )).scalar()
    if null_count and int(null_count) > 0:
        raise RuntimeError(
            f"Migration failed: {null_count} soa_coded_mentions rows could not be "
            "mapped to soa_entities. Ensure all merchant_ids in soa_coded_mentions "
            "were seeded into soa_entities in step 9 before running this migration."
        )

    # Step 4: Make entity_id not nullable
    op.alter_column("soa_coded_mentions", "entity_id", nullable=False)

    # Step 5: Add FK constraint from entity_id to soa_entities
    op.create_foreign_key(
        "fk_coded_mentions_entity",
        "soa_coded_mentions",
        "soa_entities",
        ["entity_id"],
        ["id"],
    )

    # Step 6: Add indexes on entity_id
    op.create_index(
        "ix_soa_coded_mentions_entity_id",
        "soa_coded_mentions",
        ["entity_id"],
    )
    op.create_index(
        "ix_soa_coded_mentions_run_entity",
        "soa_coded_mentions",
        ["run_id", "entity_id"],
    )
    op.create_index(
        "ix_soa_coded_mentions_entity_mentioned",
        "soa_coded_mentions",
        ["entity_id", "mentioned"],
    )

    # Add new unique constraint on (run_id, entity_id)
    op.create_unique_constraint(
        "uq_soa_coded_mentions_run_entity",
        "soa_coded_mentions",
        ["run_id", "entity_id"],
    )

    # Step 7: Drop old merchant FK constraint (keep column for data safety)
    op.drop_constraint(
        "soa_coded_mentions_merchant_id_fkey",
        "soa_coded_mentions",
        type_="foreignkey",
    )

    # Drop old unique constraint on (run_id, merchant_id)
    op.drop_constraint(
        "uq_soa_coded_mentions_run_merchant",
        "soa_coded_mentions",
        type_="unique",
    )

    # Drop old composite indexes replaced by entity versions
    op.drop_index("ix_soa_coded_mentions_run_merchant", "soa_coded_mentions")
    op.drop_index("ix_soa_coded_mentions_merchant_mentioned", "soa_coded_mentions")

    # ==================================================================
    # PART E — Add NOT NULL constraints and indexes
    # ==================================================================

    # 12. Make study columns NOT NULL
    op.alter_column("soa_queries", "study_type", nullable=False)
    op.alter_column("soa_queries", "study_pattern", nullable=False)
    op.alter_column("soa_cycles", "study_type", nullable=False)
    op.alter_column("soa_cycles", "study_pattern", nullable=False)

    # 13. Indexes on new study columns
    op.create_index("ix_soa_queries_study_type", "soa_queries", ["study_type"])
    op.create_index("ix_soa_queries_study_pattern", "soa_queries", ["study_pattern"])
    op.create_index("ix_soa_cycles_study_type", "soa_cycles", ["study_type"])

    # 14. Check constraints on study columns
    op.create_check_constraint(
        "ck_soa_queries_study_pattern",
        "soa_queries",
        "study_pattern IN ('retailer','brand_at_retail','brand_vs_brand')",
    )
    op.create_check_constraint(
        "ck_soa_cycles_study_pattern",
        "soa_cycles",
        "study_pattern IN ('retailer','brand_at_retail','brand_vs_brand')",
    )


def downgrade() -> None:
    # Restore soa_coded_mentions merchant FK
    op.create_foreign_key(
        "soa_coded_mentions_merchant_id_fkey",
        "soa_coded_mentions",
        "merchants",
        ["merchant_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_soa_coded_mentions_run_merchant",
        "soa_coded_mentions",
        ["run_id", "merchant_id"],
    )
    op.create_index(
        "ix_soa_coded_mentions_run_merchant",
        "soa_coded_mentions",
        ["run_id", "merchant_id"],
    )
    op.create_index(
        "ix_soa_coded_mentions_merchant_mentioned",
        "soa_coded_mentions",
        ["merchant_id", "mentioned"],
    )

    # Remove entity-related additions to coded_mentions
    op.drop_constraint("uq_soa_coded_mentions_run_entity", "soa_coded_mentions", type_="unique")
    op.drop_constraint("fk_coded_mentions_entity", "soa_coded_mentions", type_="foreignkey")
    op.drop_index("ix_soa_coded_mentions_entity_id", "soa_coded_mentions")
    op.drop_index("ix_soa_coded_mentions_run_entity", "soa_coded_mentions")
    op.drop_index("ix_soa_coded_mentions_entity_mentioned", "soa_coded_mentions")
    op.drop_column("soa_coded_mentions", "entity_id")

    # Remove study columns and constraints
    op.drop_constraint("ck_soa_queries_study_pattern", "soa_queries", type_="check")
    op.drop_constraint("ck_soa_cycles_study_pattern", "soa_cycles", type_="check")
    op.drop_index("ix_soa_queries_study_type", "soa_queries")
    op.drop_index("ix_soa_queries_study_pattern", "soa_queries")
    op.drop_index("ix_soa_cycles_study_type", "soa_cycles")
    op.drop_column("soa_queries", "study_type")
    op.drop_column("soa_queries", "study_pattern")
    op.drop_column("soa_cycles", "study_type")
    op.drop_column("soa_cycles", "study_pattern")

    # Drop new tables (reverse dependency order)
    op.drop_table("soa_cycle_entities")
    op.drop_table("soa_entities")
