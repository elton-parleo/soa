"""
Stage 16 (Part 1, R3): parity tests for soa_shared/scan_dimensions.py —
the v3 three-pillar registry. A rubric change that touches only one
side (registry vs. the functions that consume it) fails here instead
of silently drifting, the same discipline as Stage 14's status-parity
tests.

This file covers the registry's OWN internal shape (pillar sums,
seen/said splits, band-table declarations, the composite formula).
The cross-module "every registry code has a scoring implementation"
check is added once apps/pipeline/scan/scorer.py's v3 dimension
functions exist (Stage 16 Parts 2/3) — see test_scorer.py.
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
    apply_count_band,
    apply_rate_band,
    applicable_max,
    compute_composite,
    dimension_max,
)
import soa_shared.scan_dimensions as scan_dimensions


def test_scorer_version_is_3():
    assert SCORER_VERSION == "3"


def test_pillar_weights_sum_to_spec():
    assert PILLAR_WEIGHTS[PILLAR_VISIBILITY] == 40
    assert PILLAR_WEIGHTS[PILLAR_ACCESSIBILITY] == 20
    assert PILLAR_WEIGHTS[PILLAR_TRUE_VALUE] == 40
    assert TOTAL_MAX == 100
    assert sum(PILLAR_WEIGHTS.values()) == TOTAL_MAX


def test_pillar_order_covers_every_pillar_exactly_once():
    assert set(PILLAR_ORDER) == set(PILLAR_WEIGHTS.keys())
    assert len(PILLAR_ORDER) == len(set(PILLAR_ORDER))


def test_dimension_order_matches_dimensions_and_has_no_duplicates():
    assert DIMENSION_ORDER == tuple(d.code for d in DIMENSIONS)
    assert len(DIMENSION_ORDER) == len(set(DIMENSION_ORDER)) == 8


def test_every_dimension_weight_sums_correctly_within_its_pillar():
    for pillar in PILLAR_ORDER:
        dims = [d for d in DIMENSIONS if d.pillar == pillar]
        assert sum(d.weight for d in dims) == PILLAR_WEIGHTS[pillar]


@pytest.mark.parametrize("code,expected_weight", [
    ("share_of_mentions", 25),
    ("recommendation_strength", 15),
    ("agent_access", 6),
    ("catalog_context", 8),
    ("protocol_feed", 6),
    ("price_truth", 14),
    ("member_value", 19),
    ("deal_citability", 7),
])
def test_dimension_weights_match_spec(code, expected_weight):
    assert DIMENSIONS_BY_CODE[code].weight == expected_weight


def test_only_true_value_dimensions_have_a_seen_said_split():
    true_value_codes = {"price_truth", "member_value", "deal_citability"}
    for d in DIMENSIONS:
        if d.code in true_value_codes:
            assert d.has_seen_said_split, f"{d.code} should have a seen/said split"
            assert d.pillar == PILLAR_TRUE_VALUE
        else:
            assert not d.has_seen_said_split, f"{d.code} should NOT have a seen/said split"


def test_seen_plus_said_equals_dimension_weight():
    for d in DIMENSIONS:
        if d.has_seen_said_split:
            assert d.seen_max + d.said_max == d.weight, d.code


@pytest.mark.parametrize("code,seen,said", [
    ("price_truth", 6, 8),
    ("member_value", 12, 7),
    ("deal_citability", 4, 3),
])
def test_seen_said_split_matches_spec(code, seen, said):
    d = DIMENSIONS_BY_CODE[code]
    assert d.seen_max == seen
    assert d.said_max == said


def test_every_said_sublens_declares_opportunity_set_and_band_type():
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
    (1, 0.60),
    (2, 1.0),
    (5, 1.0),
    (None, 0.0),
])
def test_apply_count_band_edges(count, expected_fraction):
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
    assert applicable_max(member_value_na=True) == 81  # 100 - 19


def test_compute_composite_full_scoring():
    assert compute_composite(100, member_value_na=False) == 100
    assert compute_composite(50, member_value_na=False) == 50
    assert compute_composite(0, member_value_na=False) == 0


def test_compute_composite_na_normalization():
    assert compute_composite(81, member_value_na=True) == 100
    assert compute_composite(0, member_value_na=True) == 0
    # 40 of 81 applicable points -> ~49%
    assert compute_composite(40, member_value_na=True) == round(40 / 81 * 100)


def test_compute_composite_never_raises_on_degenerate_basis(monkeypatch):
    monkeypatch.setattr(scan_dimensions, "TOTAL_MAX", 0)
    assert compute_composite(0, member_value_na=False) == 0


def test_perturbation_changing_member_value_weight_moves_applicable_max_and_composite(monkeypatch):
    """
    Part 7, A3: nothing about the /81 normalization is hard-coded — it's
    TOTAL_MAX minus member_value's registered weight, read fresh at call
    time. Perturb ONLY member_value's weight (TOTAL_MAX untouched) and
    confirm applicable_max/compute_composite move to a DIFFERENT number
    than the spec's 81, proving the formula — not a baked-in constant —
    drives the result.
    """
    perturbed_member_value = dataclasses.replace(
        scan_dimensions.DIMENSIONS_BY_CODE["member_value"], weight=29,
    )
    monkeypatch.setattr(
        scan_dimensions, "DIMENSIONS_BY_CODE",
        {**scan_dimensions.DIMENSIONS_BY_CODE, "member_value": perturbed_member_value},
    )

    assert applicable_max(member_value_na=True) == 71  # 100 - 29, not the spec's 81
    assert applicable_max(member_value_na=False) == 100  # unaffected when member_value IS scored
    assert compute_composite(71, member_value_na=True) == 100
    assert compute_composite(35.5, member_value_na=True) == 50


# ── Per-dimension seen/said rescale (Part 3, T2) ────────────────────────

def test_dimension_max_no_split_dimension_ignores_said_na():
    agent_access = DIMENSIONS_BY_CODE["agent_access"]
    assert dimension_max(agent_access, said_na=False) == agent_access.weight
    assert dimension_max(agent_access, said_na=True) == agent_access.weight


@pytest.mark.parametrize("code", ["price_truth", "member_value", "deal_citability"])
def test_dimension_max_split_dimension_full_weight_when_said_present(code):
    dim = DIMENSIONS_BY_CODE[code]
    assert dimension_max(dim, said_na=False) == dim.weight


@pytest.mark.parametrize("code", ["price_truth", "member_value", "deal_citability"])
def test_dimension_max_split_dimension_rescales_to_seen_when_said_na(code):
    dim = DIMENSIONS_BY_CODE[code]
    assert dimension_max(dim, said_na=True) == dim.seen_max


def test_dimension_max_defaults_said_na_to_false():
    price_truth = DIMENSIONS_BY_CODE["price_truth"]
    assert dimension_max(price_truth) == price_truth.weight
