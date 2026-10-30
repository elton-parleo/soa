"""
2V-4 (B8): brand mode and the hosted seller do not move. Each read below is
pinned by the sha256 of its canonical JSON (sorted keys, wall-clock stamps
dropped), computed on soa `main` before 2V-4 (the pin file says the commit):
Pampers at retail on 2U-5's recorded harness (mode manufacturer), and Wiggle
& Snug, the Parleo-hosted seller, on 2P-1's pair. A read that differs fails
here with its endpoint named.

SOA_2V4_PIN_WRITE=1 rewrites tests/fixtures/console/pins_2v4.json; run it on
main, never on a branch it is meant to check.
"""
import hashlib
import json
import os

from tests import test_console_2u5 as t2u5
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import WS, _get, _pair, f2p1
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

PINS = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'pins_2v4.json')
#: A stamp of when the read ran, not what it read.
VOLATILE = ('scored_at',)
BRAND_READS = (('overview', {'cycle': f2p1.CYCLE_2}), ('truesync', {}), ('publishing', {}), ('rules', {}),
               ('approvals', {}), ('fixes', {}), ('record/list', {}), ('true-value', {'cycle': f2p1.CYCLE_2}),
               ('prove', {'cycle': f2p1.CYCLE_2}), ('accessibility', {}), ('revenue', {'cycle': f2p1.CYCLE_2}))
HOSTED_READS = (('overview', {}), ('truesync', {'cycle': None}), ('record/list', {'cycle': None}), ('true-value', {}),
                ('prove', {}), ('accessibility', {'cycle': None}), ('revenue', {}))


def _canon(value):
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_canon(v) for v in value]
    return value


def digest(body) -> str:
    return hashlib.sha256(json.dumps(_canon(body), sort_keys=True).encode()).hexdigest()


def _check(kind: str, got: dict):
    if os.environ.get('SOA_2V4_PIN_WRITE'):
        pins = json.load(open(PINS)) if os.path.exists(PINS) else {}
        pins[kind] = got
        with open(PINS, 'w') as fh:
            json.dump(pins, fh, indent=1, sort_keys=True)
        return
    with open(PINS) as fh:
        want = json.load(fh)[kind]
    moved = sorted(k for k in want if want[k] != got.get(k))
    assert not moved, f"{kind} reads moved: {moved}"
    assert set(got) == set(want)


def test_brand_mode_reads_are_unchanged(http, db, upstream):
    t2u5._shape(db, http, upstream)
    got = {}
    for endpoint, params in BRAND_READS:
        got[endpoint] = digest(t2u5._read(http, endpoint, **params))
    record = t2u5._read(http, 'record/list')['products'][0]
    got['record'] = digest(t2u5._read(http, 'record', product=record['sku']))
    _check('brand_pampers_2u5', got)


def test_the_hosted_seller_reads_are_unchanged(http, db, upstream):
    _pair(db, http, upstream)
    got = {}
    for endpoint, params in HOSTED_READS:
        if params.get('cycle', '') is None:
            as_('op')
            r = http.get(f'/api/console/{endpoint}', params={'org': 10, 'merchant': WS})
            assert r.status_code == 200, r.text
            got[endpoint] = digest(r.json())
        else:
            got[endpoint] = digest(_get(http, endpoint, merchant=WS))
    _check('hosted_wiggle_and_snug', got)
