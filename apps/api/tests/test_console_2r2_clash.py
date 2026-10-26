"""
2R-2 (B5): H34, a quote for a variant the record does not have says which.

FL15's lead signal read "Wrong price on Pampers Zzz overnight, Size 4, 104 ct
… most often $44.99 against $44.99": ChatGPT (run-15988) quoted $44.99 for
"Pampers ZZZ Size 3, 116-count", and the price check judged it wrong with
reason variant_clash (conflict "model or size number differs", no pack count,
so 2Q-1 B4's pack clause never applied). The signal and the product issue line
now name the variant the quote named (the claim's own words) and the one asked
about (the row's name). Copy only: no outcome, no score moves.
"""
from sqlalchemy import text

from app.services import console_parity as parity
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)

FL15_PRODUCT = 'Pampers Zzz overnight, Size 4, 104 ct'
FL15_CLAIM = 'Pampers ZZZ Size 3, 116-count'


def _q(stated, outcome, clash=None, live='$44.99', retailer='walmart.com'):
    return {'stated': stated, 'outcome': outcome, 'live': live, 'retailer': retailer,
            **({'clash': clash} if clash else {})}


def fl15_quotes():
    """FL15's shape for the row: three wrong quotes of $44.99 for Zzz Size 3, 116-count (ChatGPT's run-15988
    among them), two other wrong amounts, seven right."""
    return ([_q('44.99', 'wrong', FL15_CLAIM)] * 3 + [_q('25.00', 'wrong'), _q('27.97', 'wrong')]
            + [_q('44.99', 'exact')] * 7)


def test_the_rule_by_hand_on_fl15_s_shape():
    quotes = fl15_quotes()
    # before: the most common wrong amount, as 2Q-2 B2 left it
    assert parity.TEMPLATES['product.wrong_quote'].format(n=5, runs=12, runs_word='runs', quote='$44.99', live='$44.99') == \
        'Quoted a wrong price in 5 of 12 runs, most often $44.99 against $44.99.'
    assert parity.product_issue(quotes, FL15_PRODUCT) == (
        'product.wrong', 'Quoted $44.99 for Size 3, 116 ct against $44.99 for the Size 4, 104 ct in 3 of 12 runs.')
    assert parity.variant_clash(quotes, FL15_PRODUCT) == {
        'quote': '$44.99', 'named': 'Size 3, 116 ct', 'asked': 'Size 4, 104 ct', 'live': '$44.99', 'n': 3}
    # a top wrong amount that is not a clash reads as before
    plain = [_q('41.99', 'wrong')] * 3 + [_q('44.99', 'wrong', FL15_CLAIM)] * 2
    assert parity.variant_clash(plain, FL15_PRODUCT) is None
    assert parity.product_issue(plain, FL15_PRODUCT)[1] == \
        'Quoted a wrong price in 5 of 5 runs, most often $41.99 against $44.99.'
    # a pack count clash is still 2Q-1's line, never this one
    packed = [{**_q('44.99', 'wrong'), 'pack': 58}] * 3
    assert parity.product_issue(packed, FL15_PRODUCT)[1].startswith('Quoted $44.99 for a 58 ct pack')
    assert 'variant_clash' not in parity._pack_field(packed, FL15_PRODUCT)


def test_variant_words():
    assert parity.variant_words(FL15_CLAIM) == 'Size 3, 116 ct'
    assert parity.variant_words(FL15_PRODUCT) == 'Size 4, 104 ct'
    assert parity.variant_words('Pampers Swaddlers Newborn 84 count') == 'Newborn, 84 ct'
    assert parity.variant_words('Pampers Zzz') is None
    # a row named with no size or count: the line says "variant asked about"
    assert parity.variant_clash([_q('44.99', 'wrong', FL15_CLAIM)], 'Zzz')['asked'] == 'variant asked about'


def _quoted_for_another_variant(db, cycle_id, vid, retailer, price):
    """The runs of `vid` at `retailer` quote the reference's own price for Zzz Size 3, 116-count: the
    check's variant_clash, the claim as the scorer stores it (target clash, no pack count)."""
    with db.begin() as c:
        rows = c.execute(text("""
            SELECT o.id, o.platform FROM soa_expectation_outcomes o JOIN soa_queries q ON q.id = o.query_id
            WHERE o.cycle_id = :c AND q.tier = 'catalog_accuracy' AND q.query_text LIKE :t
        """), {'c': cycle_id, 't': f"%{dict((p[0], p[1]) for p in f2p1.PRICED)[vid]} cost at {retailer}%"}).fetchall()
        n = 0
        for oid, platform in rows:
            if platform not in ('chatgpt', 'gemini_grounded', 'perplexity', 'claude'):
                continue
            claim = [{'target': 'clash', 'stated': price, 'outcome': 'wrong', 'product': FL15_CLAIM,
                      'conflict': 'model or size number differs', 'reason_code': 'variant_clash',
                      'reason': 'model or size number differs, and the record has no such variant'}]
            c.execute(text("UPDATE soa_expectation_outcomes SET outcome = 'wrong', reason_code = 'variant_clash', "
                           "claim_results = :cl WHERE id = :i"), {'cl': _encode(claim), 'i': oid})
            n += 1
    return n


def test_the_signal_and_the_issue_line_over_http(http, db, upstream):
    _pair(db, http, upstream, changes=False)
    assert _quoted_for_another_variant(db, f2p1.ID_1, 'v2', 'amazon.com', '42.97') == 4
    block = _get(http, 'overview', cycle=f2p1.CYCLE_1, merchant=WS)['by_surface']['all']
    signal = next(s for s in block['signals'] if s['rule'] == 'wrong_product')
    assert signal['title'] == 'Wrong price on Size 4, 120 ct in 4 runs.'
    assert signal['detail'].startswith('Quoted $42.97 for Size 3, 116 ct against $42.97 for the Size 4, 120 ct. ')
    product = next(p for p in block['products'] if p['name'] == 'Size 4, 120 ct')
    assert product['issue'] == 'Quoted $42.97 for Size 3, 116 ct against $42.97 for the Size 4, 120 ct in 4 of 12 runs.'
    assert product['variant_clash'] == {'quote': '$42.97', 'named': 'Size 3, 116 ct', 'asked': 'Size 4, 120 ct',
                                        'live': '$42.97', 'n': 4}
    assert 'pack_mismatch' not in product
    # True Value's quotes carry the words the check had
    tv = _get(http, 'true-value', cycle=f2p1.CYCLE_1, merchant=WS)
    quotes = [q for r in tv['rows'] for cell in r['cells'].values() for q in cell.get('quotes') or []]
    assert sum(1 for q in quotes if q.get('clash') == FL15_CLAIM) == 4
