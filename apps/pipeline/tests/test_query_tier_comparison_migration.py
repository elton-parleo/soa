"""
f7c2a9e4b1d6 — ck_soa_queries_tier admits `comparison` (2K-1).

The mock-based convention of the other constraint migrations: assert what
op.* was called with. The "model and migration mean the same thing"
tripwire for the tier list lives here now (a9f3c21b7e40's test checks the
four it was written for).
"""
import importlib.util
import os
from unittest.mock import MagicMock, patch

import pytest

from soa_shared.expected_answers import QUERY_TIERS

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "alembic", "versions", "f7c2a9e4b1d6_query_tier_comparison.py")


def _load():
    spec = importlib.util.spec_from_file_location("query_tier_comparison_mig", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _calls(direction, blocking=0):
    mod = _load()
    with patch.object(mod, "op") as mock_op:
        mock_op.get_bind.return_value.execute.return_value.scalar.return_value = blocking
        getattr(mod, direction)()
    return mod, mock_op


def test_chains_off_the_revenue_inputs_migration():
    mod = _load()
    assert (mod.revision, mod.down_revision) == ("f7c2a9e4b1d6", "e5b1d7f3a8c2")


def test_the_new_constraint_admits_exactly_the_shared_tiers():
    mod = _load()
    for tier in QUERY_TIERS:
        assert f"'{tier}'" in mod.NEW, tier
    assert mod.NEW.count("'") == 2 * len(QUERY_TIERS), "an extra value is admitted"
    assert "tier IS NULL" in mod.NEW            # an untiered question stays legal


def test_no_value_the_old_constraint_admitted_is_dropped():
    mod = _load()
    for tier in ('brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control'):
        assert f"'{tier}'" in mod.OLD and f"'{tier}'" in mod.NEW


def test_upgrade_replaces_the_constraint_and_writes_no_row():
    mod, mock_op = _calls("upgrade")
    assert mock_op.drop_constraint.call_args.args == ("ck_soa_queries_tier", "soa_queries")
    assert mock_op.drop_constraint.call_args.kwargs["type_"] == "check"
    assert mock_op.create_check_constraint.call_args.args == ("ck_soa_queries_tier", "soa_queries", mod.NEW)
    mock_op.execute.assert_not_called()
    mock_op.add_column.assert_not_called()


def test_downgrade_restores_the_four_and_refuses_while_a_question_is_comparison():
    mod, mock_op = _calls("downgrade")
    assert mock_op.create_check_constraint.call_args.args[2] == mod.OLD
    with pytest.raises(RuntimeError, match="1 question"):
        _calls("downgrade", blocking=1)


def test_the_model_s_constraint_admits_comparison():
    from soa_shared.models.soa_models import SoaQuery
    check = next(c for c in SoaQuery.__table__.constraints if getattr(c, 'name', None) == 'ck_soa_queries_tier')
    assert "'comparison'" in str(check.sqltext)
