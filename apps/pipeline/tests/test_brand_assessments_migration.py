"""
b4c7e19d2a08 — the outcome constraint widens, and near_miss appears.

Same mock-based convention as the tier migration's tests: assert what
op.* was called with, so the statements are checked without a database.

The property that matters most here is the one about NOT changing things.
Cycle 20260915-113207 is going to be re-scored on top of this, and the
catalog-accuracy and value-incentives rows have to come out of that with
the numbers they went in with. That holds because this migration rewrites
no row and removes no legal value: every outcome those tiers can produce
is still admitted afterwards.
"""
import importlib.util
import os
from unittest.mock import patch

import pytest

from soa_shared.expected_answers import (
    BRAND_ASSESSMENTS, EXPECTATION_OUTCOMES, VALUE_OUTCOMES,
)

_VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions",
)
_PATH = os.path.join(_VERSIONS_DIR, "b4c7e19d2a08_brand_direct_assessments.py")


def _load():
    spec = importlib.util.spec_from_file_location("brand_assessments_mig", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _calls(direction):
    mod = _load()
    with patch.object(mod, "op") as mock_op:
        getattr(mod, direction)()
    return mock_op


def test_chains_off_the_tier_migration():
    mod = _load()
    assert mod.revision == "b4c7e19d2a08"
    assert mod.down_revision == "a9f3c21b7e40"


# ── the constraint ────────────────────────────────────────────────────────

def test_the_new_constraint_admits_both_vocabularies():
    mod = _load()
    for value in VALUE_OUTCOMES + BRAND_ASSESSMENTS:
        assert f"'{value}'" in mod.NEW, value


def test_the_new_constraint_admits_exactly_what_the_models_constraint_does():
    """Two places state this list — the migration and the model's
    CheckConstraint. They are allowed to be written differently; they are
    not allowed to mean different things."""
    mod = _load()
    for value in EXPECTATION_OUTCOMES:
        assert f"'{value}'" in mod.NEW
    quoted = mod.NEW.count("'")
    assert quoted == 2 * len(EXPECTATION_OUTCOMES), "an extra value is admitted"


def test_no_value_the_old_constraint_admitted_is_dropped():
    """A migration that narrowed this would make every stored catalog and
    value row illegal the moment it ran."""
    mod = _load()
    for value in VALUE_OUTCOMES:
        assert f"'{value}'" in mod.OLD
        assert f"'{value}'" in mod.NEW


def test_upgrade_replaces_the_constraint_rather_than_adding_a_second():
    mock_op = _calls("upgrade")
    mock_op.drop_constraint.assert_called_once()
    assert mock_op.drop_constraint.call_args.args[0] == (
        "ck_soa_expectation_outcomes_outcome"
    )
    assert mock_op.drop_constraint.call_args.kwargs["type_"] == "check"
    mock_op.create_check_constraint.assert_called_once()


# ── near_miss ─────────────────────────────────────────────────────────────

def test_upgrade_adds_near_miss_as_nullable():
    """Null on every row scored before it existed, which is every row in
    the cycle this was written for. Not false — we did not observe that a
    code was named correctly, we did not look."""
    mock_op = _calls("upgrade")
    column = mock_op.add_column.call_args.args[1]
    assert column.name == "near_miss"
    assert column.nullable is True


def test_downgrade_is_the_exact_inverse_column_before_constraint():
    """Ordered on purpose: a row carrying a brand assessment fails the
    narrowed constraint, and dropping the column after that failure would
    leave the table half-migrated."""
    mock_op = _calls("downgrade")
    assert mock_op.drop_column.call_args.args == (
        "soa_expectation_outcomes", "near_miss",
    )
    mod = _load()
    assert mock_op.create_check_constraint.call_args.args[2] == mod.OLD


def test_upgrade_rewrites_no_row():
    """No UPDATE, no data migration. Re-scoring is what changes an
    outcome, and it is a separate, re-runnable act."""
    mock_op = _calls("upgrade")
    mock_op.execute.assert_not_called()
