"""
Tests for the Pet Care category / personas migration.
The migration's value lists are hand-copied (as in the Baby Care template),
so these tests pin them to soa_shared.constants and check that downgrade
restores exactly the previous constraint definitions.
"""
import importlib.util
import os
import re
from unittest.mock import patch

from soa_shared.constants import QUERY_CATEGORIES, QUERY_PERSONAS

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)

_MODULE = "d439b7309af4_add_pet_care_category_personas"

_PET_CARE_PERSONAS = [
    "New Pet Parent",
    "Value-Conscious Pet Parent",
    "Health-Focused Pet Parent",
    "Subscription / Replenishment Pet Parent",
    "Premium / Quality-First Pet Parent",
]


def _load_migration(module_name):
    path = os.path.join(_VERSIONS_DIR, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _values(direction, constraint):
    """Run upgrade/downgrade against a mocked op; return the quoted values
    in the named constraint's condition, in order."""
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        getattr(mod, direction)()
    calls = mock_op.create_check_constraint.call_args_list
    condition = next(c for c in calls if c.args[0] == constraint).args[2]
    return re.findall(r"'([^']*)'", condition)


# ── revision metadata ──────────────────────────────────────────────────────────

def test_chains_off_correct_head():
    mod = _load_migration(_MODULE)
    assert mod.revision == "d439b7309af4"
    assert mod.down_revision == "b4c7e19d2a08"


# ── upgrade ────────────────────────────────────────────────────────────────────

def test_upgrade_touches_only_category_and_persona():
    mod = _load_migration(_MODULE)
    with patch.object(mod, "op") as mock_op:
        mod.upgrade()
    names = [c.args[0] for c in mock_op.create_check_constraint.call_args_list]
    assert names == ["ck_soa_queries_category", "ck_soa_queries_persona"]
    assert mock_op.drop_constraint.call_count == 2


def test_upgrade_category_list_matches_constants():
    assert _values("upgrade", "ck_soa_queries_category") == list(QUERY_CATEGORIES)


def test_upgrade_persona_list_matches_constants():
    assert _values("upgrade", "ck_soa_queries_persona") == list(QUERY_PERSONAS)


def test_upgrade_adds_pet_care_values():
    assert "Pet Care" in _values("upgrade", "ck_soa_queries_category")
    personas = _values("upgrade", "ck_soa_queries_persona")
    for p in _PET_CARE_PERSONAS:
        assert p in personas


# ── downgrade ──────────────────────────────────────────────────────────────────

def test_downgrade_restores_previous_category_list():
    assert _values("downgrade", "ck_soa_queries_category") == [
        c for c in QUERY_CATEGORIES if c != "Pet Care"
    ]


def test_downgrade_restores_previous_persona_list():
    assert _values("downgrade", "ck_soa_queries_persona") == [
        p for p in QUERY_PERSONAS if p not in _PET_CARE_PERSONAS
    ]
