"""
Tests for the soa_lite_requests / 'General' category migration. Verifies
upgrade/downgrade SQL is well-formed and the category CHECK constraint
change is additive (existing values are preserved). Mirrors the pattern in
test_baby_care_migration.py.
"""
import importlib.util
import os
from unittest.mock import patch

import sqlalchemy as sa

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)

_MODULE = "6fdb77471ebc_add_soa_lite_requests_and_general_"


def _load_migration(module_name):
    path = os.path.join(_VERSIONS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── revision metadata ──────────────────────────────────────────────────────

def test_chains_off_correct_head():
    mod = _load_migration(_MODULE)
    assert mod.revision == "6fdb77471ebc"
    assert mod.down_revision == "c5d6e7f8a9b0"


# ── upgrade ──────────────────────────────────────────────────────────────

def test_upgrade_creates_soa_lite_requests_table():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    assert mock_op.create_table.call_count == 1
    table_call = mock_op.create_table.call_args
    assert table_call.args[0] == "soa_lite_requests"
    column_names = [c.name for c in table_call.args[1:] if isinstance(c, sa.Column)]
    assert column_names == [
        "id", "token", "email", "brand_name", "competitor_names",
        "brand_entity_id", "competitor_entity_ids", "study_type", "cycle_id",
        "status", "error_message", "ip_hash", "organization_id",
        "created_at", "updated_at",
    ]


def test_upgrade_creates_expected_indexes():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    index_names = {c.args[0] for c in mock_op.create_index.call_args_list}
    assert index_names == {
        "ix_soa_lite_requests_status",
        "ix_soa_lite_requests_ip_hash_created_at",
        "ix_soa_lite_requests_organization_id",
    }


def test_upgrade_category_keeps_existing_and_adds_general():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    condition = mock_op.create_check_constraint.call_args.args[2]
    for existing in ("Skincare", "Makeup", "Fragrance", "Haircare",
                     "Cross-Category", "Grooming", "Oral Care", "Baby Care"):
        assert existing in condition
    assert "General" in condition


# ── downgrade ────────────────────────────────────────────────────────────

def test_downgrade_drops_soa_lite_requests_table():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()
    mock_op.drop_table.assert_called_once_with("soa_lite_requests")


def test_downgrade_removes_general_from_category():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()
    condition = mock_op.create_check_constraint.call_args.args[2]
    assert "General" not in condition
    for existing in ("Skincare", "Makeup", "Fragrance", "Haircare",
                     "Cross-Category", "Grooming", "Oral Care", "Baby Care"):
        assert existing in condition
