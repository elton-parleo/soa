"""
2T-5 (Accessibility): the demo's Accessibility for a brand at retail.

  AC1, AC3  2T-4 (4)'s six brand-page checks, the retailer checks apart, the
            hero from the data: confirmed served, read here
  AC2       the identity list is supply config: soa serves the identities
            supply's access run requested, `identities.missing` the demo's it
            did not (ClaudeBot, GPTBot, OAI-SearchBot, Google-Extended on
            FL15's run)
  AC6       `rivals` null, `rivals_reason` "no access reads of rival domains"

On supply #33's RECORDED access, feed, reference and retailer-prices
responses (2T-1 harness). No production read, no model call.
"""
from app.services import console_measure as measure
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape


def _acc(db, http, upstream):
    _shape(db, http, upstream)
    upstream.answer('GET', f'{f2r2.BASE}/reference', body=f2r2.body('reference'), token=f2r2.TOKEN_A)
    return _read(http, 'accessibility')


def test_the_six_checks_the_retailer_checks_and_the_hero_are_served(http, db, upstream):
    body = _acc(db, http, upstream)
    assert [c['key'] for c in body['checks']] == ['robots', 'html', 'product_group', 'prices', 'gtin', 'weight']
    assert body['retailer_checks'] and body['hero']['text'].startswith(body['hero']['lead'])


def test_the_identities_supply_ran_and_the_demos_it_did_not(http, db, upstream):
    body = _acc(db, http, upstream)
    ids = body['identities']
    assert ids['served'] == [r['identity'] for r in body['requests']]
    assert ids['missing'] == [n for n, _v in measure.DEMO_IDENTITIES
                              if n.lower() not in {s.split(' (')[0].lower() for s in ids['served']}]
    for name in ('ClaudeBot', 'GPTBot', 'Google-Extended'):
        assert name in ids['missing']
    assert ids['note'] == measure.IDENTITY_GAP_NOTE


def test_fl15s_identity_gap():
    """The finding's gap (ClaudeBot, GPTBot, OAI-SearchBot, Google-Extended not requested), DERIVED as a
    request log of the rest: the order is the demo's."""
    served = [{'identity': i} for i in ('ChatGPT-User', 'Googlebot', 'PerplexityBot', 'Bingbot', 'Claude-User',
                                        'ParleoAuditBot (control)')]
    assert measure.identities(served)['missing'] == ['GPTBot', 'OAI-SearchBot', 'Google-Extended', 'ClaudeBot']
    assert measure.identities([{'identity': n} for n, _v in measure.DEMO_IDENTITIES])['note'] is None


def test_no_rivals_table_until_rival_domains_are_read(http, db, upstream):
    body = _acc(db, http, upstream)
    assert body['rivals'] is None and body['rivals_reason'] == 'no access reads of rival domains'
