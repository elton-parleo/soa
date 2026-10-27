"""
2T-7: seven items from the Oct 26 walk of the Measure screens (org 12,
FL15-pampers-20261024, scorer 18). No scorer change.

  1  the Visibility gap's second line from the counts (test_console_2t5_visibility's table)
  2  one cycle label (rm.cycle_label) for every "since / vs / against" string
  3  Accessibility's weight and GTIN checks as the demo words them
  4  True Value's brand column: "Markup lists no pack count" once
  5  the variant-clash clause on every cell whose shown run has one
  6  the receipt's SKU: a live deal first, then a list-vs-sale difference
  7  "Offer per retailer" on pampers.com: absence, explained, not drift

Inputs: the 2T-1 harness (supply #33's answers and pages RECORDED), with
console_fixture_2t5's FL15 shape (DERIVED and labelled), and rows built in
the served shapes where an item needs FL15's numbers. No production read, no
model call.
"""
import re

import pytest

from app.services import console_read_models as rm
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2r2 as f2r2
from tests import console_fixture_2t5 as f2t5
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape


# ── 2: one cycle label ────────────────────────────────────────────────────

def test_the_label_is_the_cycles_local_day():
    """FL15 against FL14: the cycle created 03:10 UTC on Oct 24 started Oct 23 in Los Angeles."""
    prev = {'cycle_code': 'FL14-pampers-20261023', 'created_at': '2026-10-24T03:10:00+00:00',
            'start_date': '2026-10-24'}
    assert rm.cycle_label(prev, 'America/Los_Angeles') == {
        'code': 'FL14-pampers-20261023', 'day': 'Oct 23', 'name': 'the Oct 23 cycle', 'since': 'Since Oct 23',
        'vs': 'vs Oct 23'}
    # no created_at: the UTC start date
    assert rm.cycle_label({'cycle_code': 'X', 'start_date': '2026-10-23'})['day'] == 'Oct 23'
    # no date at all: the code stands in
    assert rm.cycle_label({'cycle_code': 'X'}) == {'code': 'X', 'day': None, 'name': 'X', 'since': 'Since X',
                                                   'vs': 'vs X'}


def _strings(body, path=''):
    if isinstance(body, dict):
        for k, v in body.items():
            yield from _strings(v, f'{path}.{k}')
    elif isinstance(body, list):
        for i, v in enumerate(body):
            yield from _strings(v, f'{path}[{i}]')
    elif isinstance(body, str):
        yield path, body


#: the four Measure screens, the Overview (and its score card) and TrueSync
SCREENS = ('overview', 'score', 'answers', 'answers/summary', 'visibility', 'true-value', 'accessibility', 'truesync')


@pytest.mark.parametrize('shape', ['compared', 'fl15'])
def test_no_served_string_carries_a_cycle_code(shape, http, db, upstream):
    """Both cycles carry a local day, so no copy names either by its code: an identifier (a string that IS the
    code) stays. `compared` is 2P-1's pair (Changes, moved, drift); `fl15` adds FL15's comparison questions, so
    the pair does not compare (the "Not comparable" notes)."""
    _shape(db, http, upstream)
    if shape == 'fl15':
        f2t5.comparison(db, _encode)
    upstream.answer('GET', f'{f2r2.BASE}/reference', body=f2r2.body('reference'), token=f2r2.TOKEN_A)
    codes = (f2p1.CYCLE_1, f2p1.CYCLE_2)
    hits = []
    for endpoint in SCREENS:
        params = {} if endpoint in ('accessibility', 'truesync') else {'cycle': f2p1.CYCLE_2}
        body = _read(http, endpoint, **params)
        hits += [(endpoint, p, s) for p, s in _strings(body) if s not in codes and any(c in s for c in codes)]
    assert hits == []


def test_the_previous_block_and_the_copy_read_the_label(http, db, upstream):
    _shape(db, http, upstream)
    vis = _read(http, 'visibility', cycle=f2p1.CYCLE_2)
    assert vis['previous'] == {'cycle': f2p1.CYCLE_1, 'status': 'compared', 'note': None, 'day': 'Oct 14',
                               'name': 'the Oct 14 cycle', 'since': 'Since Oct 14', 'vs': 'vs Oct 14'}
    assert vis['lede'].startswith('Who the answers name, and who they name first, in the Oct 21 cycle.')
    assert all(re.search(r'in the Oct 14 cycle\.$', b['detail']) for b in vis['moved']['all']['brands'])
    over = _read(http, 'overview', cycle=f2p1.CYCLE_2)
    assert over['vs_label'] == 'vs Oct 14' and over['vs_cycle'] == f2p1.CYCLE_1
    assert all(c['detail'].endswith('in the Oct 14 cycle.') for c in over['by_surface']['all']['changes'])
    score = _read(http, 'score', cycle=f2p1.CYCLE_2)
    assert (score['previous']['cycle'], score['previous']['vs']) == (f2p1.CYCLE_1, 'vs Oct 14')

