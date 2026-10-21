"""
2L-1 §B1: the reference on a "left out" check row.

When an agent gave no price the check row's `live` was the question's stored
amount, and FL13's questions, generated before their pages were read, stored
0.00: the drawer and the TrueSync readback said "Judged against $0.00". The
row now carries the reference the answer was judged against whether or not
the agent quoted one: the True Value cell's (the cycle's cached reference row
for the variant at the retailer the question names), its price and its basis
(`live_basis`). Applied on read, so a stored cycle reads right without a
rescore. `0.00` is never served as a reference; with none the row says "—".

FL13-shaped: console_fixture_2j2 (Pampers at Walmart and Amazon, six agents),
whose Claude and Copilot runs gave no price (Copilot quoted another brand's).
Here every one of those 40 runs' questions stored 0.00, as FL13's did.
"""
import json

import pytest
from sqlalchemy import text

from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

LEFT_OUT = ('claude', 'copilot')


def _fixture(db, amount='0.00', reference=True):
    f2j2.load(db, _encode)
    with db.begin() as c:
        if not reference:
            c.execute(text("UPDATE soa_cycles SET reference_prices = NULL WHERE id = 229"))
        rows = c.execute(text("SELECT run_id, expected_answer FROM soa_expectation_outcomes "
                              "WHERE cycle_id = 229 AND tier = 'catalog_accuracy'")).mappings().all()
        for r in rows:
            expected = r['expected_answer']
            expected = json.loads(expected) if isinstance(expected, str) else dict(expected)
            c.execute(text("UPDATE soa_expectation_outcomes SET expected_answer = :e WHERE run_id = :r"),
                      {'e': _encode({**expected, 'amount': amount}), 'r': r['run_id']})


def _answers(http):
    as_('op')
    r = http.get('/api/console/answers', params={'org': 10, 'cycle': f2j2.CYCLE})
    assert r.status_code == 200, r.text
    return [a for a in r.json() if a['tier'] == 'catalog_accuracy']


def _walmart(answer):
    return answer['query'].endswith('at walmart.com?')


def _expected(answer) -> str:
    label = answer['query'][len('What does the Pampers '):-len(' cost at walmart.com?')]
    walmart = next(v[3] for v in f2j2.VARIANTS if v[0] == label)
    price = walmart if _walmart(answer) else f2j2.price_at(walmart, 'amazon.com')
    return f"${price} at {'walmart.com' if _walmart(answer) else 'amazon.com'}"


def test_a_left_out_run_carries_the_cell_s_reference_never_zero(http, db):
    _fixture(db)
    answers = _answers(http)
    left = [a for a in answers if a['platform'] in LEFT_OUT]
    assert len(left) == 40
    for a in left:
        [check] = a['checks']
        assert check['claim'] == '—' and check['verdict'] == 'missed'
        assert check['live'] == _expected(a) if _walmart(a) else check['live'].startswith('$')
        assert check['live_basis'] == 'reference_read'
    # one by hand: Swaddlers NB 84 at Walmart, the cell's live price
    nb = next(a for a in left if a['query'] == 'What does the Pampers Swaddlers NB 84 cost at walmart.com?')
    assert nb['checks'][0]['live'] == '$24.97 at walmart.com'
    nb_amazon = next(a for a in left if a['query'] == 'What does the Pampers Swaddlers NB 84 cost at amazon.com?')
    assert nb_amazon['checks'][0]['live'] == '$27.97 at amazon.com'
    assert not any('0.00' in c['live'] for a in answers for c in a['checks'])


def test_the_left_out_row_reads_the_same_cell_true_value_shows(http, db):
    _fixture(db)
    as_('op')
    tv = http.get('/api/console/true-value', params={'org': 10, 'cycle': f2j2.CYCLE, 'merchant': f2j2.MERCHANT}).json()
    for a in _answers(http):
        if a['platform'] not in LEFT_OUT:
            continue
        row = next(r for r in tv['rows'] if (r['gtin'] == a['gtin'].zfill(14) if a.get('gtin')
                                             else r['sku'] == a['variant_id'].removeprefix('sku:')))
        cell = row['cells'][a['retailer']]
        assert a['checks'][0]['live'] == f"{cell['live']} at {a['retailer']}"
        assert cell['live_basis'] == a['checks'][0]['live_basis']


def test_a_question_that_stored_no_amount_reads_the_cell_too(http, db):
    _fixture(db, amount=None)
    nb = next(a for a in _answers(http) if a['platform'] == 'claude'
              and a['query'] == 'What does the Pampers Swaddlers NB 84 cost at walmart.com?')
    assert (nb['checks'][0]['live'], nb['checks'][0]['live_basis']) == ('$24.97 at walmart.com', 'reference_read')


def test_with_no_reference_and_a_zero_amount_the_row_says_dash(http, db):
    _fixture(db, reference=False)
    left = [a for a in _answers(http) if a['platform'] in LEFT_OUT]
    assert left and all(a['checks'][0]['live'] == '—' and 'live_basis' not in a['checks'][0] for a in left)


def test_a_quoted_run_is_untouched(http, db):
    """A run that quoted a price keeps the reference its claim was judged against."""
    _fixture(db, amount=None)
    quoted = [a for a in _answers(http) if a['platform'] == 'chatgpt']
    assert quoted and all(c['claim'] != '—' for a in quoted for c in a['checks'])


@pytest.mark.parametrize('stated_live', ['$0.00', '—'])
def test_build_answer_unit(stated_live):
    """The read model alone: a claim about another product (no reference of
    its own) and a no-claim row both read the cell."""
    from app.services import console_read_models as rm
    reference = {'prices': [{'retailer_domain': 'walmart.com', 'gtin': '00037000863434', 'price': '24.97',
                             'currency': 'USD', 'verifiable': True, 'role': 'retailer'}]}
    index = rm.reference_index(reference)
    expected = {'type': 'price', 'amount': '0.00' if stated_live == '$0.00' else None, 'currency': 'USD',
                'attributed_to': 'walmart.com'}
    run = {'id': 1, 'platform': 'claude', 'run_number': 1, 'run_at': None, 'raw_response': 'no idea',
           'answer_status': 'answered'}
    query = {'tier': 'catalog_accuracy', 'query_text': 'q', 'source_ref': {'variant_id': '00037000863434',
                                                                         'gtin': '00037000863434'}}
    for claims in ([], [{'target': 'not_ours', 'stated': '9.99', 'product': 'Huggies', 'outcome': 'absent'}]):
        outcome = {'outcome': 'absent', 'claim_results': claims, 'expected_answer': expected, 'flags': []}
        a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='C', references=index)
        assert (a['checks'][0]['live'], a['checks'][0]['live_basis']) == ('$24.97 at walmart.com', 'reference_read')
        bare = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='C')
        assert bare['checks'][0]['live'] == '—'
