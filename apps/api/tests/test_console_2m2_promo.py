"""
2M-2: promo pass-through, sqlite and Postgres.

The FL13 shape (2K-4's _fl13_shape) with 10 cheapest-place questions and 2
where-to-buy questions added (brand-direct, source_ref.intent, as
catalog_tiers.build_intent_questions writes them), one run per agent, AI
Mode unanswered: 5 answers each. Supply's /deals (parleo-supply-app 2M-2)
carries three live deals:

  Amazon multi-buy   "Save 40% on 1 when you buy 2", on v0 to v4 ($47.99 on v0)
  Walmart Rollback   $49.77, was $59.77, on v5 and v6
  Sam's Club         "$15 Sam's Cash on $100 of P&G", Sam's Cash, on v7
  v8, v9             no deal. Target walled every read.

Cheapest place, by hand (N named, L loose, S subscribe):
  v0  "Amazon … when you buy 2 you save 40% on one"            N L
      "Amazon sells it for $47.99"
      "Walmart … on sale"                                         L
      "At Amazon two boxes come to $76.78" (47.99 + 60% of it)  N
      "Amazon Subscribe & Save brings it to $40.79"               L S
  v1  "Target has 40% off this week" (not the deal's retailer)    L
      three plain, one "with auto-delivery"                       S
  v2  five plain
  v3  "Amazon … there is a coupon on the page" (not a multi-buy)  L; four plain
  v4  five plain
  v5  "Walmart has a Rollback at $49.77"                         N L
      "Walmart's price is $49.77" (the price without the word Rollback: not counted)
      "Walmart, was $59.77, now $49.77"                          N
      "Amazon at $52.00"
      "Walmart at $49.77, a great deal"                           L
  v6  five "Walmart at $49.77"
  v7  "Sam's Club gives $15 Sam's Cash on $100 of P&G"           N; four plain
  v8  "Amazon at $27.97, with a 5% discount for Prime"            L; four plain
  v9  "Amazon at $27.97 through a subscription"                   S; four plain

  n 50, k 5, loose 8, subscribe 3.
  Per deal: Amazon multi-buy named 2 of 25, Walmart Rollback 2 of 10, Sam's Cash 1 of 5.
  Where to buy (v0, v5): 10 answers, 1 names the multi-buy ("buy 2").
"""
import json
import os

from sqlalchemy import text

from app.services import console_read_models as rm
from soa_shared import promo_pass_through as ppt
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i9 import AGENTS6
from tests.test_console_2k4_comparable import _fl13_shape
from tests.test_console_2l4_routing import _supply
from tests.test_console_read_models import TOKEN_A, WS_TENANT, _encode, as_, http, upstream  # noqa: F401

WS = 'wiggle-and-snug'

PLAIN = 'Amazon at $27.97.'
CHEAPEST = {
    'v0': ["Amazon has it at $47.99, and when you buy 2 you save 40% on one.", "Amazon sells it for $47.99.",
           "Walmart is cheapest at $45.99 and it is on sale.", "At Amazon two boxes come to $76.78.",
           "Amazon Subscribe & Save brings it to $40.79."],
    'v1': ["Target has 40% off this week at $29.99.", PLAIN, PLAIN, "Walmart at $27.97.",
           "Amazon at $27.97 with auto-delivery."],
    'v2': [PLAIN] * 5,
    'v3': ["Amazon at $27.97, and there is a coupon on the page.", PLAIN, PLAIN, PLAIN, PLAIN],
    'v4': [PLAIN] * 5,
    'v5': ["Walmart has a Rollback at $49.77.", "Walmart's price is $49.77.", "Walmart, was $59.77, now $49.77.",
           "Amazon at $52.00.", "Walmart at $49.77, a great deal."],
    'v6': ["Walmart at $49.77."] * 5,
    'v7': ["Sam's Club gives $15 Sam's Cash on $100 of P&G.", "Sam's Club members pay $46.98.", "Costco at $45.99.",
           "Sam's Club at $46.98.", "Sam's Club at $46.98."],
    'v8': ["Amazon at $27.97, with a 5% discount for Prime.", PLAIN, PLAIN, PLAIN, PLAIN],
    'v9': ["Amazon at $27.97 through a subscription.", PLAIN, PLAIN, PLAIN, PLAIN],
}
WHERE = {
    'v0': ["You can buy it at Amazon, and if you buy 2 you save on one.", PLAIN, PLAIN, PLAIN, PLAIN],
    'v5': ["Walmart carries it.", "Walmart and Target.", "Walmart.", "Amazon.", "Target."],
}


def _variant(vid, shelf, price=None, was=None):
    return {'variant_ref': f'feed_sku:{vid}', 'gtin': None, 'sku': vid, 'variant_label': f'{vid}, 84 ct',
            'product_name': f'Pampers Swaddlers {vid}', 'url': f'https://example.com/{vid}', 'reference_read_id': 1,
            'observed_at': '2026-10-14T14:00:00+00:00', 'shelf_price': shelf, 'price': price, 'was_price': was,
            'evidence': 'on the page'}


MULTI = {'retailer_domain': 'amazon.com', 'kind': 'multi_buy', 'text': 'Save 40% on 1 when you buy 2',
         'value': '40.00', 'value_unit': 'percent', 'terms': 'when you buy 2', 'program': None,
         'variants': [_variant('v0', '47.99')] + [_variant(v, '27.97') for v in ('v1', 'v2', 'v3', 'v4')]}
ROLLBACK = {'retailer_domain': 'walmart.com', 'kind': 'rollback_or_was', 'text': 'Rollback', 'value': None,
            'value_unit': None, 'terms': None, 'program': None,
            'variants': [_variant(v, '49.77', '49.77', '59.77') for v in ('v5', 'v6')]}
CASH = {'retailer_domain': 'samsclub.com', 'kind': 'member_cash', 'text': "$15 Sam's Cash on $100 of P&G",
        'value': '15.00', 'value_unit': 'usd', 'terms': 'on $100 of P&G', 'program': "Sam's Cash",
        'variants': [_variant('v7', '46.98')]}
DEALS = {'merchant': WS, 'kind': 'brand', 'as_of': '2026-10-14T23:59:59.999999+00:00', 'read_date': '2026-10-14',
         'deals': [MULTI, CASH, ROLLBACK],
         'retailers': [{'retailer_domain': 'amazon.com', 'rows': 10, 'shelf_seen': 10, 'asked': 10, 'with_deals': 5},
                       {'retailer_domain': 'target.com', 'rows': 10, 'shelf_seen': 0, 'asked': 0, 'with_deals': 0}],
         'walled': ['target.com'], 'partial': []}


def _questions(db):
    """10 cheapest-place and 2 where-to-buy questions, one run per agent (AI Mode unanswered)."""
    with db.begin() as c:
        rid, qid = 98000, 3300
        for intent, verb, plan in (('cheapest_place', 'Cheapest place to buy', CHEAPEST),
                                   ('where_to_buy', 'Where can I buy', WHERE)):
            for vid, texts in plan.items():
                qid += 1
                ref = {'merchant_slug': WS, 'listing_id': 70 + qid % 100, 'variant_id': vid, 'intent': intent}
                c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, study_pattern, "
                               "organization_id, tier, expected_answer, provenance, source_ref) VALUES (:i, :c, :t, "
                               "'Ready to Buy', 'Active', :st, 'brand_at_retail', 1, 'brand_direct', :e, 'catalog', :r)"),
                          {'i': qid, 'c': f'WSP_{qid}', 't': f'{verb} Pampers Swaddlers {vid}?', 'st': f229.STUDY,
                           'e': _encode({'type': 'brand_mention', 'brand': 'Pampers'}), 'r': _encode(ref)})
                answers = iter(texts)
                for platform, surface, collector in AGENTS6:
                    rid += 1
                    answered = platform != 'aimode'
                    c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, raw_response, "
                                   "status, surface, collector, answer_status) VALUES (:r, 229, :q, :p, 1, "
                                   "'2026-10-14T15:00:00+00:00', :t, :s, :surf, :col, :a)"),
                              {'r': rid, 'q': qid, 'p': platform, 't': next(answers) if answered else '',
                               's': 'success' if answered else 'error', 'surf': surface, 'col': collector,
                               'a': 'answered' if answered else None})


def _shape(db, http, upstream, deals=DEALS, status=200):
    _fl13_shape(db, http, upstream)
    _questions(db)
    _supply(upstream)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/deals', status=status, body=deals, token=TOKEN_A)


def _get(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'cycle': f229.CYCLE_229, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _dump(name, body):
    """SOA_2M2_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2M2_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


# ---------------------------------------------------------------------------
# The counts
# ---------------------------------------------------------------------------

def test_the_tile_input_by_hand(http, db, upstream):
    _shape(db, http, upstream)
    overview = _get(http, 'overview', merchant=WS)
    _dump('overview-2m2.json', overview)
    promo = overview['promo_pass_through']
    assert (promo['n'], promo['k'], promo['loose'], promo['subscribe']) == (50, 5, 8, 3)
    assert [(d['short'], d['kind'], d['asked'], d['named']) for d in promo['per_deal']] == [
        ('Amazon multi-buy', 'multi_buy', 25, 2), ('Walmart Rollback', 'rollback_or_was', 10, 2),
        ("Sam's Club Sam's Cash", 'member_cash', 5, 1)]
    assert promo['per_deal'][0]['title'] == 'Amazon: save 40% on 1 when you buy 2'
    assert promo['note'] == 'Cheapest-place answers naming a deal live that day. Amazon multi-buy: named 2 of 25'
    assert promo['where_to_buy']['n'] == 10 and promo['where_to_buy']['k'] == 1
    assert promo['rule'] == ppt.RULE and promo['walled'] == ['target.com'] and promo['read_date'] == '2026-10-14'
    assert sum(c['n'] for c in promo['by_surface'].values()) == 50 and 'judged' not in promo
    # supply was asked for the cycle's read date
    call = next(c for c in upstream.calls if c['path'].endswith('/deals'))
    assert (call.get('params') or {}).get('as_of')


def test_the_rollback_price_without_the_word_is_not_counted():
    live = ppt.live_for(DEALS, {'variant_id': 'v5'})
    assert [d['kind'] for d in live] == ['rollback_or_was']
    assert not ppt.names_deal("Walmart's price is $49.77.", live[0])          # the demo's AI Mode case
    assert ppt.names_deal("Walmart has a Rollback at $49.77.", live[0])
    assert ppt.names_deal("Walmart, was $59.77, now $49.77.", live[0])       # the struck price
    assert not ppt.names_deal("Amazon has a Rollback.", live[0])              # not the deal's retailer
    multi = ppt.live_for(DEALS, {'variant_id': 'v0'})[0]
    assert ppt.names_deal("At Amazon two boxes come to $76.78.", multi)        # the two-box total
    assert ppt.names_deal("Amazon takes 40 percent off one.", multi)
    assert not ppt.names_deal("Amazon has a coupon.", multi)


def test_each_kind_s_named_rule():
    sale = {'retailer_domain': 'kroger.com', 'kind': 'sale', 'variant': {'price': '28.49', 'was_price': '30.49'}}
    coupon = {'retailer_domain': 'bjs.com', 'kind': 'coupon', 'value': '5.00', 'variant': {}}
    cash = {'retailer_domain': 'cvs.com', 'kind': 'member_cash', 'program': 'ExtraBucks', 'variant': {}}
    assert ppt.names_deal('Kroger has it for $28.49.', sale) and not ppt.names_deal('Kroger has it for $30.49.', sale)
    assert ppt.names_deal("BJ's has a $5 coupon.", coupon) and ppt.names_deal("BJ's knocks $5 off.", coupon)
    assert not ppt.names_deal("BJ's has it.", coupon)
    assert ppt.names_deal('CVS gives ExtraBucks on it.', cash) and not ppt.names_deal('CVS rewards members.', cash)
    assert ppt.judge('A great deal, save now', [])['loose'] and not ppt.judge('Buy it at Costco.', [])['loose']
    assert ppt.judge('Subscribe and Save', [])['subscribe']


def test_the_score_tile_is_measured(http, db, upstream):
    _shape(db, http, upstream)
    score = _get(http, 'score', merchant=WS, rescore=1)
    _dump('score-2m2.json', score)
    tile = next(m for m in score['metrics'] if m['key'] == 'promo')
    assert (tile['state'], tile['value'], tile['denominator']) == ('measured', 5, 50)
    assert tile['sub'] == 'Cheapest-place answers naming a deal live that day. Amazon multi-buy: named 2 of 25'
    assert tile['surface_note'] == 'across every agent, cheapest-place answers'
    assert sum(v['of'] for v in tile['by_surface'].values()) == 50
    assert sum(v['value'] for v in tile['by_surface'].values()) == 5


def test_changes_and_the_impact_baseline(http, db, upstream):
    _shape(db, http, upstream)
    block = _get(http, 'overview', merchant=WS)['by_surface']['all']
    (line,) = [c for c in block['changes'] if c.get('metric') == 'promo']
    assert (line['label'], line['delta'], line['now'], line['of_now'], line['route']) == \
        ('Deals named, cheapest-place answers', 'new', 5, 50, 'prove')
    assert line['detail'] == (
        "5 of 50. Named Amazon multi-buy twice, Walmart Rollback twice and Sam's Club Sam's Cash once. Amazon "
        "multi-buy ran on 5 SKUs and 2 of 25 answers named it. First cycle with this question.")
    revenue = _get(http, 'revenue', merchant=WS)
    _dump('revenue-2m2.json', revenue)
    assert revenue['baseline'][-1] == {'key': 'promo', 'label': 'Promo pass-through', 'value': '5 of 50',
                                       'note': 'Named a deal live that day', 'n': 50, 'k': 5}
    assert rm.promo_baseline(None) is None
    assert rm.promo_baseline({'n': 50, 'k': 5}) == {'key': 'promo', 'label': 'Promo pass-through', 'value': '5 of 50',
                                                     'note': 'Named a deal live that day', 'n': 50, 'k': 5}


def test_the_changes_line_takes_a_delta_against_a_compared_cycle():
    now = {'n': 50, 'k': 5, 'per_deal': [], 'by_surface': {}}
    (line,) = rm.promo_changes(now, {'n': 50, 'k': 4, 'per_deal': [], 'by_surface': {}}, 'FL12', 'all', compared=True)
    assert (line['delta'], line['dir'], line['tone'], line['detail']) == ('+1', 'up', 'ok', '5 of 50 this cycle against 4 of 50 in FL12.')
    assert rm.promo_changes(None, None, None, 'all', compared=False) == []


# ---------------------------------------------------------------------------
# Prove: the Trade promotions screen
# ---------------------------------------------------------------------------

def test_the_trade_promotions_table(http, db, upstream):
    _shape(db, http, upstream)
    body = _get(http, 'prove', merchant=WS)
    _dump('prove-2m2.json', body)
    assert body['state'] == 'measured' and body['title'] == 'Trade promotions'
    assert [(r['title'], r['agents'], r['value'], r['terms'], r['tone']) for r in body['rows']] == [
        ('Amazon: save 40% on 1 when you buy 2', 'Named 2 of 25', '40% off', 'Amazon, when you buy 2', 'warn'),
        ('Walmart: Rollback', 'Named 2 of 10', '$10.00', 'Rollback', 'warn'),
        ("Sam's Club: $15 Sam's Cash on $100 of P&G", 'Named 1 of 5', '$15.00', "Sam's Cash", 'warn')]
    assert body['rows'][1]['detail'] == ('Live on Pampers Swaddlers v5, Pampers Swaddlers v6. Pampers Swaddlers v5 '
                                         '$59.77 to $49.77. Pampers Swaddlers v6 $59.77 to $49.77.')
    assert body['aside']['value'] == '5 of 50' and body['aside']['kick'] == 'Promo pass-through, Oct 14'
    assert body['aside']['label'] == 'cheapest-place answers named a deal that was live on a shelf that day'
    assert body['aside']['sub'].startswith("Answers named Amazon multi-buy twice, Walmart Rollback twice and Sam's Club")
    assert body['aside']['sub'].endswith(
        'Subscribe & Save came up in 3 answers, and the charter counts it as a standing program.')
    assert body['note'] == ('Manufacturer mode never sets a price. Every figure here is what a named retailer showed '
                            'on Oct 14. Target walled every read, so their deals could not be checked.')


def test_no_deals_read_this_cycle(http, db, upstream):
    _shape(db, http, upstream, deals={**DEALS, 'deals': [], 'walled': []})
    body = _get(http, 'prove', merchant=WS)
    assert body['state'] == 'no_deals' and body['rows'] == []
    assert body['note'].startswith('No deals read this cycle')
    promo = _get(http, 'overview', merchant=WS)['promo_pass_through']
    assert (promo['n'], promo['k'], promo['per_deal']) == (50, 0, [])
    assert promo['note'] == 'Cheapest-place answers naming a deal live that day'


def test_a_failed_deals_read_is_named_never_zero(http, db, upstream):
    _shape(db, http, upstream, deals={'detail': 'boom'}, status=502)
    body = _get(http, 'prove', merchant=WS)
    assert body['state'] == 'not_measured' and body['read_errors'].get('deals')
    overview = _get(http, 'overview', merchant=WS)
    assert 'promo_pass_through' not in overview and overview['read_errors'].get('deals')


def test_a_retailer_merchant_is_unaffected(http, db, upstream):
    _shape(db, http, upstream)
    seller = {**WS_TENANT, 'merchants': [{**WS_TENANT['merchants'][0], 'kind': 'seller'}]}
    _supply(upstream, tenant=seller)
    before = len(upstream.calls)
    assert 'promo_pass_through' not in _get(http, 'overview', merchant=WS)
    assert _get(http, 'prove', merchant=WS)['state'] == 'not_measured'
    assert not [c for c in upstream.calls[before:] if c['path'].endswith('/deals')]


def test_a_study_with_no_cheapest_place_question_reads_no_deals(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _supply(upstream)
    before = len(upstream.calls)
    assert 'promo_pass_through' not in _get(http, 'overview', merchant=WS)
    assert not [c for c in upstream.calls[before:] if c['path'].endswith('/deals')]
