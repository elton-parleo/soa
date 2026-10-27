"""
2T-4 (2): severity by verdict, not by question group.

FL15's Answers (Oct 26, org 12) read "395 shown, worst first" with well over
100 High: exact prices, cheapest-place answers "with no deal live for this SKU
that day", "no reference row for this page", every where-to-buy answer naming
fewer than two retailers. Each was High because an answer flag
(fabricated_availability, a store off the question's list) overrode the
answer's own verdict. soa_shared/severity.classify is now the one rule, read
by /answers, /answers/summary's `severity`, the brand Overview's `flagged` and
the narratives' flag rule.

  * one case per bullet, through classify;
  * a brand's fabricated_availability never counts (2T-4 (1)), a seller's does;
  * on 2P-1's pair, cycle 2 FL15-shaped: the flags coder 7 stored, DERIVED
    here from each answer's own stored stores against its question's retailer
    list (coder 7's rule: any store off the list raised it). On main every
    such answer read High; now each reads its verdict's severity;
  * /answers/summary's and the brand Overview's counts are /answers' own;
  * a value answer's severity is its outcome's, never its last claim's (the
    answer row read `raw` after the claims loop had reused it).

Nothing is read from production and no model is called.
"""
import json
from collections import Counter

import pytest
from sqlalchemy import text

from app.services import console_read_models as rm
from soa_shared import severity as sev
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import _get, _pair
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)

V, B = 'catalog_accuracy', 'brand_direct'


# ── one case per bullet ───────────────────────────────────────────────────

@pytest.mark.parametrize('kw,want', [
    # High
    ({'tier': V, 'outcome': 'wrong'}, (sev.HIGH, sev.WRONG_PRICE)),
    ({'tier': V, 'outcome': 'stale'}, (sev.HIGH, sev.WRONG_PRICE)),
    ({'tier': V, 'outcome': 'wrong', 'reason_code': 'variant_clash'}, (sev.HIGH, sev.WRONG_PRICE)),
    ({'tier': B, 'intent': 'attribute', 'intent_verdict': 'mismatch'}, (sev.HIGH, sev.WRONG_FACT)),
    ({'tier': B, 'outcome': 'fabricated'}, (sev.HIGH, sev.WRONG_FACT)),
    ({'tier': B, 'outcome': 'misattributed'}, (sev.HIGH, sev.WRONG_FACT)),
    ({'tier': B, 'intent': 'retired', 'retired_called_current': True}, (sev.HIGH, sev.RETIRED_CURRENT)),
    ({'tier': B, 'intent': 'retired', 'intent_verdict': 'no_successor'}, (sev.HIGH, sev.NO_SUCCESSOR)),
    ({'tier': B, 'intent': 'where_to_buy', 'intent_verdict': 'partial', 'club_only': True, 'first_store_club': False},
     (sev.HIGH, sev.CLUB_ELSEWHERE)),
    ({'tier': 'comparison', 'outcome': None, 'brand_in_question': True, 'brand_first': False},
     (sev.HIGH, sev.BRAND_NOT_FIRST)),
    ({'tier': B, 'outcome': 'grounded', 'flags': [{'flag': 'fabricated_citation'}]}, (sev.HIGH, sev.FABRICATED)),
    ({'tier': V, 'outcome': 'exact', 'flags': [{'flag': 'fabricated_availability'}], 'merchant_kind': 'seller'},
     (sev.HIGH, sev.FABRICATED)),
    # Medium
    ({'tier': B, 'intent': 'cheapest_place', 'intent_verdict': 'missed_deal'}, (sev.MEDIUM, sev.MISSED_DEAL)),
    ({'tier': B, 'intent': 'where_to_buy', 'intent_verdict': 'partial', 'listed': 4}, (sev.MEDIUM, sev.FEWER_RETAILERS)),
    ({'tier': B, 'intent': 'attribute', 'intent_verdict': 'absent'}, (sev.MEDIUM, sev.NO_WEIGHT)),
    ({'tier': V, 'outcome': 'partial'}, (sev.MEDIUM, sev.PARTIAL_PRICE)),
    # not flagged
    ({'tier': V, 'outcome': 'exact', 'flags': [{'flag': 'fabricated_availability'}], 'merchant_kind': 'brand'},
     (sev.OK, sev.RIGHT)),
    ({'tier': B, 'intent': 'cheapest_place', 'intent_verdict': 'no_deal_live',
      'flags': [{'flag': 'fabricated_availability'}], 'merchant_kind': 'brand'}, (sev.LOW, sev.NO_DEAL_LIVE)),
    ({'tier': V, 'outcome': 'unverifiable'}, (sev.LOW, sev.UNCHECKED)),
    ({'tier': B, 'outcome': 'grounded', 'flags': [{'flag': 'fabricated_availability'}]}, (sev.OK, sev.RIGHT)),
    ({'tier': B, 'outcome': 'unverified'}, (sev.LOW, sev.UNVERIFIED)),
    ({'tier': B, 'intent': 'where_to_buy', 'intent_verdict': 'covered'}, (sev.OK, sev.RIGHT)),
    ({'tier': B, 'intent': 'where_to_buy', 'intent_verdict': 'partial', 'listed': 1}, (sev.LOW, sev.NOT_FLAGGED)),
    ({'tier': B, 'intent': 'where_to_buy', 'intent_verdict': 'partial', 'club_only': True, 'first_store_club': True,
      'listed': 1}, (sev.LOW, sev.NOT_FLAGGED)),
    ({'tier': 'comparison', 'outcome': None, 'brand_in_question': False, 'brand_first': False},
     (sev.LOW, sev.NOT_FLAGGED)),
    # 2T-5 (A5b): the agent said it could not find the product
    ({'tier': B, 'outcome': 'acknowledged_unknown'}, (sev.MEDIUM, sev.COULD_NOT_FIND)),
    ({'tier': B, 'outcome': 'acknowledged_unknown', 'intent': 'where_to_buy', 'intent_verdict': 'partial', 'listed': 1},
     (sev.MEDIUM, sev.COULD_NOT_FIND)),
    # an answer right on its own verdict stays right
    ({'tier': B, 'outcome': 'acknowledged_unknown', 'intent': 'where_to_buy', 'intent_verdict': 'covered'},
     (sev.OK, sev.RIGHT)),
])
def test_one_case_per_bullet(kw, want):
    out = sev.classify(**{'outcome': None, **kw})
    assert (out['severity'], out['rule']) == want


def test_a_page_we_could_not_check_is_listed_not_flagged():
    out = sev.classify(tier=V, outcome='unverifiable')
    assert out['could_not_check'] == 'unverifiable' and not sev.is_flagged(out['severity'])


def test_a_brands_store_flag_never_counts():
    flags = [{'flag': 'fabricated_availability'}, {'flag': 'variant_swap'}]
    assert [f['flag'] for f in sev.counted_flags(flags, 'brand')] == ['variant_swap']
    assert [f['flag'] for f in sev.counted_flags(flags, None)] == ['variant_swap']
    assert [f['flag'] for f in sev.counted_flags(flags, 'seller')] == ['fabricated_availability', 'variant_swap']


def test_the_sync_copies_are_identical():
    import filecmp
    import os
    root = os.path.join(os.path.dirname(__file__), '..', '..', '..')
    for module in ('severity.py', 'narratives.py'):
        assert filecmp.cmp(os.path.join(root, 'apps/api/soa_shared', module),
                           os.path.join(root, 'apps/pipeline/soa_shared', module), shallow=False), module


# ── a value answer reads its own outcome ──────────────────────────────────

def test_the_severity_is_the_answers_outcome_never_its_last_claims():
    run = {'id': 1, 'platform': 'chatgpt', 'run_number': 1, 'run_at': None, 'answer_status': 'answered',
           'raw_response': 'It costs $21.49, or $27.97 for the big box.'}
    query = {'tier': V, 'query_text': 'What does the Acme Swaddle cost at Target?', 'source_ref': {}}
    outcome = {'outcome': 'wrong', 'expected_answer': {'type': 'price', 'amount': '27.97', 'attributed_to': 'target.com'},
               'claim_results': [{'stated': '21.49', 'outcome': 'wrong', 'target': 'asked'},
                                 {'stated': '27.97', 'outcome': 'exact', 'target': 'asked'}],
               'extraction': {}, 'flags': []}
    a = rm.build_answer(run, query, outcome, [], runs_per_query=1, cycle_code='c')
    assert (a['severity'], a['severity_rule']) == ('high', sev.WRONG_PRICE)


# ── the FL15 shape: coder 7's store flags, derived ────────────────────────

def _coder7_flags(db, cycle_id) -> int:
    """FL15's shape on cycle 2, DERIVED from the fixture's own rows and said so. Production's catalog-built
    questions carry the brand's record (catalog_tiers.external_ref: merchant_kind, retailer_list); the
    fixture's carry none, so each is given the list the fixture's own priced questions carry. Then coder 7's
    fabricated_availability on every answer that named a store off its question's list (stores_in_order over
    the stored extraction, the own domain allowed): the flag FL15's rows carried. Returns how many it flagged."""
    n = 0
    with db.begin() as c:
        rows = c.execute(text("""SELECT o.run_id, o.extraction, o.flags, q.id AS query_id, q.source_ref
                                 FROM soa_expectation_outcomes o JOIN soa_runs r ON r.id = o.run_id
                                 JOIN soa_queries q ON q.id = r.query_id WHERE o.cycle_id = :c"""),
                         {'c': cycle_id}).mappings().all()
        record = next(ref for ref in (rm._json(r['source_ref']) or {} for r in rows) if 'retailer_list' in ref)
        record = {k: record.get(k) for k in ('merchant_kind', 'retailer_list', 'own_domain')}
        done = set()
        for r in rows:
            ref = rm._json(r['source_ref']) or {}
            if ref.get('intent') and 'retailer_list' not in ref:
                ref = {**ref, **record}
                if r['query_id'] not in done:
                    c.execute(text("UPDATE soa_queries SET source_ref = :s WHERE id = :q"),
                              {'s': json.dumps(ref), 'q': r['query_id']})
                    done.add(r['query_id'])
            if 'retailer_list' not in ref:
                continue
            allowed = set(ref['retailer_list']) | {ref.get('own_domain')}
            off = [st for st in rm.stores_in_order(rm._json(r['extraction'])) or []
                   if st.get('domain') and st['domain'] not in allowed]
            if not off:
                continue
            flags = [f for f in rm._json(r['flags']) or [] if f.get('flag') != 'fabricated_availability']
            flags.append({'flag': 'fabricated_availability', 'retailers': [{'name': st['name'], 'domain': st['domain']}
                                                                           for st in off], 'unrecognised': []})
            c.execute(text("UPDATE soa_expectation_outcomes SET flags = :f WHERE run_id = :r"),
                      {'f': json.dumps(flags), 'r': r['run_id']})
            n += 1
    return n


#: cycle 2 with the derived flags, 66 answers flagged. main (6f88ee1, this branch's base) read it
#: {'high': 140, 'medium': 14, 'ok': 126, 'low': 572}: the 66 all High, 20 of them where-to-buy answers that
#: named two or more of the brand's retailers, 24 that named one, 22 cheapest-place with no deal live.
NOW = {'high': 75, 'medium': 29, 'ok': 146, 'low': 602}
#: 2T-5 (A5b): the 12 brand-direct answers saying they could not find the product are Medium (2T-4: low)
NOW = {**NOW, 'medium': NOW['medium'] + 12, 'low': NOW['low'] - 12}
#: what each of the 66 reads now
FLAGGED_NOW = {('ok', 'covered'): 20, ('medium', 'partial'): 24, ('low', 'no_deal_live'): 22}


def test_fl15_shape_the_flags_no_longer_decide(http, db, upstream):
    _pair(db, http, upstream)
    assert _coder7_flags(db, f2p1.ID_2) == 66
    answers = _get(http, 'answers')
    assert len(answers) == 852 and dict(Counter(a['severity'] for a in answers)) == NOW
    tally = sev.tally(answers)
    assert (tally['high'], tally['medium'], tally['right'], tally['flagged']) == (75, 41, 146, 116)
    assert dict(Counter((a['severity'], a['intent_verdict']) for a in answers
                        if 'fabricated_availability' in a['flags'])) == FLAGGED_NOW
    # the summary's counts are the list's
    assert _get(http, 'answers/summary')['severity'] == tally


# ── the brand Overview's flagged counts are the list's ────────────────────

def test_the_brand_overviews_flagged_counts_are_the_answers_list(http, db, upstream):
    from tests.test_console_2t1_overview_truesync import _overview, _read, _shape
    _shape(db, http, upstream)
    flagged = _overview(http)['flagged']
    answers = _read(http, 'answers', cycle=f2p1.CYCLE_2)
    assert flagged == sev.tally(answers) and flagged['shown'] == len(answers) == 852
    assert flagged['flagged'] == flagged['high'] + flagged['medium']
