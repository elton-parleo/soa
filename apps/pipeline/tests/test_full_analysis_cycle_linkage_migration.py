"""
Tests for the Full Analysis cycle-linkage migration (9fe17836f9d5) —
verifies the upgrade/downgrade SQL for soa_cycles' new
source_lite_request_id/study_series_id/prior_cycle_id columns and
soa_lite_scan_results' new cycle_id column, without needing a live
database. Mirrors the pattern used in test_scope_sku_migration.py.
"""
import importlib.util
import os
from unittest.mock import patch

import sqlalchemy as sa

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)


def _load_migration(module_name):
    path = os.path.join(_VERSIONS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mod():
    return _load_migration("9fe17836f9d5_add_full_analysis_cycle_linkage")


def test_revision_chains_after_add_soa_demo_requests():
    mod = _mod()
    assert mod.revision == "9fe17836f9d5"
    assert mod.down_revision == "b3c9f1a2d4e6"


def test_upgrade_adds_nullable_columns_to_soa_cycles():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    add_column_calls = mock_op.add_column.call_args_list
    cycles_columns = {
        call.args[1].name: call.args[1]
        for call in add_column_calls if call.args[0] == "soa_cycles"
    }
    assert set(cycles_columns) == {"source_lite_request_id", "study_series_id", "prior_cycle_id"}
    for col in cycles_columns.values():
        assert col.nullable is True


def test_upgrade_adds_nullable_cycle_id_to_scan_results():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    add_column_calls = mock_op.add_column.call_args_list
    scan_columns = {
        call.args[1].name: call.args[1]
        for call in add_column_calls if call.args[0] == "soa_lite_scan_results"
    }
    assert set(scan_columns) == {"cycle_id"}
    assert scan_columns["cycle_id"].nullable is True


def test_upgrade_adds_indexes_and_self_reference_check():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    index_calls = [c.args for c in mock_op.create_index.call_args_list]
    index_names = {c[0] for c in index_calls}
    assert index_names == {
        "ix_soa_cycles_source_lite_request_id",
        "ix_soa_cycles_prior_cycle_id",
        "ix_soa_cycles_study_series_id",
        "ix_soa_lite_scan_results_cycle_id",
    }

    mock_op.create_check_constraint.assert_called_once()
    args, _ = mock_op.create_check_constraint.call_args
    assert args[0] == "ck_soa_cycles_prior_cycle_not_self"
    assert args[1] == "soa_cycles"
    assert "prior_cycle_id" in args[2]


def test_upgrade_backfills_scan_results_cycle_id_idempotently():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    executed_sql = " ".join(
        str(c.args[0]) for c in mock_op.execute.call_args_list
    )
    assert "UPDATE soa_lite_scan_results" in executed_sql
    assert "lr.cycle_id IS NOT NULL" in executed_sql
    # Idempotency guard — re-running must not re-touch already-set rows.
    assert "sr.cycle_id IS DISTINCT FROM lr.cycle_id" in executed_sql


def test_downgrade_drops_columns_indexes_and_constraint_in_safe_order():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    dropped_columns = {
        (call.args[0], call.args[1]) for call in mock_op.drop_column.call_args_list
    }
    assert dropped_columns == {
        ("soa_lite_scan_results", "cycle_id"),
        ("soa_cycles", "prior_cycle_id"),
        ("soa_cycles", "study_series_id"),
        ("soa_cycles", "source_lite_request_id"),
    }

    mock_op.drop_constraint.assert_called_once_with(
        "ck_soa_cycles_prior_cycle_not_self", "soa_cycles", type_="check",
    )

    dropped_indexes = {
        call.args[0] for call in mock_op.drop_index.call_args_list
    }
    assert dropped_indexes == {
        "ix_soa_lite_scan_results_cycle_id",
        "ix_soa_cycles_study_series_id",
        "ix_soa_cycles_prior_cycle_id",
        "ix_soa_cycles_source_lite_request_id",
    }
