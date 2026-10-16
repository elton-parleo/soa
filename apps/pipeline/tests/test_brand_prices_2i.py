"""
2I B2, the worker's side: a brand's snapshot carries the newest
retailer-prices read, so the study the worker generates asks one price
question per variant x retailer page with that page's price expected; and
the cycle's reference index never scores against a comparison page. Supply
is the real client over recorded payloads (apps/api/tests/fixtures/console,
README.md 2H and 2I): no network.
"""
import copy
import json
import os

from clients.truesync_catalog import TrueSyncCatalogClient
from generation import catalog_tiers as ct
from scoring.retailer_reference import ReferenceSet

CONSOLE = os.path.join(os.path.dirname(__file__), '..', '..', 'api', 'tests', 'fixtures', 'console')
BRAND = 'wiggle-and-snug-brand'
BASE = f'/api/truesync/merchants/{BRAND}'


def _json(name):
    with open(os.path.join(CONSOLE, name)) as fh:
        return json.load(fh)


WSB = _json('supply_ws_brand_2i.json')


class Supply(TrueSyncCatalogClient):
    def __init__(self, down=()):
        super().__init__(base_url='https://supply.example', token='t')
        self.down, self.calls = set(down), []
        self.paths = {
            '/api/truesync/tenant': _json('supply_tenant_ws_2h.json'),
            '/api/truesync/merchants': [],
            f'{BASE}/catalog': WSB['catalog'],
            f'{BASE}/incentives': WSB['incentives'],
            f'{BASE}/retailers': _json('supply_retailers_ws_2h.json')[BRAND],
            f'{BASE}/feed': WSB['feed'],
            f'{BASE}/retailer-prices': WSB['retailer_prices'],
        }

    def _get(self, path, params=None):
        self.calls.append(path)
        if path in self.down:
            return None, 'upstream returned 503'
        if path not in self.paths:
            return None, f'no TrueSync merchant at {path}'
        return self.paths[path], None


def accuracy(snap):
    return ct.build_catalog_accuracy(snap, category='Baby Care', persona='Value-Conscious Parent',
                                     study_pattern='brand_at_retail')


def test_the_workers_brand_snapshot_carries_the_read_and_asks_at_its_pages():
    supply = Supply()
    snap = supply.snapshot(BRAND, with_history=False)
    assert f'{BASE}/retailer-prices' in supply.calls
    assert sum(len(v) for v in snap.reads.values()) == 19
    rows, report = accuracy(snap)
    assert len(rows) == 19 and all(r['expected_answer']['amount'] for r in rows)
    assert {r['expected_answer']['attributed_to'] for r in rows} == {'trueshopstore.com'}
    assert report['price_source'][0]['read_count'] == 19


def test_a_failed_price_read_costs_the_price_questions_only():
    """The read fails: reads None, the 2B feed-price path, which for a feed
    with no price skips every variant. The rest of the snapshot stands."""
    snap = Supply(down={f'{BASE}/retailer-prices'}).snapshot(BRAND, with_history=False)
    assert snap.available and snap.reads is None and snap.reads_error == 'upstream returned 503'
    rows, report = accuracy(snap)
    assert rows == [] and len(report['skipped_no_price']) == 19


def test_a_hosted_merchants_snapshot_reads_no_prices():
    supply = Supply()
    supply.paths['/api/truesync/tenant'] = copy.deepcopy(supply.paths['/api/truesync/tenant'])
    for m in supply.paths['/api/truesync/tenant']['merchants']:
        m['hosting'] = 'parleo'
    snap = supply.snapshot(BRAND, with_history=False)
    assert f'{BASE}/retailer-prices' not in supply.calls and snap.reads is None


def test_the_reference_index_skips_comparison_rows():
    rows = [r for r in WSB['retailer_prices']['prices'] if r['role'] == 'retailer'][:1]
    rival = {**rows[0], 'price': '1.00', 'role': 'comparison'}
    refs = ReferenceSet({'prices': [rival] + rows})
    found = [row for (domain, _key), row in refs._rows.items() if domain == 'trueshopstore.com']
    assert found and {row.price for row in found} == {rows[0]['price']}   # the retailer's own row, not the rival's
