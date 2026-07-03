"""
Tests for scoring/observation_scorer.py's merchant resolution logic —
the four-way attribution_status dispatch plus the "contrary retailer
signal" fallback rule. Pure logic, no DB/API needed for _resolve_merchant.
"""
from types import SimpleNamespace

from scoring.observation_scorer import ObservationScorer

SLUG_BY_MERCHANT_ID = {80: "pampers", 6: "target"}


def _obs(attribution_status, merchant_slug=None):
    return SimpleNamespace(attribution_status=attribution_status, merchant_slug=merchant_slug)


def _entity(merchant_id=None):
    return SimpleNamespace(merchant_id=merchant_id)


def test_mapped_resolves_directly():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("mapped", "target"), _entity(), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug == "target"
    assert status == ""


def test_unmapped_skips_with_no_merchant_mapping_status():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unmapped"), _entity(), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "no_merchant_mapping"


def test_brand_self_reference_skips():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("brand_self_reference"), _entity(), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "skipped"


def test_unattributed_with_no_entity_merchant_configured_skips():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=None), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "skipped"


def test_unattributed_falls_back_when_no_contrary_signal():
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=80), set(), SLUG_BY_MERCHANT_ID,
    )
    assert slug == "pampers"
    assert status == ""


def test_unattributed_does_not_fall_back_with_contrary_signal():
    # Same run has a confidently-mapped OTHER retailer -> too risky to
    # assume the entity's own brand site for this ambiguous observation.
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=80), {"target"}, SLUG_BY_MERCHANT_ID,
    )
    assert slug is None
    assert status == "skipped"


def test_unattributed_falls_back_when_contrary_signal_is_the_same_merchant():
    # The only "mapped" observation in this run IS the entity's own brand
    # site — not actually a contrary signal.
    slug, status = ObservationScorer._resolve_merchant(
        _obs("unattributed"), _entity(merchant_id=80), {"pampers"}, SLUG_BY_MERCHANT_ID,
    )
    assert slug == "pampers"
    assert status == ""
