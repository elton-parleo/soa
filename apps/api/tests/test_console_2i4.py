"""
2I-4: a console-generated study is its org's and the selected merchant's.

On production a study generated on the Wiggle & Snug Brand workspace with
the brand box off was queued with no customer org (only the brand path set
it), so /studio/studies' org filter dropped it; and with no
syndicated_merchant and no tier_config.merchant it would have been the
primary merchant's (the store's) even with the org fixed. Now every console
generate carries the scope org, and the console's selected `merchant` is
recorded where study_merchants reads it. Supply answers with the recorded
2H /tenant and /retailers payloads and the W&S catalog fixture; every test
runs on sqlite and on a local Postgres (test_console_2c3a's db fixture).
"""
import json

import pytest
from sqlalchemy import text

import app.routers.studies as studies_router
from tests.console_tables import add_columns
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2h import BRAND, STORE, supply  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (fixtures)
from tests.test_console_studies import BASE, TIERS_ON, WS


@pytest.fixture
def jobs(db, monkeypatch):
    """The generation job's brief columns (production's), and the web route's engine."""
    with db.begin() as c:
        add_columns(c, 'soa_query_generation_jobs', 'stage_targets', 'rotate_named_retailer', 'naming_rule_enabled',
                    'personas', 'specificity_mode')
        if db.dialect.name == 'postgresql':   # the seed writes its ids; the serial starts after them
            c.exec_driver_sql("SELECT setval(pg_get_serial_sequence('soa_query_generation_jobs', 'id'), "
                              "(SELECT MAX(id) FROM soa_query_generation_jobs))")
    monkeypatch.setattr(studies_router, "engine", db)
    return db


def _catalog(upstream):
    upstream.answer('GET', f'{BASE}/catalog', body=WS['catalog'], token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/merchants', body=WS['merchants'], token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/incentives', body=WS['incentives'], token=TOKEN_A)


def _generate(http, **body):
    as_('op')
    return http.post('/api/console/studies/generate', params={'org': 10},
                     json={'study_name': 'W&S brand plain', 'target_count': 5, **body})


def _job(db, study_type):
    with db.connect() as c:
        job = dict(c.execute(text("SELECT * FROM soa_query_generation_jobs WHERE study_type = :st"),
                             {'st': study_type}).mappings().one())
    if isinstance(job['tier_config'], str):
        job['tier_config'] = json.loads(job['tier_config'])
    return job


def _listed(http, merchant):
    r = http.get('/api/console/studio/studies', params={'org': 10, 'merchant': merchant})
    assert r.status_code == 200, r.text
    return [s['id'] for s in r.json()]


def _job_count(db):
    with db.connect() as c:
        return c.execute(text("SELECT COUNT(*) FROM soa_query_generation_jobs")).scalar()


# ═══ the production case: the brand workspace, the brand box off ═════════

def test_without_the_brand_box_the_study_is_the_orgs_and_the_selected_merchants(http, jobs, supply):
    r = _generate(http, merchant=BRAND)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['merchant'] == {'slug': BRAND, 'from': 'request'} and body['tally'] is None
    job = _job(jobs, body['study_type'])
    assert (job['organization_id'], job['customer_organization_id'], job['syndicated_merchant']) == (1, 10, None)
    assert job['tier_config'] == {'merchant': {'slug': BRAND}}          # no tiers: nothing to ground
    assert body['study_type'] in _listed(http, BRAND)
    assert body['study_type'] not in _listed(http, STORE)
    assert not any('/catalog' in c['path'] for c in supply.calls)


def test_a_merchant_that_is_not_the_orgs_is_a_404_and_writes_nothing(http, jobs, supply):
    before = _job_count(jobs)
    r = _generate(http, merchant='brandco')
    assert r.status_code == 404 and r.json()['detail'] == "merchant 'brandco' not found"
    assert _job_count(jobs) == before


def test_no_merchant_is_the_primary_and_says_so(http, jobs, supply):
    r = _generate(http)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['merchant'] == {'slug': STORE, 'from': 'primary',
                                'note': "no merchant sent: the study is the org's primary merchant's"}
    job = _job(jobs, body['study_type'])
    assert (job['customer_organization_id'], job['syndicated_merchant'], job['tier_config']) == (10, None, None)
    assert body['study_type'] in _listed(http, STORE)
    assert body['study_type'] not in _listed(http, BRAND)


# ═══ the brand box ═══════════════════════════════════════════════════════

def test_with_the_brand_box_a_different_merchant_is_a_422(http, jobs, supply):
    _catalog(supply)
    before = _job_count(jobs)
    r = _generate(http, target_count=50, syndicated_merchant=STORE, tiers=TIERS_ON, merchant=BRAND)
    assert r.status_code == 422
    assert r.json()['detail'] == (f"merchant {BRAND!r} is not the syndicated merchant {STORE!r}: "
                                  "a brand study is generated for the merchant whose catalog it reads")
    assert _job_count(jobs) == before
    assert not any('/catalog' in c['path'] for c in supply.calls)


def test_the_brand_box_path_is_unchanged_apart_from_the_merchant_field(http, jobs, supply):
    _catalog(supply)
    brief = {'target_count': 50, 'study_pattern': 'brand_at_retail', 'syndicated_merchant': STORE, 'tiers': TIERS_ON,
             'stage_targets': {'Awareness': 10, 'Research': 12, 'Comparison': 12, 'Ready to Buy': 16},
             'allowed_categories': ['Baby Care']}
    old = _generate(http, **brief)               # what a client before 2I-4 sends
    new = _generate(http, **brief, merchant=STORE)
    assert old.status_code == new.status_code == 201, (old.text, new.text)
    a, b = old.json(), new.json()
    assert a.pop('merchant') == {'slug': STORE, 'from': 'syndicated_merchant'}
    assert b.pop('merchant') == {'slug': STORE, 'from': 'request'}
    differ = {'study_type', 'job_id'}
    assert {k: v for k, v in a.items() if k not in differ} == {k: v for k, v in b.items() if k not in differ}
    assert a['tally']['total'] == 87
    ja, jb = _job(jobs, a['study_type']), _job(jobs, b['study_type'])
    differ = {'id', 'study_type', 'created_at'}
    assert {k: v for k, v in ja.items() if k not in differ} == {k: v for k, v in jb.items() if k not in differ}
    assert (ja['customer_organization_id'], ja['syndicated_merchant']) == (10, STORE)
    assert ja['tier_config'] == {'brand_direct': {'enabled': True, 'count': 12}, 'catalog_accuracy': {'enabled': True},
                                 'value_incentives': {'enabled': True}, 'category_control': {'enabled': False}}
    assert a['study_type'] in _listed(http, STORE) and a['study_type'] not in _listed(http, BRAND)
