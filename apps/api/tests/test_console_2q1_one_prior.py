"""
2Q-1 (B2): one prior for every delta.

FL15's Overview read Attribute accuracy "53 of 77, +5", the prior FL14's
score as stored before its reference refresh (48 of 68), while Impact's
"What moved since the baseline" read "54 of 77 -> 53 of 77, -1", FL14
recomputed. Now the score's previous is the previous cycle's current read
(router _previous_score): a stored score that predates a refresh or a
rescore is recomputed, as opening that cycle would (score_svc.
needs_recompute, 2N-2). On 2P-1's pair (console_fixture_2p1.py), cycle 1's
cached reference is refreshed after its score was stored, with a new Size 4
truth, and every screen's delta then agrees: the score's tiles (the
Overview's), the Overview's Changes, Visibility's moved, True Value's drift,
Trade promotions' aside and Impact's since-the-baseline.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.services import console_score as score_svc
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2m1_attribute import R
from tests.test_console_2p1_two_cycles import WS, _get, _pair
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)

PREV = f2p1.CYCLE_1


def _refresh_truth(db, cycle_id, sku, truth):
    """rescore_cycle --refresh-reference on the cycle: supply's corrected own-page truth
    for one variant, and the envelope's refreshed_at."""
    with db.begin() as c:
        ref = c.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :c"), {'c': cycle_id}).scalar()
        ref = ref if isinstance(ref, dict) else json.loads(ref)
        for row in ref.get('prices') or []:
            if row.get('sku') == sku and row.get('role') == 'own' and row.get('attribute'):
                row['attribute'] = {**row['attribute'], 'stated': truth, 'truth': truth}
        ref['refreshed_at'] = datetime.now(timezone.utc).isoformat()
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = :c"), {'p': _encode(ref), 'c': cycle_id})


def _attribute(body) -> tuple:
    a = body['metric_counts'][body['metric_surface']]['attribute']
    return a['value'], a['of']


def _delta(now, then) -> str:
    d = now - then
    return f'+{d}' if d > 0 else str(d)


def test_every_delta_takes_the_previous_cycle_s_current_read(http, db, upstream):
    _pair(db, http, upstream)
    stored_before = score_svc.stored_score(db, f2p1.ID_1)
    assert _attribute(stored_before) == (61, 79)
    # supply corrected Swaddlers Size 4's range after cycle 1's score was stored: 22 to 37 lb
    _refresh_truth(db, f2p1.ID_1, 'v2', R(22, 37))

    score = _get(http, 'score', merchant=WS)
    tiles = {m['key']: m for m in score['metrics']}
    # the prior is cycle 1 recomputed on its refreshed reference, and stored as its own read stores it
    prior = score_svc.stored_score(db, f2p1.ID_1)
    assert prior['history'][-1]['replaced_because'] == 'cycle reference refreshed'
    assert _attribute(prior) == (63, 79)
    assert (tiles['attribute']['value'], tiles['attribute']['delta']) == (62, -1)
    assert score['previous']['score'] == prior['score']

    # Impact: what moved since the baseline, cycle 1 read live
    since = {m['label']: m for m in _get(http, 'revenue', merchant=WS)['since_baseline']}
    labels = {'attribute': 'Attribute accuracy', 'coverage': 'Retailer coverage', 'promo': 'Promo pass-through',
              'presence': 'Category presence'}
    for key, label in labels.items():
        m = tiles[key]
        assert since[label]['now'] == f"{m['value']} of {m['denominator']}", key
        assert since[label]['delta'] == _delta(m['value'], m['value'] - m['delta']), key
    assert (since['Attribute accuracy']['then'], since['Attribute accuracy']['delta']) == ('63 of 79', '-1')

    # the Overview's Changes: the weight-range lines sum to the tile's move, and coverage and the deals agree
    block = _get(http, 'overview', merchant=WS)['by_surface']['all']
    changes = {c['label']: c for c in block['changes']}
    sizes = {c['label']: c['delta'] for c in block['changes'] if c['label'].endswith('weight range right')}
    assert sizes == {'Newborn weight range right': '0', 'Size 4 weight range right': '-1'}
    assert sum(int(d) for d in sizes.values()) == tiles['attribute']['delta']
    assert int(changes['Retailer coverage']['delta']) == tiles['coverage']['delta']
    assert int(changes['Deals named, cheapest-place answers']['delta']) == tiles['promo']['delta']

    # Visibility's moved, against the same cycle 1
    vis = _get(http, 'visibility', merchant=WS)
    assert vis['moved']['all']['coverage']['delta'] == _delta(tiles['coverage']['value'],
                                                              tiles['coverage']['value'] - tiles['coverage']['delta'])
    # Trade promotions' aside
    assert _get(http, 'prove', merchant=WS)['aside']['delta']['delta'] == _delta(
        tiles['promo']['value'], tiles['promo']['value'] - tiles['promo']['delta'])
    # True Value's drift: the cells that changed verdict net to the Changes block's Prices right
    tv = _get(http, 'true-value', merchant=WS)
    net = sum(1 if d['dir'] == 'better' else -1 for d in tv['drift'])
    assert net == int(changes['Prices right']['delta'])
