"""
2K-1 §2: the brand's own page carries no price, and the answers priced
against it are not "prices that could not be checked". On the FL12-shaped
brand fixture (console_fixture_2j2: Pampers, own pampers.com, six agents),
sqlite and Postgres.

The fixture's 20 catalog questions are asked at Walmart and Amazon. Two more
are added here, asked at pampers.com: Swaddlers NB 84 (a GTIN) and Ultra (no
GTIN, keyed sku:PAM-ULTRA-120), on every agent, each answer quoting $9.97 and
stored `unverifiable`, as a cycle scored before 2K-1 stored it. 12 runs.

  before: the cycle's cached reference has pampers.com rows as 2J-2 left
    them (not read, verifiable false). 12 prices could not be checked.
  after:  supply 2J-1 serves them `none_by_design` ("brand site, no price
    set"). The 12 are not scored (`brand_sets_no_price`): the count drops by
    exactly 12, Price Truth's denominator does not move, the drawer still
    shows the quote.

NB 84's stored claim carries the reference it was judged against (the
scorer's own record); Ultra's carries none, so its run is found from the
cached reference. Both paths are read.
"""
import json

import pytest
from sqlalchemy import text

from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

QUOTE = '9.97'
ASKED = (('Swaddlers NB 84', 'PAM-SW-NB-84', '00037000863434'), ('Ultra', 'PAM-ULTRA-120', None))
NOTE = "the brand's site sets no price; the agent priced it anyway"
FIRST_RUN = 95000


def _own_rows(payload: dict, none_by_design: bool) -> dict:
    for row in payload['prices']:
        if row['retailer_domain'] == f2j2.OWN:
            if none_by_design:
                row.update(method='none_by_design', read_status='ok', verifiable=False, reference_source='honest_fetch',
                           unverifiable_reason='brand site, no price set', observed_at='2026-10-19T14:01:58+00:00')
    return payload


def _fixture(db, none_by_design: bool):
    f2j2.load(db, _encode)
    payload = _own_rows(f2j2.reference_prices(), none_by_design)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = 229"), {'p': json.dumps(payload)})
        rid = FIRST_RUN
        for n, (label, sku, gtin) in enumerate(ASKED):
            qid = 3900 + n
            expected = {'type': 'price', 'amount': None, 'currency': 'USD', 'attributed_to': f2j2.OWN}
            ref = {'merchant_slug': f2j2.MERCHANT, 'variant_id': f2j2.variant_id(sku, gtin), 'own_domain': f2j2.OWN,
                   'merchant_kind': 'brand', **({'gtin': gtin} if gtin else {})}
            c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, study_pattern, "
                           "organization_id, tier, expected_answer, provenance, source_ref) VALUES (:i, :c, :t, 'Ready to Buy', "
                           "'Active', :st, 'brand_at_retail', 1, 'catalog_accuracy', :e, 'catalog', :r)"),
                      {'i': qid, 'c': f'PAM_{qid}', 't': f"What does the Pampers {label} cost at {f2j2.OWN}?",
                       'st': f2j2.STUDY, 'e': _encode(expected), 'r': _encode(ref)})
            own = next(r for r in payload['prices'] if r['retailer_domain'] == f2j2.OWN and r['sku'] == sku)
            reference = ({'retailer_domain': f2j2.OWN, 'method': own['method'], 'verifiable': False,
                          'unverifiable_reason': own['unverifiable_reason'], 'against': None} if gtin else None)
            claims = [{'target': 'asked', 'stated': QUOTE, 'outcome': 'unverifiable', 'variant_id': ref['variant_id'],
                       'reason': own['unverifiable_reason'], **({'reference': reference} if reference else {})}]
            for platform, surface, collector in f2j2.f2i8.AGENTS:
                rid += 1
                c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, raw_response, "
                               "status, surface, collector, answer_status) VALUES (:r, 229, :q, :p, 1, "
                               "'2026-10-19T15:00:00+00:00', 'Pampers Swaddlers are $9.97 on pampers.com.', 'success', :s, "
                               ":col, 'answered')"),
                          {'r': rid, 'q': qid, 'p': platform, 's': surface, 'col': collector})
                c.execute(text("INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id, platform, tier, "
                               "expected_answer, extraction, outcome, outcome_reason, flags, surface, claim_results) VALUES "
                               "(:r, :q, 229, :p, 'catalog_accuracy', :e, '{}', 'unverifiable', :why, '[]', :s, :cl)"),
                          {'r': rid, 'q': qid, 'p': platform, 'e': _encode(expected), 's': surface,
                           'why': own['unverifiable_reason'], 'cl': _encode(claims)})
    return f2j2.CYCLE


def _get(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'org': 10, 'cycle': f2j2.CYCLE, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _catalog_all(http):
    summary = _get(http, 'answers/summary')
    return next(c for t in summary['tiers'] if t['tier'] == 'catalog_accuracy' for c in t['surfaces'] if c['surface'] == 'all')


def _counts(http):
    catalog = _catalog_all(http)
    signals = {s['id']: s for s in _get(http, 'overview', merchant=f2j2.MERCHANT)['by_surface']['all']['signals']}
    totals = _get(http, 'overview', merchant=f2j2.MERCHANT)['by_surface']['all']['totals']
    return catalog, signals, totals


@pytest.mark.parametrize('none_by_design', [False, True])
def test_could_not_be_checked_drops_by_exactly_the_runs_priced_at_the_brand_s_own_page(http, db, none_by_design):
    _fixture(db, none_by_design)
    catalog, signals, totals = _counts(http)
    if not none_by_design:
        assert catalog['unverifiable'] == 12
        assert signals['unverifiable']['count'] == 12
        assert signals['unverifiable']['title'] == '12 prices could not be checked.'
    else:
        assert catalog['unverifiable'] == 0 and 'unverifiable' not in signals
        assert catalog['counts'].get('unscoreable', 0) >= 12
    # Price Truth's denominator does not move: the 12 were never scored
    assert catalog['scored'] == 80
    assert (totals['scored'], totals['exact']) == (110, 74)


# Price Truth's denominator, the same in both states: the catalog tier's 20
# questions x the four agents that quote a price = 80 scored; the Overview's
# totals add the value tier's 30 (110 scored, 74 exact).


def test_the_drawer_still_shows_the_quote(http, db):
    _fixture(db, True)
    answers = {a['id']: a for a in _get(http, 'answers')}
    for run in (FIRST_RUN + 1, FIRST_RUN + 7):      # NB 84 (the claim's reference), Ultra (the cached reference)
        a = answers[f'run-{run}']
        assert (a['verdict'], a['reason'], a['summary']) == ('unscoreable', 'brand_sets_no_price', NOTE)
        [check] = a['checks']
        assert check['claim'] == '$9.97' and check['note'] == NOTE and check['reason'] == 'brand_sets_no_price'
        assert check['verdict'] == 'unscoreable' and check['tone'] == 'neu'
    assert answers[f'run-{FIRST_RUN + 1}']['checks'][0]['live'] == "no price set at pampers.com, the brand's own site"


def test_the_true_value_cell_is_not_priced_and_not_unverifiable(http, db):
    _fixture(db, True)
    tv = _get(http, 'true-value', merchant=f2j2.MERCHANT)
    cell = next(r for r in tv['rows'] if r['product'] == 'Swaddlers NB 84')['cells'][f2j2.OWN]
    assert (cell['live'], cell['status']) == ('not priced', 'none')
    assert {q['outcome'] for q in cell['quotes']} == {'unscoreable'} and len(cell['quotes']) == 6


def test_the_revenue_model_s_unverifiable_count_drops_too(http, db, upstream):
    from soa_shared.models.soa_models import SoaMerchantRevenueInputs
    from app.services import console_revenue as revenue_svc
    _fixture(db, True)
    SoaMerchantRevenueInputs.__table__.create(db, checkfirst=True)
    with db.connect() as c:
        cycle = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one())
        rows = revenue_svc.load_catalog_rows(c, cycle)
    mine = [r for r in rows if r['run_id'] > FIRST_RUN]
    assert len(mine) == 12 and all((r['outcome'], r['reason_code']) == ('unscoreable', 'brand_sets_no_price') for r in mine)
    shares = revenue_svc.revenue_shares([], rows)
    assert shares['missed']['unverifiable'] == 0
