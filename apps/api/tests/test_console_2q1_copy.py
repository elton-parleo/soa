"""
2Q-1 (B4): two copy items on reads.

1. FL15's lead signal read "Wrong price on Pampers Zzz overnight, Size 4, 104
   ct in 11 runs. Quoted $44.99 against $44.99." The quotes were for another
   pack: the price check had moved each off the asked variant for its count
   (the claim's conflict "pack count 58", variant_clash). The line now says
   the reason the check has, "Quoted $44.99 for a 58 ct pack against $44.99
   for the 104 ct.", and so does the products table's issue line.
2. A deal on a shelf that says out of stock is not live (supply's extractor
   excludes it, `out_of_stock`); Trade promotions says so for an ended or
   out-of-stock deal. See test_console_2q1_deals below.
"""
import json

from sqlalchemy import text

from app.services import console_parity as parity
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)

PACK_AGENTS = ('chatgpt', 'gemini_grounded', 'perplexity', 'claude')


def _quoted_for_another_pack(db, cycle_id, vid, retailer, price):
    """The runs of `vid` at `retailer` quote the reference's own price for a 58 ct pack: the check's clash."""
    with db.begin() as c:
        rows = c.execute(text("""
            SELECT o.id, o.platform FROM soa_expectation_outcomes o JOIN soa_queries q ON q.id = o.query_id
            WHERE o.cycle_id = :c AND q.tier = 'catalog_accuracy' AND q.query_text LIKE :t
        """), {'c': cycle_id, 't': f"%{dict((p[0], p[1]) for p in f2p1.PRICED)[vid]} cost at {retailer}%"}).fetchall()
        n = 0
        for oid, platform in rows:
            if platform not in PACK_AGENTS:
                continue
            claim = [{'target': 'clash', 'stated': price, 'outcome': 'wrong', 'conflict': 'pack count 58',
                      'product': 'Pampers Swaddlers Size 4, 58 ct', 'reason_code': 'variant_clash',
                      'reason': 'pack count 58, and the record has no such variant'}]
            c.execute(text("UPDATE soa_expectation_outcomes SET outcome = 'wrong', reason_code = 'variant_clash', "
                           "claim_results = :cl WHERE id = :i"), {'cl': _encode(claim), 'i': oid})
            n += 1
    return n


def test_a_quote_for_another_pack_says_so(http, db, upstream):
    _pair(db, http, upstream, changes=False)
    assert _quoted_for_another_pack(db, f2p1.ID_1, 'v2', 'amazon.com', '42.97') == 4
    over = _get(http, 'overview', cycle=f2p1.CYCLE_1, merchant=WS)
    block = over['by_surface']['all']
    signal = next(s for s in block['signals'] if s['rule'] == 'wrong_product')
    assert signal['title'] == 'Wrong price on Size 4, 120 ct in 4 runs.'
    assert signal['detail'].startswith('Quoted $42.97 for a 58 ct pack against $42.97 for the 120 ct. ')
    product = next(p for p in block['products'] if p['name'] == 'Size 4, 120 ct')
    assert product['issue'] == 'Quoted $42.97 for a 58 ct pack against $42.97 for the 120 ct in 4 of 12 runs.'
    assert product['pack_mismatch'] == {'quote': '$42.97', 'pack': 58, 'asked': '120 ct', 'live': '$42.97', 'n': 4}


def test_the_rule_by_hand():
    q = lambda stated, outcome, pack=None, live='$44.99': {'stated': stated, 'outcome': outcome, 'pack': pack,  # noqa: E731
                                                           'live': live, 'retailer': 'walmart.com'}
    name = 'Pampers Zzz overnight, Size 4, 104 ct'
    eleven = [q('44.99', 'wrong', 58)] * 11 + [q('44.99', 'exact')] * 7
    assert parity.product_issue(eleven, name) == (
        'product.wrong', 'Quoted $44.99 for a 58 ct pack against $44.99 for the 104 ct in 11 of 18 runs.')
    # a wrong price for the pack asked about reads as before
    plain = [q('41.99', 'wrong')] * 3 + [q('44.99', 'wrong', 58)] * 2
    assert parity.product_issue(plain, name) == ('product.wrong', 'Quoted a wrong price in 5 of 5 runs, most often $41.99 against $44.99.')
    # no pack in the name: the line names the pack asked about
    assert parity.pack_mismatch([q('44.99', 'wrong', 58)], 'Zzz Size 4')['asked'] == 'pack asked about'
    # a reference that is not a price is not quoted as one
    assert parity.pack_mismatch([q('44.99', 'wrong', 58, live='unverifiable')], name)['live'] == 'the reference'
    assert parity.TEMPLATES['signal.wrong_product_pack'] == \
        'Quoted {quote} for a {pack} ct pack against {live} for the {asked}. {split}.'


# ── 2: a deal beside "Out of stock" is not live ───────────────────────────

def _out_of_stock(deals, title='Rollback'):
    """supply's /deals with the deal's shelf words beside "Out of stock", as FL15's Walmart Rollback read
    ("… Out of stock …"): the deal's own text and price, then the shelf's stock line."""
    out = json.loads(json.dumps(deals))
    for deal in out['deals']:
        if deal['text'] == title:
            for v in deal['variants']:
                v['evidence'] = f"{deal['text']} ${v.get('price') or v.get('shelf_price')} Out of stock Get in-stock alert"
    return out


def test_an_out_of_stock_deal_is_not_live_and_its_row_says_so(http, db, upstream):
    from tests import test_console_2m2_promo as t2m2
    t2m2._shape(db, http, upstream)
    before = t2m2._get(http, 'prove', merchant=WS)
    rollback = next(r for r in before['rows'] if r['title'].startswith('Walmart'))
    assert rollback['asked'] > 0
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/deals', body=_out_of_stock(t2m2.DEALS), token=t2m2.TOKEN_A)
    after = t2m2._get(http, 'prove', merchant=WS)
    row = next(r for r in after['rows'] if r['title'] == rollback['title'])
    assert (row['live'], row['not_live'], row['asked'], row['named'], row['tone']) == (False, 'out_of_stock', 0, 0, 'neu')
    assert row['agents'] == 'Not counted: out of stock'
    assert row['detail'].startswith('Not live: the shelf said out of stock on Oct 14, so no answer is counted against it. Shown on ')
    assert 'Live on' not in row['detail']
    assert after['rows'][-1]['title'] == rollback['title']   # last
    # the answers about its SKUs are judged against the deals that were live (none for them): the aside moves
    # two answers named the Rollback: no longer a live deal named, out of the same 50
    assert (before['promo_pass_through']['k'], after['promo_pass_through']['k']) == (5, 3)
    assert after['promo_pass_through']['n'] == before['promo_pass_through']['n'] == 50
    assert not [d for d in after['promo_pass_through']['per_deal'] if d['title'] == rollback['title']]


def test_live_for_and_the_rule_by_hand():
    from soa_shared import promo_pass_through as ppt
    deal = {'retailer_domain': 'walmart.com', 'kind': 'rollback_or_was', 'text': 'Rollback',
            'variants': [{'sku': 'v5', 'evidence': 'Rollback $49.77 Out of stock'}, {'sku': 'v6', 'evidence': 'Rollback $49.77'}]}
    payload = {'deals': [deal]}
    assert ppt.live_for(payload, {'sku': 'v5'}) == []
    assert [d['variant']['sku'] for d in ppt.live_for(payload, {'sku': 'v6'})] == ['v6']
    assert ppt.out_of_stock(deal) is False and ppt.out_of_stock(deal, deal['variants'][0]) is True
    # supply's own fields, when it serves them
    assert ppt.out_of_stock({**deal, 'excluded': 'out_of_stock'}) is True
    assert ppt.out_of_stock({'variants': [{'availability': 'out_of_stock'}]}) is True


def test_an_ended_deal_and_an_out_of_stock_one_against_the_previous_cycle(http, db, upstream):
    from tests.test_console_2p1_two_cycles import PREV_NAME
    _pair(db, http, upstream)
    # cycle 2's Amazon multi-buy, kept since cycle 1, is now beside "Out of stock"
    deals_2 = f2p1.deals_2(__import__('tests.test_console_2m2_promo', fromlist=['DEALS']).DEALS)
    multi = deals_2['deals'][0]['text']
    upstream.routes.by_date[0] = ('2026-10-21', _out_of_stock(deals_2, multi))
    prove = _get(http, 'prove', merchant=WS)
    row = next(r for r in prove['rows'] if r.get('not_live'))
    assert row['change'] == 'out_of_stock'
    assert row['change_note'] == f'Out of stock on Oct 21: Amazon showed it beside "Out of stock". Live in {PREV_NAME}.'
    # the Rollback that ended still reads as ended
    assert [e['change'] for e in prove['ended'] if e['title'].startswith('Walmart')] == ['ended']
