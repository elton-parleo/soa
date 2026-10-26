"""
2Q-2 (B2): two copy and severity items seen on FL15.

1. The lead signal read "Wrong price on Pampers Zzz overnight, Size 4, 104 ct
   in 11 runs. Quoted $44.99 against $44.99.": the most quoted amount, an
   exact one (Amazon's), while the wrong quotes were $25, $27.97 and $23.79
   for a 58 ct pack. The signal and the product's issue line now quote the
   most common WRONG amount (wrong_quote), with 2Q-1 B4's pack clause when
   that is the reason.
2. The retired-line question ("Is Pampers Pure Protection still sold, and
   what replaced it?") read every answer High and red, the four that named
   AMORE too. An answer that names the successor is grounded and unflagged;
   one that does not is Medium, "did not name AMORE, its successor". Still
   sold stays uncounted (2L-2).
"""
from sqlalchemy import text

from app.services import console_parity as parity
from app.services import console_read_models as rm
from soa_shared import retired_lines as rl
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)

NAME = 'Pampers Zzz overnight, Size 4, 104 ct'


def q(stated, outcome, pack=None, live='$44.99'):
    return {'stated': stated, 'outcome': outcome, 'pack': pack, 'live': live, 'retailer': 'walmart.com'}


def fl15(pack=None):
    """FL15's row: 7 exact at $44.99 (the most quoted amount), 11 wrong at three other amounts."""
    return ([q('44.99', 'exact')] * 7 + [q('25.00', 'wrong', pack)] * 5 + [q('27.97', 'wrong', pack)] * 4
            + [q('23.79', 'wrong', pack)] * 2)


# ── 1: the most common wrong amount ───────────────────────────────────────

def test_the_issue_line_quotes_the_most_common_wrong_amount():
    assert parity.wrong_quote(fl15()) == {'quote': '$25.00', 'live': '$44.99', 'n': 5}
    assert parity.product_issue(fl15(), NAME) == (
        'product.wrong', 'Quoted a wrong price in 11 of 18 runs, most often $25.00 against $44.99.')
    # with the pack the reason: 2Q-1 B4's clause, on the most common wrong amount too
    assert parity.product_issue(fl15(pack=58), NAME) == (
        'product.wrong', 'Quoted $25.00 for a 58 ct pack against $44.99 for the 104 ct in 5 of 18 runs.')
    # a wrong quote that stated no amount: the line as before
    assert parity.wrong_quote([q(None, 'wrong')]) is None
    assert parity.product_issue([q(None, 'wrong'), q('44.99', 'exact')], NAME) == (
        'product.wrong', 'Quoted a wrong price in 1 of 2 runs.')
    assert parity.wrong_quote([q('25.00', 'wrong', live='unverifiable')])['live'] == 'the reference'


def _wrong_at(db, cycle_id, vid, retailer, price, conflict=None):
    """The ChatGPT, Gemini, Perplexity and Claude runs of `vid` at `retailer` quote `price`, wrong."""
    with db.begin() as c:
        rows = c.execute(text("""
            SELECT o.id, o.platform FROM soa_expectation_outcomes o JOIN soa_queries q ON q.id = o.query_id
            WHERE o.cycle_id = :c AND q.tier = 'catalog_accuracy' AND q.query_text LIKE :t
        """), {'c': cycle_id, 't': f"%{dict((p[0], p[1]) for p in f2p1.PRICED)[vid]} cost at {retailer}%"}).fetchall()
        n = 0
        for oid, platform in rows:
            if platform not in ('chatgpt', 'gemini_grounded', 'perplexity', 'claude'):
                continue
            claim = {'target': 'asked', 'stated': price, 'outcome': 'wrong'}
            if conflict:
                claim.update(target='clash', conflict=conflict, reason_code='variant_clash')
            c.execute(text("UPDATE soa_expectation_outcomes SET outcome = 'wrong', claim_results = :cl WHERE id = :i"),
                      {'cl': _encode([claim]), 'i': oid})
            n += 1
    return n


def test_the_signal_quotes_the_most_common_wrong_amount(http, db, upstream):
    _pair(db, http, upstream, changes=False)
    assert _wrong_at(db, f2p1.ID_1, 'v2', 'amazon.com', '25.00') == 4
    block = _get(http, 'overview', cycle=f2p1.CYCLE_1, merchant=WS)['by_surface']['all']
    product = next(p for p in block['products'] if p['name'] == 'Size 4, 120 ct')
    assert product['wrong_quote'] == {'quote': '$25.00', 'live': '$42.97', 'n': 4}
    assert product['issue'] == 'Quoted a wrong price in 4 of 12 runs, most often $25.00 against $42.97.'
    signal = next(s for s in block['signals'] if s['rule'] == 'wrong_product')
    assert signal['title'] == 'Wrong price on Size 4, 120 ct in 4 runs.'
    assert signal['detail'].startswith('Quoted $25.00 against $42.97. ')


def test_the_signal_never_quotes_the_most_quoted_amount():
    """FL15's row: the cell's most quoted amount is Amazon's exact $44.99."""
    quotes = fl15()
    product = {'name': NAME, 'sku': 'zzz-s4-104', 'wrong_runs': 11, 'quote': '$44.99', 'live_price': '$44.99',
               'quoted': 'Amazon $44.99, 7 of 18 runs', 'answer_ids': [1], **parity._pack_field(quotes, NAME)}
    zero = dict.fromkeys(('other_brand', 'fabricated', 'unverifiable', 'scored', 'left_out', 'brand_scored'), 0)
    signals = parity.build_signals({'total': zero, 'agents': {}}, [product], surface='all', brand='Pampers',
                                   cycle_start=None, access_problems=[])
    (signal,) = signals
    assert signal['title'] == f'Wrong price on {NAME} in 11 runs.'
    assert signal['detail'] == 'Quoted $25.00 against $44.99. Amazon $44.99, 7 of 18 runs.'
    packed = {**product, **parity._pack_field(fl15(pack=58), NAME)}
    (signal,) = parity.build_signals({'total': zero, 'agents': {}}, [packed], surface='all', brand='Pampers',
                                     cycle_start=None, access_problems=[])
    assert signal['detail'].startswith('Quoted $25.00 for a 58 ct pack against $44.99 for the 104 ct. ')


def test_the_signal_keeps_the_pack_clause_on_the_wrong_amount(http, db, upstream):
    _pair(db, http, upstream, changes=False)
    assert _wrong_at(db, f2p1.ID_1, 'v2', 'amazon.com', '25.00', conflict='pack count 58') == 4
    block = _get(http, 'overview', cycle=f2p1.CYCLE_1, merchant=WS)['by_surface']['all']
    signal = next(s for s in block['signals'] if s['rule'] == 'wrong_product')
    assert signal['detail'].startswith('Quoted $25.00 for a 58 ct pack against $42.97 for the 120 ct. ')


# ── 2: the retired line's successor ───────────────────────────────────────

PURE_REF = {'merchant_slug': 'pampers', 'listing_id': 41,
            'retired_line': {'variant_ids': ['sku:sku_pg_pure_s1'], 'line': 'Pure Protection'}}
#: the expectation catalog_tiers.build_retired_line_questions writes: the successor without its terms
PURE_EXPECTED = {'type': 'brand_mention', 'brand': 'Pampers', 'domain': 'pampers.com',
                 'successor': {'variant_id': 'sku:sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132',
                               'product_name': 'Pampers AMORE', 'line': 'AMORE', 'label': 'AMORE'}}
STILL = 'Whether it called Pure Protection still sold is not coded'


def _verdict(answer, expectation=PURE_EXPECTED, ref=PURE_REF):
    return rm.catalog_verdict('retired', ref, {}, answer, expectation=expectation)


def test_an_answer_naming_the_successor_is_grounded():
    for answer in ('It was replaced by Pampers AMORE.', 'AMORE replaced it.', 'pampers amore is the new one'):
        assert _verdict(answer) == {'verdict': 'grounded', 'line': f'named AMORE, its successor. {STILL}',
                                    'severity': 'ok', 'tone': 'ok'}, answer


def test_an_answer_naming_neither_is_high():
    """2T-4 (2): the successor not named on the direct question is High (2Q-2 read it medium)."""
    for answer in ('Yes, still sold widely.', 'Still at Walmart.', 'Amorepacific makes skincare.'):
        assert _verdict(answer) == {'verdict': 'no_successor', 'line': f'did not name AMORE, its successor. {STILL}',
                                    'severity': 'high', 'tone': 'bad'}, answer


def test_no_successor_or_no_answer_is_not_judged():
    plain = {'verdict': None, 'severity': 'low', 'tone': 'neu',
             'line': 'asked about Pure Protection, which the brand retired. Whether the answer called it still sold '
                     'is not coded'}
    assert _verdict('', ) == plain
    assert _verdict('AMORE replaced it.', expectation={**PURE_EXPECTED, 'successor': None}) == plain
    # a successor on the question's own reference, with its terms, reads the same
    ref = {**PURE_REF, 'retired_line': {**PURE_REF['retired_line'],
                                        'successor': {'label': 'AMORE', 'terms': rl.terms('Pampers AMORE', 'Pampers')}}}
    assert _verdict('AMORE replaced it.', expectation={}, ref=ref)['verdict'] == 'grounded'


def _answer(raw, flags=None):
    import json
    run = {'id': 95000, 'platform': 'chatgpt', 'run_number': 1, 'raw_response': raw, 'status': 'success',
           'answer_status': 'answered', 'surface': 'grounded_api'}
    query = {'query_text': 'Is Pampers Pure Protection still sold, and what replaced it?', 'tier': 'brand_direct',
             'source_ref': json.dumps(PURE_REF), 'query_code': 'WSF_3001'}
    outcome = {'outcome': 'grounded', 'expected_answer': json.dumps(PURE_EXPECTED), 'extraction': '{}',
               'flags': json.dumps(flags or [])}
    return rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='FL15-pampers-20261024')


def test_the_answer_row_is_never_high_for_a_store_on_a_retired_line():
    off_list = [{'flag': 'fabricated_availability', 'detail': 'Walmart is not on the brand list'}]
    named = _answer('It was replaced by Pampers AMORE, at Walmart.', off_list)
    assert (named['severity'], named['tone'], named['intent_verdict'], named['flags']) == ('ok', 'ok', 'grounded', [])
    assert named['summary'] == f'named AMORE, its successor. {STILL}'
    neither = _answer('Yes, still at Walmart.', off_list)
    # 2T-4 (2): the successor not named on the direct question is High (was 2Q-2's medium)
    assert (neither['severity'], neither['tone'], neither['intent_verdict'], neither['flags']) == \
        ('high', 'bad', 'no_successor', [])
    assert neither['summary'] == f'did not name AMORE, its successor. {STILL}'
