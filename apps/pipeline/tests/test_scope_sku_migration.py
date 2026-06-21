"""
Tests for the soa_scope_skus migration (e5f6a7b8c9d0) — verifies the
upgrade/downgrade SQL for the new table and the two new nullable
soa_incentive_scores columns, without needing a live database. Mirrors the
pattern used in test_platform_migrations.py.
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
    return _load_migration("e5f6a7b8c9d0_add_soa_scope_skus")


def test_revision_chains_after_retrieved_sources():
    mod = _mod()
    assert mod.revision == "e5f6a7b8c9d0"
    assert mod.down_revision == "d4e5f6a7b8c9"


def test_upgrade_creates_soa_scope_skus_table_with_role_check():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.create_table.assert_called_once()
    args, _ = mock_op.create_table.call_args
    table_name = args[0]
    assert table_name == "soa_scope_skus"

    columns = {c.name: c for c in args[1:] if isinstance(c, sa.Column)}
    expected_nullable_true = {
        "cycle_id", "entity_id", "dealengine_listing_id",
        "dealengine_catalog_product_id", "merchant_slug", "merchant_sku",
        "brand", "category", "product_url", "listed_price", "currency",
        "display_name", "updated_at",
    }
    for col_name in expected_nullable_true:
        assert columns[col_name].nullable is True, f"{col_name} must be nullable"

    assert columns["role"].nullable is False
    assert columns["is_active"].nullable is False

    check_constraints = [c for c in args[1:] if isinstance(c, sa.CheckConstraint)]
    assert any("role IN" in str(c.sqltext) for c in check_constraints)


def test_upgrade_adds_indexes_on_scope_skus():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    index_calls = [c.args for c in mock_op.create_index.call_args_list]
    index_names = {c[0] for c in index_calls}
    assert "ix_soa_scope_skus_cycle_id" in index_names
    assert "ix_soa_scope_skus_entity_id" in index_names
    assert "ix_soa_scope_skus_dealengine_listing_id" in index_names


def test_upgrade_adds_nullable_columns_to_soa_incentive_scores():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    add_column_calls = mock_op.add_column.call_args_list
    targets = {call.args[0]: call.args[1] for call in add_column_calls}

    assert "soa_incentive_scores" in targets
    incentive_score_columns = [
        call.args[1] for call in add_column_calls if call.args[0] == "soa_incentive_scores"
    ]
    col_by_name = {c.name: c for c in incentive_score_columns}
    assert "scope_sku_id" in col_by_name
    assert col_by_name["scope_sku_id"].nullable is True
    assert "dealengine_listing_id" in col_by_name
    assert col_by_name["dealengine_listing_id"].nullable is True


def test_downgrade_drops_table_and_columns_in_safe_order():
    mod = _mod()
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    mock_op.drop_table.assert_called_once_with("soa_scope_skus")
    dropped_columns = {
        call.args[1] for call in mock_op.drop_column.call_args_list
        if call.args[0] == "soa_incentive_scores"
    }
    assert dropped_columns == {"scope_sku_id", "dealengine_listing_id"}
