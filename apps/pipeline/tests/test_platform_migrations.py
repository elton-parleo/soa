"""
Tests for the gemini_grounded platform CHECK-constraint migration and the
retrieved_sources column migration — verifies the upgrade/downgrade SQL is
well-formed and additive (existing platform values are preserved), without
needing a live database. Mirrors the pattern used for the existing
bea689d5b3ff_add_claude_to_soa_runs_platform.py migration.
"""
import importlib.util
import os
from unittest.mock import MagicMock, patch

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)


def _load_migration(module_name):
    # The installed "alembic" library package shadows the local alembic/
    # directory for normal package imports, so load the migration file
    # directly from its path instead of via `import alembic.versions.*`.
    path = os.path.join(_VERSIONS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gemini_grounded_migration_upgrade_keeps_existing_values_and_adds_new():
    mod = _load_migration("c3d4e5f6a7b8_add_gemini_grounded_to_soa_runs_platform")

    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.drop_constraint.assert_called_once_with(
        "ck_soa_runs_platform", "soa_runs", type_="check"
    )
    mock_op.create_check_constraint.assert_called_once()
    args, _ = mock_op.create_check_constraint.call_args
    constraint_name, table_name, condition = args
    assert constraint_name == "ck_soa_runs_platform"
    assert table_name == "soa_runs"
    for existing in ("chatgpt", "perplexity", "gemini", "claude"):
        assert existing in condition
    assert "gemini_grounded" in condition


def test_gemini_grounded_migration_downgrade_removes_new_value_only():
    mod = _load_migration("c3d4e5f6a7b8_add_gemini_grounded_to_soa_runs_platform")

    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    args, _ = mock_op.create_check_constraint.call_args
    _, _, condition = args
    assert "gemini_grounded" not in condition
    for existing in ("chatgpt", "perplexity", "gemini", "claude"):
        assert existing in condition


def test_gemini_grounded_migration_revision_chains_correctly():
    mod = _load_migration("c3d4e5f6a7b8_add_gemini_grounded_to_soa_runs_platform")
    assert mod.revision == "c3d4e5f6a7b8"
    assert mod.down_revision == "b2c3d4e5f6a7"


def test_retrieved_sources_migration_adds_nullable_json_column():
    mod = _load_migration("d4e5f6a7b8c9_add_retrieved_sources_to_soa_runs")

    with patch.object(mod, "op") as mock_op:
        mod.upgrade()

    mock_op.add_column.assert_called_once()
    args, _ = mock_op.add_column.call_args
    table_name, column = args
    assert table_name == "soa_runs"
    assert column.name == "retrieved_sources"
    assert column.nullable is True


def test_retrieved_sources_migration_downgrade_drops_column():
    mod = _load_migration("d4e5f6a7b8c9_add_retrieved_sources_to_soa_runs")

    with patch.object(mod, "op") as mock_op:
        mod.downgrade()

    mock_op.drop_column.assert_called_once_with("soa_runs", "retrieved_sources")


def test_retrieved_sources_migration_chains_after_gemini_grounded():
    mod = _load_migration("d4e5f6a7b8c9_add_retrieved_sources_to_soa_runs")
    assert mod.revision == "d4e5f6a7b8c9"
    assert mod.down_revision == "c3d4e5f6a7b8"
