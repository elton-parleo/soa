"""
Stage 16 (Part 1, R3), rescaled Stage 25 (Part 1, R1): parity tests for
soa_shared/scan_dimensions.py — the v4 three-pillar registry. A rubric
change that touches only one side (registry vs. the functions that
consume it) fails here instead of silently drifting, the same
discipline as Stage 14's status-parity tests.

This file covers the registry's OWN internal shape (pillar sums,
seen/said splits, band-table declarations, the composite formula, the
verdict gate). The cross-module "every registry code has a scoring
implementation" check lives in test_scorer.py.
"""
import dataclasses

import pytest

from soa_shared.scan_dimensions import (
    BAND_TYPE_COUNT,
    BAND_TYPE_RATE,
    COUNT_BAND_TABLE,
    DIMENSIONS,
    DIMENSIONS_BY_CODE,
    DIMENSION_ORDER,
    LITE_QUERIES_PER_STAGE,
    LITE_QUERY_COUNT,
    MEMBER_VALUE_CODE,
    MIN_OPPORTUNITY_SET_MENTIONS,
    OPPORTUNITY_SET_ALL_MENTIONS,
    OPPORTUNITY_SET_PURCHASE_INTENT,
    PILLAR_ACCESSIBILITY,
    PILLAR_ORDER,
    PILLAR_TRUE_VALUE,
    PILLAR_VISIBILITY,
    PILLAR_WEIGHTS,
    RATE_BAND_TABLE,
    SCORER_VERSION,
    TOTAL_MAX,
    VERDICT_AGENT_READY,
    VERDICT_COMPOSITE_THRESHOLD,
    VERDICT_NOT_AGENT_READY,
    VERDICT_TRUE_VALUE_RATIO_THRESHOLD,
    apply_count_band,
    apply_rate_band,
    applicable_max,
    compute_composite,
    compute_verdict,
    dimension_max,
)
import soa_shared.scan_dimensions as scan_dimensions

TRUE_VALUE_SPLIT_CODES = ("price_truth", "member_value", "deal_citability")
TRUE_VALUE_CODES = ("price_truth", "member_value", "deal_citability", "value_protocols")


def test_scorer_version_is_5():
    assert SCORER_VERSION == "5"


def test_lite_query_count_is_24():
    assert LITE_QUERIES_PER_STAGE == 6
    assert LITE_QUERY_COUNT == 24


def test_pillar_weights_sum_to_spec():
    # Re-weighting session: True Value is the pillar only Parleo
    # measures, so it now carries half the composite (40->50);
    # Visibility/Accessibility absorbed the reduction (40->32, 20->18).
    assert PILLAR_WEIGHTS[PILLAR_VISIBILITY] == 32
    assert PILLAR_WEIGHTS[PILLAR_ACCESSIBILITY] == 18
    assert PILLAR_WEIGHTS[PILLAR_TRUE_VALUE] == 50
    assert TOTAL_MAX == 100
    assert sum(PILLAR_WEIGHTS.values()) == TOTAL_MAX


def test_true_value_dimension_weight_ordering_encodes_universality():
    """Re-weighting session: within True Value, weight ordering follows
    universality, not sentiment. Member Value only applies to brands
    running a loyalty program (N/A on a large share of runs), so it
    must never outweigh Deal Citability or Value Protocols, both of
    which apply to every run — asserted directly so a future edit
    can't silently invert it."""
    member_value = DIMENSIONS_BY_CODE["member_value"].weight
    assert DIMENSIONS_BY_CODE["deal_citability"].weight > member_value
    assert DIMENSIONS_BY_CODE["value_protocols"].weight > member_value


def test_pillar_order_covers_every_pillar_exactly_once():
    assert set(PILLAR_ORDER) == set(PILLAR_WEIGHTS.keys())
    assert len(PILLAR_ORDER) == len(set(PILLAR_ORDER))


def test_dimension_order_matches_dimensions_and_has_no_duplicates():
    assert DIMENSION_ORDER == tuple(d.code for d in DIMENSIONS)
    assert len(DIMENSION_ORDER) == len(set(DIMENSION_ORDER)) == 9


def test_every_dimension_weight_sums_correctly_within_its_pillar():
    for pillar in PILLAR_ORDER:
        dims = [d for d in DIMENSIONS if d.pillar == pillar]
        assert sum(d.weight for d in dims) == PILLAR_WEIGHTS[pillar]


@pytest.mark.parametrize("code,expected_weight", [
    ("share_of_mentions", 22),
    ("recommendation_strength", 10),
    ("agent_access", 5),
    ("catalog_context", 8),
    ("protocol_feed", 5),
    ("price_truth", 16),
    ("member_value", 8),
    ("deal_citability", 12),
    ("value_protocols", 14),
])
def test_dimension_weights_match_spec(code, expected_weight):
    assert DIMENSIONS_BY_CODE[code].weight == expected_weight


def test_only_true_value_split_dimensions_have_a_seen_said_split():
    """value_protocols is a True Value pillar member but is encode-only
    (a seen half, no said half at all) — has_seen_said_split requires
    BOTH to be set, so it correctly reads False for value_protocols,
    same as every non-True-Value dimension."""
    for d in DIMENSIONS:
        if d.code in TRUE_VALUE_SPLIT_CODES:
            assert d.has_seen_said_split, f"{d.code} should have a seen/said split"
            assert d.pillar == PILLAR_TRUE_VALUE
        else:
            assert not d.has_seen_said_split, f"{d.code} should NOT have a seen/said split"


def test_value_protocols_has_a_seen_half_but_no_said_half():
    vp = DIMENSIONS_BY_CODE["value_protocols"]
    assert vp.pillar == PILLAR_TRUE_VALUE
    assert vp.seen_max == vp.weight == 14
    assert vp.said_max is None
    assert vp.said_opportunity_set is None
    assert vp.said_band_type is None


def test_true_value_pillar_has_exactly_four_dimensions_in_documented_order():
    tv_codes = tuple(d.code for d in DIMENSIONS if d.pillar == PILLAR_TRUE_VALUE)
    assert tv_codes == TRUE_VALUE_CODES


def test_seen_plus_said_equals_dimension_weight():
    for d in DIMENSIONS:
        if d.has_seen_said_split:
            assert d.seen_max + d.said_max == d.weight, d.code


@pytest.mark.parametrize("code,seen,said", [
    ("price_truth", 7, 9),
    ("member_value", 5, 3),
    ("deal_citability", 7, 5),
])
def test_seen_said_split_matches_spec(code, seen, said):
    d = DIMENSIONS_BY_CODE[code]
    assert d.seen_max == seen
    assert d.said_max == said


def test_every_split_sublens_declares_opportunity_set_and_band_type():
    for d in DIMENSIONS:
        if d.has_seen_said_split:
            assert d.said_opportunity_set is not None, d.code
            assert d.said_band_type is not None, d.code
            assert d.said_opportunity_set in (OPPORTUNITY_SET_ALL_MENTIONS, OPPORTUNITY_SET_PURCHASE_INTENT)
            assert d.said_band_type in (BAND_TYPE_RATE, BAND_TYPE_COUNT)


def test_opportunity_sets_match_part0_calibration():
    # price_truth.said: all mentions (not purchase-stage-gated)
    assert DIMENSIONS_BY_CODE["price_truth"].said_opportunity_set == OPPORTUNITY_SET_ALL_MENTIONS
    # member_value.said / deal_citability.said: purchase-intent only,
    # per the Stage 16 Part 0 calibration (citations concentrate 94%+
    # in Comparison + Ready to Buy)
    assert DIMENSIONS_BY_CODE["member_value"].said_opportunity_set == OPPORTUNITY_SET_PURCHASE_INTENT
    assert DIMENSIONS_BY_CODE["deal_citability"].said_opportunity_set == OPPORTUNITY_SET_PURCHASE_INTENT


def test_band_types_match_spec():
    assert DIMENSIONS_BY_CODE["price_truth"].said_band_type == BAND_TYPE_RATE
    assert DIMENSIONS_BY_CODE["member_value"].said_band_type == BAND_TYPE_RATE
    assert DIMENSIONS_BY_CODE["deal_citability"].said_band_type == BAND_TYPE_COUNT


def test_min_opportunity_set_mentions_guard_value():
    assert MIN_OPPORTUNITY_SET_MENTIONS == 2


# ── Band tables ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("rate_pct,expected_fraction", [
    (0, 0.0),
    (0.01, 0.40),
    (24.99, 0.40),
    (25, 0.40),
    (25.01, 0.70),
    (49.99, 0.70),
    (50, 0.70),
    (50.01, 1.0),
    (100, 1.0),
    (None, 0.0),
])
def test_apply_rate_band_edges(rate_pct, expected_fraction):
    assert apply_rate_band(rate_pct) == expected_fraction


@pytest.mark.parametrize("count,expected_fraction", [
    (0, 0.0),
    (1, 0.40),
    (2, 0.70),
    (3, 0.70),
    (4, 1.0),
    (10, 1.0),
    (None, 0.0),
])
def test_apply_count_band_edges(count, expected_fraction):
    """Stage 25 (Part 4, Q3): recalibrated for the 24-query study's
    doubled purchase-intent opportunity set — 0/40/70/100% at
    0/1/2-3/4+ citations, up from the v3 0/60/100% at 0/1/2+."""
    assert apply_count_band(count) == expected_fraction


def test_rate_band_table_is_monotonically_increasing():
    fractions = [f for _, f in RATE_BAND_TABLE]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0


def test_count_band_table_is_monotonically_increasing():
    fractions = [f for _, f in COUNT_BAND_TABLE]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0


# ── Composite formula (Part 4 P4 / Part 7 A3) ───────────────────────────

def test_applicable_max_full():
    assert applicable_max(member_value_na=False) == 100


def test_applicable_max_member_value_na():
    assert applicable_max(member_value_na=True) == 92  # 100 - 8


def test_compute_composite_full_scoring():
    assert compute_composite(100, member_value_na=False) == 100
    assert compute_composite(50, member_value_na=False) == 50
    assert compute_composite(0, member_value_na=False) == 0


def test_compute_composite_na_normalization():
    assert compute_composite(92, member_value_na=True) == 100
    assert compute_composite(0, member_value_na=True) == 0
    # 40 of 92 applicable points -> ~43%
    assert compute_composite(40, member_value_na=True) == round(40 / 92 * 100)


def test_compute_composite_never_raises_on_degenerate_basis(monkeypatch):
    monkeypatch.setattr(scan_dimensions, "TOTAL_MAX", 0)
    assert compute_composite(0, member_value_na=False) == 0


def test_perturbation_changing_member_value_weight_moves_applicable_max_and_composite(monkeypatch):
    """
    Part 7, A3: nothing about the /92 normalization is hard-coded — it's
    TOTAL_MAX minus member_value's registered weight, read fresh at call
    time. Perturb ONLY member_value's weight (TOTAL_MAX untouched) and
    confirm applicable_max/compute_composite move to a DIFFERENT number
    than the spec's 92, proving the formula — not a baked-in constant —
    drives the result.
    """
    perturbed_member_value = dataclasses.replace(
        scan_dimensions.DIMENSIONS_BY_CODE["member_value"], weight=29,
    )
    monkeypatch.setattr(
        scan_dimensions, "DIMENSIONS_BY_CODE",
        {**scan_dimensions.DIMENSIONS_BY_CODE, "member_value": perturbed_member_value},
    )

    assert applicable_max(member_value_na=True) == 71  # 100 - 29, not the spec's 92
    assert applicable_max(member_value_na=False) == 100  # unaffected when member_value IS scored
    assert compute_composite(71, member_value_na=True) == 100
    assert compute_composite(35.5, member_value_na=True) == 50


# ── Per-dimension seen/said rescale (Part 3, T2) ────────────────────────

def test_dimension_max_no_split_dimension_ignores_said_na():
    agent_access = DIMENSIONS_BY_CODE["agent_access"]
    assert dimension_max(agent_access, said_na=False) == agent_access.weight
    assert dimension_max(agent_access, said_na=True) == agent_access.weight


def test_dimension_max_value_protocols_ignores_said_na_too():
    """value_protocols has a seen half (seen_max == weight) but no said
    half — has_seen_said_split is False, so said_na is meaningless and
    dimension_max always returns the full weight, same as any other
    no-split dimension."""
    vp = DIMENSIONS_BY_CODE["value_protocols"]
    assert dimension_max(vp, said_na=False) == vp.weight
    assert dimension_max(vp, said_na=True) == vp.weight


@pytest.mark.parametrize("code", TRUE_VALUE_SPLIT_CODES)
def test_dimension_max_split_dimension_full_weight_when_said_present(code):
    dim = DIMENSIONS_BY_CODE[code]
    assert dimension_max(dim, said_na=False) == dim.weight


@pytest.mark.parametrize("code", TRUE_VALUE_SPLIT_CODES)
def test_dimension_max_split_dimension_rescales_to_seen_when_said_na(code):
    dim = DIMENSIONS_BY_CODE[code]
    assert dimension_max(dim, said_na=True) == dim.seen_max


def test_dimension_max_defaults_said_na_to_false():
    price_truth = DIMENSIONS_BY_CODE["price_truth"]
    assert dimension_max(price_truth) == price_truth.weight


# ── Detail copy (Stage 25, Part 1, R1) ──────────────────────────────────

def test_every_dimension_has_non_empty_detail_copy():
    # Re-weighting session (Part 1): value_protocols carries 5
    # how_measured entries (schema_resolution/version_currency split
    # out of a former compound check) — the upper bound moved 4 -> 5.
    for d in DIMENSIONS:
        assert isinstance(d.what_it_is, str) and d.what_it_is, d.code
        assert isinstance(d.how_measured, tuple) and 2 <= len(d.how_measured) <= 5, d.code
        assert all(isinstance(c, str) and c for c in d.how_measured), d.code
        assert isinstance(d.how_scored, str) and d.how_scored, d.code


def test_value_protocols_how_measured_has_five_entries_in_check_order():
    vp = DIMENSIONS_BY_CODE["value_protocols"]
    assert len(vp.how_measured) == 5


# ── Verdict gate (Stage 25, Part 5, G1) ─────────────────────────────────

def test_verdict_thresholds_match_spec():
    assert VERDICT_COMPOSITE_THRESHOLD == 60
    assert VERDICT_TRUE_VALUE_RATIO_THRESHOLD == 0.25


@pytest.mark.parametrize("composite,tv_earned,tv_max,expected", [
    # High composite, near-zero True Value -> NOT AGENT-READY regardless
    # of composite (the case the whole gate exists for).
    (90, 0, 40, VERDICT_NOT_AGENT_READY),
    (60, 0, 40, VERDICT_NOT_AGENT_READY),
    # Composite below threshold -> NOT AGENT-READY even with full TV.
    (59, 40, 40, VERDICT_NOT_AGENT_READY),
    # Both thresholds cleared -> AGENT-READY.
    (60, 10, 40, VERDICT_AGENT_READY),  # tv_ratio 0.25 exactly clears
    (100, 40, 40, VERDICT_AGENT_READY),
    # tv_ratio just under the threshold -> NOT AGENT-READY.
    (60, 9.9, 40, VERDICT_NOT_AGENT_READY),
])
def test_compute_verdict_decision_table(composite, tv_earned, tv_max, expected):
    assert compute_verdict(composite, tv_earned, tv_max) == expected


def test_compute_verdict_never_raises_on_degenerate_true_value_max():
    assert compute_verdict(100, 0, 0) == VERDICT_NOT_AGENT_READY
    assert compute_verdict(100, 0, None) == VERDICT_NOT_AGENT_READY


def test_compute_verdict_never_raises_on_none_composite():
    assert compute_verdict(None, 40, 40) == VERDICT_NOT_AGENT_READY
