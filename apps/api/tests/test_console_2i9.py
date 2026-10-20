"""
2I-9: the revenue model behind Impact, the Overview's revenue block and the
dollars on the screens the demo puts them on.

B1: the merchant's inputs (soa_merchant_revenue_inputs), read with their
defaults and sources, written field by field, reset by DELETE, tenant
isolated. On sqlite and a local Postgres.
"""
import pytest
from sqlalchemy import text

from soa_shared import revenue as defaults
from soa_shared.models.soa_models import SoaMerchantRevenueInputs
from tests.test_console_2c3a import _supply, db  # noqa: F401
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)

WS = 'wiggle-and-snug'


@pytest.fixture
def inputs_table(db):
    SoaMerchantRevenueInputs.__table__.create(db, checkfirst=True)
    return db


def _inputs(http, method='GET', merchant=WS, json=None, **params):
    return http.request(method, '/api/console/revenue-inputs', params={'merchant': merchant, **params}, json=json)


# ═══ B1: the inputs ══════════════════════════════════════════════════════

def test_with_nothing_saved_the_shares_read_the_demo_s_defaults_and_sales_in_scope_is_not_entered(http, inputs_table, upstream):
    _supply(upstream)
    as_('alice')
    body = _inputs(http).json()
    assert body['saved'] is False and body['currency'] == '$'
    assert body['scope'] == {'label': 'Sales in scope, all channels', 'value': None, 'entered': False, 'display': None,
                             'source': defaults.SCOPE['source']}
    assert {k: (body[k]['value'], body[k]['display'], body[k]['default']) for k in ('influence', 'horizon', 'penalty', 'lost_gainable')} == {
        'influence': (0.114, '11.4%', True), 'horizon': (0.2, '20%', True), 'penalty': (0.14, '14%', True),
        'lost_gainable': (0.25, '25%', True)}   # the demo's Pampers figure (Elton, Oct 20)
    # the demo's source sentences, verbatim (v2common.ts)
    assert body['influence']['source'].startswith('Similarweb, Sep 10 2026: an AI tool was part of 11.4% of US desktop')
    assert body['horizon']['source'].startswith('Morgan Stanley: agentic shoppers could reach $385B')
    assert body['penalty']['source'].startswith('McKinsey research across 3,000+ e-commerce companies')


def test_put_writes_the_fields_sent_records_who_and_get_reads_them_back(http, inputs_table, upstream):
    _supply(upstream)
    as_('alice')
    r = _inputs(http, 'PUT', json={'scope_value': 3.99e9, 'scope_source': 'Pampers NA, FY26', 'lost_gainable': 0.25})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['saved'] is True and body['updated_by'] == 'alice@test'
    assert (body['scope']['value'], body['scope']['display'], body['scope']['source']) == (3.99e9, '$4.0B', 'Pampers NA, FY26')
    assert (body['lost_gainable']['value'], body['lost_gainable']['default']) == (0.25, False)
    assert body['influence']['default'] is True                # untouched fields keep their default
    # a second write changes only what it sends; null resets one field
    body = _inputs(http, 'PUT', json={'influence': 0.15, 'lost_gainable': None}).json()
    assert (body['influence']['value'], body['influence']['display']) == (0.15, '15%')
    assert (body['lost_gainable']['value'], body['lost_gainable']['default']) == (0.25, True)
    assert body['scope']['value'] == 3.99e9
    assert _inputs(http).json() == body


def test_delete_resets_to_the_defaults(http, inputs_table, upstream):
    _supply(upstream)
    as_('alice')
    _inputs(http, 'PUT', json={'scope_value': 1e9, 'penalty': 0.2})
    body = _inputs(http, 'DELETE').json()
    assert body['saved'] is False and body['scope']['entered'] is False and body['penalty']['value'] == 0.14
    assert _inputs(http).json()['saved'] is False
    with inputs_table.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM soa_merchant_revenue_inputs")).scalar() == 0


@pytest.mark.parametrize('payload, why', [
    ({'influence': 1.5}, 'influence must be between 0 and 1'),
    ({'penalty': -0.1}, 'penalty must be between 0 and 1'),
    ({'lost_gainable': 2}, 'lost_gainable must be between 0 and 1'),
    ({'scope_value': -5}, 'scope_value must be 0 or more'),
    ({'horizon': 'lots'}, 'horizon must be a number'),
    ({'currency': '£'}, "currency must be one of '$', '€', 'SEK '"),
    ({'margin': 0.3}, "unknown field 'margin'"),
])
def test_out_of_range_values_are_a_422_and_nothing_is_written(http, inputs_table, upstream, payload, why):
    _supply(upstream)
    as_('alice')
    r = _inputs(http, 'PUT', json=payload)
    assert r.status_code == 422 and r.json()['detail'] == why
    with inputs_table.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM soa_merchant_revenue_inputs")).scalar() == 0


def test_the_inputs_are_tenant_isolated(http, inputs_table, upstream):
    _supply(upstream)
    as_('alice')
    _inputs(http, 'PUT', json={'scope_value': 3.99e9})
    # another org's member never reads them, and naming this org is refused
    as_('bob')
    assert _inputs(http, org=10).status_code == 403
    assert _inputs(http).json()['scope']['entered'] is False      # bob's org has its own row (none)
    # a merchant that is not the org's is a 404, read or write
    as_('alice')
    assert _inputs(http, merchant='brandco').status_code == 404
    assert _inputs(http, 'PUT', merchant='brandco', json={'scope_value': 1}).status_code == 404
    # an operator reads them naming the org: the merchant's own console read
    as_('op')
    assert _inputs(http, org=10).json()['scope']['value'] == 3.99e9
    with inputs_table.connect() as c:
        rows = c.execute(text("SELECT org_id, merchant_slug FROM soa_merchant_revenue_inputs ORDER BY org_id")).fetchall()
    assert [tuple(r) for r in rows] == [(10, WS)]


# ═══ B2: the measured shares ═════════════════════════════════════════════
#
# FL12's shape for money: 2I-8's six-agent fixture (console_fixture_2i8: 50
# category-control questions, 17 unbranded, one run each on four grounded and
# two consumer agents) plus 7 catalog questions, so 26 in all:
#   3 unverifiable on every agent (18 runs, outside both shares),
#   2 exact (12), 1 wrong (6), 1 left out with no reference price (6, outside).
# Lost: of the 102 unprompted answers, Pampers first in 27 and Huggies in 30,
#   ours in 33, nobody in 12: 57 of 102.
# Missed: the 19 catalog questions as 2I-8 built them, per agent 2 exact,
#   5 wrong, 6 another brand's price, 6 left out (the reference had 12.99);
#   AI Mode and Copilot quote 5 of the wrong ones right: grounded 17 of 19
#   missed, consumer 12 of 19. 4 x 17 + 2 x 12 = 92 of 114, plus the new
#   wrong 6 of 18 scored: 98 of 132. Once-counted: 98/132 x (1 - 57/102).
import copy  # noqa: E402
from fractions import Fraction  # noqa: E402

from app.services import console_revenue as revenue_svc  # noqa: E402
from tests import console_fixture_2i8 as f2i8  # noqa: E402
from tests import console_fixture_229 as f229  # noqa: E402
from tests.test_console_2c3a import _cycle_229  # noqa: E402
from tests.test_console_2i8 import _fl12 as _load_fl12  # noqa: E402
from tests.test_console_read_models import TOKEN_A, _encode, _fixture  # noqa: E402

LOST = Fraction(57, 102)
RAW = Fraction(98, 132)
MISSED = RAW * (1 - LOST)
AGENTS6 = f2i8.AGENTS


def _fl12_money(db):
    """The 2I-8 fixture plus 7 catalog questions (see above)."""
    _load_fl12(db)
    SoaMerchantRevenueInputs.__table__.create(db, checkfirst=True)
    plan = ['unverifiable'] * 3 + ['exact'] * 2 + ['wrong', 'absent_no_reference']
    with db.begin() as c:
        rid = 90000
        for i, kind in enumerate(plan):
            qid = 2001 + i
            amount = None if kind == 'absent_no_reference' else '12.99'
            expected = {'type': 'price', 'amount': amount, 'currency': 'USD'}
            c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, study_pattern, "
                           "organization_id, tier, expected_answer, provenance) VALUES (:i, :c, :t, 'Ready to Buy', 'Active', "
                           ":st, 'brand_at_retail', 1, 'catalog_accuracy', :e, 'catalog')"),
                      {'i': qid, 'c': f'WSF_{qid}', 't': f'price question {qid}', 'st': f229.STUDY, 'e': _encode(expected)})
            for platform, surface, collector in AGENTS6:
                rid += 1
                c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, raw_response, "
                               "status, surface, collector, answer_status) VALUES (:r, 229, :q, :p, 1, '2026-10-14T15:00:00+00:00', "
                               "'answer', 'success', :s, :col, 'answered')"),
                          {'r': rid, 'q': qid, 'p': platform, 's': surface, 'col': collector})
                c.execute(text("INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id, platform, tier, expected_answer, "
                               "outcome, outcome_reason, flags, surface) VALUES (:r, :q, 229, :p, 'catalog_accuracy', :e, :o, 'r', "
                               "'[]', :s)"),
                          {'r': rid, 'q': qid, 'p': platform, 'e': _encode(expected), 's': surface,
                           'o': 'absent' if kind == 'absent_no_reference' else kind})
    return f2i8.CYCLE


def _revenue(http, cycle, **params):
    as_('alice')
    r = http.get('/api/console/revenue', params={'cycle': cycle, 'merchant': WS, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_fl12_s_shares_by_hand(http, db, upstream):
    cycle = _fl12_money(db)
    _supply(upstream)
    body = _revenue(http, cycle)
    assert body['measured'] is True and body['reason'] is None
    assert body['counts']['lost'] == {'n': 57, 'of': 102, 'you_first': 33}
    assert body['counts']['lost_rivals'] == [['Huggies', 30], ['Pampers', 27]]
    assert body['counts']['missed'] == {'n': 98, 'of': 132, 'unverifiable': 18}
    assert body['shares']['lost'] == pytest.approx(float(LOST))
    assert body['shares']['missed_raw'] == pytest.approx(float(RAW))
    assert body['shares']['missed'] == pytest.approx(float(MISSED))      # counted once
    lost, missed = body['drivers']
    assert (lost['kind'], lost['share'], lost['gainable']) == ('lost', pytest.approx(float(LOST)), 0.25)   # the default
    assert (missed['kind'], missed['share'], missed['gainable']) == ('missed', pytest.approx(float(MISSED)), 1.0)
    # no sales in scope yet: the shares and no dollars, with the reason
    assert body['dollars'] is False and body['dollars_reason'] == 'enter sales in scope on Impact'
    assert body['today'] is None and body['by_2030'] is None


def test_lost_s_denominator_is_visibility_s_unprompted_answers(http, db, upstream):
    cycle = _fl12_money(db)
    _supply(upstream)
    body = _revenue(http, cycle)
    as_('op')
    vis = http.get('/api/console/visibility', params={'cycle': cycle, 'org': 10}).json()
    assert body['counts']['lost']['of'] == vis['headlines']['all']['denom'] == 102
    summary = http.get('/api/console/answers/summary', params={'cycle': cycle, 'org': 10}).json()
    catalog = next(c for t in summary['tiers'] if t['tier'] == 'catalog_accuracy' for c in t['surfaces'] if c['surface'] == 'all')
    assert body['counts']['missed']['unverifiable'] == catalog['unverifiable'] == 18


@pytest.mark.parametrize('lost_gainable', [0.0, 0.25])
def test_fl12_s_dollars_at_the_defaults(http, db, upstream, lost_gainable):
    cycle = _fl12_money(db)
    _supply(upstream)
    as_('alice')
    _inputs(http, 'PUT', json={'scope_value': 4e9, 'lost_gainable': lost_gainable})
    body = _revenue(http, cycle)
    assert body['dollars'] is True and body['dollars_reason'] is None
    ai = 4e9 * 0.114
    lost_d, missed_d = ai * float(LOST) * 0.14, ai * float(MISSED) * 0.14
    t = body['today']
    assert t['ai_touched'] == pytest.approx(ai)
    assert (t['lost'], t['missed'], t['exposed']) == (pytest.approx(lost_d), pytest.approx(missed_d), pytest.approx(lost_d + missed_d))
    assert t['gainable'] == pytest.approx(missed_d + lost_d * lost_gainable)
    assert t['in_answers'] == pytest.approx(ai * float(LOST + MISSED))
    assert body['by_2030']['exposed'] == pytest.approx((lost_d + missed_d) * 0.2 / 0.114)
    # FL12's shape at $4.0B: $36M lost, $21M missed, $57M at stake, $21M gainable (+$8.9M at 25%)
    assert (round(lost_d / 1e6, 1), round(missed_d / 1e6, 1)) == (35.7, 20.9)


def test_the_driver_sentences_and_by_agent(http, db, upstream):
    cycle = _fl12_money(db)
    _supply(upstream)
    body = _revenue(http, cycle)
    lost, missed = body['drivers']
    # the recorded W&S tenant lists the merchant as a brand: the brand wording
    assert lost['title'] == 'Another brand gets the first pick'
    assert lost['measured'] == ('57 of the 102 unprompted answers put another brand first, 56%. '
                                'Huggies first in 30, Pampers in 27. Wiggle & Snug came first in 33.')
    assert missed['measured'] == ("98 of the 132 price answers got the price wrong, quoted another brand's price or left "
                                  "out the price the page had, 74%. Counted once: only for shoppers the brand choice did "
                                  "not already send elsewhere, 33%.")
    assert lost['answerId'].startswith('run-') and missed['answerId'].startswith('run-')
    assert (lost['route'], missed['route']) == ('visibility', 'true-value')
    # byAgent: each agent's share of the 57 + 98 answers that go against you
    by = {b['agent']: b for b in body['byAgent']}
    assert [b['agent'] for b in body['byAgent']] == ['chatgpt', 'gemini', 'aimode', 'perplexity', 'copilot', 'claude']
    assert sum(b['n'] for b in body['byAgent']) == body['counts']['against'] == 57 + 98
    # lost: 17 unprompted less ours first (Claude 4, AI Mode 6) less the 2 nobody leads; missed: 17 or 12, plus the new wrong
    assert by['claude']['n'] == (17 - 4 - 2) + (17 + 1) and by['aimode']['n'] == (17 - 6 - 2) + (12 + 1)
    assert by['claude']['note'] == 'Claude: 29 of the 155 answers that go against you.'
    assert sum(b['share'] for b in body['byAgent']) == pytest.approx(1.0)


def test_a_brand_merchant_reads_the_brand_wording_and_a_retailer_first_is_not_lost():
    vis = [{'answered': True, 'unprompted': True, 'agent': 'chatgpt', 'run': f'run-{i}', 'first': f}
           for i, f in enumerate([{'name': 'Huggies', 'you': False}, {'name': 'Target', 'you': False},
                                  {'name': 'Pampers', 'you': True}, None])]
    shares = revenue_svc.revenue_shares(vis, [], kind='brand')
    assert (shares['lost']['n'], shares['lost']['of']) == (1, 4)          # Target is a retailer, no brand is none
    seller = revenue_svc.revenue_shares(vis, [], kind='retailer')
    assert seller['lost']['n'] == 2                                       # a store first is lost for a store
    inputs = revenue_svc.inputs_view(None, 'pampers')
    model = revenue_svc.build_model(shares, inputs, cycle='C', kind='brand', name='Pampers', domain='pampers.com')
    assert model['drivers'][0]['title'] == 'Another brand gets the first pick'
    assert model['drivers'][0]['measured'].startswith('1 of the 4 unprompted answers put another brand first, 25%.')
    assert len(model['drivers']) == 1                                     # no price question: no Missed line


def test_the_access_line_names_the_blocked_identities(http, db, upstream):
    from tests.test_console_parity import _access_with_a_problem
    cycle = _fl12_money(db)
    _supply(upstream)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/access', body=_access_with_a_problem(), token=TOKEN_A)
    body = _revenue(http, cycle)
    a = body['access']
    assert a['n'] == 1 and a['identities'] == ['PerplexityBot']
    assert a['measured'] == 'One agent identity could not read the pages in the last access run: PerplexityBot.'.replace('One', '1')
    assert a['fix'] == 'Feeds put the offer where agents look, with no crawl needed'


def test_229_s_shares(http, db, upstream):
    _cycle_229(db)
    SoaMerchantRevenueInputs.__table__.create(db, checkfirst=True)
    _supply(upstream)
    body = _revenue(http, f229.CYCLE_229)
    # 300 unprompted answers: Pampers first in 38, Huggies 24, Pull-Ups 3; 26 uncoded and the rest name nobody
    assert body['counts']['lost'] == {'n': 65, 'of': 300, 'you_first': 0}
    # catalog: 9 exact, 32 wrong, 34 another brand's price, 37 left out (the record had 12.99); 2 errored
    assert body['counts']['missed'] == {'n': 103, 'of': 112, 'unverifiable': 0}
    assert body['shares']['missed'] == pytest.approx(103 / 112 * (1 - 65 / 300))


def test_no_unprompted_question_withholds_the_dollars_with_the_reason_never_0(http, db, upstream):
    cycle = _fl12_money(db)
    with db.begin() as c:   # every category-control question names the brand: none is unprompted
        c.execute(text("UPDATE soa_queries SET query_text = 'Is Wiggle & Snug right for me?' WHERE tier = 'category_control'"))
    _supply(upstream)
    as_('alice')
    _inputs(http, 'PUT', json={'scope_value': 4e9})
    body = _revenue(http, cycle)
    assert body['measured'] is False and body['reason'] == 'no unprompted question this cycle'
    assert body['dollars'] is False and body['dollars_reason'] == 'no unprompted question this cycle'
    assert body['drivers'] == [] and body['today'] is None and body['shares']['lost'] is None
    assert body['counts']['missed']['of'] == 132          # the price share is still counted, and shown


def test_history_over_two_cycles(http, db, upstream):
    _fl12_money(db)
    _supply(upstream)
    as_('alice')
    _inputs(http, 'PUT', json={'scope_value': 4e9})
    h = http.get('/api/console/revenue/history', params={'merchant': WS}).json()
    assert h['dollars'] is True and [c['cycle'] for c in h['cycles']] == [f229.PREVIOUS, f229.CYCLE_229]
    prev, now = h['cycles']
    # the September cycle asked no unprompted question: not measured, no dollars
    assert (prev['measured'], prev['reason'], prev['exposed']) == (False, 'no unprompted question this cycle', None)
    assert now['shares']['lost'] == pytest.approx(float(LOST)) and now['exposed'] == pytest.approx(
        4e9 * 0.114 * float(LOST + MISSED) * 0.14)


def test_revenue_is_tenant_scoped(http, db, upstream):
    cycle = _fl12_money(db)
    _supply(upstream)
    as_('bob')
    assert http.get('/api/console/revenue', params={'cycle': cycle, 'merchant': WS}).status_code == 404
    as_('alice')
    assert http.get('/api/console/revenue', params={'cycle': cycle, 'merchant': 'brandco'}).status_code == 404
