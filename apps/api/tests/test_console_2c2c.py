"""
2C-2c: the member price, the TrueSync readback verdicts, and four leftovers,
on the production-shaped W&S fixture. Size 1 small (no GTIN) has two page
reads: Oct 14, the newest, with no member price, and Oct 9 with $12.09,
which only supply's read history (#20, retailer-prices?history=1) returns.
"""
import copy

from sqlalchemy import text

from tests.test_console_read_models import (  # noqa: F401  (pytest fixtures)
    CYCLE, TOKEN_A, _fixture, as_, db, http, upstream,
)
from tests.test_console_truesync import WS_CATALOG, read as read_truesync, supply as truesync_supply
from tests.test_console_visibility_record import (
    WS, WS_PRICE_HISTORY, WS_PRICES_PRE_20, record, ws_supply,
)
from tests.test_console_2c2a import _add, _question, _run
from app.services import console_parity as parity
from app.services import console_read_models as rm

LISTING_90 = next(l for l in WS_CATALOG['listings'] if l['listing_id'] == 90)
S1 = 'snug-fit-diapers-s1-small'


# ═══ 1. The member price reaches the read that states it ═════════════════

def test_the_record_reads_the_member_price_from_supply_s_read_history(http, upstream):
    """Live: no Member+ price for Size 1 small, although 7 of 19 pages state
    one. The newest read of its page (Oct 14) states none; the Oct 9 read
    did, and /reference returns only the newest read per page."""
    ws_supply(upstream)
    as_('alice')
    body = record(http, str(LISTING_90['product_id']))
    s1 = next(v for v in body['variants'] if v['id'] == S1)
    assert s1['price'] == '$17.99 · member $12.09, from the page read Oct 9'
    prices = [c for c in upstream.calls if c['path'].endswith('/retailer-prices')]
    # the member-price read asks for history; 2G's availability read is the plain one
    assert {'history': '1', 'limit': '10'} in [c['params'] for c in prices]


def test_a_supply_before_20_falls_back_to_the_newest_read(http, upstream):
    """Before #20 supply ignores `history` and answers one row per page with
    no `history: true`: the rule reads /reference as before, and says nothing
    it does not have."""
    ws_supply(upstream)
    upstream.answer('GET', f'{WS}/retailer-prices', body=WS_PRICES_PRE_20, token=TOKEN_A)
    as_('alice')
    body = record(http, str(LISTING_90['product_id']))
    s1 = next(v for v in body['variants'] if v['id'] == S1)
    assert s1['price'] == '$17.99' and s1['member_price'] is None
    assert 'retailer_prices' not in body['read_errors']


def test_the_ladder_takes_the_same_history():
    entry = next(l for l in _incentives()['listings'] if l['listing_id'] == 90)
    ladder, receipt = parity.build_ladder({'listings': [LISTING_90]}, {'listings': [entry]}, [],
                                          [{'variant_id': S1}], own_domain='trueshopstore.com',
                                          reads=_fixture('supply_reference_ws.json')['rows'],
                                          member_reads=WS_PRICE_HISTORY['prices'])
    assert (ladder['steps'][-1]['value'], ladder['steps'][-1]['note']) == ('$12.09', 'from the page read Oct 9')
    assert receipt['rows'][-1]['v'] == '$12.09'


def _incentives():
    from tests.test_console_visibility_record import WS_INCENTIVES
    return WS_INCENTIVES


# ═══ 2. A swap is graded by the question, against the asked variant ══════

SWAP_OLD = {'stated': '6.99', 'amount': '6.99', 'product': 'Snug-Fit Trial Pack', 'tier': None,
            'conflict': 'names a sibling variant', 'target': 'swap', 'variant_id': 'snug-fit-trial-pack',
            'same_group': False, 'outcome': 'exact', 'matched_at': None, 'against': '6.99', 'question_outcome': 'wrong'}
SWAP_NEW = {**{k: v for k, v in SWAP_OLD.items() if k != 'question_outcome'}, 'outcome': 'wrong', 'priced_as_named': True}


def _trial_pack_question(db):
    _question(db, 110, 'catalog_accuracy', 'What does the Wiggle & Snug Snug-Fit Trial Pack cost?',
              {'type': 'price', 'amount': '6.99', 'currency': 'USD'},
              {'merchant_slug': 'wiggle-and-snug', 'listing_id': 94, 'variant_id': 'snug-fit-trial-pack'})


def test_the_readback_grades_a_swap_wrong_against_the_asked_variant(http, db):
    """Live: nine Trial Pack quotes graded Right, "judged against $6.99", on
    the Snug-Fit Diapers readback, while True Value grades them wrong."""
    _trial_pack_question(db)
    expected = {'type': 'price', 'amount': '22.99', 'currency': 'USD'}
    _run(db, 2401, 4, 'gemini_grounded', 'catalog_accuracy', 'wrong', [SWAP_OLD], reason='variant_swap', expected=expected)
    _run(db, 2402, 4, 'gemini_grounded', 'catalog_accuracy', 'wrong', [SWAP_NEW], reason='variant_swap', expected=expected)
    as_('alice')
    answers = {a['id']: a for a in http.get('/api/console/answers', params={'cycle': CYCLE}).json()}
    for rid in ('run-2401', 'run-2402'):
        [c] = answers[rid]['checks']
        assert (c['claim'], c['live'], c['verdict'], c['reason']) == ('$6.99 for Snug-Fit Trial Pack', '$22.99', 'wrong', 'variant_swap')
        assert c['note'] == 'priced Snug-Fit Trial Pack instead'
    tv = http.get('/api/console/true-value', params={'cycle': CYCLE}).json()
    s3 = next(r for r in tv['rows'] if r['sku'] == 'snug-fit-diapers-s3-small')
    gem = s3['cells']['gemini']
    assert (gem['status'], gem['live']) == ('wrong', '$22.99')        # the same verdict, the same reference


def test_a_clash_is_judged_against_the_asked_variant_too():
    clash = {'stated': '9.99', 'amount': '9.99', 'product': 'Size 3 jumbo', 'target': 'clash', 'outcome': 'wrong',
             'reason': 'names a sibling variant, and the record has no such variant', 'reason_code': 'variant_clash'}
    a = rm.build_answer({'id': 1, 'platform': 'chatgpt', 'run_number': 1, 'answer_status': 'answered', 'raw_response': 'x'},
                        {'tier': 'catalog_accuracy', 'query_text': 'q'},
                        {'outcome': 'wrong', 'claim_results': [clash], 'expected_answer': {'type': 'price', 'amount': '22.99', 'currency': 'USD'}},
                        [], runs_per_query=1, cycle_code='C')
    assert (a['checks'][0]['live'], a['checks'][0]['reason']) == ('$22.99', 'variant_clash')


# ═══ 3. No check row is blank on both sides ══════════════════════════════

def test_a_check_with_no_claim_says_what_was_expected():
    """Live: six readback rows read "— — Wrong" / "— — Right": a run with no
    stored claim whose expectation has no `amount` (a code or points
    question) printed a dash for the reference."""
    code = {'type': 'code', 'code': 'SNUG3', 'value_kind': 'amount_off', 'value': '3.00'}
    a = rm.build_answer({'id': 1, 'platform': 'chatgpt', 'run_number': 1, 'answer_status': 'answered', 'raw_response': 'x'},
                        {'tier': 'value_incentives', 'query_text': 'q'},
                        {'outcome': 'exact', 'claim_results': [], 'expected_answer': code}, [], runs_per_query=1, cycle_code='C')
    [c] = a['checks']
    assert c['claim'] == '—' and c['live'] != '—' and 'SNUG3' in c['live']


# ═══ 4. The publish timeline comes with the matrix ═══════════════════════

def test_each_truesync_product_carries_its_timeline(http, upstream):
    """Live: "Reading the journal…" for a whole visit: the console read the
    full record per product (sixteen supply reads) to draw a timeline the
    matrix's own reads already hold."""
    truesync_supply(upstream)
    body = read_truesync(http)
    p = next(x for x in body['products'] if x['listing_id'] == 93)
    assert p['timeline'] and {e['kind'] for e in p['timeline']} <= {'publication', 'verification'}
    assert p['timeline'] == sorted(p['timeline'], key=lambda e: e['at'] or '', reverse=True)
    assert not any(c['path'].endswith('/reference') or c['path'].endswith('/incentives') for c in upstream.calls)


# ═══ 5. Swap quotes grouped by the sibling, named once ═══════════════════

def test_swap_quotes_group_by_the_resolved_sibling(http, upstream, db):
    """Live, Size 4 small: "$6.99 for Snug-Fit Trial Pack, 2 of 6" and "$6.99
    for Wiggle & Snug Snug-Fit Trial Pack, 1 of 6" as two lines."""
    _trial_pack_question(db)
    other = {**SWAP_OLD, 'product': 'Wiggle & Snug Snug-Fit Trial Pack'}
    for rid, claim in ((2501, SWAP_OLD), (2502, SWAP_OLD), (2503, other)):
        _run(db, rid, 4, 'gemini_grounded', 'catalog_accuracy', 'wrong', [claim], reason='variant_swap')
    ws_supply(upstream)
    upstream.answer('GET', f'{WS}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)
    as_('alice')
    body = http.get('/api/console/overview', params={'cycle': CYCLE, 'merchant': 'wiggle-and-snug'}).json()
    s3 = next(p for p in body['by_surface']['grounded_api']['products'] if p['sku'] == 'snug-fit-diapers-s3-small')
    assert s3['quoted'] == '$6.99 for Snug-Fit Trial Pack, 3 of 4 runs (Gemini 3). $9.99, 1 of 4 runs (ChatGPT 1)'
    assert sum(g['runs'] for g in s3['quote_groups']) == s3['runs']


# ═══ 6. Studies: branded by tier, one question count, status by cycles ═══

def test_studies_count_by_tier_and_take_their_status_from_cycles(http, db):
    _question(db, 120, None, 'What are the best diapers for a newborn?', {}, {}, stage='Awareness')
    as_('alice')
    [study] = http.get('/api/console/studio/studies').json()
    assert study['prompt_counts'] == {'branded': 6, 'unbranded': 1, 'prompts': 7}
    assert study['status'] == 'done'                     # one complete cycle
    overview = http.get('/api/console/overview', params={'cycle': CYCLE}).json()
    assert (overview['coverage']['questions'], overview['coverage']['asked']) == (7, 6)
    _add(db, 'soa_cycles', {'id': 2, 'cycle_code': 'WS-NEXT', 'study_type': 'ws-2b-fixture', 'status': 'running',
                            'start_date': '2026-10-16', 'platforms': ['chatgpt'], 'runs_per_query': 1, 'organization_id': 1})
    assert http.get('/api/console/studio/studies').json()[0]['status'] == 'active'
    assert rm.study_status([]) == 'draft'


# ═══ 7. The Answers strip counts every tier by the run rule ══════════════

def test_the_answers_strip_counts_runs_and_answers_over_every_tier(http, db):
    """Live: "450 runs, 450 answered" beside 516 answers: the strip read the
    value tiers only (516 - 66 brand-direct)."""
    with db.begin() as c:
        c.execute(text("UPDATE soa_runs SET status = 'error', answer_status = NULL WHERE id = 1003"))
    as_('alice')
    body = http.get('/api/console/answers/summary', params={'cycle': CYCLE}).json()
    every = {s['surface']: (s['runs'], s['answered']) for s in body['all_tiers']}
    assert every == {'all': (8, 6), 'grounded_api': (7, 6), 'consumer_ui': (1, 0)}   # 2I-8: `all` first
    value = {s['surface']: s['runs'] for s in body['surfaces']}
    assert value == {'all': 6, 'grounded_api': 5, 'consumer_ui': 1}          # brand-direct is not a price question
