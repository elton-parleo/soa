"""
2L-1 (B3): a2c4e6f8b1d3 adds soa_query_generation_jobs.archived_at, one
nullable column, and its downgrade drops it. Round-tripped on a throwaway
local Postgres (scripts/migration_roundtrip.py --from f7c2a9e4b1d6); these
pin the operations without a database.
"""
import importlib.util
import os
from unittest import mock

_PATH = os.path.join(os.path.dirname(__file__), '..', 'alembic', 'versions', 'a2c4e6f8b1d3_study_archived_at.py')


def _load():
    spec = importlib.util.spec_from_file_location('m_a2c4e6f8b1d3', _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chains_off_the_comparison_tier():
    mod = _load()
    assert (mod.revision, mod.down_revision) == ('a2c4e6f8b1d3', 'f7c2a9e4b1d6')


def test_upgrade_adds_one_nullable_timestamptz_column():
    mod = _load()
    with mock.patch.object(mod, 'op') as op:
        mod.upgrade()
    [call] = op.add_column.call_args_list
    table, column = call.args
    assert table == 'soa_query_generation_jobs' and column.name == 'archived_at'
    assert column.nullable and column.type.timezone
    assert not op.execute.called


def test_downgrade_drops_it():
    mod = _load()
    with mock.patch.object(mod, 'op') as op:
        mod.downgrade()
    op.drop_column.assert_called_once_with('soa_query_generation_jobs', 'archived_at')
