"""
2K-4 §B5: Missed counts wrong prices. An agent that gave no price is reported,
not counted (Elton, Oct 21: an agent that declines to price is not a wrong
answer).

2I-9's Missed share counted "wrong, another brand's price, or left out the price
the page had" over scored price answers: on FL13 89 of 100, 42 of them answers
that quoted no price at all. Now the numerator is wrong (stale included) plus
another brand's price, the denominator the scored price answers (exact,
partial, stale, wrong, another brand's), and the answers that gave no price are
`no_price_runs`, said on the driver's second line. Once-counting is unchanged.
"""
import pytest

from app.services import console_revenue as revenue_svc

LOST_N, LOST_OF = 30, 60


def _fl13_shape():
    """FL13's price answers: 47 wrong, 42 that gave no price, 11 exact; 60 brand-choice answers, 30 lost."""
    vis = [{'answered': True, 'unprompted': True, 'agent': 'chatgpt', 'run': f'run-{i}',
            'first': {'name': 'Huggies', 'you': False} if i < LOST_N else {'name': 'Pampers', 'you': True}}
           for i in range(LOST_OF)]
    plan = ['wrong'] * 47 + ['absent'] * 42 + ['exact'] * 11
    catalog = [{'run_id': 1000 + i, 'platform': 'chatgpt', 'answer_status': 'answered', 'outcome': o, 'reason_code': None,
                'reference_price': '24.97'} for i, o in enumerate(plan)]
    return vis, catalog


def test_fl13_s_missed_is_47_of_58_and_the_42_no_price_answers_are_said_apart():
    vis, catalog = _fl13_shape()
    shares = revenue_svc.revenue_shares(vis, catalog, 0.25, kind='brand')
    m = shares['missed']
    assert (m['n'], m['of'], m['no_price_runs']) == (47, 58, 42)            # 2I-9 read 89 of 100
    assert m['raw'] == pytest.approx(47 / 58) and round(m['raw'] * 100) == 81
    assert m['share'] == pytest.approx(47 / 58 * (1 - LOST_N / LOST_OF))     # counted once, as before
    model = revenue_svc.build_model(shares, revenue_svc.inputs_view(None, 'pampers'), cycle='FL13', kind='brand',
                                    name='Pampers', domain='pampers.com')
    missed = next(d for d in model['drivers'] if d['kind'] == 'missed')
    assert missed['measured'] == ("47 of the 58 price answers got the price wrong or quoted another brand's price, 81%. "
                                  "Counted once: only for shoppers the brand choice did not already send elsewhere, 41%.")
    assert missed['no_price'] == {'count': 42, 'line': '42 answers gave no price at all.'}
    assert model['shares']['missed_raw'] == pytest.approx(47 / 58)
    assert model['counts']['missed']['no_price_runs'] == 42


def test_another_brand_s_price_is_a_miss_and_a_stale_one_too():
    vis, _ = _fl13_shape()
    catalog = [{'run_id': i, 'platform': 'chatgpt', 'answer_status': 'answered', 'outcome': o, 'reason_code': rc,
                'reference_price': None}
               for i, (o, rc) in enumerate([('absent', 'other_brand'), ('stale', None), ('exact', None), ('absent', None)])]
    m = revenue_svc.revenue_shares(vis, catalog, 0.25, kind='brand')['missed']
    assert (m['n'], m['of'], m['no_price_runs']) == (2, 3, 1)


def test_no_no_price_answer_no_second_line():
    vis, _ = _fl13_shape()
    catalog = [{'run_id': 1, 'platform': 'chatgpt', 'answer_status': 'answered', 'outcome': 'wrong', 'reason_code': None}]
    shares = revenue_svc.revenue_shares(vis, catalog, 0.25, kind='brand')
    model = revenue_svc.build_model(shares, revenue_svc.inputs_view(None, 'pampers'), cycle='C', kind='brand',
                                    name='Pampers', domain='pampers.com')
    assert 'no_price' not in next(d for d in model['drivers'] if d['kind'] == 'missed')
