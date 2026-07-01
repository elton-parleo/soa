"""
Tests for the add_expected_incentive_to_soa_queries migration.
Verifies upgrade adds the column + CHECK constraint, downgrade removes both,
and that NULL is accepted (nullable column). No live DB required.
Mirrors the pattern in test_platform_migrations.py.
"""
import importlib.util
import os

import pytest
from unittest.mock import MagicMock, call, patch

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)

_MODULE = "9ca1aba348c4_add_expected_incentive_to_soa_queries"


def _load_migration(module_name):
    path = os.path.join(_VERSIONS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── revision metadata ──────────────────────────────────────────────────────────

def test_chains_off_baby_care_migration():
    mod = _load_migration(_MODULE)
    assert mod.revision == "9ca1aba348c4"
    assert mod.down_revision == "8d154bad5968"


# ── upgrade ────────────────────────────────────────────────────────────────────

def test_upgrade_adds_column_then_constraint():
    mod = _load_migration(_MODULE)
    call_order = []

    with patch.object(mod, "op") as mock_op:
        mock_op.add_column.side_effect = lambda *a, **kw: call_order.append("add_column")
        mock_op.create_check_constraint.side_effect = lambda *a, **kw: call_order.append("create_check_constraint")
        mod.upgrade()

    assert call_order == ["add_column", "create_check_constraint"]


def test_upgrade_adds_nullable_text_column():
    import sqlalchemy as sa

    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.add_column.assert_called_once()
    table_name, column = mock_op.add_column.call_args.args
    assert table_name == "soa_queries"
    assert column.name == "expected_incentive"
    assert isinstance(column.type, sa.Text)
    assert column.nullable is True


def test_upgrade_creates_correct_check_constraint():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.create_check_constraint.assert_called_once()
    args = mock_op.create_check_constraint.call_args.args
    constraint_name, table_name, condition = args
    assert constraint_name == "ck_soa_queries_expected_incentive"
    assert table_name == "soa_queries"
    for val in ("Low", "Mixed", "High"):
        assert val in condition


# ── downgrade ─────────────────────────────────────────────────────────────────

def test_downgrade_drops_constraint_then_column():
    mod = _load_migration(_MODULE)
    call_order = []

    with patch.object(mod, "op") as mock_op:
        mock_op.drop_constraint.side_effect = lambda *a, **kw: call_order.append("drop_constraint")
        mock_op.drop_column.side_effect = lambda *a, **kw: call_order.append("drop_column")
        mod.downgrade()

    assert call_order == ["drop_constraint", "drop_column"]


def test_downgrade_drops_correct_constraint_and_column():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    mock_op.drop_constraint.assert_called_once_with(
        "ck_soa_queries_expected_incentive", "soa_queries", type_="check"
    )
    mock_op.drop_column.assert_called_once_with("soa_queries", "expected_incentive")
