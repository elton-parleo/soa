"""
Tests for app/services/lite_crosswalk.py — pure fixture tests, no DB.
One test per rule, plus a couple of no-false-positive checks.
"""
from app.services.lite_crosswalk import RunSignal, link_dimensions


def _gap(score, max_=10.0):
    """A scan dimension dict with the given score/max — used to control
    whether a rule's 'gap below half max' condition is met."""
    return {"score": score, "max": max_}


# ─── absent at research/comparison -> F1, F2 ───────────────────────────────

def test_absent_in_half_or_more_research_comparison_queries_links_f1_f2():
    signals = [
        RunSignal(stage="Research", primary_mentioned=False),
        RunSignal(stage="Research", primary_mentioned=False),
        RunSignal(stage="Comparison", primary_mentioned=True),
        RunSignal(stage="Comparison", primary_mentioned=True),
    ]
    linked = link_dimensions(signals, {})
    assert linked["F1"] == "absent at research"
    assert linked["F2"] == "absent at research"


def test_absent_in_under_half_research_comparison_queries_does_not_link():
    signals = [
        RunSignal(stage="Research", primary_mentioned=True),
        RunSignal(stage="Research", primary_mentioned=True),
        RunSignal(stage="Comparison", primary_mentioned=False),
    ]
    linked = link_dimensions(signals, {})
    assert "F1" not in linked
    assert "F2" not in linked


def test_awareness_and_ready_to_buy_stages_excluded_from_absence_check():
    signals = [
        RunSignal(stage="Awareness", primary_mentioned=False),
        RunSignal(stage="Ready to Buy", primary_mentioned=False),
    ]
    linked = link_dimensions(signals, {})
    assert "F1" not in linked  # no Research/Comparison rows at all -> rule can't fire


# ─── mentioned but no price surfaced -> V1 ─────────────────────────────────

def test_mentioned_with_no_price_ever_surfaced_links_v1():
    signals = [
        RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=False),
        RunSignal(stage="Research", primary_mentioned=True, primary_price_quoted=False),
    ]
    linked = link_dimensions(signals, {})
    assert linked["V1"] == "mentioned but no price surfaced"


def test_mentioned_with_price_surfaced_at_least_once_does_not_link_v1():
    signals = [
        RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=False),
        RunSignal(stage="Research", primary_mentioned=True, primary_price_quoted=True),
    ]
    linked = link_dimensions(signals, {})
    assert "V1" not in linked


def test_never_mentioned_does_not_link_v1():
    signals = [RunSignal(stage="Awareness", primary_mentioned=False)]
    linked = link_dimensions(signals, {})
    assert "V1" not in linked


# ─── list price quoted + scan V3 gap -> V3 ─────────────────────────────────

def test_list_price_quoted_with_v3_gap_links_v3():
    signals = [RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=True)]
    linked = link_dimensions(signals, {"V3": _gap(3.0, 14)})  # 3/14 < 50%
    assert linked["V3"] == "list price quoted"


def test_list_price_quoted_without_v3_gap_does_not_link_v3():
    signals = [RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=True)]
    linked = link_dimensions(signals, {"V3": _gap(12.0, 14)})  # 12/14 >= 50%
    assert "V3" not in linked


def test_no_price_quoted_does_not_link_v3_even_with_gap():
    signals = [RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=False)]
    linked = link_dimensions(signals, {"V3": _gap(1.0, 14)})
    assert "V3" not in linked


# ─── loyalty never mentioned + scan V2 gap -> V2 ───────────────────────────

def test_loyalty_never_mentioned_with_v2_gap_links_v2():
    signals = [RunSignal(stage="Awareness", primary_mentioned=True)]
    linked = link_dimensions(signals, {"V2": _gap(2.0, 14)})
    assert linked["V2"] == "loyalty program never mentioned"


def test_loyalty_mentioned_via_deal_types_does_not_link_v2():
    signals = [
        RunSignal(
            stage="Awareness", primary_mentioned=True, primary_deal_cited=True,
            primary_deal_types=("loyalty_points",),
        ),
    ]
    linked = link_dimensions(signals, {"V2": _gap(2.0, 14)})
    assert "V2" not in linked


def test_loyalty_mentioned_via_member_price_claimed_does_not_link_v2():
    signals = [RunSignal(stage="Awareness", primary_mentioned=True, primary_member_price_claimed=True)]
    linked = link_dimensions(signals, {"V2": _gap(2.0, 14)})
    assert "V2" not in linked


def test_v2_no_gap_does_not_link_even_if_never_mentioned():
    signals = [RunSignal(stage="Awareness", primary_mentioned=True)]
    linked = link_dimensions(signals, {"V2": _gap(13.0, 14)})
    assert "V2" not in linked


# ─── competitor cited with deal, primary never -> V4, V5 ───────────────────

def test_competitor_deal_with_primary_never_cited_links_v4_v5():
    signals = [
        RunSignal(stage="Comparison", competitor_mentioned=True, competitor_deal_cited=True, primary_deal_cited=False),
        RunSignal(stage="Comparison", primary_mentioned=True, primary_deal_cited=False),
    ]
    linked = link_dimensions(signals, {})
    assert linked["V4"] == "competitor cited with deal, primary never is"
    assert linked["V5"] == "competitor cited with deal, primary never is"


def test_primary_also_cited_with_deal_does_not_link_v4_v5():
    signals = [
        RunSignal(stage="Comparison", competitor_mentioned=True, competitor_deal_cited=True),
        RunSignal(stage="Comparison", primary_mentioned=True, primary_deal_cited=True),
    ]
    linked = link_dimensions(signals, {})
    assert "V4" not in linked
    assert "V5" not in linked


def test_no_competitor_deal_signal_does_not_link_v4_v5():
    signals = [RunSignal(stage="Comparison", primary_mentioned=True, primary_deal_cited=False)]
    linked = link_dimensions(signals, {})
    assert "V4" not in linked
    assert "V5" not in linked


# ─── combined / determinism ─────────────────────────────────────────────

def test_empty_run_signals_links_nothing():
    assert link_dimensions([], {"V2": _gap(1.0, 14), "V3": _gap(1.0, 14)}) == {}


def test_multiple_rules_fire_independently():
    signals = [
        RunSignal(stage="Research", primary_mentioned=False),
        RunSignal(stage="Research", primary_mentioned=False),
        RunSignal(
            stage="Comparison", competitor_mentioned=True, competitor_deal_cited=True,
            primary_mentioned=False, primary_deal_cited=False,
        ),
    ]
    linked = link_dimensions(signals, {})
    assert set(linked.keys()) == {"F1", "F2", "V4", "V5"}
