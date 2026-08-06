"""
Tests for exposure_reasons.py — Part 4's table-driven library of
run-tailored "why you're leaking value" reasons, replacing the report's
old static three-cause exposure breakdown.
"""
import pytest

from app.services.exposure_reasons import REASONS, select_exposure_reasons


def _dim(earned, max_, na=False, blocked=False, **extra):
    return {"earned": earned, "max": max_, "na": na, "blocked": blocked, **extra}


def _full_credit_ctx():
    """Every sub-lens at full credit — nothing should trigger."""
    return {
        "price_truth_seen": _dim(5, 5),
        "price_truth_said": _dim(7, 7, cited=7, total=7),
        "member_value_applicable": True,
        "member_value_seen": _dim(9, 9),
        "member_value_said": _dim(6, 6, cited=6, total=6),
        "deal_citability_seen": _dim(4, 4),
        "deal_citability_said": _dim(2, 2, cited=2, total=2),
        "value_protocols": _dim(7, 7),
        "catalog_context": _dim(8, 8),
        "agent_access": _dim(6, 6),
        "visibility": {"earned": 25, "max": 25, "na": False, "som_pct": 100.0, "total_mentions": 24},
    }


# ─── honest baseline: nothing triggers when everything is full credit ───

def test_nothing_triggers_on_a_fully_earned_run():
    assert select_exposure_reasons(_full_credit_ctx()) == []


# ─── table-driven trigger fixtures, one per registry entry (4e) ─────────

@pytest.mark.parametrize("reason_id,ctx_overrides,expected_fragment", [
    ("pt_said", {"price_truth_said": _dim(0, 7, cited=0, total=7)}, "quoted in 0 of 7"),
    ("pt_seen", {"price_truth_seen": _dim(2, 5)}, "earn 2 of 5"),
    ("mv_seen", {"member_value_seen": _dim(3, 9)}, "earns 3 of 9"),
    ("mv_said", {"member_value_said": _dim(0, 6, cited=0, total=4)}, "credited in 0 of 4"),
    ("dc_seen", {"deal_citability_seen": _dim(0, 4)}, "earn 0 of 4"),
    ("dc_said", {"deal_citability_said": _dim(0, 2, cited=0, total=3)}, "cited in 0 of 3"),
    ("value_protocols", {"value_protocols": _dim(0, 7)}, "earns 0 of 7"),
    ("catalog_context", {"catalog_context": _dim(2, 8)}, "earns 2 of 8"),
    ("agent_access", {"agent_access": _dim(4, 6)}, "earns 4 of 6"),
    ("visibility", {"visibility": {"earned": 10, "max": 25, "na": False, "som_pct": 20.0, "total_mentions": 24}}, "20% share"),
])
def test_each_reason_triggers_from_its_own_gap_and_interpolates_real_numbers(reason_id, ctx_overrides, expected_fragment):
    ctx = {**_full_credit_ctx(), **ctx_overrides}
    selected = select_exposure_reasons(ctx)
    assert [r["id"] for r in selected] == [reason_id]
    assert expected_fragment in selected[0]["text"]


def test_registry_has_at_least_ten_entries_covering_every_pillar():
    assert len(REASONS) >= 10
    assert len({r.id for r in REASONS}) == len(REASONS)  # unique ids


# ─── honest-state gating (4b): unmeasured dimensions never trigger ──────

def test_na_dimension_never_triggers_a_reason():
    ctx = {**_full_credit_ctx(), "price_truth_seen": _dim(0, 5, na=True)}
    assert select_exposure_reasons(ctx) == []


def test_blocked_dimension_never_triggers_a_reason():
    ctx = {**_full_credit_ctx(), "catalog_context": _dim(0, 8, blocked=True)}
    assert select_exposure_reasons(ctx) == []


def test_member_value_reasons_never_trigger_when_not_applicable():
    ctx = {
        **_full_credit_ctx(),
        "member_value_applicable": False,
        "member_value_seen": _dim(0, 9),
        "member_value_said": _dim(0, 6, cited=0, total=4),
    }
    assert select_exposure_reasons(ctx) == []


def test_visibility_reason_never_triggers_with_zero_tracked_mentions():
    ctx = {**_full_credit_ctx(), "visibility": {"earned": 0, "max": 25, "na": False, "som_pct": 0.0, "total_mentions": 0}}
    assert select_exposure_reasons(ctx) == []


def test_starved_run_with_nothing_measured_selects_no_reasons():
    ctx = {
        "price_truth_seen": _dim(0, 5, na=True), "price_truth_said": _dim(0, 7, na=True),
        "member_value_applicable": False, "member_value_seen": _dim(0, 9, na=True), "member_value_said": _dim(0, 6, na=True),
        "deal_citability_seen": _dim(0, 4, na=True), "deal_citability_said": _dim(0, 2, na=True),
        "value_protocols": _dim(0, 7, na=True),
        "catalog_context": _dim(0, 8, blocked=True),
        "agent_access": _dim(0, 6, na=True),
        "visibility": {"earned": 0, "max": 25, "na": True, "som_pct": 0.0, "total_mentions": 0},
    }
    assert select_exposure_reasons(ctx) == []


# ─── selection: top 3 by severity, never padded ──────────────────────────

def _many_gaps_ctx():
    ctx = _full_credit_ctx()
    ctx["price_truth_seen"] = _dim(0, 5)       # missed 5
    ctx["catalog_context"] = _dim(0, 8)         # missed 8
    ctx["agent_access"] = _dim(3, 6)            # missed 3
    ctx["value_protocols"] = _dim(0, 7)         # missed 7
    return ctx


def test_selects_only_the_top_3_by_severity_never_more():
    selected = select_exposure_reasons(_many_gaps_ctx())
    assert len(selected) == 3
    assert [r["id"] for r in selected] == ["catalog_context", "value_protocols", "pt_seen"]
    assert [r["severity_rank"] for r in selected] == [1, 2, 3]


def test_fewer_than_three_triggers_returns_fewer_never_padded():
    ctx = {**_full_credit_ctx(), "agent_access": _dim(4, 6)}  # exactly one gap
    selected = select_exposure_reasons(ctx)
    assert len(selected) == 1


# ─── high-True-Value-gap vs high-visibility-gap runs select different flavors (4e) ───

def test_high_true_value_gap_run_selects_true_value_flavored_reasons():
    ctx = _full_credit_ctx()
    ctx["price_truth_seen"] = _dim(0, 5)
    ctx["deal_citability_said"] = _dim(0, 2, cited=0, total=3)
    ctx["value_protocols"] = _dim(0, 7)
    selected = select_exposure_reasons(ctx)
    ids = {r["id"] for r in selected}
    assert ids == {"value_protocols", "pt_seen", "dc_said"}
    assert "visibility" not in ids
    assert "catalog_context" not in ids
    assert "agent_access" not in ids


def test_high_visibility_gap_run_selects_visibility_flavored_reasons():
    ctx = _full_credit_ctx()
    ctx["visibility"] = {"earned": 2, "max": 25, "na": False, "som_pct": 8.0, "total_mentions": 24}
    selected = select_exposure_reasons(ctx)
    assert [r["id"] for r in selected] == ["visibility"]
    assert "8% share" in selected[0]["text"]


# ─── impact_weight: proportional to severity, sums to exactly 1.0 (4c) ──

def test_impact_weights_sum_to_exactly_one_across_selected_reasons():
    selected = select_exposure_reasons(_many_gaps_ctx())
    assert sum(r["impact_weight"] for r in selected) == pytest.approx(1.0)


def test_impact_weight_is_proportional_to_severity():
    # catalog_context (missed 8) should carry a bigger share than
    # price_truth_seen (missed 5) among the same selected group.
    selected = select_exposure_reasons(_many_gaps_ctx())
    by_id = {r["id"]: r["impact_weight"] for r in selected}
    assert by_id["catalog_context"] > by_id["pt_seen"]


def test_single_selected_reason_gets_the_full_weight():
    ctx = {**_full_credit_ctx(), "agent_access": _dim(4, 6)}
    selected = select_exposure_reasons(ctx)
    assert selected[0]["impact_weight"] == 1.0


# ─── deterministic tiebreak ───────────────────────────────────────────────

def test_equal_severity_ties_break_deterministically_by_id():
    ctx = _full_credit_ctx()
    ctx["price_truth_seen"] = _dim(0, 5)   # missed 5
    ctx["deal_citability_seen"] = _dim(0, 5)  # missed 5, tie
    selected = select_exposure_reasons(ctx)
    ids = [r["id"] for r in selected]
    assert ids == sorted(ids)  # alphabetical tiebreak, same both runs
