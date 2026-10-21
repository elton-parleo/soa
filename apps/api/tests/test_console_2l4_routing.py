"""
2L-4 (B2): "Where agents send <brand> shoppers first" and the Retailer
coverage input, sqlite and Postgres.

The FL13-shaped fixture (2K-4's _fl13_shape) with 10 where-to-buy and 10
cheapest-place questions added (brand-direct, source_ref.intent, as
catalog_tiers.build_intent_questions writes them), one run per agent, the AI
Mode one unanswered: 50 answers each. Each answer's Layer 2 coding
(retailer_mentions, spans) is written below; the merchant's retailers (supply's
/retailers) are Walmart, Target and Amazon, and every Target read is walled.

Where to buy, 50 answers, stores in the order the answer names them:
  20  Walmart, Target, Amazon                          first Walmart   2+
  10  Target, Walmart                                  first Target    2+
   8  Amazon, Costco                                   first Amazon
   5  Costco, Walmart, Target                          first Costco    2+
   3  coded Walmart, Target; the answer says Target first  first Target    2+
   2  Target unavailable, Amazon                       first Amazon    (Target is not sent to)
   1  no store                                         none
   1  no coding (not scored)                           uncoded
  coverage: 38 of 49 coded answers name 2 or more of the three.

Cheapest place, 50 answers: Walmart 15, Amazon 12 (as "Subscribe & Save"),
Target 10, Sam's Club 5, Kroger 4, Publix 2, eBay 1, no store 1.

First store named, of 97 answers that name one: Walmart 35, Target 23, Amazon
22, Other stores 17 (Costco 5, Sam's Club 5, Kroger 4, Publix 2, eBay 1).
"""
import json
import os

from sqlalchemy import text

from app.services import console_read_models as rm
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i9 import AGENTS6
from tests.test_console_2k4_comparable import _fl13_shape
from tests.test_console_read_models import TOKEN_A, WS_TENANT, _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

WS = 'wiggle-and-snug'
RETAILERS = {'merchant': WS, 'own_domain': 'trueshopstore.com', 'own_domains': ['trueshopstore.com'],
             'domains': ['walmart.com', 'target.com', 'amazon.com']}
REFERENCE = {'merchant': WS, 'reference_run': {'id': 7}, 'rows': [
    {'retailer_domain': 'target.com', 'read_status': 'blocked', 'price': None, 'variant_ref': 'v1'},
    {'retailer_domain': 'target.com', 'read_status': 'challenged', 'price': None, 'variant_ref': 'v2'},
    {'retailer_domain': 'walmart.com', 'read_status': 'ok', 'price': '24.99', 'variant_ref': 'v1'},
    {'retailer_domain': 'amazon.com', 'read_status': 'blocked', 'price': None, 'variant_ref': 'v1'},
    {'retailer_domain': 'amazon.com', 'read_status': 'ok', 'price': '23.49', 'variant_ref': 'v2'}]}


def _answer(stores, *, said=None, roles=None):
    """A Layer 2 coding: the stores as coded, and the answer's spans naming
    them in the order the answer does (`said`, else the coded order)."""
    roles = roles or {}
    return {'retailer_mentions': [{'name': s, 'role': roles.get(s, 'recommendation')} for s in stores],
            'spans': [{'id': i + 1, 'text': f'You can find it at {s}.'} for i, s in enumerate(said or stores)],
            'other_brands_named': []}


NONE = {'retailer_mentions': [], 'spans': [{'id': 1, 'text': 'Most stores carry it.'}], 'other_brands_named': []}
UNCODED = 'uncoded'
WHERE = ([_answer(['Walmart', 'Target', 'Amazon'])] * 20 + [_answer(['Target', 'Walmart'])] * 10
         + [_answer(['Amazon', 'Costco'])] * 8 + [_answer(['Costco', 'Walmart', 'Target'])] * 5
         + [_answer(['Walmart', 'Target'], said=['Target', 'Walmart'])] * 3
         + [_answer(['Target', 'Amazon'], roles={'Target': 'unavailable'})] * 2 + [NONE, UNCODED])
CHEAPEST = ([_answer(['Walmart', 'Amazon'])] * 15 + [_answer(['Subscribe & Save', 'Walmart'])] * 12
            + [_answer(['Target'])] * 10 + [_answer(["Sam's Club"])] * 5 + [_answer(['Kroger', 'Walmart'])] * 4
            + [_answer(['Publix'])] * 2 + [_answer(['eBay'])] + [NONE])


def _intents(db):
    """20 intent questions, one run per agent (AI Mode unanswered), and the codings above."""
    answers = {'where_to_buy': iter(WHERE), 'cheapest_place': iter(CHEAPEST)}
    with db.begin() as c:
        rid, qid = 96000, 3100
        for intent, verb in (('where_to_buy', 'Where can I buy'), ('cheapest_place', 'Cheapest place to buy')):
            for i in range(10):
                qid += 1
                ref = {'merchant_slug': WS, 'listing_id': 40 + i, 'variant_id': f'v{i}', 'intent': intent}
                c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, study_pattern, "
                               "organization_id, tier, expected_answer, provenance, source_ref) VALUES (:i, :c, :t, "
                               "'Ready to Buy', 'Active', :st, 'brand_at_retail', 1, 'brand_direct', :e, 'catalog', :r)"),
                          {'i': qid, 'c': f'WSF_{qid}', 't': f'{verb} Wiggle & Snug product {i}?', 'st': f229.STUDY,
                           'e': _encode({'type': 'brand_mention', 'brand': 'Wiggle & Snug'}), 'r': _encode(ref)})
                for platform, surface, collector in AGENTS6:
                    rid += 1
                    answered = platform != 'aimode'
                    c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, raw_response, "
                                   "status, surface, collector, answer_status) VALUES (:r, 229, :q, :p, 1, "
                                   "'2026-10-14T15:00:00+00:00', :t, :s, :surf, :col, :a)"),
                              {'r': rid, 'q': qid, 'p': platform, 't': 'an answer' if answered else '',
                               's': 'success' if answered else 'error', 'surf': surface, 'col': collector,
                               'a': 'answered' if answered else None})
                    if not answered:
                        continue
                    coding = next(answers[intent])
                    if coding == UNCODED:
                        continue
                    c.execute(text("INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id, platform, tier, "
                                   "expected_answer, outcome, outcome_reason, flags, surface, extraction) VALUES (:r, :q, 229, "
                                   ":p, 'brand_direct', :e, 'grounded', 'r', '[]', :s, :x)"),
                              {'r': rid, 'q': qid, 'p': platform, 's': surface, 'x': _encode(coding),
                               'e': _encode({'type': 'brand_mention', 'brand': 'Wiggle & Snug'})})


def _supply(upstream, tenant=WS_TENANT):
    upstream.answer('GET', '/api/truesync/tenant', body=tenant, token=TOKEN_A)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/retailers', body=RETAILERS, token=TOKEN_A)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/reference', body=REFERENCE, token=TOKEN_A)


def _get(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'cycle': f229.CYCLE_229, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _dump(name, body):
    """SOA_2L4_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2L4_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def test_the_ranking_on_the_fl13_shape_by_hand(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _intents(db)
    _supply(upstream)
    vis = _get(http, 'visibility')
    _dump('visibility-2l4.json', vis)
    routing = vis['routing']
    assert routing['title'] == 'Where agents send Wiggle & Snug shoppers first'
    assert routing['sub'] == 'First store named in 97 where-to-buy and cheapest-place answers'
    assert [(r['name'], r['first'], r.get('note')) for r in routing['rows']] == [
        ('Walmart', 35, None), ('Target', 23, 'Walled every read'), ('Amazon', 22, None),
        ('Other stores', 17, 'Costco, Sam\'s Club, Kroger, Publix, eBay')]
    assert (routing['total'], routing['answers'], routing['no_store'], routing['uncoded']) == (97, 100, 2, 1)
    assert routing['footnote'] == rm.ROUTING_FOOTNOTE
    assert routing['retailers'] == ['Walmart', 'Target', 'Amazon'] and routing['retailers_source'] == 'supply'
    assert routing['read_errors'] == {}
    # each surface's own counts add up to every agent together
    for row in routing['rows']:
        assert sum(v for s, v in row['surfaces'].items() if s != 'all') == row['first']
    assert sum(v for s, v in routing['totals'].items() if s != 'all') == 97


def test_the_coverage_ratio(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _intents(db)
    _supply(upstream)
    routing = _get(http, 'visibility')['routing']
    assert routing['coverage']['all'] == {'answers': 49, 'named_two_plus': 38}
    parts = [v for s, v in routing['coverage'].items() if s != 'all']
    assert (sum(p['answers'] for p in parts), sum(p['named_two_plus'] for p in parts)) == (49, 38)
    assert routing['coverage_line'] == '38 of 49 where-to-buy answers name 2 or more of Walmart, Target, Amazon'
    # the Overview carries the same block, the Retailer coverage tile's input
    assert _get(http, 'overview')['routing'] == routing


def test_the_order_is_the_answer_s_not_the_coding_s():
    coded = _answer(['Walmart', 'Target'], said=['Target', 'Walmart'])
    assert [s['name'] for s in rm.stores_in_order(coded)] == ['Target', 'Walmart']
    # a store the answer says is unavailable there is not one it sends the shopper to
    assert [s['name'] for s in rm.stores_in_order(_answer(['Target', 'Amazon'], roles={'Target': 'unavailable'}))] == ['Amazon']
    # an alias is its retailer
    assert rm.stores_in_order(_answer(['Subscribe & Save']))[0] == {'key': 'amazon.com', 'name': 'Amazon', 'domain': 'amazon.com'}
    assert rm.stores_in_order(None) is None


def test_a_failed_retailer_read_uses_the_study_s_list_and_says_so(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _intents(db)
    with db.begin() as c:
        config = rm._json(c.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                                    {'st': f229.STUDY}).scalar()) or {}
        config['merchant'] = {**config.get('merchant', {}), 'retailer_list': ['walmart.com', 'amazon.com']}
        c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = :t WHERE study_type = :st"),
                  {'t': _encode(config), 'st': f229.STUDY})
    upstream.answer('GET', '/api/truesync/tenant', body=WS_TENANT, token=TOKEN_A)
    routing = _get(http, 'visibility')['routing']
    assert routing['retailers_source'] == 'study' and 'retailers' in routing['read_errors']
    assert [r['name'] for r in routing['rows']] == ['Walmart', 'Amazon', 'Other stores']


def test_a_retailer_merchant_is_unaffected(http, db, upstream):
    """The W&S store: a seller. No routing, and no supply read for it."""
    _fl13_shape(db, http, upstream)
    _intents(db)
    seller = {**WS_TENANT, 'merchants': [{**WS_TENANT['merchants'][0], 'kind': 'seller'}]}
    _supply(upstream, tenant=seller)
    before = len(upstream.calls)
    vis = _get(http, 'visibility')
    assert 'routing' not in vis
    assert not [c for c in upstream.calls[before:] if c['path'].endswith(('/retailers', '/reference'))]
    assert 'routing' not in _get(http, 'overview')


def test_a_study_with_no_intent_question_reads_no_supply(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _supply(upstream)
    before = len(upstream.calls)
    assert 'routing' not in _get(http, 'visibility')
    assert upstream.calls[before:] == []
