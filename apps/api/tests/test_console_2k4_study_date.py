"""
2K-4 §B2: the study's own date, in the merchant's zone, on every study read.

Prompts and the Overview header read "The Oct 21 study" for a study generated
at 23:10 PDT on Oct 20 (06:10 UTC on Oct 21). Neither label read the study:
the Overview's read the cycle's created_at_local and Prompts the cycle's start
(until 2K-3 the UTC start_date, soa's `last_run`), and only /studio/studies
served the study's own created_at_local. The study block on /prompts,
/full-loop/latest and /overview now carries it too.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from soa_shared import local_time
from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2j2 import _brand, _get, pampers_tenant  # noqa: F401  (fixture)
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (fixtures)

#: 06:10 UTC on Oct 21 is 23:10 PDT on Oct 20
GENERATED = datetime(2026, 10, 21, 6, 10, tzinfo=timezone.utc)
LOCAL = '2026-10-20T23:10:00-07:00'


@pytest.fixture(autouse=True)
def _no_env_zone(monkeypatch):
    monkeypatch.delenv(local_time.TIMEZONE_ENV, raising=False)


def _generated(db):
    cycle = _brand(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET created_at = :t WHERE study_type = :st"),
                  {'t': GENERATED, 'st': f2j2.STUDY})
    return cycle


def test_a_study_created_06_10_utc_oct_21_is_the_oct_20_study_on_every_read(http, db, pampers_tenant):
    cycle = _generated(db)
    prompts = _get(http, 'prompts', merchant=f2j2.MERCHANT)
    assert prompts['study']['created_at_local'] == LOCAL and prompts['study']['timezone'] == 'America/Los_Angeles'
    assert datetime.fromisoformat(prompts['study']['created_at']) == GENERATED            # UTC beside it
    [study] = [s for s in _get(http, 'studio/studies', merchant=f2j2.MERCHANT) if s['id'] == f2j2.STUDY]
    assert study['created_at_local'] == LOCAL
    over = _get(http, 'overview', cycle=cycle)
    assert over['study'] == {'id': f2j2.STUDY, 'name': 'Wiggle & Snug full', 'created_at': prompts['study']['created_at'],
                             'created_at_local': LOCAL, 'timezone': 'America/Los_Angeles'}
    with db.begin() as c:
        c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
            runs_per_query, status, cycle_id, created_by, created_at, updated_at)
            VALUES (10, :m, :st, '["chatgpt"]', 1, 'scored', 229, 'op', :t, :t)"""),
                  {'m': f2j2.MERCHANT, 'st': f2j2.STUDY, 't': GENERATED})
    loop = _get(http, 'full-loop/latest', merchant=f2j2.MERCHANT)
    assert loop['study']['created_at_local'] == LOCAL


def test_the_merchant_s_zone_decides_the_study_s_day(http, db, pampers_tenant):
    _generated(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = :t WHERE study_type = :st"),
                  {'t': '{"merchant": {"slug": "pampers", "timezone": "Europe/Stockholm"}}', 'st': f2j2.STUDY})
    assert _get(http, 'prompts', merchant=f2j2.MERCHANT)['study']['created_at_local'] == '2026-10-21T08:10:00+02:00'
