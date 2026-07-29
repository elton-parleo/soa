"""
Stage 16 (Part 2/Part 3 T2): tests for lite_pillars.py's mention/
metrics-derived scoring — visibility (score_share_of_mentions,
score_recommendation_strength) and True Value's 'said' outcome sub-
lenses (score_price_truth_said, score_member_value_said,
score_deal_citability_said).
"""
import pytest

from app.services.lite_crosswalk import RunSignal
from app.services.lite_pillars import (
    build_pillars_payload,
    member_value_applicable,
    score_deal_citability_said,
    score_member_value_said,
    score_price_truth_said,
    score_recommendation_strength,
    score_share_of_mentions,
)


# ─── score_share_of_mentions (V1) ────────────────────────────────────────

def test_zero_mentions_scores_zero_not_na():
    result = score_share_of_mentions(som_pct=0.0, total_mentions=0)
    assert result["earned"] == 0.0
    assert result["max"] == 25
    assert result["code"] == "share_of_mentions"


def test_none_som_with_zero_mentions_scores_zero():
    result = score_share_of_mentions(som_pct=None, total_mentions=0)
    assert result["earned"] == 0.0


@pytest.mark.parametrize("som_pct,expected_earned", [
    (30.77, 15),
    (36.36, 18),
    (50.0, 25),      # exactly at the cap — full marks
    (50.01, 25),      # just above the cap — still full marks (capped)
    (60.0, 25),
    (100.0, 25),
])
def test_share_of_mentions_cap_at_50(som_pct, expected_earned):
    result = score_share_of_mentions(som_pct=som_pct, total_mentions=6)
    assert result["earned"] == expected_earned
    assert result["max"] == 25


def test_share_of_mentions_below_cap_is_linear():
    # 25% share -> 25/50*25 = 12.5 -> round to 12 (banker's rounding on .5 -> even)
    result = score_share_of_mentions(som_pct=25.0, total_mentions=3)
    assert result["earned"] == round(25.0 / 50 * 25)


def test_share_of_mentions_evidence_present():
    result = score_share_of_mentions(som_pct=42.0, total_mentions=5)
    assert result["evidence"]
    assert "42.0%" in result["evidence"][0]


# ─── score_recommendation_strength (V2) ──────────────────────────────────

def test_zero_mentions_recommendation_strength_scores_zero():
    result = score_recommendation_strength(rsi_score=None, total_mentions=0)
    assert result["earned"] == 0.0
    assert result["max"] == 15


@pytest.mark.parametrize("rsi_score,expected_earned", [
    (-1.0, 0),    # all Negative -> floor
    (0.17, 4),
    (1.44, 9),
    (2.12, 12),
    (3.0, 15),    # all Primary -> ceiling
])
def test_recommendation_strength_linear_mapping(rsi_score, expected_earned):
    result = score_recommendation_strength(rsi_score=rsi_score, total_mentions=4)
    assert result["earned"] == expected_earned
    assert result["max"] == 15


def test_recommendation_strength_clamps_below_theoretical_min():
    # rsi_score is mathematically bounded to [-1, 3] by construction, but
    # the mapping must never raise/go negative even if that ever changes.
    result = score_recommendation_strength(rsi_score=-2.0, total_mentions=4)
    assert result["earned"] == 0


def test_recommendation_strength_clamps_above_theoretical_max():
    result = score_recommendation_strength(rsi_score=5.0, total_mentions=4)
    assert result["earned"] == 15


def test_recommendation_strength_evidence_present():
    result = score_recommendation_strength(rsi_score=1.44, total_mentions=4)
    assert result["evidence"]


# Stage 21 (bug fix 2): the raw rsi_score and its internal -1..+3 scale
# must never reach a visitor — evidence is a banded plain-language line
# keyed off the earned/max ratio the visitor already sees numerically.
@pytest.mark.parametrize("rsi_score,expected_line", [
    (3.0, "Consistently the top pick."),            # 15/15 = 100%
    (1.44, "Often listed, rarely singled out as the pick."),  # 9/15 = 60%
    (-0.6, "Mentioned, but rarely recommended outright."),    # earned 2/15 ~ 13%
    (-1.0, "Named, but never actually recommended."),         # 0/15 = 0%
])
def test_recommendation_strength_evidence_is_banded_plain_language(rsi_score, expected_line):
    result = score_recommendation_strength(rsi_score=rsi_score, total_mentions=4)
    assert result["evidence"] == [expected_line]


def test_recommendation_strength_evidence_never_leaks_the_raw_metric_or_its_scale():
    for rsi_score in (-1.0, -0.6, 0.17, 1.44, 2.12, 3.0):
        result = score_recommendation_strength(rsi_score=rsi_score, total_mentions=4)
        evidence_text = " ".join(result["evidence"]).lower()
        assert "rsi" not in evidence_text
        assert "scale" not in evidence_text


# ─── True Value 'said' sub-lenses (Stage 16, Part 3 T2) ──────────────────

def _mentioned(stage="Awareness", price_quoted=False, member_price_claimed=False,
               deal_types=(), deal_cited=False, member_value_cited=False):
    return RunSignal(
        stage=stage, primary_mentioned=True, primary_deal_cited=deal_cited,
        primary_deal_types=tuple(deal_types), primary_price_quoted=price_quoted,
        primary_member_price_claimed=member_price_claimed,
        primary_member_value_cited=member_value_cited,
    )


def _not_mentioned(stage="Awareness"):
    return RunSignal(stage=stage, primary_mentioned=False)


# — price_truth.said (rate band, opportunity set = all mentions) —

def test_price_truth_said_na_below_two_mentions():
    result = score_price_truth_said([_mentioned(price_quoted=True)])
    assert result["na"] is True
    assert result["earned"] == 0.0
    assert result["max"] == 8


def test_price_truth_said_excludes_unmentioned_runs_from_opportunity_set():
    signals = [_mentioned(price_quoted=True), _mentioned(price_quoted=True), _not_mentioned()]
    result = score_price_truth_said(signals)
    assert "2/2" in result["evidence"][0]


@pytest.mark.parametrize("cited,total,expected_earned", [
    (0, 4, 0),    # 0% -> 0%
    (1, 4, 3),    # 25% -> 40% of 8 -> 3.2 -> 3
    (2, 4, 6),    # 50% -> 70% of 8 -> 5.6 -> 6
    (3, 4, 8),    # 75% -> 100% of 8 -> 8
])
def test_price_truth_said_rate_bands(cited, total, expected_earned):
    signals = [_mentioned(price_quoted=True) for _ in range(cited)]
    signals += [_mentioned(price_quoted=False) for _ in range(total - cited)]
    result = score_price_truth_said(signals)
    assert result["na"] is False
    assert result["earned"] == expected_earned
    assert result["max"] == 8


# — member_value.said (rate band, opportunity set = purchase-intent only) —

def test_member_value_said_na_below_two_purchase_intent_mentions():
    signals = [
        _mentioned(stage="Comparison", member_price_claimed=True),
        _mentioned(stage="Awareness", member_price_claimed=True),
        _mentioned(stage="Awareness", member_price_claimed=True),
    ]
    result = score_member_value_said(signals)
    assert result["na"] is True
    assert result["max"] == 7


def test_member_value_said_excludes_non_purchase_intent_stages():
    signals = [
        _mentioned(stage="Comparison", member_price_claimed=True),
        _mentioned(stage="Ready to Buy", member_price_claimed=False),
        _mentioned(stage="Awareness", member_price_claimed=True),
        _mentioned(stage="Research", member_price_claimed=True),
    ]
    result = score_member_value_said(signals)
    assert result["na"] is False
    assert "1/2" in result["evidence"][0]


def test_member_value_said_citation_via_member_price_claimed_or_deal_types():
    signals = [
        _mentioned(stage="Comparison", member_price_claimed=True),
        _mentioned(stage="Comparison", deal_types=["loyalty_points"]),
        _mentioned(stage="Ready to Buy", deal_types=["discount_pct"]),  # not a member-value type
        _mentioned(stage="Ready to Buy"),
    ]
    result = score_member_value_said(signals)
    assert "2/4" in result["evidence"][0]


def test_member_value_said_citation_via_member_value_cited_alone():
    """Stage 16 (Part 5): member_value_cited counts as a citation even
    when neither member_price_claimed nor deal_types fired — the
    broader signal the coding extension exists to catch."""
    signals = [
        _mentioned(stage="Comparison", member_value_cited=True),  # vague program mention only
        _mentioned(stage="Comparison"),
        _mentioned(stage="Ready to Buy"),
        _mentioned(stage="Ready to Buy"),
    ]
    result = score_member_value_said(signals)
    assert "1/4" in result["evidence"][0]


def test_member_value_said_does_not_double_count_when_all_three_signals_fire():
    signals = [
        _mentioned(stage="Comparison", member_price_claimed=True, member_value_cited=True,
                   deal_types=["loyalty_points"]),
        _mentioned(stage="Ready to Buy"),
    ]
    result = score_member_value_said(signals)
    assert "1/2" in result["evidence"][0]


@pytest.mark.parametrize("cited,total,expected_earned", [
    (0, 4, 0),
    (1, 4, 3),    # 25% -> 40% of 7 -> 2.8 -> 3
    (2, 4, 5),    # 50% -> 70% of 7 -> 4.9 -> 5
    (3, 4, 7),    # 75% -> 100% of 7 -> 7
])
def test_member_value_said_rate_bands(cited, total, expected_earned):
    signals = [_mentioned(stage="Comparison", member_price_claimed=True) for _ in range(cited)]
    signals += [_mentioned(stage="Comparison", member_price_claimed=False) for _ in range(total - cited)]
    result = score_member_value_said(signals)
    assert result["na"] is False
    assert result["earned"] == expected_earned
    assert result["max"] == 7


# — deal_citability.said (count band, opportunity set = purchase-intent only) —

def test_deal_citability_said_na_below_two_purchase_intent_mentions():
    signals = [_mentioned(stage="Comparison", deal_cited=True), _mentioned(stage="Awareness", deal_cited=True)]
    result = score_deal_citability_said(signals)
    assert result["na"] is True
    assert result["max"] == 3


@pytest.mark.parametrize("cited_count,expected_earned", [
    (0, 0),   # 0 -> 0%
    (1, 2),   # 1 -> 60% of 3 -> 1.8 -> 2
    (2, 3),   # 2+ -> 100% of 3 -> 3
])
def test_deal_citability_said_count_bands(cited_count, expected_earned):
    signals = [_mentioned(stage="Comparison", deal_cited=True) for _ in range(cited_count)]
    signals += [_mentioned(stage="Comparison", deal_cited=False) for _ in range(2)]
    result = score_deal_citability_said(signals)
    assert result["na"] is False
    assert result["earned"] == expected_earned
    assert result["max"] == 3


# ─── member_value applicability (Stage 16, Part 4, P3) ───────────────────

def test_member_value_applicable_when_probe_says_yes_even_with_zero_seen_score():
    assert member_value_applicable(probe_result="yes", seen_score=0.0) is True


def test_member_value_applicable_when_crawl_earned_credit_even_if_probe_unknown():
    assert member_value_applicable(probe_result="unknown", seen_score=4.0) is True


def test_member_value_applicable_when_both_signals_agree():
    assert member_value_applicable(probe_result="yes", seen_score=6.0) is True


def test_member_value_not_applicable_when_probe_no_and_crawl_found_nothing():
    assert member_value_applicable(probe_result="no", seen_score=0.0) is False


def test_member_value_not_applicable_when_probe_unknown_and_crawl_found_nothing():
    """An 'unknown' probe result is an abstention, not a finding — it
    must not count as evidence on its own."""
    assert member_value_applicable(probe_result="unknown", seen_score=0.0) is False


def test_member_value_applicable_handles_none_seen_score_defensively():
    assert member_value_applicable(probe_result="no", seen_score=None) is False
    assert member_value_applicable(probe_result="yes", seen_score=None) is True


# ─── build_pillars_payload (Stage 16, Part 7) ─────────────────────────────

_FULL_CRAWL_DIMS = {
    "agent_access": {"score": 6, "max": 6, "coverage": "full", "evidence": ["e"], "fix": "fix agent_access"},
    "catalog_context": {"score": 8, "max": 8, "coverage": "full", "evidence": ["e"], "fix": "fix catalog_context"},
    "protocol_feed": {"score": 6, "max": 6, "coverage": "full", "evidence": ["e"], "fix": "fix protocol_feed"},
    "price_truth_seen": {"score": 6, "max": 6, "coverage": "full", "evidence": ["e"], "fix": "fix price_truth"},
    "member_value_seen": {"score": 12, "max": 12, "coverage": "full", "evidence": ["e"], "fix": "fix member_value"},
    "deal_citability_seen": {"score": 4, "max": 4, "coverage": "full", "evidence": ["e"], "fix": "fix deal_citability"},
}


def _full_credit_signals():
    """2 mentions, both purchase-intent, citing everything — every said
    sub-lens should land at its max band."""
    return [
        RunSignal(
            stage="Comparison", primary_mentioned=True, primary_deal_cited=True,
            primary_deal_types=("member_price",), primary_price_quoted=True,
            primary_member_price_claimed=True, primary_member_value_cited=True,
        ),
        RunSignal(
            stage="Ready to Buy", primary_mentioned=True, primary_deal_cited=True,
            primary_deal_types=("member_price",), primary_price_quoted=True,
            primary_member_price_claimed=True, primary_member_value_cited=True,
        ),
    ]


def test_full_credit_scenario_scores_100_on_every_pillar_and_composite():
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    assert result["visibility"]["score"] == 100
    assert result["accessibility"]["score"] == 100
    assert result["true_value"]["score"] == 100
    assert result["composite"] == 100
    assert result["member_value_na"] is False


def test_zero_credit_scenario_scores_0_on_every_pillar_and_composite():
    empty_crawl = {
        code: {"score": 0, "max": d["max"], "coverage": "full", "evidence": []}
        for code, d in _FULL_CRAWL_DIMS.items()
    }
    result = build_pillars_payload(
        som_pct=0.0, rsi_score=None, total_mentions=0,
        crawl_dimensions=empty_crawl, run_signals=[],
        membership_probe_result="no",
    )
    assert result["visibility"]["score"] == 0
    assert result["accessibility"]["score"] == 0
    # member_value is N/A here (probe='no', seen score 0) -> true_value
    # rescales onto price_truth + deal_citability only, both 0 -> still 0.
    assert result["true_value"]["score"] == 0
    assert result["composite"] == 0
    assert result["member_value_na"] is True


def test_accessibility_excludes_na_protocol_feed_from_denominator():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["protocol_feed"] = {"score": 0, "max": 6, "coverage": "na", "evidence": []}
    result = build_pillars_payload(
        som_pct=0.0, rsi_score=None, total_mentions=0,
        crawl_dimensions=crawl, run_signals=[], membership_probe_result="unknown",
    )
    # agent_access(6) + catalog_context(8) = 14 applicable, both full marks -> 100%.
    assert result["accessibility"]["score"] == 100
    protocol_feed_row = next(d for d in result["accessibility"]["dimensions"] if d["code"] == "protocol_feed")
    assert protocol_feed_row["na"] is True


def test_member_value_na_excludes_it_entirely_from_true_value_and_composite():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["member_value_seen"] = {"score": 0, "max": 12, "coverage": "full", "evidence": []}
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="no",
    )
    assert result["member_value_na"] is True
    member_value_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is True
    assert member_value_row["earned"] == 0.0
    assert member_value_row["max"] == 0.0
    # price_truth(14) + deal_citability(7) = 21, both full -> true_value 100%.
    assert result["true_value"]["score"] == 100
    # composite: visibility(40) + accessibility(20) + true_value(21) = 81
    # earned out of applicable_max(member_value_na=True) = 81 -> 100.
    assert result["composite"] == 100


# Stage 21 (bug fix 3): the applicable path only ever showed crawl
# evidence, silently dropping the probe finding that made the dimension
# applicable in the first place when the crawl itself found nothing.

def test_member_value_applicable_with_probe_yes_and_empty_crawl_surfaces_both_signals():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["member_value_seen"] = {"score": 0, "max": 12, "coverage": "full", "evidence": ["no loyalty page found"]}
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    assert result["member_value_na"] is False
    member_value_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is False
    assert member_value_row["seen"]["evidence"][0] == "program exists (probe) · not discoverable on site"
    assert "no loyalty page found" in member_value_row["seen"]["evidence"]


def test_member_value_applicable_via_crawl_credit_does_not_add_the_probe_line():
    """Applicable via real crawl credit (score > 0) — no probe finding
    to surface, so evidence stays crawl-only."""
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="no",
    )
    member_value_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is False
    assert "program exists (probe)" not in " ".join(member_value_row["seen"]["evidence"])


def test_said_na_thin_opportunity_set_rescales_dimension_onto_seen_only():
    """Fewer than 2 mentions in price_truth's opportunity set (all
    mentions) -> price_truth_said is N/A -> the dimension rescales onto
    its seen half (6 pts) instead of the full 14."""
    one_signal = [RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=True)]
    result = build_pillars_payload(
        som_pct=0.0, rsi_score=None, total_mentions=1,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=one_signal,
        membership_probe_result="yes",
    )
    price_truth_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "price_truth")
    assert price_truth_row["max"] == 6  # seen_max only, not the full 14
    assert price_truth_row["earned"] == 6  # seen's full score, said contributes nothing
    assert price_truth_row["said"]["na"] is True


def test_build_pillars_payload_delegates_composite_to_the_registry_function(monkeypatch):
    """Part 7's 'ONE composite function' requirement: build_pillars_
    payload must never compute its own 0-100 rescale for the cross-
    pillar total — it always calls soa_shared.scan_dimensions.
    compute_composite, proven here by replacing that function and
    checking its return value flows straight through unchanged."""
    calls = []

    def fake_compute_composite(total_earned, member_value_na=False):
        calls.append((total_earned, member_value_na))
        return 42

    monkeypatch.setattr("app.services.lite_pillars.compute_composite", fake_compute_composite)
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    assert result["composite"] == 42
    assert len(calls) == 1


# ─── fix/locked ranking (Stage 19, R5) ────────────────────────────────────
#
# scan.dimensions is v1/v2-keyed and unusable for a v3 row (see
# public_lite.py::_build_scan_payload's DIMENSION_ORDER) — the v3 report's
# ranked-fix list has to come from here instead. All 6 crawl-derived
# dimensions (accessibility's 3 + True Value's 3 seen-halves) carry a
# 'fix' string in crawl_dimensions in these fixtures; visibility's two
# mention-derived dimensions never do.

def _dims_by_code(result):
    return {
        d["code"]: d
        for d in result["accessibility"]["dimensions"] + result["true_value"]["dimensions"]
    }


def test_fix_text_flows_through_for_crawl_derived_dimensions():
    # All 6 dimensions are at zero gap in this fixture, so the top-3-
    # by-gap ranking falls back to its alphabetical tiebreak — asserting
    # on agent_access/catalog_context (both land in that free top 3)
    # keeps this test independent of the ranking behavior itself, which
    # test_top_three_by_gap_stay_free_rest_are_locked covers directly.
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    dims = _dims_by_code(result)
    assert dims["agent_access"]["fix"] == "fix agent_access"
    assert dims["catalog_context"]["fix"] == "fix catalog_context"


def test_visibility_dimensions_never_carry_fix():
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    for d in result["visibility"]["dimensions"]:
        assert d.get("fix") is None
        assert d.get("locked", False) is False


def test_top_three_by_gap_stay_free_rest_are_locked():
    # Distinct, unambiguous gaps: protocol_feed(6) and price_truth(4) and
    # deal_citability(2) are the three biggest opportunities; the other
    # three are fully earned (gap 0) and should end up locked.
    crawl = {
        "agent_access": {"score": 6, "max": 6, "coverage": "full", "fix": "f-aa"},
        "catalog_context": {"score": 8, "max": 8, "coverage": "full", "fix": "f-cc"},
        "protocol_feed": {"score": 0, "max": 6, "coverage": "full", "fix": "f-pf"},
        "price_truth_seen": {"score": 2, "max": 6, "coverage": "full", "fix": "f-pt"},
        "member_value_seen": {"score": 12, "max": 12, "coverage": "full", "fix": "f-mv"},
        "deal_citability_seen": {"score": 2, "max": 4, "coverage": "full", "fix": "f-dc"},
    }
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    dims = _dims_by_code(result)

    for code in ("protocol_feed", "price_truth", "deal_citability"):
        assert dims[code]["locked"] is False, code
        assert dims[code]["fix"] is not None, code

    for code in ("agent_access", "catalog_context", "member_value"):
        assert dims[code]["locked"] is True, code
        assert dims[code]["fix"] is None, code


def test_na_dimension_is_never_locked_and_excluded_from_ranking():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["protocol_feed"] = {"score": 0, "max": 6, "coverage": "na", "fix": "f-pf"}
    result = build_pillars_payload(
        som_pct=0.0, rsi_score=None, total_mentions=0,
        crawl_dimensions=crawl, run_signals=[], membership_probe_result="unknown",
    )
    dims = _dims_by_code(result)
    assert dims["protocol_feed"]["na"] is True
    assert dims["protocol_feed"]["locked"] is False


def test_member_value_na_dimension_has_no_fix_and_is_not_locked():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["member_value_seen"] = {"score": 0, "max": 12, "coverage": "full", "fix": "f-mv"}
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="no",
    )
    dims = _dims_by_code(result)
    assert dims["member_value"]["na"] is True
    assert dims["member_value"]["fix"] is None
    assert dims["member_value"]["locked"] is False
