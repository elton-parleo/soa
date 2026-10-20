"""
2I-8a: the score block's five metric rows count every agent, as the rest
of the Overview does since 2I-8. The rows are counts beside the score, not
the score: its dimensions stay per surface and pool by score (2C-3).

The score itself is pinned: on three fixtures (229 as recorded, FL8's shape;
229 with the brand box on, 2I-7's FL12 shape; 2I-8's six-agent FL12 shape),
the body minus the metric rows, the scorer version and the volatile fields is
what main (35c9952) served, sha256 per dialect. On sqlite and a local Postgres.
"""
import copy
import hashlib
import json
import os

import pytest
from sqlalchemy import text

from app.services import console_score as score_svc
from tests import console_fixture_2i8 as f2i8
from tests.test_console_2c3a import _cycle_229, _get, _supply, db  # noqa: F401
from tests.test_console_2i8 import _fl12 as _fl12_2i8
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_unprompted_2i7 import _fl12 as _fl12_2i7

PIN = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'score_pin_2i8a.json')
DUMP = os.getenv('SOA_2I8A_PIN_DUMP')
FIXTURES = {'229': _cycle_229, 'fl12_2i7': _fl12_2i7, 'fl12_2i8': _fl12_2i8}
#: what 2I-8a changes on purpose: the rows and what they are built from, the version, the rule texts
CHANGED = ('metrics', 'metric_counts', 'metric_surface', 'scorer_version', 'rules')
VOLATILE = ('scored_at', 'stored', 'history')


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def score_view(body):
    return _strip({k: v for k, v in copy.deepcopy(body).items() if k not in CHANGED})


def _score(http, db, upstream, name):
    FIXTURES[name](db)
    _supply(upstream)
    r = _get(http, rescore=1)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize('name', list(FIXTURES))
def test_the_score_is_what_main_served_but_for_the_rows_and_the_version(name, http, db, upstream):
    body = _score(http, db, upstream, name)
    view = score_view(body)
    got = hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()
    if DUMP:
        os.makedirs(DUMP, exist_ok=True)
        with open(os.path.join(DUMP, f'{name}-{db.dialect.name}.json'), 'w') as fh:
            json.dump({'view': view, 'metrics': body['metrics'], 'metric_surface': body['metric_surface']}, fh, indent=1, sort_keys=True)
    with open(PIN) as fh:
        assert got == json.load(fh)[db.dialect.name][name]


# ═══ FL12's shape: the rows on every agent ═══════════════════════════════

#: each row's by_surface as main (35c9952) served it on the six-agent FL12 shape: unchanged
MAIN_BY_SURFACE = {
    'first': {'consumer_ui': {'of': 34, 'value': 11}, 'grounded_api': {'of': 68, 'value': 22}},
    'share': {'consumer_ui': {'of': 34, 'value': 17}, 'grounded_api': {'of': 68, 'value': 34}},
    'program': {'consumer_ui': {'of': 17, 'value': 0}, 'grounded_api': {'of': 34, 'value': 0}},
    'exact': {'consumer_ui': {'of': 14, 'value': 14}, 'grounded_api': {'of': 28, 'value': 8}},
    'terms': {'consumer_ui': {'of': 10, 'value': 8}, 'grounded_api': {'of': 20, 'value': 16}},
}


def test_fl12_s_rows_count_every_agent_as_the_overview_does(http, db, upstream):
    body = _score(http, db, upstream, 'fl12_2i8')
    rows = {m['key']: m for m in body['metrics']}
    assert body['metric_surface'] == 'all' and all(m['surface'] == 'all' for m in body['metrics'])
    assert {k: (m['value'], m['denominator']) for k, m in rows.items()} == {
        'first': (33, 102), 'share': (51, 102), 'program': (0, 51), 'exact': (22, 42), 'terms': (24, 30)}
    assert {k: m['by_surface'] for k, m in rows.items()} == MAIN_BY_SURFACE
    assert rows['first']['surface_note'] == 'across every agent, unprompted answers'
    assert rows['exact']['surface_note'] == 'across every agent, catalog tier, exact of scored'
    # the same counts as 2I-8's Overview headline, totals and answers summary
    as_('op')
    params = {'cycle': f2i8.CYCLE, 'org': 10, 'merchant': 'wiggle-and-snug'}
    over = http.get('/api/console/overview', params=params).json()['by_surface']['all']['totals']
    assert (over['first'], over['named'], over['named_of']) == (33, 51, 102)
    summary = http.get('/api/console/answers/summary', params=params).json()
    catalog = next(c for t in summary['tiers'] if t['tier'] == 'catalog_accuracy' for c in t['surfaces'] if c['surface'] == 'all')
    assert (catalog['counts']['exact'], catalog['scored']) == (22, 42)


def test_the_score_moves_by_version_only(http, db, upstream):
    """FL12's stored v9 score re-scores under 10 with the same number, and the
    history line says the version alone (2I-8a never explains a moved score)."""
    _score(http, db, upstream, 'fl12_2i8')
    with db.begin() as c:
        raw = c.execute(text("SELECT share_of_algorithm FROM soa_cycles WHERE id = 229")).scalar()
        old = json.loads(raw) if isinstance(raw, str) else raw
        old['scorer_version'] = '9'
        c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = '9' WHERE id = 229"),
                  {'b': json.dumps(old)})
    body = _get(http).json()
    assert (body['score'], body['scorer_version']) == (old['score'], '10')
    assert body['history'][-1]['replaced_because'] == 'scorer 9 → 10'
    assert score_svc.SCORER_CHANGES['10'] == 'metric rows count every agent'
