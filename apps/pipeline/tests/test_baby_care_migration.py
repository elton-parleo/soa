"""
Tests for the Baby Care category / personas / Awareness stage migration.
Verifies upgrade/downgrade SQL is well-formed and additive (existing values
are preserved). Mirrors the pattern in test_platform_migrations.py.
"""
import importlib.util
import os
from unittest.mock import MagicMock, call, patch

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)

_MODULE = "8d154bad5968_add_baby_care_category_personas_"


def _load_migration(module_name):
    path = os.path.join(_VERSIONS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── revision metadata ──────────────────────────────────────────────────────────

def test_chains_off_correct_head():
    mod = _load_migration(_MODULE)
    assert mod.revision == "8d154bad5968"
    assert mod.down_revision == "b8c9d0e1f2a3"


# ── upgrade ────────────────────────────────────────────────────────────────────

def test_upgrade_updates_all_three_constraints():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    assert mock_op.drop_constraint.call_count == 3
    assert mock_op.create_check_constraint.call_count == 3


def test_upgrade_category_keeps_existing_and_adds_baby_care():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    calls = mock_op.create_check_constraint.call_args_list
    category_call = next(c for c in calls if c.args[0] == "ck_soa_queries_category")
    condition = category_call.args[2]
    for existing in ("Skincare", "Makeup", "Fragrance", "Haircare",
                     "Cross-Category", "Grooming", "Oral Care"):
        assert existing in condition
    assert "Baby Care" in condition


def test_upgrade_stage_adds_awareness_first_and_keeps_existing():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    calls = mock_op.create_check_constraint.call_args_list
    stage_call = next(c for c in calls if c.args[0] == "ck_soa_queries_stage")
    condition = stage_call.args[2]
    for existing in ("Research", "Comparison", "Ready to Buy"):
        assert existing in condition
    assert "Awareness" in condition


def test_upgrade_persona_keeps_existing_and_adds_baby_care_personas():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    calls = mock_op.create_check_constraint.call_args_list
    persona_call = next(c for c in calls if c.args[0] == "ck_soa_queries_persona")
    condition = persona_call.args[2]
    for existing in ("Casual / Gift Buyer", "Value-Conscious", "Beauty Enthusiast",
                     "Problem-Skin Sufferer", "Eco-Conscious / Minimalist",
                     "Oral Health Symptom Sufferer"):
        assert existing in condition
    for new in ("New / First-Time Parent", "Value-Conscious Parent",
                "Sensitive-Skin Baby Parent", "Subscription / Replenishment Parent",
                "Eco-Conscious Parent"):
        assert new in condition


# ── downgrade ─────────────────────────────────────────────────────────────────

def test_downgrade_removes_baby_care_from_category():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()
    calls = mock_op.create_check_constraint.call_args_list
    category_call = next(c for c in calls if c.args[0] == "ck_soa_queries_category")
    condition = category_call.args[2]
    assert "Baby Care" not in condition
    for existing in ("Skincare", "Makeup", "Fragrance", "Haircare",
                     "Cross-Category", "Grooming", "Oral Care"):
        assert existing in condition


def test_downgrade_removes_awareness_from_stage():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()
    calls = mock_op.create_check_constraint.call_args_list
    stage_call = next(c for c in calls if c.args[0] == "ck_soa_queries_stage")
    condition = stage_call.args[2]
    assert "Awareness" not in condition
    for existing in ("Research", "Comparison", "Ready to Buy"):
        assert existing in condition


def test_downgrade_removes_baby_care_personas():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()
    calls = mock_op.create_check_constraint.call_args_list
    persona_call = next(c for c in calls if c.args[0] == "ck_soa_queries_persona")
    condition = persona_call.args[2]
    for new in ("New / First-Time Parent", "Value-Conscious Parent",
                "Sensitive-Skin Baby Parent", "Subscription / Replenishment Parent",
                "Eco-Conscious Parent"):
        assert new not in condition
    for existing in ("Casual / Gift Buyer", "Value-Conscious", "Beauty Enthusiast",
                     "Problem-Skin Sufferer", "Eco-Conscious / Minimalist",
                     "Oral Health Symptom Sufferer"):
        assert existing in condition


def test_downgrade_updates_all_three_constraints():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.downgrade()
    assert mock_op.drop_constraint.call_count == 3
    assert mock_op.create_check_constraint.call_count == 3
