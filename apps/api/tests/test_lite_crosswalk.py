"""
Tests for app/services/lite_crosswalk.py — pure fixture tests, no DB.
One test per rule, plus a couple of no-false-positive checks.
"""
from app.services.lite_crosswalk import RunSignal, link_dimensions, link_incentive_citation


def _gap(score, max_=10.0, coverage=None):
    """A scan dimension dict with the given score/max — used to control
    whether a rule's 'gap below half max' condition is met. Stage 10:
    coverage='na' must short-circuit to "no gap" regardless of score/max."""
    d = {"score": score, "max": max_}
    if coverage is not None:
        d["coverage"] = coverage
    return d


# ─── absent at research/comparison -> F1, F2 ───────────────────────────────

def test_absent_in_half_or_more_research_comparison_queries_links_f1_f2():
    signals = [
        RunSignal(stage="Research", primary_mentioned=False),
        RunSignal(stage="Research", primary_mentioned=False),
        RunSignal(stage="Comparison", primary_mentioned=True),
        RunSignal(stage="Comparison", primary_mentioned=True),
    ]
    linked = link_dimensions(signals, {})
    assert linked["F1"] == "absent from most answers"
    assert linked["F2"] == "absent from most answers"


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
        RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=False, pass2_coded=True),
        RunSignal(stage="Research", primary_mentioned=True, primary_price_quoted=False, pass2_coded=True),
    ]
    linked = link_dimensions(signals, {})
    assert linked["V1"] == "mentioned but no price surfaced"


# Part 1 (P4 adjacent fix): the same "no price surfaced" claim is
# actively misleading when pass 2 never coded any of the primary
# entity's mentions at all — primary_price_quoted is unpopulated, not
# genuinely absent, so the rule must not fire.
def test_mentioned_with_no_price_but_never_pass2_coded_does_not_link_v1():
    signals = [
        RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=False, pass2_coded=False),
        RunSignal(stage="Research", primary_mentioned=True, primary_price_quoted=False, pass2_coded=False),
    ]
    linked = link_dimensions(signals, {})
    assert "V1" not in linked


def test_mentioned_with_no_price_mixed_sentinel_coverage_still_links_v1():
    """Even one sentineled mention with no price is enough real signal
    to link V1 — the gate only excludes runs pass 2 never touched at
    all, not the whole rule whenever coverage is partial."""
    signals = [
        RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=False, pass2_coded=True),
        RunSignal(stage="Research", primary_mentioned=True, primary_price_quoted=False, pass2_coded=False),
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


def test_v3_marked_na_does_not_link_even_at_a_zero_score():
    """Stage 10 (A3): a brand-only site's V3 is coverage='na' with
    score=0/14 — that's "not applicable", not a 100%-gap, so it must
    never fire the crosswalk chip."""
    signals = [RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=True)]
    linked = link_dimensions(signals, {"V3": _gap(0.0, 14, coverage="na")})
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


# ─── A3: emitted display strings must never name a funnel stage ──────────
# (the RULES still compute over stage-tagged run_signals server-side —
# only the copy shown in the public report is de-staged.)

_STAGE_NAMES = ("awareness", "research", "comparison", "ready to buy")


def test_no_linked_reason_string_names_a_funnel_stage():
    signals = [
        RunSignal(stage="Awareness", primary_mentioned=False),
        RunSignal(stage="Research", primary_mentioned=False),
        RunSignal(stage="Comparison", primary_mentioned=True, primary_price_quoted=False),
        RunSignal(
            stage="Comparison", competitor_mentioned=True, competitor_deal_cited=True,
            primary_mentioned=True, primary_deal_cited=False, primary_price_quoted=True,
        ),
    ]
    scan_dimensions = {"V2": _gap(1.0, 14), "V3": _gap(1.0, 14)}
    linked = link_dimensions(signals, scan_dimensions)

    assert linked  # sanity: the fixture actually exercises multiple rules
    for code, reason in linked.items():
        lowered = reason.lower()
        for stage_name in _STAGE_NAMES:
            assert stage_name not in lowered, f"{code}'s reason '{reason}' names stage '{stage_name}'"


# ─── Stage 8 (A4): link_incentive_citation ────────────────────────────

def _ic(entity, is_primary, mentions, rate_pct):
    return {"entity": entity, "is_primary": is_primary, "mentions": mentions, "rate_pct": rate_pct}


def test_zero_rate_with_v2_low_links_value_never_cited():
    incentive_citation = [
        _ic("Acme Co", True, 6, 0),
        _ic("Rival Co", False, 4, 30),
    ]
    scan_dimensions = {"V2": _gap(4.0, 14), "V3": _gap(10.0, 14)}  # V2 gap, V3 no gap
    linked = link_incentive_citation(incentive_citation, scan_dimensions)
    assert linked == {"V2": "value never cited"}


def test_v2_and_v3_both_na_means_no_chip_even_at_zero_rate():
    """Stage 10 (A3): both candidate dimensions are 'na' (e.g. a
    brand-only site) — there's nothing to link to, so the rule must not
    fall back to picking one anyway."""
    incentive_citation = [
        _ic("Acme Co", True, 6, 0),
        _ic("Rival Co", False, 4, 30),
    ]
    scan_dimensions = {"V2": _gap(0.0, 14, coverage="na"), "V3": _gap(0.0, 14, coverage="na")}
    assert link_incentive_citation(incentive_citation, scan_dimensions) == {}


def test_zero_rate_with_too_few_mentions_does_not_fire():
    incentive_citation = [_ic("Acme Co", True, 1, 0)]
    scan_dimensions = {"V2": _gap(4.0, 14)}
    assert link_incentive_citation(incentive_citation, scan_dimensions) == {}


def test_trailing_every_rival_by_25_links_value_rarely_cited():
    incentive_citation = [
        _ic("Acme Co", True, 8, 10),
        _ic("Rival A", False, 5, 40),
        _ic("Rival B", False, 3, 35),
    ]
    scan_dimensions = {"V3": _gap(5.0, 14)}
    linked = link_incentive_citation(incentive_citation, scan_dimensions)
    assert linked == {"V3": "value rarely cited"}


def test_rival_below_25_gap_prevents_trailing_condition():
    incentive_citation = [
        _ic("Acme Co", True, 8, 10),
        _ic("Rival A", False, 5, 30),  # only 20pts ahead — not enough
    ]
    scan_dimensions = {"V3": _gap(5.0, 14)}
    assert link_incentive_citation(incentive_citation, scan_dimensions) == {}


def test_zero_mention_rival_excluded_from_trailing_check():
    incentive_citation = [
        _ic("Acme Co", True, 8, 10),
        _ic("Rival A", False, 5, 40),   # trails by 30 — qualifies
        _ic("Rival B", False, 0, None),  # zero mentions — must not block the rule
    ]
    scan_dimensions = {"V2": _gap(4.0, 14)}
    linked = link_incentive_citation(incentive_citation, scan_dimensions)
    assert linked == {"V2": "value rarely cited"}


def test_does_not_fire_when_scan_incomplete_or_dimensions_absent():
    # A blocked/skipped scan yields an empty scan_dimensions dict —
    # _dimension_gap_below_half returns False for every code, so the
    # rule can't fire regardless of the citation data.
    incentive_citation = [_ic("Acme Co", True, 6, 0), _ic("Rival Co", False, 4, 40)]
    assert link_incentive_citation(incentive_citation, {}) == {}


def test_does_not_fire_when_v2_and_v3_both_score_at_or_above_half_max():
    incentive_citation = [_ic("Acme Co", True, 6, 0), _ic("Rival Co", False, 4, 40)]
    scan_dimensions = {"V2": _gap(7.0, 14), "V3": _gap(7.0, 14)}  # exactly half — not below
    assert link_incentive_citation(incentive_citation, scan_dimensions) == {}


def test_no_primary_rate_does_not_fire():
    incentive_citation = [_ic("Acme Co", True, 0, None), _ic("Rival Co", False, 4, 40)]
    scan_dimensions = {"V2": _gap(4.0, 14)}
    assert link_incentive_citation(incentive_citation, scan_dimensions) == {}


def test_picks_the_lower_scoring_of_v2_and_v3_when_both_have_gaps():
    incentive_citation = [_ic("Acme Co", True, 6, 0)]
    scan_dimensions = {"V2": _gap(6.0, 14), "V3": _gap(2.0, 14)}  # V3 scores lower
    linked = link_incentive_citation(incentive_citation, scan_dimensions)
    assert linked == {"V3": "value never cited"}


def test_incentive_citation_reasons_never_name_a_funnel_stage():
    incentive_citation = [_ic("Acme Co", True, 6, 0), _ic("Rival Co", False, 4, 40)]
    scan_dimensions = {"V2": _gap(4.0, 14)}
    linked = link_incentive_citation(incentive_citation, scan_dimensions)
    assert linked
    for code, reason in linked.items():
        lowered = reason.lower()
        for stage_name in _STAGE_NAMES:
            assert stage_name not in lowered, f"{code}'s reason '{reason}' names stage '{stage_name}'"
