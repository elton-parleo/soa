"""
2K-1 §4: local dates on cycle codes and study labels, sqlite and Postgres.

FL12-pampers-20261020 ran on Oct 19 in Los Angeles; the console called the
study generated that evening "the Oct 20 study". A new cycle code and the
study's display date now read the merchant's local time: the study's
tier_config.merchant.timezone when set, else SOA_DEFAULT_TIMEZONE (default
America/Los_Angeles). Stored stamps stay UTC; studies and cycles carry
`created_at_local` beside them. Existing codes are not renamed.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.routers import console_ops
from app.services import console_read_models as rm
from soa_shared import local_time
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import _cycle_229, db  # noqa: F401  (fixture)
from tests.test_console_2i4 import _catalog, _generate, _job, jobs  # noqa: F401  (fixture)
from tests.test_console_2i5 import STUDY, first  # noqa: F401  (fixture)
from tests.test_console_2h import BRAND, supply  # noqa: F401  (fixture)
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)

#: 04:26 UTC on Oct 20 is 21:26 PDT on Oct 19
PLANNED = datetime(2026, 10, 20, 4, 26, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_env_zone(monkeypatch):
    monkeypatch.delenv(local_time.TIMEZONE_ENV, raising=False)


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return PLANNED if tz else PLANNED.replace(tzinfo=None)


def _start(http, monkeypatch):
    monkeypatch.setattr(console_ops, 'datetime', _Frozen)
    as_('op')
    r = http.post('/api/console/cycles', params={'org': 10}, json={'study_type': STUDY, 'platforms': ['chatgpt']})
    assert r.status_code == 201, r.text
    return r.json()['cycle_code']


def test_a_cycle_started_at_04_26_utc_oct_20_is_coded_oct_19_by_default(http, first, monkeypatch):
    assert _start(http, monkeypatch) == f'20261019-212600-{STUDY}'


def test_the_study_s_merchant_timezone_codes_it(http, first, monkeypatch):
    with first.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = :t WHERE study_type = :st"),
                  {'t': '{"merchant": {"slug": "%s", "timezone": "Europe/Stockholm"}}' % BRAND, 'st': STUDY})
    assert _start(http, monkeypatch) == f'20261020-062600-{STUDY}'


def test_soa_default_timezone_sets_the_default(http, first, monkeypatch):
    monkeypatch.setenv(local_time.TIMEZONE_ENV, 'UTC')
    assert _start(http, monkeypatch) == f'20261020-042600-{STUDY}'


def test_a_code_sent_is_kept(http, first, monkeypatch):
    monkeypatch.setattr(console_ops, 'datetime', _Frozen)
    as_('op')
    r = http.post('/api/console/cycles', params={'org': 10},
                  json={'study_type': STUDY, 'platforms': ['chatgpt'], 'cycle_code': 'WSB-MINE'})
    assert r.json()['cycle_code'] == 'WSB-MINE'


# ═══ created_at_local beside the UTC stamp ═══════════════════════════════

def test_runs_carry_created_at_local_beside_the_utc_stamp(http, db):
    _cycle_229(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET created_at = :t WHERE id = 229"), {'t': PLANNED})
    as_('op')
    runs = {r['id']: r for r in http.get('/api/console/runs', params={'org': 10}).json()}
    run = runs[f229.CYCLE_229]
    assert datetime.fromisoformat(run['started']) == PLANNED                     # UTC, as before
    assert (run['created_at_local'], run['timezone']) == ('2026-10-19T21:26:00-07:00', 'America/Los_Angeles')


def test_a_study_carries_created_at_local_in_its_merchant_s_zone():
    job = {'study_type': 's', 'study_name': 'S', 'created_at': PLANNED,
           'tier_config': {'merchant': {'slug': 'pampers', 'timezone': 'America/New_York'}}}
    study = rm.build_study(job, [], [], [])
    assert study['created'] == '2026-10-20T04:26:00+00:00'
    assert (study['created_at_local'], study['timezone']) == ('2026-10-20T00:26:00-04:00', 'America/New_York')
    plain = rm.build_study({**job, 'tier_config': None}, [], [], [])
    assert plain['created_at_local'] == '2026-10-19T21:26:00-07:00'


# ═══ the wizard's field, stored on the merchant ══════════════════════════

def test_generate_stores_the_timezone_on_tier_config_merchant(http, jobs, supply):
    r = _generate(http, merchant=BRAND, timezone='America/New_York')
    assert r.status_code == 201, r.text
    job = _job(jobs, r.json()['study_type'])
    assert job['tier_config']['merchant'] == {'slug': BRAND, 'timezone': 'America/New_York'}


def test_no_timezone_sent_stores_none_and_the_default_applies(http, jobs, supply):
    r = _generate(http, merchant=BRAND)
    job = _job(jobs, r.json()['study_type'])
    assert job['tier_config']['merchant'] == {'slug': BRAND}
    assert rm.study_timezone(job['tier_config']) == 'America/Los_Angeles'


def test_an_unknown_zone_is_a_422(http, jobs, supply):
    r = _generate(http, merchant=BRAND, timezone='Pacific Time')
    assert r.status_code == 422 and 'IANA' in r.text
