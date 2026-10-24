"""
2P-1 (B3): week-over-week preflight on a synthetic second cycle, sqlite and
Postgres. See console_fixture_2p1.py for the pair.
"""
import json
import os

from tests import console_fixture_2p1 as f2p1
from tests import test_console_2m1_attribute as t2m1
from tests import test_console_2m2_promo as t2m2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2k4_comparable import _fl13_shape
from tests.test_console_2l2_retired import _retired
from tests.test_console_2l4_routing import _intents, _supply
from tests.test_console_read_models import TOKEN_A, _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

WS = 'wiggle-and-snug'


def _get(http, endpoint, cycle=f2p1.CYCLE_2, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'cycle': cycle, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _dump(name, body):
    """SOA_2P1_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2P1_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _pair(db, http, upstream):
    _fl13_shape(db, http, upstream)
    _retired(db)
    _intents(db)
    t2m2._questions(db)
    t2m1._attribute_questions(db)
    t2m1._cache_truths(db)
    _supply(upstream)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/reference', body=t2m1.ATTRIBUTE_REFERENCE, token=TOKEN_A)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/deals', body=t2m2.DEALS, token=TOKEN_A)
    # cycle 1's score stored, as the console's first read stores it
    _get(http, 'score', cycle=f2p1.CYCLE_1, merchant=WS)
    f2p1.clone(db, _encode)


def test_explore(http, db, upstream):
    _pair(db, http, upstream)
    for ep in ('overview', 'score', 'visibility', 'true-value', 'prove', 'revenue', 'truesync', 'answers'):
        _dump(f'{ep}.json', _get(http, ep, merchant=WS))
    as_('op')
    _dump('revenue-history.json', http.get('/api/console/revenue/history', params={'merchant': WS, 'org': 10}).json())
