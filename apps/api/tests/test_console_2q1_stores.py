"""
2Q-1 (B1): Retailer coverage, routing ("Where agents send Pampers shoppers
first"), the where-to-buy verdict and the "sent the shopper to" fact read
the stores the scorer coded over the whole answer (`named_stores`); a row
scored before 2Q-1 still reads its retailer_mentions. The console's scorer
is "17", brand-claim coder 7; no dimension reads it.
"""
from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import expected_answers as ea
from soa_shared import narratives
from soa_shared import retailers as rt

LISTED = ['walmart.com', 'target.com', 'amazon.com', 'costco.com']
OWN = ['pampers.com']
LIST = "Pampers Swaddlers Size 1:\n- Amazon: $26.99\n- Target: $28.49\n- Walmart: $27.97"


def _coded(answer):
    return {'named_stores': rt.named_stores(answer, retailers=LISTED, own_domains=OWN, brand='Pampers')}


def test_the_version():
    assert score_svc.SCORER_VERSION == '17' and ea.BRAND_CODER_VERSION == 7
    assert score_svc.SCORER_CHANGES['17'] == 'where-to-buy stores coded over the whole answer'
    assert score_svc.SCORER_CHANGE_APPLIES['17']({}) is False
    assert score_svc.CODER_SCORER_VERSIONS == {None: '11', 1: '11', 2: '12', 3: '13', 4: '14', 5: '15', 6: '16',
                                               7: '17'}


def _body(version, coded, of=60, oldest=None):
    return {'scorer_version': version, 'score': 50, 'surfaces': [{'surface': 'grounded_api'}],
            'metric_counts': {}, 'metric_surface': None,
            'brand_coder': {'version': ea.BRAND_CODER_VERSION, 'coded': coded, 'of': of, 'oldest': oldest}}


def test_comparability_as_before():
    assert score_svc.comparable_version(_body('17', 60, oldest=7)) == '17'
    # FL15 re-scored, FL14 not yet: its version-6 rows compare as 16
    assert score_svc.comparable_version(_body('17', 0, oldest=6)) == '16'
    prev = score_svc.compare(_body('17', 60, oldest=7), 'FL14-pampers-20261023', _body('17', 0, oldest=6))
    assert prev['comparable'] is False and prev['reason'] == 'Scored under v16, re-score to compare.'


def test_stores_in_order_reads_named_stores():
    x = _coded("Pampers.com sells it, and Costco doesn't carry it. " + LIST)
    assert [(s['name'], s['domain']) for s in rm.stores_in_order(x)] == [
        ('pampers.com', 'pampers.com'), ('Amazon', 'amazon.com'), ('Target', 'target.com'), ('Walmart', 'walmart.com')]
    # an empty coding is an answer that named no store, not an uncoded one
    assert rm.stores_in_order({'named_stores': [], 'retailer_mentions': [{'name': 'Walmart'}]}) == []
    # a row scored before 2Q-1 reads its retailer_mentions, as it did
    old = {'spans': [{'text': 'Buy it at Target.'}], 'retailer_mentions': [{'name': 'Target', 'role': 'recommendation'}]}
    assert [s['name'] for s in rm.stores_in_order(old)] == ['Target']


def _routing(answers):
    rows = [{'run': f'run-{i}', 'answered': True, 'surface': 'grounded_api'} for i in range(1, len(answers) + 1)]
    runs = [{'id': i, 'source_ref': {'intent': 'where_to_buy'}} for i in range(1, len(answers) + 1)]
    extractions = {i: x for i, x in enumerate(answers, 1)}
    return rm.build_routing(rows, runs, extractions, surface_list=['all', 'grounded_api'], brand='Pampers',
                            retailers=LISTED, own_domains=OWN)


def test_coverage_and_routing_on_the_coded_stores():
    old_style = {'spans': [{'text': t} for t in LIST.split('\n')],
                 'retailer_mentions': [{'name': 'Walmart', 'role': 'recommendation'}]}
    before = _routing([old_style, old_style])
    after = _routing([_coded(LIST), _coded("Order it on the Pampers website or at Target. Walmart has it too.")])
    assert before['coverage']['all'] == {'answers': 2, 'named_two_plus': 0}
    assert after['coverage']['all'] == {'answers': 2, 'named_two_plus': 2}
    assert after['coverage_line'] == '2 of 2 where-to-buy answers name 2 or more of Walmart, Target, Amazon, Costco'
    # the brand's own site is its row, first in the second answer
    rows = {r['name']: (r['first'], r['you']) for r in after['rows']}
    assert rows['Amazon'] == (1, False) and rows['pampers.com'] == (1, True) and rows['Walmart'] == (0, False)
    assert after['total'] == 2 and 'named_stores' in after['rule']


def test_the_where_to_buy_verdict_reads_them():
    got = rm.catalog_verdict('where_to_buy', {'intent': 'where_to_buy'}, _coded(LIST), LIST)
    assert (got['verdict'], got['line']) == ('covered', "named Amazon, Target and Walmart, 3 of the brand's retailers")


def test_sent_to_reads_them_and_leaves_an_unavailable_store_out():
    x = _coded("Costco doesn't carry Size 1. Walmart has it for $27.97, and so does pampers.com.")
    assert narratives.sent_to(x, []) == ['Walmart', 'pampers.com']
    # before 2Q-1: the labeller's recommendation
    assert narratives.sent_to({'retailer_mentions': [{'name': 'Target', 'role': 'recommendation'}]}, []) == ['Target']
