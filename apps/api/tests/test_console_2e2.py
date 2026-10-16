"""
2E-2: two score-tile bugs from cycle 229.

Deal Citability's seen evidence read "member price 19 of 19 pages: yes · promo
19 of 19 pages: yes". The payload here is #114's retailer-prices shape
(`prices`, apps/pipeline/tests/test_domain_checks_pdp.py ws_payload), each
row's offer_text and incentive_in_markup computed by supply's own
parse.offer_text and incentive.incentive_in_markup (parleo-supply-app ef3c267)
from the store's announcement bar ("Free shipping on orders of $35 or more ·
30-day returns · Members earn …", truesync-demo-store SiteChrome.tsx) with a
JSON-LD half of member_price only. Supply serves a flag as the JSON-LD half OR
a text half read from offer_text, so the bar sets promo (and member_price) on
every page: soa printed what supply served. The fix: a page counts as carrying
an incentive in markup only when a flag is true AND supply says it came from
structured data, and a flag true on pages that carry offer_text says the page
text is included.

The verdict: soa computed it in the all-measured case (scan_dimensions.
compute_verdict); the tile did not render it (the console half of 2E-2).
"""
import copy

import pytest

from app.services import console_score as score_svc
from soa_shared.scan_dimensions import VERDICT_AGENT_READY, VERDICT_NOT_AGENT_READY, compute_verdict
from tests.test_console_read_models import _fixture

BAR = _fixture('supply_retailer_prices_229_bar.json')


def _rows(payload=BAR):
    return copy.deepcopy(payload['prices'])


def test_the_fixture_is_supplys_shape_and_supplys_flags():
    assert 'rows' not in BAR and len(BAR['prices']) == 19
    m = BAR['prices'][0]['incentive_in_markup']
    # what 229's reads serve: promo true from the bar's "Free shipping", source json_ld from the member price
    assert m == {'member_price': True, 'promo': True, 'subscription': False, 'code': False, 'source': 'json_ld',
                 'json_ld_scanned': True}
    assert BAR['prices'][0]['offer_text'].startswith('Free shipping on orders of $35 or more')


def test_229s_seen_half_is_19_of_19_on_the_member_price_in_markup():
    crawl = score_svc.crawl_counts(None, _rows())
    part = score_svc.deal_seen_part(crawl, 'x')
    assert (part['numerator'], part['denominator'], part['score']) == (19, 19, 7.0)
    assert part['line'] == 'Incentive in markup 19 of 19 pages'


def test_each_flag_reads_its_value_and_says_when_the_page_text_is_included():
    part = score_svc.deal_seen_part(score_svc.crawl_counts(None, _rows()), 'x')
    assert [(c['label'], c['state']) for c in part['checks']] == [
        ('member price 19 of 19 pages, the page text included', 'pass'),
        ('promo 19 of 19 pages, the page text included', 'pass'),
        ('subscription 0 of 19 pages', 'fail'),
        ('code 0 of 19 pages', 'fail')]


def test_a_flag_that_is_false_reads_no_whatever_keys_the_row_carries():
    rows = _rows()
    for r in rows:
        r['offer_text'] = None
        r['incentive_in_markup'] = {**r['incentive_in_markup'], 'promo': False}
    part = score_svc.deal_seen_part(score_svc.crawl_counts(None, rows), 'x')
    assert [(c['label'], c['state']) for c in part['checks']][:2] == [
        ('member price 19 of 19 pages', 'pass'), ('promo 0 of 19 pages', 'fail')]


def test_a_page_whose_flags_come_from_its_text_alone_does_not_count():
    """No JSON-LD flag, only the bar: supply serves source 'text'. Not an
    incentive in markup, so not in the seen count; still in its denominator."""
    rows = _rows()
    for r in rows[:5]:
        r['incentive_in_markup'] = {**r['incentive_in_markup'], 'source': 'text'}
    crawl = score_svc.crawl_counts(None, rows)
    assert (crawl['incentive_any'], crawl['incentive_scanned']) == (14, 19)
    assert crawl['incentive_flags']['promo'] == 19          # what supply serves, read as served


def test_every_flag_false_is_not_an_incentive():
    rows = _rows()
    for r in rows:
        r['incentive_in_markup'] = {'member_price': False, 'promo': False, 'subscription': False, 'code': False,
                                    'source': 'json_ld', 'json_ld_scanned': True}
    assert score_svc.crawl_counts(None, rows)['incentive_any'] == 0


def test_the_adapter_revision_moves_so_stored_scores_recompute():
    """A score stored under 2E's rule reads stale and is recomputed (kept in
    its history) on its next read."""
    stored = {'scorer_version': score_svc.SCORER_VERSION, 'adapter_revision': 2, 'measured': []}
    assert score_svc.ADAPTER_REVISION == 3
    assert score_svc.needs_recompute(stored, None) == 'stale'


# ═══ the verdict ═════════════════════════════════════════════════════════

@pytest.mark.parametrize('score, tv, unmeasured, expected', [
    (72, {'score': 20.0, 'applicable_max': 50.0}, 0, VERDICT_AGENT_READY),        # at the bar, True Value 40%
    (72, {'score': 10.0, 'applicable_max': 50.0}, 0, VERDICT_NOT_AGENT_READY),    # at the bar, True Value 20%
    (28, {'score': 22.1, 'applicable_max': 50.0}, 0, VERDICT_NOT_AGENT_READY),    # 229, all measured
    (49, {'score': 30.0, 'applicable_max': 50.0}, 12, None),                       # 12 points not measured
    (None, None, 0, None),
])
def test_the_verdict_is_the_audits_in_the_measured_case_only(score, tv, unmeasured, expected):
    assert score_svc.verdict(score, tv, unmeasured) == expected
    if expected is not None:
        assert expected == compute_verdict(score, tv['score'], tv['applicable_max'])
