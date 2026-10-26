"""
2T-3: eleven items from the Oct 26 walk of the brand Overview and TrueSync
(org 12, Pampers, cycle FL15-pampers-20261024, the compile-and-hold of Oct
26). Each test quotes what the live console showed.

Two kinds of input, each named where it is used:
  - the 2T-1 harness (2P-1's pair with supply #33's answers RECORDED,
    tests/fixtures/console/supply_2r1/PROVENANCE.md), served end to end;
  - FL15-shaped rows: FL15's retailer-prices and deals are production reads
    this pass never makes, so the rows that state FL15's shape (Amazon read by
    our own fetch, Target by the hosted render, Walmart walled on some SKUs;
    the Amazon list price cut and the Walmart Rollback) are built here in
    supply's served shape (truesync/fullloop/prices.py _row, deals.py) and say
    so. No model call, no production read.
"""
from app.services import console_brand_overview as bo
from app.services import console_release as rel

OWN = ['pampers.com']
SKUS = ['sku_pg_swd_nb_84', 'sku_pg_swd_s1_96', 'sku_pg_amore_s1_132', 'sku_pg_zzz_s4_104', 'sku_pg_cr360_s3_168',
        'sku_pg_swultra_s3']


def _shelf(domain, sku, method, price, at='2026-10-24T14:00:00'):
    """One FL15-shaped retailer-prices row (supply's served row, the fields these readers use)."""
    return {'retailer_domain': domain, 'role': 'retailer', 'sku': sku, 'gtin': None, 'variant_ref': f"feed_sku:{sku}",
            'observed_at': at, 'method': method, 'price': price,
            'read_status': 'ok' if method not in rel.WALLED_METHODS else 'blocked'}


def fl15_shelf_rows():
    """FL15's shelf as the walk found it: Amazon read by our own fetch on every SKU but one, Target by the hosted
    render (regex_rendered) on four, Walmart walled on three SKUs and read on three."""
    rows = []
    for i, sku in enumerate(SKUS):
        rows.append(_shelf('amazon.com', sku, 'none' if i == 5 else 'json_ld' if i % 2 else 'regex',
                           None if i == 5 else '27.97'))
        rows.append(_shelf('target.com', sku, 'none' if i in (3, 5) else 'regex_rendered',
                           None if i in (3, 5) else '27.99'))
        rows.append(_shelf('walmart.com', sku, 'none' if i in (0, 2, 4) else 'regex', None if i in (0, 2, 4) else '27.97'))
    return rows


def _old_activity_line(prices):
    """The activity's shelf line as 2T-1 counted it (any SKU walled walls its retailer), for the before."""
    shelf = [r for r in prices if r.get('observed_at')]
    domains = {r['retailer_domain'] for r in shelf}
    walled = sorted({bo._name(r['retailer_domain']) for r in shelf if r.get('price') is None
                     and r.get('method') in ('none', 'wall')})
    return bo.T['activity.shelf'].format(n=len(domains), read=len(domains) - len(walled), walled=bo.T[
        'activity.shelf.walled'].format(names=bo.manu._and(walled)) if walled else '')


# ── 1: the activity and the timeline read the shelf one way ─────────────

def test_the_activity_counts_shelf_reads_the_way_the_timeline_does():
    prices = fl15_shelf_rows()
    before = _old_activity_line(prices)
    assert before == 'Shelf reads at 3 retailers: 0 read, Amazon, Target and Walmart walled'   # what the walk saw
    activity = bo.build_activity(cycle={'status': 'complete'}, first_at=None, last_at=None, answers=0, usable=0,
                                 agents=6, questions=0, prices=prices, own_domains=OWN, pubs=[], workspace=None)
    shelf = next(e for e in activity if e['stage'] == 'shelf')
    assert shelf['text'] == 'Shelf reads at 3 retailers: 3 read'
    assert (shelf['read'], shelf['walled'], shelf['walled_skus']) == (
        ['Amazon', 'Target', 'Walmart'], [], {'Amazon': 1, 'Target': 2, 'Walmart': 3})
    # the same helper on one record's rows (the Zzz Size 4 SKU): Target walled on it, Amazon and Walmart read
    zzz = [r for r in prices if r['sku'] == 'sku_pg_zzz_s4_104']
    assert rel.shelf_reads(zzz, OWN)['read'] == ['Amazon', 'Walmart']
    assert rel.shelf_reads(zzz, OWN)['walled'] == ['Target']
    line = rel.timeline([{'sku': 'sku_pg_zzz_s4_104'}], {}, prices=prices, own_domains=OWN, lines=[], cycle=None,
                        channels={})
    assert [e['what'] for e in line] == ['Shelf read: Amazon and Walmart read. Target walled']
    # a retailer walled on every SKU is named
    walled = [r for r in prices if r['retailer_domain'] != 'walmart.com'] + \
        [_shelf('walmart.com', s, 'none', None) for s in SKUS]
    activity = bo.build_activity(cycle={'status': 'complete'}, first_at=None, last_at=None, answers=0, usable=0,
                                 agents=6, questions=0, prices=walled, own_domains=OWN, pubs=[], workspace=None)
    assert next(e for e in activity if e['stage'] == 'shelf')['text'] == \
        'Shelf reads at 3 retailers: 2 read, Walmart walled'
