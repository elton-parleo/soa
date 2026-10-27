"""
2T-8 (B4, B5): the Fix queue and Approvals of a brand at retail, derived from
what exists (the Overview's ranked signals, supply's rules, the hold and its
journal, the brand stated sent, the GTIN rows). No table: owner, due, team and
condition are None.

On the 2T-1 harness (2P-1's pair with supply #33's answers RECORDED), and
FL15-shaped rule and hold states built here in supply's served shape
(rules.json's own rows with their approval, `on` and history changed), each
saying so. No model call, no production read.
"""
import copy
import json
import os

import pytest

from app.services import console_fixes as fx
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape

HOLD_AT = '2026-10-25T22:02:33+00:00'


def _dump(name, body):
    out = os.environ.get('SOA_2T8_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _rules(**changes):
    """rules.json's six as recorded, with `changes` {code: {approval, on, history}} applied (DERIVED)."""
    rules = copy.deepcopy(f2r2.body('rules'))
    for r in rules['rules']:
        r.update(changes.get(r['code'], {}))
    return rules


def _on(at):
    return {'approval': 'approved', 'on': True, 'approved_at': at,
            'history': [{'actor': 'op@test', 'at': at, 'changes': {'approval': ['needs_approval', 'approved'],
                                                                   'on': [False, True]}}]}


# ── the state rules ───────────────────────────────────────────────────────

@pytest.mark.parametrize('rule, state', [
    (None, 'needs_decision'),
    ({'approval': 'needs_approval', 'on': False}, 'needs_decision'),
    ({'approval': 'approved', 'on': False}, 'needs_decision'),
    ({'approval': 'declined', 'on': False}, 'needs_decision'),
    (_on('2026-10-26T09:00:00'), 'in_flight'),     # on after the newest hold
    (_on('2026-10-25T08:00:00'), 'shipped'),       # a hold after the rule came on
])
def test_a_gated_fix_s_state(rule, state):
    pubs = [{'compiled_at': HOLD_AT, 'status': 'compiled_not_published', 'reason': 'held_for_merchant'}]
    assert fx.gated_state(rule, pubs) == state


def test_each_source_and_its_state():
    """The FL15 shape: a size-chart, retired and club-only signal, the markup's 11-digit GTINs, a held release."""
    signals = [
        {'id': 'size_chart', 'kind': 'size_chart', 'pool': 'missed', 'tone': 'bad', 'count': 14,
         'facts': {'two': [{'size': 'Size 4', 'groups': [
             {'range': '15 to 34 lb', 'lines': ['Swaddlers', 'Baby-Dry', 'AMORE', 'Ultra']},
             {'range': '22 to 37 lb', 'lines': ['Cruisers 360', 'Zzz']}]}]}},
        {'id': 'retired', 'kind': 'retired', 'pool': 'lost', 'tone': 'bad', 'count': 10,
         'facts': {'retired': 'Pure', 'successor': 'AMORE', 'n': 10, 'of': 29}},
        {'id': 'store', 'kind': 'store', 'pool': 'missed', 'tone': 'warn', 'count': 3,
         'facts': {'line_label': 'Swaddlers Ultra Day + Night', 'clubs': ['Costco', "Sam's Club", "BJ's"],
                   'elsewhere': 3, 'answers': 9, 'stores': ['Walmart']}},
    ]
    drift = [{'field': 'zzz.size_4.weight (markup)', 'was': '15 to 34 lb', 'now': '22 to 37 lb', 'kind': 'markup'},
             {'field': 'cruisers_360.size_3.weight (markup)', 'was': '13 to 26 lb', 'now': '16 to 28 lb', 'kind': 'markup'}]
    gtins = [{'where': 'markup', 'line': 'AMORE', 'digits': 11, 'was': '30772244425'},
             {'where': 'markup', 'line': 'Swaddlers Ultra', 'digits': 11, 'was': '30772098141'}]
    pubs = [{'compiled_at': HOLD_AT, 'status': 'compiled_not_published', 'reason': 'held_for_merchant', 'journal': []}]
    feed = [{'product_name': f'Pampers {l}', 'variant_label': 'Size 4'} for l in
            ('Swaddlers', 'Baby-Dry', 'AMORE', 'Swaddlers Ultra', 'Cruisers 360', 'Zzz')] + \
        [{'product_name': 'Pampers Swaddlers', 'variant_label': 'Newborn'} for _ in range(4)] + \
        [{'product_name': 'Pampers Pure Protection', 'variant_label': 'Size 1', 'lifecycle': 'retired'}]
    rules = _rules(r6=_on('2026-10-20T00:00:00'))['rules']
    body = fx.build_fixes(signals=signals, rules=rules, pubs=pubs, feed_rows=feed, drift=drift, gtin_rows=gtins,
                          twice=[], values={'lost': 0.3, 'missed': 0.26}, brand='Pampers', domain='pampers.com',
                          records=10, skus=10)
    fixes = {f['kind']: f for f in body['fixes']}
    assert [(f['n'], f['kind']) for f in body['fixes']] == [
        (1, 'release'), (2, 'retired'), (3, 'size_chart'), (4, 'store'), (5, 'gtin'), (6, 'deals')]
    assert (fixes['size_chart']['state'], fixes['size_chart']['scope'], fixes['size_chart']['severity']) == (
        'needs_decision', '6 lines, 10 SKUs', 'High')
    assert fixes['size_chart']['text'] == (
        "Swaddlers, Baby-Dry, AMORE and Ultra Size 4: 15 to 34 lb. Cruisers 360 and Zzz Size 4: 22 to 37 lb. Start "
        "with pampers.com's own markup, where Zzz says 15 to 34 for Size 4 and Cruisers 360 says 13 to 26 for Size 3, "
        "then the record retailers receive.")
    assert (fixes['retired']['title'], fixes['retired']['state']) == ('Retire Pure, with AMORE as the successor', 'shipped')
    assert (fixes['store']['title'], fixes['store']['severity']) == ('Show Swaddlers Ultra Day + Night as club only', 'Quick')
    assert fixes['gtin']['text'] == ("Every AMORE and Swaddlers Ultra GTIN drops the leading zero. Pampers' web team "
                                     "fixes it on pampers.com.")
    assert (fixes['release']['state'], fixes['release']['state_label'], fixes['release']['text']) == (
        'in_flight', 'Compiled, held', "10 records compiled in manufacturer mode, no price, every retailer shown the same "
        "way. Pampers' own team sends it.")
    assert (fixes['deals']['state'], fixes['deals']['title']) == (
        'needs_decision', 'Publish Pampers-funded deals retailer-neutral, with dates')
    assert all(f['owner'] is None and f['due'] is None for f in body['fixes'])
    s = body['summary']
    assert s['hero'] == '4 of 6 fixes need a decision. First up: One size chart per line, on every surface.'
    assert s['by_state'] == {'needs_decision': 4, 'in_flight': 1, 'queued': 0, 'shipped': 1}
    assert s['by_pool'] == {'missed': 4, 'lost': 1, 'both': 1}
    # sent: the release ships; r4 approved and off: queued
    sent = [{**pubs[0], 'journal': [{'event': 'sent_by_merchant', 'sent_at': '2026-10-26T10:00:00Z',
                                     'stated_by': 'Dana', 'channel': 'manufacturer_center'}]}]
    rules = _rules(r4={'approval': 'approved', 'on': False})['rules']
    again = {f['kind']: f for f in fx.build_fixes(
        signals=signals, rules=rules, pubs=sent, feed_rows=feed, drift=drift, gtin_rows=gtins, twice=[],
        values={'lost': 0.3, 'missed': 0.26}, brand='Pampers', domain='pampers.com', records=10, skus=10)['fixes']}
    assert (again['release']['state'], again['deals']['state']) == ('shipped', 'queued')


# ── end to end, and the write path ────────────────────────────────────────

def test_the_queue_and_the_requests_as_served(http, db, upstream):
    _shape(db, http, upstream)
    fixes = _read(http, 'fixes')
    _dump('fixes-2t8.json', fixes)
    assert [f['kind'] for f in fixes['fixes']] == ['release', 'retired', 'deals', 'size_chart']
    values = [f['value'] for f in fixes['fixes']]
    assert values == sorted(values, reverse=True)
    approvals = _read(http, 'approvals')
    _dump('approvals-2t8.json', approvals)
    assert [(r['code'], r['state']) for r in approvals['requests']] == [
        ('r6', 'pending'), ('r4', 'pending'), ('r5', 'pending'), ('release', 'held')]
    assert approvals['summary']['hero'] == '3 of 4 requests waiting. Retired products carry a successor waits on approval.'
    assert all(r['team'] is None and r['condition'] is None for r in approvals['requests'])
    assert approvals['chains'][0] == {'change': 'Price or program price', 'team': None}
    assert _read(http, 'fixes', merchant=f2r2.PAIR_SLUG, status=404)


@pytest.mark.parametrize('decision, rule, state', [
    ('approve', _on('2026-10-26T09:00:00'), 'in_flight'),
    ('return', {'approval': 'declined', 'on': False}, 'needs_decision'),
])
def test_approve_and_return_go_through_put_rules(decision, rule, state, http, db, upstream):
    _shape(db, http, upstream)
    upstream.answer('PUT', f'{f2r2.BASE}/rules/r5', body={'code': 'r5'}, token=TOKEN_A)
    # supply's re-read after the write, as the PUT left it (DERIVED on rules.json)
    upstream.answer('GET', f'{f2r2.BASE}/rules', body=_rules(r5=rule), token=TOKEN_A)
    as_('op')
    r = http.post('/api/console/approvals/r5', params={'merchant': f2r2.SLUG, 'org': 10},
                  json={'decision': decision, 'note': 'Counsel read it'})
    assert r.status_code == 200, r.text
    put = next(c for c in upstream.calls if c['method'] == 'PUT')
    assert put['json'] == ({'approval': 'approved', 'on': True, 'note': 'Counsel read it', 'actor': 'op@test'}
                           if decision == 'approve' else
                           {'approval': 'declined', 'on': False, 'note': 'Counsel read it', 'actor': 'op@test'})
    assert next(x for x in r.json()['requests'] if x['code'] == 'r5')['state'] == \
        ('approved' if decision == 'approve' else 'returned')
    size = next(f for f in _read(http, 'fixes')['fixes'] if f['kind'] == 'size_chart')
    assert size['state'] == state


def test_the_release_has_no_write_and_members_cannot_decide(http, db, upstream):
    _shape(db, http, upstream)
    as_('op')
    r = http.post('/api/console/approvals/release', params={'merchant': f2r2.SLUG, 'org': 10},
                  json={'decision': 'approve'})
    assert r.status_code == 409
    as_('alice')
    r = http.post('/api/console/approvals/r5', params={'merchant': f2r2.SLUG}, json={'decision': 'approve'})
    assert r.status_code == 403
