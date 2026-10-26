"""
2T-4 (3): one read per True Value cell.

FL15's True Value (Oct 26, org 12) read "$46.99 · live $46.49 · couldn't
verify (page blocked)", "$47.97 · live $36.18 · couldn't verify", "$49.77 ·
live $49.77 · couldn't verify": the verdict came from runs judged against an
unverifiable read, the live price beside it from a later read of the same page
(the cycle's cached reference refreshed, or supply's newest read).

The rule: a cell shows the read its runs were judged against (the deciding
claim's `reference`, the scorer's ReferenceRow; for a run stored unverifiable
with none, an unreadable read with the scorer's reason), so its price and its
verdict agree; a later read of the page is a second line, `later` ("page read
later: $36.18, Oct 24"). The same on the Overview's products row (`live_later`)
and TrueSync's readback (`later`), which read the cell.

  * build_true_value, an unverifiable read followed by a priced one: the cell
    says unverifiable, and the priced read is the second line;
  * a priced read followed by another price: the judged price and its verdict,
    the later price beside;
  * the same read twice: no second line;
  * through /true-value and /overview on 2P-1's pair, cycle 2's v1 at Amazon
    judged against a blocked read, its cached row read priced three days later;
  * TrueSync's readback: the truth is the judged read, the later one its own line.

2P-1's pair is the fixtures' (console_fixture_2p1), not production's.
"""
import json

from sqlalchemy import text

from app.services import console_read_models as rm
from app.services import console_release as rel
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)

BLOCKED = {'price': None, 'verifiable': False, 'unverifiable_reason': 'page blocked', 'read_status': 'blocked',
           'reference_source': 'honest_fetch', 'method': None, 'observed_at': '2026-10-23T14:00:00+00:00'}
LATER = {'variant_ref': 'v1', 'gtin': None, 'sku': 'v1', 'variant_label': 'Size 1, 96 ct',
         'retailer_domain': 'amazon.com', 'price': '36.18', 'currency': 'USD', 'verifiable': True,
         'observed_at': '2026-10-24T14:00:00+00:00', 'reference_source': 'honest_fetch', 'method': 'json_ld'}


def _run(n, stated, outcome, judged):
    return {'variant_id': 'v1', 'gtin': None, 'retailer': 'amazon.com', 'outcome': outcome, 'stated': stated,
            'judged': judged, 'run': f'run-{n}', 'agent': 'chatgpt', 'surface': 'grounded_api'}


def _cell(runs, row=LATER):
    tv = rm.build_true_value({'prices': [row]}, runs, own_domain='pampers.com', record_variants=[])
    return tv['rows'][0]['cells']['amazon.com'] if 'amazon.com' in tv['rows'][0]['cells'] else \
        tv['rows'][0]['retailer_cells']['amazon.com']


def test_an_unverifiable_read_then_a_priced_one():
    cell = _cell([_run(1, '47.97', 'unverifiable', BLOCKED), _run(2, '46.99', 'unverifiable', BLOCKED)])
    assert (cell['live'], cell['status'], cell['observed_at']) == ('unverifiable', 'unverifiable', BLOCKED['observed_at'])
    assert cell['later'] == {'live': '$36.18', 'observed_at': LATER['observed_at'],
                             'text': 'page read later: $36.18, Oct 24'}


def test_a_run_stored_unverifiable_with_no_read_is_judged_unreadable():
    judged = rm.judged_read(None, 'unverifiable', 'no reference row for this page')
    assert judged['verifiable'] is False and judged['unverifiable_reason'] == 'no reference row for this page'
    cell = _cell([_run(1, '46.99', 'unverifiable', judged)])
    assert (cell['live'], cell['status'], cell['later']['text']) == ('unverifiable', 'unverifiable',
                                                                     'page read later: $36.18, Oct 24')


def test_a_priced_read_then_another_price():
    judged = {**LATER, 'price': '47.97', 'observed_at': '2026-10-23T14:00:00+00:00'}
    cell = _cell([_run(1, '47.97', 'exact', judged)])
    assert (cell['live'], cell['status'], cell['quoted']) == ('$47.97', 'exact', '$47.97')
    assert cell['later']['text'] == 'page read later: $36.18, Oct 24'


def test_the_same_read_has_no_second_line():
    cell = _cell([_run(1, '36.18', 'exact', dict(LATER))])
    assert (cell['live'], cell['status']) == ('$36.18', 'exact') and 'later' not in cell
    # a run that carries no read (scored against the record, or before the scorer stored one): the cell's own
    cell = _cell([_run(1, '36.18', 'exact', None)])
    assert (cell['live'], cell['status']) == ('$36.18', 'exact') and 'later' not in cell


def test_a_later_line_only_for_a_later_read():
    earlier = {**LATER, 'observed_at': '2026-10-20T14:00:00+00:00'}
    cell = _cell([_run(1, '47.97', 'unverifiable', BLOCKED)], row=earlier)
    assert cell['live'] == 'unverifiable' and 'later' not in cell


# ── through the endpoints ─────────────────────────────────────────────────

def _blocked_then_priced(db):
    """Cycle 2's v1 at Amazon: every run judged against a blocked read on Oct 23, the cached row read
    priced on Oct 24 (as a refresh after scoring leaves it)."""
    with db.begin() as c:
        runs = c.execute(text("""SELECT o.run_id, o.claim_results FROM soa_expectation_outcomes o
                                 JOIN soa_queries q ON q.id = o.query_id
                                 WHERE o.cycle_id = :c AND q.query_text LIKE '%Size 1, 96 ct cost at amazon.com%'"""),
                         {'c': f2p1.ID_2}).mappings().all()
        for r in runs:
            claims = [{**cl, 'outcome': 'unverifiable', 'reference': dict(BLOCKED)}
                      for cl in rm._json(r['claim_results']) or []]
            c.execute(text("UPDATE soa_expectation_outcomes SET outcome = 'unverifiable', claim_results = :cl, "
                           "outcome_reason = 'page blocked' WHERE run_id = :r"),
                      {'cl': json.dumps(claims), 'r': r['run_id']})
        ref = rm._json(c.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :c"),
                                 {'c': f2p1.ID_2}).scalar())
        for row in ref['prices']:
            if row.get('sku') == 'v1' and row.get('retailer_domain') == 'amazon.com':
                row.update(price='36.18', observed_at='2026-10-24T14:00:00+00:00', verifiable=True)
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = :c"),
                  {'p': json.dumps(ref), 'c': f2p1.ID_2})
    return len(runs)


def test_true_value_and_the_products_row(http, db, upstream):
    _pair(db, http, upstream)
    assert _blocked_then_priced(db) > 0
    tv = _get(http, 'true-value', merchant=WS)
    row = next(r for r in tv['rows'] if r['variant_id'] in ('feed_sku:v1', 'v1'))
    cell = (row.get('retailer_cells') or row['cells'])['amazon.com']
    assert (cell['live'], cell['status']) == ('unverifiable', 'unverifiable')
    assert cell['later']['text'] == 'page read later: $36.18, Oct 24'
    overview = _get(http, 'overview', merchant=WS)
    (product,) = [p for p in overview['by_surface']['all']['products'] if p['name'] == 'Size 1, 96 ct']
    # a row read across its retailers: Amazon's half is the judged read, its later read its own line
    assert product['live'] == '$27.97 at walmart.com, our own fetch, Oct 21. Could not be read at amazon.com'
    assert product['live_later'] == 'Amazon: page read later: $36.18, Oct 24'
    amazon = next(r for r in product['retailers'] if r['retailer'] == 'amazon.com')
    assert (amazon['live_price'], amazon['live_later']) == ('unverifiable', 'page read later: $36.18, Oct 24')


def test_truesyncs_readback_reads_the_judged_read():
    judged = {**LATER, 'price': '47.97', 'observed_at': '2026-10-23T14:00:00+00:00'}
    tv = rm.build_true_value({'prices': [LATER]}, [_run(1, '47.97', 'exact', judged)], own_domain='pampers.com',
                             record_variants=[])
    variants = [{'variant_id': 'v1', 'sku': 'v1', 'label': 'Size 1, 96 ct', 'product_name': 'Pampers Swaddlers'}]
    lines = rel.readback(variants, attribute_answers=[], true_value_rows=tv['rows'], promo=None, deals=None,
                         brand='Pampers')
    (line,) = [l for l in lines if l['fact'] == 'price']
    assert (line['said'], line['truth'], line['verdict']) == ('Amazon $47.97', 'Amazon $47.97', 'right')
    assert line['later'] == 'page read later: $36.18, Oct 24'
