"""
2E: the three dimensions 2C-3 left unmeasured, on the 229-shaped fixture.

Protocol & Feed Presence and Value Protocols come from the cycle's stored
domain checks (soa_cycles.domain_checks), a record the worker writes with
the Audit's own functions: the two records read here are that code's output
(apps/pipeline/tests/test_domain_checks.py writes and pins them). Deal
Citability's seen half comes from supply #21's incentive_in_markup on the
reference read. Every test runs on sqlite and on a local Postgres (the db
fixture of test_console_2c3a).
"""
import copy
import json

import pytest
from sqlalchemy import text

from app.services import console_score as score_svc
from clients import truesync_client as supply_fields
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import _cycle_229, _get, _stored, db  # noqa: F401  (db is a fixture)
from tests.test_console_read_models import TOKEN_A, _fixture, as_, http, upstream  # noqa: F401
from tests.test_console_visibility_record import WS, WS_REFERENCE, ws_supply

NONE = _fixture('domain_checks_ws_none.json')
FULL = _fixture('domain_checks_ws_full.json')


def reference_2a3(scanned=19):
    """The Oct 14 reads as supply #21 serves them: every readable row carries
    incentive_in_markup. member_price where the read has one (parse.py takes
    it from JSON-LD only), a promo in markup (validThrough) on three pages
    that have none, no offer_text anywhere; the first
    `scanned` rows were read after 2A-3 (json_ld_scanned), the rest before."""
    ref = copy.deepcopy(WS_REFERENCE)
    promo_left = 3
    for i, row in enumerate(ref['rows']):
        member = row.get('member_price') not in (None, '')
        promo = not member and promo_left > 0
        promo_left -= promo
        row['offer_text'] = None
        row['incentive_in_markup'] = {'member_price': member, 'promo': promo, 'subscription': False, 'code': False,
                                      'source': 'json_ld' if member or promo else 'none',
                                      'json_ld_scanned': i < scanned}
    return ref


def _supply(upstream, reference=None):
    ws_supply(upstream, reference=reference if reference is not None else WS_REFERENCE)
    upstream.answer('GET', f'{WS}/access', body=_fixture('supply_access_ws.json'), token=TOKEN_A)


def _with_domain_checks(db, record=None):
    kind = 'JSON' if db.dialect.name == 'postgresql' else 'TEXT'
    with db.begin() as c:
        c.exec_driver_sql(f"ALTER TABLE soa_cycles ADD COLUMN domain_checks {kind}")   # b4e8f1c3a9d2
        if record is not None:
            c.execute(text("UPDATE soa_cycles SET domain_checks = :j WHERE id = 229"), {'j': json.dumps(record)})


def _set_domain_checks(db, record):
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET domain_checks = :j WHERE id = 229"), {'j': json.dumps(record)})


def _dims(body):
    return {d['code']: d for p in body['pillars'] for d in p['dimensions']}


# ═══ supply #21's fields, read tolerantly ════════════════════════════════

def test_a_row_with_the_field_is_read():
    row = reference_2a3()['rows'][0]
    assert supply_fields.incentive_in_markup(row) == {**row['incentive_in_markup']}


@pytest.mark.parametrize('row', [{}, {'incentive_in_markup': None}, {'incentive_in_markup': 'yes'}, None, 'x'])
def test_a_row_without_the_field_is_not_measured_never_an_error(row):
    assert supply_fields.incentive_in_markup(row) is None


def test_a_flag_that_is_not_true_is_false_and_an_unknown_source_is_none():
    m = supply_fields.incentive_in_markup({'incentive_in_markup': {'promo': 'yes', 'source': 'html'}})
    assert m == {'member_price': False, 'promo': False, 'subscription': False, 'code': False, 'source': None,
                 'json_ld_scanned': False}


def test_an_older_supply_carries_no_fields():
    assert supply_fields.carries_incentive_fields(WS_REFERENCE['rows']) is False
    assert supply_fields.carries_incentive_fields(reference_2a3()['rows']) is True
    assert supply_fields.carries_incentive_fields([{'incentive_in_markup': None}]) is True


def test_the_robots_roll_up_and_token_rules():
    payload = {'robots_by_domain': [
        {'retailer_domain': 'trueshopstore.com', 'robots_url': 'https://trueshopstore.com/robots.txt', 'robots_status': 'ok',
         'robots_names_agents': {'answer_time_tokens_named': 5, 'answer_time_tokens_total': 7, 'wildcard_only': False}},
        {'retailer_domain': 'target.com', 'robots_status': 'challenged',
         'robots_names_agents': {'answer_time_tokens_named': None, 'answer_time_tokens_total': 7, 'wildcard_only': False}},
        'junk']}
    assert supply_fields.robots_by_domain(payload) == [
        {'retailer_domain': 'trueshopstore.com', 'robots_url': 'https://trueshopstore.com/robots.txt',
         'robots_status': 'ok', 'named': 5, 'total': 7, 'wildcard_only': False},
        {'retailer_domain': 'target.com', 'robots_url': None, 'robots_status': 'challenged', 'named': None,
         'total': 7, 'wildcard_only': False}]
    assert supply_fields.robots_by_domain({}) is None and supply_fields.robots_by_domain({'robots_by_domain': []}) == []
    row = {'detail': {'tokens': [{'token': 'OAI-SearchBot', 'verdict': 'allow', 'rule_source': 'token',
                                  'matched_rule': 'Allow: /', 'agents': ['chatgpt'], 'answer_time': True}]}}
    assert supply_fields.token_rules(row) == [{'token': 'OAI-SearchBot', 'verdict': 'allow', 'rule_source': 'token',
                                               'matched_rule': 'Allow: /'}]
    assert supply_fields.token_rules({'detail': {}}) is None


# ═══ the three dimensions ════════════════════════════════════════════════

def test_with_everything_measured_the_applicable_max_is_100_and_the_verdict_applies(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, FULL)
    _supply(upstream, reference_2a3())
    body = _get(http).json()
    dims = _dims(body)
    assert {c: d['state'] for c, d in dims.items()} == {c: 'measured' for c in dims}
    assert body['applicable_max'] == 100.0
    # 22.3 (2C-3's six) + 3.8 + 14 + Deal Citability 3.7 + 5.0
    assert dims['protocol_feed']['score'] == 3.8 and dims['value_protocols']['score'] == 14.0
    seen, said = dims['deal_citability']['parts']
    assert (seen['numerator'], seen['denominator'], seen['score']) == (10, 19, 3.7)   # 7 member price + 3 promo
    assert seen['line'] == 'Incentive in markup 10 of 19 pages'
    assert said['score'] == 5.0                                                       # 9 of 12, the v6 rate
    assert body['earned'] == 48.8 and body['score'] == 49
    assert body['verdict'] == 'NOT AGENT-READY' and body['verdict_note'] is None
    assert body['measured'] == [d.code for d in score_svc.DIMENSIONS]


def test_an_older_supply_leaves_deal_citability_unmeasured_applicable_88(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, FULL)
    _supply(upstream)                              # the Oct 14 reads, before #21
    body = _get(http).json()
    dc = _dims(body)['deal_citability']
    assert dc['state'] == 'not_measured'
    assert dc['parts'][0]['reason'] == 'supply serves no incentive in markup on its page reads (a supply before #21)'
    assert dc['parts'][1]['state'] == 'measured'   # said computed, shown, uncounted
    assert body['applicable_max'] == 88.0
    assert (body['earned'], body['score']) == (40.1, 46)         # 22.3 + 3.8 + 14, of 88
    assert body['verdict'] is None
    assert body['verdict_note'] == ('No readiness verdict while 12 of 100 points are not measured. '
                                    'The Audit gives one only when every dimension is.')


def test_reads_not_yet_scanned_count_as_not_scanned_never_as_false(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, FULL)
    _supply(upstream, reference_2a3(scanned=10))
    seen = _dims(_get(http).json())['deal_citability']['parts'][0]
    ref = reference_2a3(scanned=10)['rows']
    hits = sum(1 for r in ref[:10] if any(r['incentive_in_markup'][f] for f in supply_fields.INCENTIVE_FLAGS))
    assert (seen['numerator'], seen['denominator']) == (hits, 10)


def test_no_read_scanned_yet_is_not_measured_with_the_reason(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, FULL)
    _supply(upstream, reference_2a3(scanned=0))
    dc = _dims(_get(http).json())['deal_citability']
    assert dc['state'] == 'not_measured'
    assert dc['parts'][0]['reason'].startswith('no page read has had its markup scanned for incentives yet')


def test_the_domain_checks_carry_the_audits_sub_check_names(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, NONE)
    _supply(upstream, reference_2a3())
    dims = _dims(_get(http).json())
    pf, vp = dims['protocol_feed'], dims['value_protocols']
    assert (pf['state'], pf['score'], vp['state'], vp['score']) == ('measured', 0.0, 'measured', 0.0)
    assert [(c['label'], c['state']) for c in pf['parts'][0]['checks']] == [
        ('llms.txt', 'fail'), ('MCP declaration', 'fail'), ('a UCP profile exists', 'fail')]
    assert [c['label'] for c in vp['parts'][0]['checks']] == list(score_svc.DIMENSIONS_BY_CODE['value_protocols'].how_measured)
    assert {c['state'] for c in vp['parts'][0]['checks']} == {'na'}          # no manifest: none of them ran
    assert pf['parts'][0]['line'] == 'Protocol checks passed 0 of 3'
    assert vp['parts'][0]['line'] == 'no protocol profile found'
    assert pf['source'] == 'domain checks on trueshopstore.com, 2026-10-16'


def test_a_brand_only_site_is_the_audits_na_and_leaves_the_applicable_max(http, upstream, db):
    record = copy.deepcopy(FULL)
    record['protocol_feed'] = {**record['protocol_feed'], 'score': 0.0, 'coverage': 'na',
                               'evidence': ['protocol & feed presence is not applicable — no cart, commerce paths, '
                                            'platform markers, or Offer markup found']}
    _cycle_229(db)
    _with_domain_checks(db, record)
    _supply(upstream, reference_2a3())
    body = _get(http).json()
    pf = _dims(body)['protocol_feed']
    assert (pf['state'], pf['applicable_max']) == ('na', 0.0)
    assert body['applicable_max'] == 95.0 and body['verdict'] is not None     # na does not withhold it


def test_without_the_column_the_two_read_not_measured_as_before(http, upstream, db):
    _cycle_229(db)
    _supply(upstream, reference_2a3())
    body = _get(http).json()
    dims = _dims(body)
    assert dims['protocol_feed']['reason'] == 'no domain checks on this cycle yet'
    assert dims['value_protocols']['state'] == 'not_measured'
    assert body['applicable_max'] == 81.0      # Deal Citability measured from supply, the domain two not
    assert body['verdict_note'].startswith('No readiness verdict while 19 of 100 points are not measured.')


# ═══ the score of record: the second recompute trigger ═══════════════════

def test_domain_checks_stored_after_the_score_recompute_it_once_and_keep_the_old_value(http, upstream, db, monkeypatch):
    _cycle_229(db)
    _with_domain_checks(db)                        # the column, still NULL: 229 before run_domain_checks.py
    _supply(upstream, reference_2a3())
    computed = []
    real = score_svc.build_score
    monkeypatch.setattr(score_svc, 'build_score', lambda *a, **k: computed.append(1) or real(*a, **k))
    first = _get(http).json()
    assert first['applicable_max'] == 81.0 and 'protocol_feed' not in first['measured']
    assert _get(http).json()['score'] == first['score'] and len(computed) == 1     # served from the row

    _set_domain_checks(db, FULL)                    # Elton runs run_domain_checks.py
    second = _get(http).json()
    assert len(computed) == 2
    assert second['applicable_max'] == 100.0
    assert [h['score'] for h in second['history']] == [first['score']]
    assert second['history'][0]['replaced_because'] == 'measured set changed'
    assert second['history'][0]['applicable_max'] == 81.0
    raw, _ = _stored(db)
    assert (raw if isinstance(raw, dict) else json.loads(raw))['history'] == second['history']
    assert _get(http).json()['score'] == second['score'] and len(computed) == 2     # and served again


def test_the_same_measured_set_does_not_recompute():
    stored = {'scorer_version': score_svc.SCORER_VERSION, 'adapter_revision': score_svc.ADAPTER_REVISION,
              'measured': ['agent_access', 'protocol_feed', 'value_protocols']}
    assert score_svc.needs_recompute(stored, FULL) is None
    assert score_svc.needs_recompute(stored, None) == 'measured set changed'
    assert score_svc.needs_recompute({**stored, 'scorer_version': '5'}, FULL) == 'stale'
    assert score_svc.needs_recompute(None, FULL) == 'first read'


def test_history_is_kept_newest_last_and_bounded():
    old = {'score': 30, 'earned': 20.3, 'applicable_max': 69.0, 'measured': ['a'], 'scorer_version': '6',
           'adapter_revision': 1, 'inputs': {'scored_at': 't0'},
           'history': [{'score': i} for i in range(score_svc.HISTORY_KEEP)]}
    new = score_svc.carry_history({'score': 49, 'history': []}, old, 'stale')
    assert len(new['history']) == score_svc.HISTORY_KEEP
    assert new['history'][-1] == {'score': 30, 'earned': 20.3, 'applicable_max': 69.0, 'measured': ['a'],
                                  'scorer_version': '6', 'adapter_revision': 1, 'scored_at': 't0', 'pillars': [],
                                  'replaced_because': 'stale'}


# ═══ comparability: applicable points changed ════════════════════════════

def _store_on_previous(db, body):
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = :v WHERE id = 178"),
                  {'b': json.dumps(body), 'v': body['scorer_version']})


def _comparable_twin(body):
    """A previous cycle's stored score comparable with this one: same pooled
    surfaces, the same agents on each, the same scorer version."""
    return {k: body[k] for k in ('scorer_version', 'adapter_revision', 'brand_coder', 'score', 'earned', 'applicable_max',
                                 'surfaces', 'pillars', 'metric_counts', 'measured')}


def test_69_against_100_shows_the_line_and_deltas_only_where_both_measured(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db)
    _supply(upstream)                               # before #21: 69 applicable
    before = _get(http).json()
    assert before['applicable_max'] == 69.0
    _store_on_previous(db, _comparable_twin(before))
    _set_domain_checks(db, FULL)
    upstream.answer('GET', f'{WS}/reference', body=reference_2a3(), token=TOKEN_A)
    as_('op')
    now = _get(http, rescore='true').json()
    prev = now['previous']
    assert now['applicable_max'] == 100.0
    assert prev['comparable'] is True and prev['delta'] == now['score'] - before['score']
    assert prev['applicable_note'] == 'applicable points changed from 69 to 100'
    codes = [d['code'] for d in prev['dimension_deltas']]
    assert codes == ['share_of_mentions', 'recommendation_strength', 'agent_access', 'catalog_context',
                     'price_truth', 'member_value']
    assert all(d['delta'] == 0 for d in prev['dimension_deltas'])


def test_the_same_applicable_max_has_no_line_and_every_dimension_a_delta(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, FULL)
    _supply(upstream, reference_2a3())
    first = _get(http).json()
    twin = _comparable_twin(first)
    for p in twin['pillars']:
        for d in p['dimensions']:
            if d['code'] == 'value_protocols':
                d['score'] = 9.0                    # the manifest declared one capability then
    _store_on_previous(db, twin)
    as_('op')
    prev = _get(http, rescore='true').json()['previous']
    assert prev['comparable'] is True and prev['applicable_note'] is None
    assert len(prev['dimension_deltas']) == 9
    assert next(d for d in prev['dimension_deltas'] if d['code'] == 'value_protocols')['delta'] == 5.0


def test_a_not_comparable_previous_cycle_carries_no_deltas(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, FULL)
    _supply(upstream, reference_2a3())
    prev = _get(http).json()['previous']
    assert prev['comparable'] is False and 'dimension_deltas' not in prev


# ═══ Accessibility: the three rows that were "not checked" ═══════════════

def access_2a3(entries):
    body = copy.deepcopy(_fixture('supply_access_ws.json'))
    body['robots_by_domain'] = entries
    return body


ROLL_UP = [
    {'retailer_domain': 'target.com', 'robots_url': 'https://www.target.com/robots.txt', 'robots_status': 'ok',
     'robots_names_agents': {'answer_time_tokens_named': 1, 'answer_time_tokens_total': 7, 'wildcard_only': False}},
    {'retailer_domain': 'trueshopstore.com', 'robots_url': 'https://trueshopstore.com/robots.txt', 'robots_status': 'ok',
     'robots_names_agents': {'answer_time_tokens_named': 7, 'answer_time_tokens_total': 7, 'wildcard_only': False}},
]


def _access(http, upstream, *, access, retailers=None):
    ws_supply(upstream, reference=reference_2a3())
    upstream.answer('GET', f'{WS}/access', body=access, token=TOKEN_A)
    if retailers is not None:
        upstream.answer('GET', f'{WS}/retailers', body=retailers, token=TOKEN_A)
    as_('op')
    r = http.get('/api/console/accessibility', params={'merchant': 'wiggle-and-snug', 'org': 10})
    assert r.status_code == 200, r.text
    return r.json(), {c['key']: c for c in r.json()['checks']}


def test_every_row_carries_a_value_once_supply_and_the_domain_checks_are_there(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, FULL)
    body, checks = _access(http, upstream, access=access_2a3(ROLL_UP),
                           retailers={'own_domain': 'trueshopstore.com', 'own_domains': ['trueshopstore.com']})
    assert [c['key'] for c in body['checks']] == [
        'robots', 'markup', 'gtin', 'member_price', 'hosted_render', 'signed_agents', 'protocol']
    assert all(c['status'] != 'not_checked' for c in body['checks'])
    assert (checks['robots']['value'], checks['robots']['status']) == ('7 of 7', 'ok')   # the own domain, not target.com
    assert checks['robots']['basis'].startswith('https://trueshopstore.com/robots.txt')
    assert (checks['signed_agents']['value'], checks['signed_agents']['status']) == ('signed and unsigned both read', 'ok')
    assert (checks['protocol']['value'], checks['protocol']['status']) == ('UCP yes, MCP yes, llms.txt yes', 'ok')
    assert checks['protocol']['basis'] == ("the Audit's Protocol & Feed checks on trueshopstore.com, "
                                           f"for cycle {f229.CYCLE_229} on 2026-10-16")
    assert body['domain_checks'] == {'cycle': f229.CYCLE_229, 'checked_at': FULL['checked_at'],
                                     'scored_domain': 'trueshopstore.com'}


def test_nothing_published_reads_as_bad_not_as_not_checked(http, upstream, db):
    _cycle_229(db)
    _with_domain_checks(db, NONE)
    _, checks = _access(http, upstream, access=access_2a3(ROLL_UP[1:]))
    assert (checks['protocol']['value'], checks['protocol']['status']) == ('UCP no, MCP no, llms.txt no', 'bad')


def test_an_older_supply_and_no_domain_checks_are_each_not_checked_with_the_reason(http, upstream, db):
    _cycle_229(db)
    _, checks = _access(http, upstream, access=_fixture('supply_access_ws.json'))
    assert checks['robots']['status'] == 'not_checked'
    assert checks['robots']['basis'] == "supply's access payload carries no robots roll-up (a supply before #21)"
    for key in ('signed_agents', 'protocol'):
        assert (checks[key]['value'], checks[key]['basis']) == (
            'not checked', 'no domain checks on a cycle for this merchant yet')


@pytest.mark.parametrize('entries, why', [
    ([], 'no access run yet'),
    ([{'retailer_domain': 'trueshopstore.com', 'robots_status': 'challenged',
       'robots_names_agents': {'answer_time_tokens_named': None, 'answer_time_tokens_total': 7, 'wildcard_only': False}}],
     'robots.txt on trueshopstore.com was challenged, so it was not checked'),
    ([ROLL_UP[0]], 'the access run read no robots.txt on trueshopstore.com'),
])
def test_robots_not_checked_says_why(http, upstream, db, entries, why):
    _cycle_229(db)
    _, checks = _access(http, upstream, access=access_2a3(entries),
                        retailers={'own_domains': ['trueshopstore.com']})
    assert (checks['robots']['value'], checks['robots']['basis']) == ('not checked', why)


def test_a_wildcard_only_file_is_named():
    entry = [{'retailer_domain': 'shop.test', 'robots_status': 'ok',
              'robots_names_agents': {'answer_time_tokens_named': 0, 'answer_time_tokens_total': 7, 'wildcard_only': True}}]
    from app.services import console_parity as parity
    check = parity.robots_check(supply_fields.robots_by_domain({'robots_by_domain': entry}), ['shop.test'])
    assert (check['value'], check['status']) == ('0 of 7, wildcard only', 'bad')


@pytest.mark.parametrize('outcome, value, status', [
    ('signed_only', 'signed read, unsigned refused', 'ok'), ('unsigned_only', 'signed refused, unsigned read', 'bad'),
    ('neither', 'signed and unsigned both refused', 'bad')])
def test_each_probe_outcome_reads(outcome, value, status):
    from app.services import console_parity as parity
    record = {**FULL, 'signed_probe': {**FULL['signed_probe'], 'outcome': outcome}}
    check = parity.signed_agents_check(record, 'C')
    assert (check['value'], check['status']) == (value, status)


def test_a_probe_that_did_not_run_says_why():
    from app.services import console_parity as parity
    record = {**FULL, 'signed_probe': {'outcome': 'not_checked', 'reason': 'no Web Bot Auth key on the worker, so no signed request was sent'}}
    check = parity.signed_agents_check(record, 'C')
    assert (check['status'], check['basis']) == ('not_checked', 'no Web Bot Auth key on the worker, so no signed request was sent')


def test_without_the_column_accessibility_still_answers(http, upstream, db):
    # no /retailers answer and one domain in the roll-up: that domain
    _, checks = _access(http, upstream, access=access_2a3(ROLL_UP[1:]))
    assert checks['protocol']['status'] == 'not_checked' and checks['robots']['value'] == '7 of 7'


# ═══ Catalog: incentive in markup per retailer read ══════════════════════

def test_retailers_read_carries_incentive_in_markup():
    from app.services import console_parity as parity
    [row] = parity.retailers_read(reference_2a3())
    assert row['incentive_in_markup'] == {'pages': 10, 'of': 19}
    assert row['incentive_note'] == 'Incentive in markup: 10 of 19 pages'
    [partial] = parity.retailers_read(reference_2a3(scanned=5))
    assert partial['incentive_in_markup']['of'] == 5
    [unscanned] = parity.retailers_read(reference_2a3(scanned=0))
    assert unscanned['incentive_in_markup'] is None
    assert unscanned['incentive_note'] == 'Incentive in markup: not checked, no read scanned yet'
    [older] = parity.retailers_read(WS_REFERENCE)
    assert older['incentive_in_markup'] is None
    assert older['incentive_note'] == 'Incentive in markup: not measured, supply does not serve it yet'
