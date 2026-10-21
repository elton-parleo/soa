"""
2J-2: the console test schema, its column types taken from the models.

The console tests create only the tables and columns they read, but each
column's type is the model's (soa_shared/models), compiled for the engine's
dialect: on Postgres that is production's (TIMESTAMP WITH TIME ZONE for a
DateTime(timezone=True), JSON for JSON), so a type can no longer drift the
way soa_full_loop_requests' timestamps did (declared TIMESTAMP here while
production's are timestamptz, which made a fresh request look hours old on
Postgres and needed a per-test ALTER). On sqlite a JSON column is TEXT, as
the hand-written schema had it: sqlite's JSON type name has NUMERIC affinity.

What stays declared here is what is not a type: the columns each table
carries, the primary key, and the few constraints and defaults the tests
rely on (they are the ones the hand-written schema had). Nullability is not
mirrored: the recorded fixtures leave out columns production requires.
"""
from typing import Dict, Iterable, Tuple

from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql, sqlite

from soa_shared.models import merchant_ref, soa_models  # noqa: F401  (registers every table)
from soa_shared.models.base import Base

#: table -> its columns, in the order the hand-written schema declared them
CONSOLE_TABLES: Dict[str, Tuple[str, ...]] = {
    'organizations': ('id', 'name', 'created_at', 'truesync_tenant_slug', 'truesync_token_sealed', 'truesync_token_id'),
    'organization_members': ('id', 'organization_id', 'user_id', 'email', 'role', 'is_operator', 'created_at'),
    'soa_query_generation_jobs': ('id', 'study_type', 'study_name', 'description', 'target_count', 'created_count',
                                  'status', 'organization_id', 'customer_organization_id', 'created_by', 'created_at',
                                  'study_pattern', 'allowed_categories', 'retailer_names', 'syndicated_merchant',
                                  'tier_config', 'archived_at'),
    'soa_entities': ('id', 'name', 'slug', 'entity_type', 'category', 'website_url', 'aliases'),
    'soa_cycles': ('id', 'cycle_code', 'study_type', 'study_pattern', 'status', 'cycle_mode', 'start_date', 'end_date',
                   'total_runs_planned', 'completed_runs', 'platforms', 'runs_per_query', 'organization_id',
                   'created_at', 'notes', 'full_loop_run_id', 'reference_prices'),
    'soa_cycle_entities': ('id', 'cycle_id', 'entity_id', 'comparison_code', 'role'),
    'soa_queries': ('id', 'query_code', 'query_text', 'category', 'stage', 'specificity', 'persona', 'status',
                    'study_type', 'study_pattern', 'organization_id', 'tier', 'expected_answer', 'provenance',
                    'source_ref'),
    'soa_runs': ('id', 'cycle_id', 'query_id', 'platform', 'run_number', 'run_at', 'raw_response', 'status', 'surface',
                 'collector', 'answer_status', 'retrieved_sources'),
    'soa_expectation_outcomes': ('id', 'run_id', 'query_id', 'cycle_id', 'platform', 'tier', 'expected_answer',
                                 'extraction', 'outcome', 'outcome_reason', 'flags', 'claim_results', 'source_split',
                                 'reason_code', 'surface', 'source_attribution', 'domain_cited'),
    'soa_coded_mentions': ('id', 'run_id', 'entity_id', 'mentioned', 'position', 'strength', 'deal_cited',
                           'member_value_cited'),
    'soa_full_loop_requests': ('id', 'organization_id', 'merchant_slug', 'study_type', 'platforms', 'runs_per_query',
                               'allow_hosted_render', 'supply_run_id', 'supply_status', 'cycle_id', 'status', 'error',
                               'created_by', 'created_at', 'updated_at'),
}

#: (table, column) -> what follows the type: constraints and defaults, not types
EXTRAS: Dict[Tuple[str, str], str] = {
    ('organizations', 'name'): 'UNIQUE',
    ('organizations', 'truesync_tenant_slug'): 'UNIQUE',
    ('organization_members', 'role'): "DEFAULT 'member'",
    ('organization_members', 'is_operator'): 'NOT NULL DEFAULT FALSE',
    ('soa_query_generation_jobs', 'study_type'): 'UNIQUE',
    ('soa_cycles', 'cycle_code'): 'UNIQUE',
    ('soa_full_loop_requests', 'allow_hosted_render'): 'NOT NULL DEFAULT TRUE',
}

_DIALECTS = {'postgresql': postgresql.dialect(), 'sqlite': sqlite.dialect()}


def column_type(dialect_name: str, table: str, column: str) -> str:
    """The model's type for `table.column`, as `dialect_name` declares it."""
    col = Base.metadata.tables[table].c[column]
    if dialect_name == 'sqlite' and isinstance(col.type, JSON):
        return 'TEXT'
    return col.type.compile(dialect=_DIALECTS[dialect_name])


def create_table_sql(dialect_name: str, table: str, columns: Iterable[str] = None) -> str:
    pk = 'SERIAL PRIMARY KEY' if dialect_name == 'postgresql' else 'INTEGER PRIMARY KEY'
    parts = []
    for name in columns or CONSOLE_TABLES[table]:
        if name == 'id':
            parts.append(f'id {pk}')
            continue
        extra = EXTRAS.get((table, name))
        parts.append(' '.join(p for p in (name, column_type(dialect_name, table, name), extra) if p))
    return f"CREATE TABLE {table} ({', '.join(parts)})"


def create_console_tables(conn) -> None:
    for table in CONSOLE_TABLES:
        conn.exec_driver_sql(create_table_sql(conn.dialect.name, table))


def add_columns(conn, table: str, *columns: str) -> None:
    """ALTER TABLE ... ADD COLUMN for columns the console schema leaves out
    (a migration a test applies, a column one screen reads), each with the
    model's type."""
    for name in columns:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {column_type(conn.dialect.name, table, name)}")
