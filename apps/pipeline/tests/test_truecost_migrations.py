"""
Tests for the truecost cycle-mode migrations:
  - a7b8c9d0e1f2_add_cycle_mode_and_truecost_tiers (soa_cycles columns)
  - b8c9d0e1f2a3_add_soa_truecost_snapshots (new table)
and SOA_TABLES registration in alembic/env.py. Verifies the upgrade/
downgrade SQL is well-formed and additive, without needing a live
database. Mirrors the pattern in test_scope_sku_migration.py.
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


def _cycle_mode_mod():
    return _load_migration("a7b8c9d0e1f2_add_cycle_mode_and_truecost_tiers")


def _snapshots_mod():
    return _load_migration("b8c9d0e1f2a3_add_soa_truecost_snapshots")


# ---------------------------------------------------------------------------
# a7b8c9d0e1f2 — cycle_mode / truecost_tiers on soa_cycles
# ---------------------------------------------------------------------------

def test_cycle_mode_migration_chains_after_scope_freeze_fields():
    mod = _cycle_mode_mod()
    assert mod.revision == "a7b8c9d0e1f2"
    assert mod.down_revision == "f6a7b8c9d0e1"


def test_cycle_mode_upgrade_adds_columns_with_query_default():
    mod = _cycle_mode_mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    add_column_calls = mock_op.add_column.call_args_list
    columns = {
        call.args[1].name: call.args[1]
        for call in add_column_calls
        if call.args[0] == "soa_cycles"
    }

    assert "cycle_mode" in columns
    assert columns["cycle_mode"].nullable is False
    assert columns["cycle_mode"].server_default.arg == "query"

    assert "truecost_tiers" in columns
    assert columns["truecost_tiers"].nullable is True


def test_cycle_mode_upgrade_adds_check_constraint():
    mod = _cycle_mode_mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.create_check_constraint.assert_called_once_with(
        "ck_soa_cycles_cycle_mode",
        "soa_cycles",
        "cycle_mode IN ('query','truecost')",
    )


def test_cycle_mode_downgrade_drops_in_safe_order():
    mod = _cycle_mode_mod()
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    mock_op.drop_constraint.assert_called_once_with(
        "ck_soa_cycles_cycle_mode", "soa_cycles", type_="check"
    )
    dropped = [c.args[1] for c in mock_op.drop_column.call_args_list]
    assert dropped == ["truecost_tiers", "cycle_mode"]


# ---------------------------------------------------------------------------
# b8c9d0e1f2a3 — soa_truecost_snapshots table
# ---------------------------------------------------------------------------

def test_snapshots_migration_chains_after_cycle_mode():
    mod = _snapshots_mod()
    assert mod.revision == "b8c9d0e1f2a3"
    assert mod.down_revision == "a7b8c9d0e1f2"


def test_snapshots_upgrade_creates_table_with_expected_columns():
    mod = _snapshots_mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.create_table.assert_called_once()
    args, _ = mock_op.create_table.call_args
    assert args[0] == "soa_truecost_snapshots"

    columns = {c.name: c for c in args[1:] if isinstance(c, sa.Column)}

    required_not_null = {"cycle_id", "scope_sku_id", "status"}
    for name in required_not_null:
        assert columns[name].nullable is False, f"{name} must be NOT NULL"

    nullable_cols = {
        "entity_id", "dealengine_listing_id", "merchant_slug", "brand",
        "category", "user_tier_name", "listed_price", "currency",
        "true_cost", "total_savings", "total_points_earned",
        "applied_deals", "available_deals", "confidence",
        "price_refreshed_at", "error_message",
    }
    for name in nullable_cols:
        assert columns[name].nullable is True, f"{name} must be nullable"

    assert columns["price_was_refreshed"].nullable is False
    assert columns["price_was_refreshed"].server_default.arg == "false"
    assert columns["status"].server_default.arg == "captured"


def test_snapshots_upgrade_adds_status_check_constraint():
    mod = _snapshots_mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    args, _ = mock_op.create_table.call_args
    check_constraints = [c for c in args[1:] if isinstance(c, sa.CheckConstraint)]
    assert any(
        "captured" in str(c.sqltext) and "ground_truth_unavailable" in str(c.sqltext)
        for c in check_constraints
    )


def test_snapshots_upgrade_adds_indexes():
    mod = _snapshots_mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    index_names = {c.args[0] for c in mock_op.create_index.call_args_list}
    assert "ix_soa_truecost_snapshots_cycle_id" in index_names
    assert "ix_soa_truecost_snapshots_scope_sku_id" in index_names
    assert "ix_soa_truecost_snapshots_dealengine_listing_id" in index_names


def test_snapshots_downgrade_drops_table():
    mod = _snapshots_mod()
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    mock_op.drop_table.assert_called_once_with("soa_truecost_snapshots")


# ---------------------------------------------------------------------------
# SOA_TABLES registration (alembic/env.py)
# ---------------------------------------------------------------------------

def test_soa_truecost_snapshots_registered_in_soa_tables():
    """
    env.py imports `from alembic import context` and reads `context.config`
    at module scope, which only exists inside an active alembic run — so
    rather than exec'ing the whole module (as the migration tests do for
    plain migration files), extract and evaluate just the SOA_TABLES
    assignment and the include_object function body via ast, the same way
    a linter would, without pulling in the alembic context machinery.
    """
    import ast

    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "alembic", "env.py",
    )
    with open(env_path) as f:
        tree = ast.parse(f.read(), filename=env_path)

    soa_tables_node = None
    include_object_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SOA_TABLES" for t in node.targets
        ):
            soa_tables_node = node
        if isinstance(node, ast.FunctionDef) and node.name == "include_object":
            include_object_node = node

    assert soa_tables_node is not None, "SOA_TABLES assignment not found in env.py"
    assert include_object_node is not None, "include_object() not found in env.py"

    namespace: dict = {}
    exec(compile(ast.Module(body=[soa_tables_node, include_object_node], type_ignores=[]), env_path, "exec"), namespace)

    assert "soa_truecost_snapshots" in namespace["SOA_TABLES"]
    include_object = namespace["include_object"]
    assert include_object(None, "soa_truecost_snapshots", "table", False, None) is True
    assert include_object(None, "some_other_table", "table", False, None) is False
