"""
Tests for the standalone-cycle-scan migration (8c31844a4171) — verifies
the upgrade/downgrade SQL for relaxing soa_lite_scan_results.
lite_request_id to nullable and adding its ownership check constraint,
without needing a live database. Mirrors the pattern used in
test_scope_sku_migration.py.
"""
import importlib.util
import os
from unittest.mock import patch

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
    return _load_migration("8c31844a4171_allow_standalone_cycle_scan_results")


def test_revision_chains_after_full_analysis_cycle_linkage():
    mod = _mod()
    assert mod.revision == "8c31844a4171"
    assert mod.down_revision == "9fe17836f9d5"


def test_upgrade_relaxes_lite_request_id_and_adds_owned_check():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.alter_column.assert_called_once_with(
        "soa_lite_scan_results", "lite_request_id",
        existing_type=mock_op.alter_column.call_args.kwargs["existing_type"],
        nullable=True,
    )
    mock_op.create_check_constraint.assert_called_once_with(
        "ck_soa_lite_scan_results_owned",
        "soa_lite_scan_results",
        "lite_request_id IS NOT NULL OR cycle_id IS NOT NULL",
    )


def test_downgrade_drops_check_then_restores_not_null():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    mock_op.drop_constraint.assert_called_once_with(
        "ck_soa_lite_scan_results_owned", "soa_lite_scan_results", type_="check",
    )
    mock_op.alter_column.assert_called_once_with(
        "soa_lite_scan_results", "lite_request_id",
        existing_type=mock_op.alter_column.call_args.kwargs["existing_type"],
        nullable=False,
    )
