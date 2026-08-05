"""
Stage 16 (Part 2/Part 3 T2): tests for lite_pillars.py's mention/
metrics-derived scoring — visibility (score_share_of_mentions,
score_recommendation_strength) and True Value's 'said' outcome sub-
lenses (score_price_truth_said, score_member_value_said,
score_deal_citability_said).
"""
import json

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
               deal_types=(), deal_cited=False, member_value_cited=False, pass2_coded=True):
    # Part 1 (P4): defaults to pass2_coded=True — every existing caller
    # here already means "pass 2 ran and (didn't) find a price", never
    # "pass 2 never ran"; tests that specifically want the NOT EVALUATED
    # path pass pass2_coded=False explicitly.
    return RunSignal(
        stage=stage, primary_mentioned=True, primary_deal_cited=deal_cited,
        primary_deal_types=tuple(deal_types), primary_price_quoted=price_quoted,
        primary_member_price_claimed=member_price_claimed,
        primary_member_value_cited=member_value_cited,
        pass2_coded=pass2_coded,
    )


def _not_mentioned(stage="Awareness"):
    return RunSignal(stage=stage, primary_mentioned=False)


# — price_truth.said (rate band, opportunity set = all mentions) —

def test_price_truth_said_na_below_two_mentions():
    result = score_price_truth_said([_mentioned(price_quoted=True)])
    assert result["na"] is True
    assert result["earned"] == 0.0
    assert result["max"] == 7


def test_price_truth_said_excludes_unmentioned_runs_from_opportunity_set():
    signals = [_mentioned(price_quoted=True), _mentioned(price_quoted=True), _not_mentioned()]
    result = score_price_truth_said(signals)
    assert "2/2" in result["evidence"][0]


@pytest.mark.parametrize("cited,total,expected_earned", [
    (0, 4, 0),    # 0% -> 0%
    (1, 4, 3),    # 25% -> 40% of 7 -> 2.8 -> 3
    (2, 4, 5),    # 50% -> 70% of 7 -> 4.9 -> 5
    (3, 4, 7),    # 75% -> 100% of 7 -> 7
])
def test_price_truth_said_rate_bands(cited, total, expected_earned):
    signals = [_mentioned(price_quoted=True) for _ in range(cited)]
    signals += [_mentioned(price_quoted=False) for _ in range(total - cited)]
    result = score_price_truth_said(signals)
    assert result["na"] is False
    assert result["earned"] == expected_earned
    assert result["max"] == 7


# — Part 1 (P4): sentinel-aware NOT EVALUATED vs a real 0% —

def test_price_truth_said_not_evaluated_when_zero_sentineled_mentions():
    """Enough mention VOLUME (>= MIN_OPPORTUNITY_SET_MENTIONS), but none
    of it has ever been through pass-2 price coding — the audit has no
    price signal at all, which must never render as a 0% rate."""
    signals = [_mentioned(price_quoted=False, pass2_coded=False) for _ in range(3)]
    result = score_price_truth_said(signals)
    assert result["na"] is True
    assert result["not_evaluated"] is True
    assert result["earned"] == 0.0
    assert "predates price-observation coding" in result["evidence"][0]
    assert "0%" not in result["evidence"][0]
    assert "your_band" not in result
    assert "band_table_ref" not in result


def test_price_truth_said_not_evaluated_never_reachable_via_zero_percent_rate():
    """Grep-style guard: a genuinely 0%-cited but SENTINELED set must
    still render as a real 0% (na=False), never collapse into
    not_evaluated — the two states must stay distinguishable in both
    directions."""
    signals = [_mentioned(price_quoted=False, pass2_coded=True) for _ in range(3)]
    result = score_price_truth_said(signals)
    assert result["na"] is False
    assert "not_evaluated" not in result
    assert result["earned"] == 0
    assert "0%" in result["evidence"][0]


def test_price_truth_said_mixed_cycle_denominator_is_sentineled_mentions_only():
    """2 sentineled mentions (1 cited) + 1 never-coded mention — the
    never-coded one must be excluded from BOTH numerator and
    denominator, not counted as an uncited (0) mention."""
    signals = [
        _mentioned(price_quoted=True, pass2_coded=True),
        _mentioned(price_quoted=False, pass2_coded=True),
        _mentioned(price_quoted=False, pass2_coded=False),  # never coded — excluded entirely
    ]
    result = score_price_truth_said(signals)
    assert result["na"] is False
    assert "1/2 coded answers" in result["evidence"][0]


# — member_value.said (rate band, opportunity set = purchase-intent only) —

def test_member_value_said_na_below_two_purchase_intent_mentions():
    signals = [
        _mentioned(stage="Comparison", member_price_claimed=True),
        _mentioned(stage="Awareness", member_price_claimed=True),
        _mentioned(stage="Awareness", member_price_claimed=True),
    ]
    result = score_member_value_said(signals)
    assert result["na"] is True
    assert result["max"] == 6


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
    (1, 4, 2),    # 25% -> 40% of 6 -> 2.4 -> 2
    (2, 4, 4),    # 50% -> 70% of 6 -> 4.2 -> 4
    (3, 4, 6),    # 75% -> 100% of 6 -> 6
])
def test_member_value_said_rate_bands(cited, total, expected_earned):
    signals = [_mentioned(stage="Comparison", member_price_claimed=True) for _ in range(cited)]
    signals += [_mentioned(stage="Comparison", member_price_claimed=False) for _ in range(total - cited)]
    result = score_member_value_said(signals)
    assert result["na"] is False
    assert result["earned"] == expected_earned
    assert result["max"] == 6


# — deal_citability.said (count band, opportunity set = purchase-intent only) —

def test_deal_citability_said_na_below_two_purchase_intent_mentions():
    signals = [_mentioned(stage="Comparison", deal_cited=True), _mentioned(stage="Awareness", deal_cited=True)]
    result = score_deal_citability_said(signals)
    assert result["na"] is True
    assert result["max"] == 2


@pytest.mark.parametrize("cited_count,expected_earned", [
    (0, 0),   # 0 -> 0%
    (1, 1),   # 1 -> 40% of 2 -> 0.8 -> 1
    (2, 1),   # 2-3 -> 70% of 2 -> 1.4 -> 1
    (4, 2),   # 4+ -> 100% of 2 -> 2
])
def test_deal_citability_said_count_bands(cited_count, expected_earned):
    signals = [_mentioned(stage="Comparison", deal_cited=True) for _ in range(cited_count)]
    signals += [_mentioned(stage="Comparison", deal_cited=False) for _ in range(2)]
    result = score_deal_citability_said(signals)
    assert result["na"] is False
    assert result["earned"] == expected_earned
    assert result["max"] == 2


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
    "price_truth_seen": {"score": 5, "max": 5, "coverage": "full", "evidence": ["e"], "fix": "fix price_truth"},
    "member_value_seen": {"score": 9, "max": 9, "coverage": "full", "evidence": ["e"], "fix": "fix member_value"},
    "deal_citability_seen": {"score": 4, "max": 4, "coverage": "full", "evidence": ["e"], "fix": "fix deal_citability"},
    "value_protocols_seen": {"score": 7, "max": 7, "coverage": "full", "evidence": ["e"], "fix": None, "fix_human": None},
}


def _full_credit_signals():
    """4 mentions, all purchase-intent, citing everything — every said
    sub-lens should land at its max band. Needs to be 4 (not 2), since
    Stage 25's 4-tier COUNT_BAND_TABLE only reaches the 100% band at a
    cited count of 4+ (deal_citability.said is count-banded, not
    rate-banded — 2/2 cited would only clear the 70% band)."""
    return [
        RunSignal(
            stage="Comparison", primary_mentioned=True, primary_deal_cited=True,
            primary_deal_types=("member_price",), primary_price_quoted=True,
            primary_member_price_claimed=True, primary_member_value_cited=True,
            pass2_coded=True,
        ),
        RunSignal(
            stage="Comparison", primary_mentioned=True, primary_deal_cited=True,
            primary_deal_types=("member_price",), primary_price_quoted=True,
            primary_member_price_claimed=True, primary_member_value_cited=True,
            pass2_coded=True,
        ),
        RunSignal(
            stage="Ready to Buy", primary_mentioned=True, primary_deal_cited=True,
            primary_deal_types=("member_price",), primary_price_quoted=True,
            primary_member_price_claimed=True, primary_member_value_cited=True,
            pass2_coded=True,
        ),
        RunSignal(
            stage="Ready to Buy", primary_mentioned=True, primary_deal_cited=True,
            primary_deal_types=("member_price",), primary_price_quoted=True,
            primary_member_price_claimed=True, primary_member_value_cited=True,
            pass2_coded=True,
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
    # price_truth(12) + deal_citability(6) + value_protocols(7) = 25, all
    # full -> true_value 100%.
    assert result["true_value"]["score"] == 100
    # composite: visibility(40) + accessibility(20) + true_value(25) = 85
    # earned out of applicable_max(member_value_na=True) = 85 -> 100.
    assert result["composite"] == 100


# ─── N5: Member Value precedence (N/A -> NOT MEASURABLE -> scored) ───────
# probe-determined N/A beats NOT MEASURABLE — inapplicability is
# independent of the crawl. The three tiers are mutually exclusive on
# any given row; each fixture below locks in exactly one.

def test_n5_na_beats_blocked_when_probe_confirms_no_program_and_crawl_is_blocked():
    """Tier 1 (N/A): even though the crawl-side seen half is genuinely
    'blocked' (couldn't be read this run), the probe already confirmed
    there's no program at all — inapplicability doesn't depend on
    whether the crawl could read anything, so this renders N/A, never
    NOT MEASURABLE."""
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["member_value_seen"] = {
        "score": 0, "max": 9, "coverage": "blocked",
        "evidence": ["the store root and every sampled product page were rate-limited or blocked this run"],
    }
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="no",
    )
    assert result["member_value_na"] is True
    member_value_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is True
    assert member_value_row.get("blocked") is not True


def test_n5_blocked_when_probe_confirms_a_program_but_crawl_is_blocked():
    """Tier 2 (NOT MEASURABLE): the probe confirms a program EXISTS
    (applicable), but the crawl genuinely couldn't read anything this
    run — a real "couldn't verify" state, distinct from N/A."""
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["member_value_seen"] = {
        "score": 0, "max": 9, "coverage": "blocked",
        "evidence": ["the store root and every sampled product page were rate-limited or blocked this run"],
    }
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    assert result["member_value_na"] is False
    member_value_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is False
    assert member_value_row["blocked"] is True
    assert member_value_row["earned"] == 0.0
    assert member_value_row["max"] == 0.0


def test_n5_scored_for_real_when_crawl_succeeded_regardless_of_probe():
    """Tier 3 (scored): the crawl itself found real credit — applicable
    and measurable, scored normally, independent of what the probe
    said (an 'unknown' probe result is an abstention, not a finding)."""
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["member_value_seen"] = {
        "score": 9, "max": 9, "coverage": "full",
        "evidence": ["1/1 product pages expose member/tier pricing in structured data"],
    }
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="unknown",
    )
    assert result["member_value_na"] is False
    member_value_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert member_value_row["na"] is False
    assert member_value_row.get("blocked") is not True
    assert member_value_row["earned"] > 0.0


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
    its seen half (5 pts) instead of the full 12."""
    one_signal = [RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=True)]
    result = build_pillars_payload(
        som_pct=0.0, rsi_score=None, total_mentions=1,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=one_signal,
        membership_probe_result="yes",
    )
    price_truth_row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "price_truth")
    assert price_truth_row["max"] == 5  # seen_max only, not the full 12
    assert price_truth_row["earned"] == 5  # seen's full score, said contributes nothing
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
    # deal_citability(2) are the three biggest opportunities (gaps
    # computed against the real registry weight, not this fixture's own
    # "max" — price_truth/member_value's dim_max comes from
    # dimension_max(), full credit on said via _full_credit_signals());
    # the other four (including value_protocols, always seen-only) are
    # fully earned (gap 0) and should end up locked.
    crawl = {
        "agent_access": {"score": 6, "max": 6, "coverage": "full", "fix": "f-aa"},
        "catalog_context": {"score": 8, "max": 8, "coverage": "full", "fix": "f-cc"},
        "protocol_feed": {"score": 0, "max": 6, "coverage": "full", "fix": "f-pf"},
        "price_truth_seen": {"score": 1, "max": 5, "coverage": "full", "fix": "f-pt"},
        "member_value_seen": {"score": 9, "max": 9, "coverage": "full", "fix": "f-mv"},
        "deal_citability_seen": {"score": 2, "max": 4, "coverage": "full", "fix": "f-dc"},
        "value_protocols_seen": {"score": 7, "max": 7, "coverage": "full", "fix": None},
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

    for code in ("agent_access", "catalog_context", "member_value", "value_protocols"):
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


# ─── Part 3 (F1): report.fixes — top 2 free, rest a bare count ───────────
#
# Deliberately separate from pillars.*.dimensions (unchanged above,
# still needed by the True Value butterfly/Accessibility tiles) — this
# section is its own additive field, computed by _build_fixes_section.

# Six distinct gaps (1-6), all crawl-derived, so the ranking is
# unambiguous with no tiebreak needed: member_value(6) > price_truth(5)
# > deal_citability(4) > protocol_feed(3) > catalog_context(2) >
# agent_access(1). True Value gaps are against the real registry weight
# (dimension_max(), full credit on said via _full_credit_signals()), not
# this fixture's own "max". value_protocols is seen-only and pinned at
# full credit with no fix_human, so it never enters the ranking pool at
# all (see _build_fixes_section's fix_human filter) — same zero-gap,
# stays-out-of-the-way role it plays in the other fixtures above.
_SIX_FIX_CRAWL_DIMS = {
    "agent_access": {"score": 5, "max": 6, "coverage": "full", "fix": "fix-aa", "fix_human": "human-aa"},
    "catalog_context": {"score": 6, "max": 8, "coverage": "full", "fix": "fix-cc", "fix_human": "human-cc"},
    "protocol_feed": {"score": 3, "max": 6, "coverage": "full", "fix": "fix-pf", "fix_human": "human-pf"},
    "price_truth_seen": {"score": 0, "max": 5, "coverage": "full", "fix": "fix-pt", "fix_human": "human-pt"},
    "member_value_seen": {"score": 3, "max": 9, "coverage": "full", "fix": "fix-mv", "fix_human": "human-mv"},
    "deal_citability_seen": {"score": 0, "max": 4, "coverage": "full", "fix": "fix-dc", "fix_human": "human-dc"},
    "value_protocols_seen": {"score": 7, "max": 7, "coverage": "full", "fix": None, "fix_human": None},
}


def _build_six_fix_result(**overrides):
    kwargs = dict(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=_SIX_FIX_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    kwargs.update(overrides)
    return build_pillars_payload(**kwargs)


def test_fixes_visible_is_the_top_2_by_gap():
    result = _build_six_fix_result()
    assert [v["code"] for v in result["fixes"]["visible"]] == ["member_value", "price_truth"]


def test_fixes_visible_entries_carry_only_plain_language_fix_human_and_impact():
    result = _build_six_fix_result()
    top = result["fixes"]["visible"][0]
    assert top == {"code": "member_value", "name": "Member Value", "fix_human": "human-mv", "impact": 6.0}
    # No 'fix' (markup) key anywhere on a visible entry — H2's no-markup
    # rule holds at the schema level, not just by convention.
    assert "fix" not in top


def test_fixes_remaining_count_is_the_rest():
    result = _build_six_fix_result()
    assert result["fixes"]["remaining_count"] == 4


def test_fixes_leak_test_ranks_beyond_2_are_absent_entirely():
    """F1's leak test: serialize the fixes field for a 6-fix fixture and
    assert ranks 3+ are absent entirely — no code, no fix_human title,
    anywhere in the serialized object, only a bare count."""
    result = _build_six_fix_result()
    serialized = json.dumps(result["fixes"])

    for code, human in [
        ("deal_citability", "human-dc"), ("protocol_feed", "human-pf"),
        ("catalog_context", "human-cc"), ("agent_access", "human-aa"),
    ]:
        assert code not in serialized
        assert human not in serialized


def test_fixes_excludes_dimensions_with_no_fix_human_even_if_ranked_high():
    # A dimension at a large gap but with NO fix_human (crawl scorer
    # found nothing to recommend) must never occupy a free slot or count
    # toward remaining_count — it has nothing to show.
    crawl = dict(_SIX_FIX_CRAWL_DIMS)
    crawl["member_value_seen"] = {**crawl["member_value_seen"], "fix": None, "fix_human": None}
    result = _build_six_fix_result(crawl_dimensions=crawl)
    codes = [v["code"] for v in result["fixes"]["visible"]]
    assert "member_value" not in codes
    assert codes == ["price_truth", "deal_citability"]
    assert result["fixes"]["remaining_count"] == 3  # protocol_feed, catalog_context, agent_access


def test_fixes_na_dimension_excluded_from_ranking_and_count():
    # protocol_feed(gap 3) turns na, leaving 5 fixable dims: member_value(6)
    # and price_truth(5) still visible; catalog_context(2), agent_access(1),
    # and deal_citability(4) make up the remaining 3 — protocol_feed itself
    # contributes to neither the visible list nor the count.
    crawl = dict(_SIX_FIX_CRAWL_DIMS)
    crawl["protocol_feed"] = {**crawl["protocol_feed"], "coverage": "na"}
    result = _build_six_fix_result(crawl_dimensions=crawl)

    assert [v["code"] for v in result["fixes"]["visible"]] == ["member_value", "price_truth"]
    assert result["fixes"]["remaining_count"] == 3


def test_fixes_value_protocols_ranks_like_any_other_true_value_dimension():
    """Stage 25 (Part 6, A2): value_protocols is a full 7th crawl-derived
    dimension in the ranking pool — when it has the biggest opportunity
    gap and a real fix_human, it ranks and shows up in fixes.visible
    exactly like price_truth/member_value/deal_citability/accessibility
    do, not silently excluded for being the new dimension."""
    crawl = dict(_SIX_FIX_CRAWL_DIMS)
    crawl["value_protocols_seen"] = {
        "score": 0, "max": 7, "coverage": "full",
        "fix": "declare capabilities", "fix_human": "Declare your agent-checkout capabilities in your protocol manifest.",
    }
    result = _build_six_fix_result(crawl_dimensions=crawl)

    # value_protocols' gap is 7 (0/7), bigger than member_value's 6 —
    # it now takes the #1 slot, pushing member_value out of the free top 2.
    assert [v["code"] for v in result["fixes"]["visible"]] == ["value_protocols", "member_value"]
    assert result["fixes"]["visible"][0]["fix_human"] == "Declare your agent-checkout capabilities in your protocol manifest."
    assert result["fixes"]["remaining_count"] == 5


# ─── checks[]/band-context (Report redesign, Part 1, A1/A2) ─────────────
#
# Realistic, exact-wording evidence fixtures — copied verbatim from
# apps/pipeline/scan/scorer.py's own evidence-string construction, since
# checks[] is parsed from that fixed wording (no pipeline diff this
# stage — see lite_pillars.py's module comment). A change to scorer.py's
# wording that isn't mirrored here is exactly the drift risk that
# tradeoff accepted; these fixtures are the tripwire for it.

from soa_shared.scan_dimensions import DIMENSIONS_BY_CODE as _DIMS  # noqa: E402

_REALISTIC_CRAWL_DIMS = {
    "agent_access": {
        "score": 5, "max": 6, "coverage": "full",
        "evidence": [
            "robots.txt is fetchable", "robots.txt allows product paths",
            "no bot-blocking encountered on sampled pages", "no sitemap found",
        ],
    },
    "catalog_context": {
        "score": 0, "max": 8, "coverage": "full",
        "evidence": [
            "https://x/p1: missing/incomplete Product+Offer JSON-LD",
            "https://x/p2: missing/incomplete Product+Offer JSON-LD",
            "no discoverable shipping/returns terms",
            "0/2 product pages expose a gtin/mpn/sku identifier",
        ],
    },
    "protocol_feed": {
        "score": 1, "max": 6, "coverage": "partial",
        "evidence": [
            "/llms.txt present and non-empty",
            "no MCP endpoint declaration found (well-known path checked, absent; no link markup)",
            "no UCP/UIP capability markup found",
            "no agentic-commerce hints found in structured data",
        ],
    },
    "price_truth_seen": {
        "score": 0, "max": 5, "coverage": "full",
        "evidence": [
            "0/2 product pages expose a machine-readable price consistent with the page's own text",
            "0/2 product pages declare priceCurrency",
        ],
    },
    "member_value_seen": {
        "score": 0, "max": 9, "coverage": "full",
        "evidence": [
            "no loyalty/rewards page found in nav/footer",
            "no structured member/tier pricing found on sampled product pages",
        ],
    },
    "deal_citability_seen": {
        "score": 0, "max": 4, "coverage": "full",
        "evidence": [
            "0/2 product pages state a concrete amount or discount mechanic",
            "0/2 product pages declare a currently-active validity window",
            "0/2 product pages expose eligibility/code/stackability terms",
        ],
    },
    "value_protocols_seen": {
        "score": 0, "max": 7, "coverage": "full",
        "evidence": [
            "does not declare a UCP shopping-discount capability",
            "does not declare a loyalty/member protocol extension",
            "does not declare an ACP promotions capability",
            "declared protocol manifest version is missing, unrecognized, or out of date",
        ],
    },
    "price_honesty_advisory": {"scored": False, "would_have_capped": False, "evidence": [], "cap_basis": []},
}


def _no_purchase_intent_signals():
    return [
        RunSignal(stage="Comparison", primary_mentioned=True, primary_deal_cited=True, pass2_coded=True),
        RunSignal(stage="Ready to Buy", primary_mentioned=True, primary_deal_cited=False, pass2_coded=True),
    ]


def _realistic_result():
    return build_pillars_payload(
        som_pct=35.0, rsi_score=0.2, total_mentions=8,
        crawl_dimensions=_REALISTIC_CRAWL_DIMS, run_signals=_no_purchase_intent_signals(),
        membership_probe_result="no", membership_probe_evidence="Allbirds does not appear to offer...",
    )


_SEEN_SIDE_CHECK_IDS_BY_CODE = {
    "agent_access": ("robots_allows", "no_bot_blocks", "sitemap"),
    "catalog_context": ("product_data", "completeness", "identifiers"),
    "protocol_feed": ("llms_txt", "mcp", "ucp"),
    "price_truth": ("price_in_code", "price_matches_page"),
    "member_value": ("loyalty_page", "member_price_encoded", "markup_parses"),
    "deal_citability": ("not_expired", "actionable"),  # concrete_amount carries a live-count suffix
    "value_protocols": ("ucp_discount", "loyalty", "acp_promotions", "version_schema"),
}


def test_checks_seen_side_labels_are_registry_how_measured_strings():
    """A1's parity rule: every structural (non-outcome, non-advisory)
    check's label must be verbatim one of its dimension's soa_shared.
    scan_dimensions.Dimension.how_measured strings — never a second,
    independently-worded copy of the methodology text."""
    result = _realistic_result()
    all_dims = (
        result["accessibility"]["dimensions"] + result["true_value"]["dimensions"]
    )
    checked_any = False
    for dim in all_dims:
        if not dim.get("checks"):
            continue
        how_measured = set(_DIMS[dim["code"]].how_measured)
        seen_ids = _SEEN_SIDE_CHECK_IDS_BY_CODE[dim["code"]]
        for check in dim["checks"]:
            if check["code"] in seen_ids:
                assert check["label"] in how_measured, (dim["code"], check)
                checked_any = True
    assert checked_any


def test_agent_access_checks_pass_fail_from_evidence():
    result = _realistic_result()
    agent_access = next(d for d in result["accessibility"]["dimensions"] if d["code"] == "agent_access")
    by_code = {c["code"]: c["state"] for c in agent_access["checks"]}
    assert by_code == {"robots_allows": "pass", "no_bot_blocks": "pass", "sitemap": "fail"}


def test_catalog_context_checks_do_not_false_match_incomplete_as_complete():
    """Regression: 'incomplete' ends in 'complete', which an endswith
    check on 'complete Product+Offer JSON-LD' would false-match — every
    sampled page is genuinely incomplete here, so product_data must fail."""
    result = _realistic_result()
    catalog = next(d for d in result["accessibility"]["dimensions"] if d["code"] == "catalog_context")
    by_code = {c["code"]: c["state"] for c in catalog["checks"]}
    assert by_code == {"product_data": "fail", "completeness": "fail", "identifiers": "fail"}


def test_protocol_feed_checks_from_evidence():
    result = _realistic_result()
    pf = next(d for d in result["accessibility"]["dimensions"] if d["code"] == "protocol_feed")
    by_code = {c["code"]: c["state"] for c in pf["checks"]}
    assert by_code == {"llms_txt": "pass", "mcp": "fail", "ucp": "fail"}


def test_value_protocols_checks_all_fail_when_manifest_declares_nothing():
    result = _realistic_result()
    vp = next(d for d in result["true_value"]["dimensions"] if d["code"] == "value_protocols")
    by_code = {c["code"]: c["state"] for c in vp["checks"]}
    assert by_code == {
        "ucp_discount": "fail", "loyalty": "fail", "acp_promotions": "fail", "version_schema": "fail",
    }
    # Labels equal how_measured in-order (Part 1, A1) — this dimension's
    # 4 scorer.py checks map 1:1, in order, onto its 4 how_measured strings.
    assert [c["label"] for c in vp["checks"]] == list(_DIMS["value_protocols"].how_measured)


def test_value_protocols_checks_all_na_when_no_manifest_found():
    crawl = dict(_REALISTIC_CRAWL_DIMS)
    crawl["value_protocols_seen"] = {"score": 0, "max": 7, "coverage": "full", "evidence": ["no protocol profile found"]}
    result = build_pillars_payload(
        som_pct=35.0, rsi_score=0.2, total_mentions=8,
        crawl_dimensions=crawl, run_signals=_no_purchase_intent_signals(),
        membership_probe_result="no",
    )
    vp = next(d for d in result["true_value"]["dimensions"] if d["code"] == "value_protocols")
    assert all(c["state"] == "na" for c in vp["checks"])


def test_price_truth_checks_combine_seen_said_and_advisory():
    result = _realistic_result()
    pt = next(d for d in result["true_value"]["dimensions"] if d["code"] == "price_truth")
    by_code = {c["code"]: c["state"] for c in pt["checks"]}
    assert by_code["price_in_code"] == "fail"
    assert by_code["price_matches_page"] == "na"  # nothing to compare — no price at all
    assert by_code["said_price_cited"] == "fail"  # 0/8 mentions cited a price
    assert by_code["fake_sale_prices"] == "advisory"  # always advisory-styled; text varies


def test_price_truth_fake_sale_prices_label_reflects_would_have_capped():
    capped_crawl = dict(_REALISTIC_CRAWL_DIMS)
    capped_crawl["price_honesty_advisory"] = {"scored": False, "would_have_capped": True, "evidence": [], "cap_basis": ["x"]}
    result = build_pillars_payload(
        som_pct=35.0, rsi_score=0.2, total_mentions=8,
        crawl_dimensions=capped_crawl, run_signals=_no_purchase_intent_signals(),
        membership_probe_result="no",
    )
    pt = next(d for d in result["true_value"]["dimensions"] if d["code"] == "price_truth")
    fake_sale = next(c for c in pt["checks"] if c["code"] == "fake_sale_prices")
    assert "flagged" in fake_sale["label"] and "none" not in fake_sale["label"]


def test_deal_citability_checks_not_expired_is_na_when_no_deal_at_all():
    result = _realistic_result()
    dc = next(d for d in result["true_value"]["dimensions"] if d["code"] == "deal_citability")
    by_code = {c["code"]: c["state"] for c in dc["checks"]}
    assert by_code == {"concrete_amount": "fail", "not_expired": "na", "actionable": "fail"}
    concrete = next(c for c in dc["checks"] if c["code"] == "concrete_amount")
    assert "(0/2 pages)" in concrete["label"]


def test_member_value_na_dimension_has_no_checks():
    """T2: the N/A path shows a decision sentence + probe quote, not a
    checks grid — checks must be None even though seen/said data exists."""
    result = _realistic_result()
    mv = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert mv["na"] is True
    assert mv["checks"] is None


def test_member_value_checks_when_applicable():
    crawl = dict(_REALISTIC_CRAWL_DIMS)
    crawl["member_value_seen"] = {
        "score": 5, "max": 9, "coverage": "full",
        "evidence": ["loyalty page found and fetchable: https://x/rewards", "no structured member/tier pricing found on sampled product pages"],
    }
    result = build_pillars_payload(
        som_pct=35.0, rsi_score=0.2, total_mentions=8,
        crawl_dimensions=crawl, run_signals=_no_purchase_intent_signals(),
        membership_probe_result="yes",
    )
    mv = next(d for d in result["true_value"]["dimensions"] if d["code"] == "member_value")
    assert mv["na"] is False
    by_code = {c["code"]: c["state"] for c in mv["checks"]}
    assert by_code["loyalty_page"] == "pass"
    assert by_code["member_price_encoded"] == "fail"
    assert by_code["markup_parses"] == "na"  # not observable from evidence strings


def test_share_of_mentions_and_recommendation_strength_have_no_checks():
    """These two dimensions show a live meter/band ladder instead of a
    checks grid (mock: 'HOW WE MEASURE', not 'WHAT WE CHECK')."""
    result = _realistic_result()
    som = next(d for d in result["visibility"]["dimensions"] if d["code"] == "share_of_mentions")
    rs = next(d for d in result["visibility"]["dimensions"] if d["code"] == "recommendation_strength")
    assert som["checks"] is None
    assert rs["checks"] is None


# ─── Band context (Part 1, A2) ────────────────────────────────────────────

def test_share_of_mentions_your_value_is_the_live_share_pct():
    result = score_share_of_mentions(som_pct=35.0, total_mentions=8)
    assert result["your_value"] == 35.0


def test_recommendation_strength_your_band_moves_with_earned_score():
    full = score_recommendation_strength(rsi_score=3.0, total_mentions=6)
    partial = score_recommendation_strength(rsi_score=0.0, total_mentions=6)
    zero = score_recommendation_strength(rsi_score=-1.0, total_mentions=6)
    assert full["your_band"] == 0
    assert partial["your_band"] == 1
    assert zero["your_band"] == 2


@pytest.mark.parametrize("cited,total,expected_band", [
    (0, 10, 0),   # 0% -> band 0
    (2, 10, 1),   # 20% -> (0,25] -> band 1
    (4, 10, 2),   # 40% -> (25,50] -> band 2
    (8, 10, 3),   # 80% -> (50,100] -> band 3
])
def test_price_truth_said_your_band_perturbation(cited, total, expected_band):
    """Perturbation test (per the stage's own TESTS spec): changing the
    underlying cited/total ratio must move your_band, proving it's
    derived from the real value rather than a hard-coded index."""
    signals = [RunSignal(stage="Awareness", primary_mentioned=True, primary_price_quoted=(i < cited), pass2_coded=True) for i in range(total)]
    result = score_price_truth_said(signals)
    assert result["your_band"] == expected_band
    assert result["band_table_ref"] == "rate"


def test_deal_citability_said_your_band_is_count_banded_not_rate_banded():
    signals = [
        RunSignal(stage="Comparison", primary_mentioned=True, primary_deal_cited=True),
        RunSignal(stage="Ready to Buy", primary_mentioned=True, primary_deal_cited=False),
    ]
    result = score_deal_citability_said(signals)
    assert result["band_table_ref"] == "count"
    assert result["your_value"] == 1
    assert result["your_band"] == 1  # COUNT_BAND_TABLE: exactly 1 -> band index 1


def test_na_said_result_has_no_band_fields():
    result = score_price_truth_said([])
    assert result["na"] is True
    assert "your_band" not in result
    assert "band_table_ref" not in result


# ─── Fetch-resilience stage (Part C): coverage='blocked' report surfaces ──
#
# scorer.py can now return coverage='blocked' on catalog_context/
# price_truth_seen/deal_citability_seen when every sampled product page
# terminally failed to fetch this run (429/403/5xx, after the scanner's
# own retry ladder already tried). build_pillars_payload must render
# that as NOT MEASURABLE — excluded from the pillar's applicable max
# exactly like 'na', never scored as a phantom zero — and every one of
# the dimension's checks[] must report state='blocked', never a false
# 'fail' derived from evidence wording the blocked dimension never has.

_BLOCKED_EVIDENCE = ["2 of 2 product pages rate-limited our reader (HTTP 429) — couldn't be evaluated."]


def test_catalog_context_blocked_excludes_from_accessibility_denominator():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["catalog_context"] = {"score": 0, "max": 8, "coverage": "blocked", "evidence": _BLOCKED_EVIDENCE}
    result = build_pillars_payload(
        som_pct=0.0, rsi_score=None, total_mentions=0,
        crawl_dimensions=crawl, run_signals=[], membership_probe_result="unknown",
    )
    # agent_access(6) + protocol_feed(6) = 12 applicable, both full -> 100%.
    # catalog_context's 8 points never enter the denominator at all.
    assert result["accessibility"]["score"] == 100
    row = next(d for d in result["accessibility"]["dimensions"] if d["code"] == "catalog_context")
    assert row["blocked"] is True
    assert row["na"] is False
    assert row["earned"] == 0.0
    assert all(c["state"] == "blocked" for c in row["checks"])
    assert all(c["evidence"] == _BLOCKED_EVIDENCE[0] for c in row["checks"])


def test_price_truth_blocked_excludes_whole_dimension_from_true_value():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["price_truth_seen"] = {"score": 0, "max": 5, "coverage": "blocked", "evidence": _BLOCKED_EVIDENCE}
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    # member_value(9) + deal_citability(4) + value_protocols(7) = 20
    # applicable, all full -> 100%. price_truth's 12 (seen+said) never
    # enters the denominator.
    assert result["true_value"]["score"] == 100
    row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "price_truth")
    assert row["blocked"] is True
    assert row["na"] is False
    assert row["earned"] == 0.0
    assert row["max"] == 0.0
    assert row["seen"]["blocked"] is True
    # the seen sub-lens keeps its real nominal max (5) — only the
    # combined dimension's own earned/max are zeroed for the composite.
    assert row["seen"]["max"] == 5
    assert all(c["state"] == "blocked" for c in row["checks"])
    # said is untouched — a real, unrelated signal, still attached even
    # though it doesn't count toward the composite here.
    assert row["said"]["na"] is False


def test_deal_citability_blocked_excludes_whole_dimension_from_true_value():
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["deal_citability_seen"] = {"score": 0, "max": 4, "coverage": "blocked", "evidence": _BLOCKED_EVIDENCE}
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=crawl, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    row = next(d for d in result["true_value"]["dimensions"] if d["code"] == "deal_citability")
    assert row["blocked"] is True
    assert row["earned"] == 0.0
    assert row["max"] == 0.0
    # price_truth(12) + member_value(9) + value_protocols(7) = 28 applicable.
    assert result["true_value"]["score"] == 100


def test_blocked_dimension_all_ok_case_is_unaffected():
    """Sanity: nothing here changes behavior when no dimension is
    blocked — same byte-identical full-credit result as before this
    stage."""
    result = build_pillars_payload(
        som_pct=100.0, rsi_score=3.0, total_mentions=6,
        crawl_dimensions=_FULL_CRAWL_DIMS, run_signals=_full_credit_signals(),
        membership_probe_result="yes",
    )
    assert result["true_value"]["score"] == 100
    assert result["accessibility"]["score"] == 100
    for d in result["accessibility"]["dimensions"] + result["true_value"]["dimensions"]:
        assert d.get("blocked") in (False, None)


def test_blocked_dimension_excluded_from_fix_ranking_and_fixes_section():
    """A blocked dimension has no fix we can honestly attribute (we
    never read the pages that would reveal one) — it must never occupy
    a free fix slot, count toward remaining_count, or come back locked."""
    crawl = dict(_FULL_CRAWL_DIMS)
    crawl["catalog_context"] = {"score": 0, "max": 8, "coverage": "blocked", "evidence": _BLOCKED_EVIDENCE}
    result = build_pillars_payload(
        som_pct=0.0, rsi_score=None, total_mentions=0,
        crawl_dimensions=crawl, run_signals=[], membership_probe_result="unknown",
    )
    row = next(d for d in result["accessibility"]["dimensions"] if d["code"] == "catalog_context")
    assert row["locked"] is False
    assert row["fix"] is None
    assert row["fix_human"] is None
    assert not any(f["code"] == "catalog_context" for f in result["fixes"]["visible"])
