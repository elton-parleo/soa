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
        'lost_gainable': (0.0, '0%', True)}
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
    assert (body['lost_gainable']['value'], body['lost_gainable']['default']) == (0.0, True)
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
