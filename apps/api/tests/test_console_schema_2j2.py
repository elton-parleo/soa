"""
2J-2 (4): the console test schema's column types are the models'.

soa_full_loop_requests' timestamps were hand-declared TIMESTAMP in the console
test schema while production's are timestamptz (c4e2b7d9a1f3); on Postgres
that made a fresh request look hours old, and two test modules ALTERed the
columns back to production's type. The schema is now created from the models
(tests/console_tables.py). These tests fail when it drifts: a column whose
type in the test database is not its model's, or a test that patches a
console column's type again. On sqlite and a local Postgres.
"""
import os
import re

import pytest
from sqlalchemy import inspect

from soa_shared.models.base import Base
from tests.console_tables import CONSOLE_TABLES, column_type
from tests.test_console_2c3a import db  # noqa: F401  (fixture)

HERE = os.path.dirname(__file__)


def _normal(type_name: str) -> str:
    """What a reflected type and a compiled one share: Postgres reflects
    VARCHAR as VARCHAR and TIMESTAMP WITH TIME ZONE as TIMESTAMP(timezone=True),
    which compile back to the same DDL."""
    return re.sub(r'\s+', ' ', type_name.upper()).strip()


def test_every_console_column_has_its_model_s_type_in_the_test_database(db):
    insp = inspect(db)
    dialect = db.dialect
    for table, columns in CONSOLE_TABLES.items():
        reflected = {c['name']: c['type'] for c in insp.get_columns(table)}
        assert set(columns) <= set(reflected), table
        for name in columns:
            if name == 'id':
                continue
            got = _normal(reflected[name].compile(dialect=dialect))
            assert got == _normal(column_type(dialect.name, table, name)), f'{table}.{name}: {got}'


def test_timestamps_are_production_s_timestamptz_on_postgres(db):
    if db.dialect.name != 'postgresql':
        pytest.skip('sqlite has no timestamptz')
    insp = inspect(db)
    for table in ('soa_full_loop_requests', 'soa_runs', 'soa_cycles', 'organizations'):
        for c in insp.get_columns(table):
            model = Base.metadata.tables[table].c.get(c['name'])
            if model is not None and getattr(model.type, 'timezone', None) is not None:
                assert c['type'].timezone == model.type.timezone, f"{table}.{c['name']}"
    loop = {c['name']: c['type'] for c in insp.get_columns('soa_full_loop_requests')}
    assert loop['created_at'].timezone is True and loop['updated_at'].timezone is True


def test_no_test_patches_a_console_column_s_type():
    pattern = re.compile(r'ALTER TABLE (\w+) ALTER COLUMN', re.I)
    offenders = []
    for name in sorted(os.listdir(HERE)):
        if name.endswith('.py'):
            with open(os.path.join(HERE, name)) as fh:
                offenders += [(name, t) for t in pattern.findall(fh.read()) if t in CONSOLE_TABLES]
    assert offenders == []
