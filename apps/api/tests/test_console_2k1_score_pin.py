"""
2K-1: scorer 11 moves no score. Its change (the brand-choice set, read by
Lost and the first-pick tiles) is not read by any dimension, so on the three
fixtures 2I-8a pins, the whole score body, metric rows included, is what
scorer 10 served (main at acb74b1), but for the version: sha256 of the body
less the version and the volatile fields (2O-1: and the brand-direct coder count,
which no dimension reads; scorer 12 moves no score either). The pin was written by this test
run on acb74b1 with SOA_2K1_PIN_DUMP set. On sqlite and a local Postgres
(2I-8a's pins are the same on both dialects, so one hash serves both).
"""
import copy
import hashlib
import json
import os

import pytest

from app.services import console_score as score_svc
from tests.score_2l4 import before_2l4
from tests.test_console_2c3a import _cycle_229, _get, _supply, db  # noqa: F401
from tests.test_console_2i8 import _fl12 as _fl12_2i8
from tests.test_console_read_models import http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_unprompted_2i7 import _fl12 as _fl12_2i7

PIN = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'score_pin_2k1.json')
DUMP = os.getenv('SOA_2K1_PIN_DUMP')
FIXTURES = {'229': _cycle_229, 'fl12_2i7': _fl12_2i7, 'fl12_2i8': _fl12_2i8}
VOLATILE = ('scored_at', 'stored', 'history')


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


#: 2O-1 (scorer 12): the version, and the brand-direct coder count beside it
#: (console_score.brand_coder), which no dimension reads
NOT_PINNED = ('scorer_version', 'brand_coder')


def body_view(body):
    return _strip({k: v for k, v in copy.deepcopy(body).items() if k not in NOT_PINNED})


@pytest.mark.parametrize('name', list(FIXTURES))
def test_the_whole_score_body_is_scorer_10_s_but_for_the_version(name, http, db, upstream):
    FIXTURES[name](db)
    _supply(upstream)
    r = _get(http, rescore=1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['scorer_version'] == score_svc.SCORER_VERSION
    got = hashlib.sha256(json.dumps(body_view(before_2l4(body)), sort_keys=True).encode()).hexdigest()
    if DUMP and os.path.isdir(DUMP):
        with open(os.path.join(DUMP, f'{name}.json'), 'w') as fh:
            json.dump(body_view(body), fh, indent=1, sort_keys=True)
    elif DUMP:
        pins = json.load(open(PIN)) if os.path.exists(PIN) else {}
        pins[name] = got
        with open(PIN, 'w') as fh:
            json.dump(pins, fh, indent=1, sort_keys=True)
            fh.write('\n')
    with open(PIN) as fh:
        assert got == json.load(fh)[name]
