"""
2T-11 (B1): `/revenue` within the function's limit.

Live on Oct 27 (org 12, FL15): `GET /api/console/revenue?merchant=pampers&cycle=FL15-…` failed after ~30 s ("Failed
to fetch", twice); Impact showed "Couldn't load this screen" and Trade promotions' dollars stayed "reading the
model". 2T-8 (B7) recomputed every scored cycle's score on every read for the charter series, walked the
since-baseline chain reading each cycle's rows uncached, and read each cycle's baseline rows again for the
sent block.

Now one point per cycle (revenue_points.cycle_point: lost, missed, at stake, gainable and the four charter
measures), kept under the cycle's stamp, the scorer version and the revenue inputs' digest. `/revenue` reads the
current cycle's point and the prior's; the series is `/revenue/history`'s, read from the same points.

A "full cycle read" is a cycle's runs read whole (parity.load_overview_rows), which every score, Visibility and
comparison of the cycle starts from. On the 2T-1 harness (2P-1's pair with supply #33's answers RECORDED) and
two more weeks cloned on (four cycles). No model call, no production read.
"""
import time
from collections import Counter

import pytest

from app.services import console_cache
from app.services import console_parity as parity
from tests import console_fixture_2p1 as f2p1
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import _encode, http, upstream  # noqa: F401  (pytest fixtures)
from tests.test_console_2t1_overview_truesync import _read, _shape

CYCLE_3, CYCLE_4 = 'FL5-wiggle-and-snug-20261028', 'FL6-wiggle-and-snug-20261104'
ID_3, ID_4 = 231, 232


def _four(db, http, upstream):
    """Four scored cycles, each score stored as the console's first read (the Overview's) stores it: the budget is
    /revenue's own."""
    _shape(db, http, upstream)
    f2p1.clone_cycle(db, _encode, f2p1.ID_2, ID_3, CYCLE_3, 2 * f2p1.RUN_OFFSET)
    f2p1.clone_cycle(db, _encode, ID_3, ID_4, CYCLE_4, 3 * f2p1.RUN_OFFSET)
    for code in (f2p1.CYCLE_1, f2p1.CYCLE_2, CYCLE_3, CYCLE_4):
        _read(http, 'score', cycle=code)


@pytest.fixture
def cache_on(monkeypatch):
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '1')
    console_cache.clear()


@pytest.fixture
def cycle_reads(monkeypatch):
    """The cycles whose runs a read reads whole, by id."""
    seen = Counter()
    load = parity.load_overview_rows

    def counted(conn, cycle, *a, **k):
        seen[cycle["id"]] += 1
        return load(conn, cycle, *a, **k)
    monkeypatch.setattr(parity, 'load_overview_rows', counted)
    return seen


def _timed(http, upstream, endpoint, seen, **params):
    seen.clear()
    calls, started = len(upstream.calls), time.perf_counter()
    body = _read(http, endpoint, **params)
    return body, time.perf_counter() - started, dict(seen), len(upstream.calls) - calls


def test_revenue_reads_two_cycles_cold_and_none_warm(http, db, upstream, cache_on, cycle_reads):
    _four(db, http, upstream)
    console_cache.clear()
    cold, cold_s, cold_reads, cold_calls = _timed(http, upstream, 'revenue', cycle_reads, cycle=CYCLE_4)
    warm, warm_s, warm_reads, warm_calls = _timed(http, upstream, 'revenue', cycle_reads, cycle=CYCLE_4)
    history, hist_s, hist_reads, hist_calls = _timed(http, upstream, 'revenue/history', cycle_reads)
    print(f'\n2T-11 four cycles: /revenue cold {cold_s:.2f}s, cycles read {cold_reads}, {cold_calls} supply calls; '
          f'warm {warm_s:.2f}s, {warm_reads}, {warm_calls} supply calls; /revenue/history after {hist_s:.2f}s, '
          f'{hist_reads}, {hist_calls} supply calls')
    assert len(cold_reads) <= 2 and set(cold_reads) <= {ID_3, ID_4}, cold_reads
    assert warm_reads == {}, warm_reads
    assert warm == cold
    assert cold_s < 10 and warm_s < 2
    # the series is history's: every scored cycle once, oldest first
    assert 'series' not in cold
    assert [c['cycle'] for c in history['cycles']][-4:] == [f2p1.CYCLE_1, f2p1.CYCLE_2, CYCLE_3, CYCLE_4]


def test_the_fl15_pair_cold_and_warm(http, db, upstream, cache_on, cycle_reads):
    """The FL15-shaped pair (2T-1's harness): the prior compares, so it is the baseline: two cycles, cold."""
    _shape(db, http, upstream)
    _read(http, 'score', cycle=f2p1.CYCLE_2)
    console_cache.clear()
    cold, cold_s, cold_reads, cold_calls = _timed(http, upstream, 'revenue', cycle_reads, cycle=f2p1.CYCLE_2)
    warm, warm_s, warm_reads, warm_calls = _timed(http, upstream, 'revenue', cycle_reads, cycle=f2p1.CYCLE_2)
    print(f'\n2T-11 FL15 pair: /revenue cold {cold_s:.2f}s, cycles read {cold_reads}, {cold_calls} supply calls; '
          f'warm {warm_s:.2f}s, {warm_reads}, {warm_calls} supply calls')
    assert set(cold_reads) <= {f2p1.ID_1, f2p1.ID_2} and warm_reads == {} and warm == cold
    assert cold['baseline_cycle'] == f2p1.CYCLE_1 and cold['since_baseline']


def test_the_series_reads_the_cached_points(http, db, upstream, cache_on, cycle_reads):
    """History after /revenue reads only the cycles /revenue did not, and a second history read none."""
    _four(db, http, upstream)
    console_cache.clear()
    _read(http, 'revenue', cycle=CYCLE_4)
    _first, _s, reads, _c = _timed(http, upstream, 'revenue/history', cycle_reads)
    assert set(reads) == {f2p1.ID_1, f2p1.ID_2}, reads
    again, _s, reads, _c = _timed(http, upstream, 'revenue/history', cycle_reads)
    assert reads == {} and again == _first
    assert [len(s['points']) for s in again['series']] == [4, 4, 4, 4]


# ── B2: the nits from the Oct 27 walk ─────────────────────────────────────

def test_the_trade_promotions_chip_carries_the_label(http, db, upstream):
    """Live: "+3 vs FL14-pampers-20261023". The delta now carries its pair's label, as every chip does."""
    _shape(db, http, upstream)
    delta = _read(http, 'prove', cycle=f2p1.CYCLE_2)['aside']['delta']
    assert delta['vs'] == 'vs Oct 14'


def test_the_record_title_names_the_variant_once():
    """Live: "Pampers Swaddlers, Pampers Swaddlers, Newborn, 84 ct…": the feed's label led with the product name."""
    from app.services import console_product_record as pr
    v = {'product_name': 'Pampers Swaddlers', 'label': 'Pampers Swaddlers, Newborn, 84 ct', 'count': 84}
    assert pr.record_sub(v, None) == 'Newborn, 84 ct'
    assert pr.record_sub({**v, 'label': 'Newborn, 84 ct'}, None) == 'Newborn, 84 ct'


def test_a_markup_gtin_mismatch_is_an_issue():
    """Live: the GTIN row read "Markup shows 037000772552 for Newborn" while Issues said "None found"."""
    from app.services import console_product_record as pr
    v = {'product_name': 'Pampers Swaddlers', 'label': 'Newborn, 84 ct', 'gtin': '037000749622'}
    markup = {'differences': [{'field': 'gtin', 'record': '037000749622', 'page': '037000772552'}]}
    issues = pr.build_issues(v, page=None, charts=None, feed_rows=None, brand='Pampers', domain='pampers.com',
                             attribute_answers=[], drift=[], shelf_rows=[], flags=[], chart_weight=None, markup=markup)
    assert [(i['kind'], i['fix_kind'], i['text']) for i in issues] == [
        ('gtin_mapping', 'gtin', "Markup names another GTIN for Newborn: 037000772552 against the feed's 037000749622.")]


def test_the_size_chart_fix_names_the_sizes_asked():
    """Live: fix 02 listed every size with two charts. Size 4 is the study's; the others are behind More."""
    from app.services import console_fixes as fx
    two = lambda size, a, b: {'size': size, 'groups': [{'range': a, 'lines': ['Swaddlers']},  # noqa: E731
                                                       {'range': b, 'lines': ['Zzz']}]}
    signal = {'facts': {'two': [two('Size 3', '16 to 28 lb', '13 to 26 lb'), two('Size 4', '15 to 34 lb', '22 to 37 lb')]}}
    text, more = fx.size_chart_text(signal, [], 'pampers.com', ['Size 4'])
    assert text == 'Swaddlers Size 4: 15 to 34 lb. Zzz Size 4: 22 to 37 lb.'
    assert more == ['Swaddlers Size 3: 16 to 28 lb.', 'Zzz Size 3: 13 to 26 lb.']
    # no size asked: every size, nothing behind More
    text, more = fx.size_chart_text(signal, [], 'pampers.com', [])
    assert text.startswith('Swaddlers Size 3') and more == []


def test_the_release_counts_skus_and_the_why_line_counts_gating_requests(http, db, upstream):
    """Live: "Send the Manufacturer Center file · 7 records" beside Publishing's 10; Approvals' why-line "0
    approvals stand between …" under "3 of 4 requests waiting"."""
    _shape(db, http, upstream)
    fixes = {f['kind']: f for f in _read(http, 'fixes')['fixes']}
    approvals = _read(http, 'approvals')
    release = next(r for r in approvals['requests'] if r['code'] == 'release')
    assert fixes['release']['text'].startswith('6 records ') and fixes['release']['scope'] == '6 SKUs'
    assert release['title'] == '6 records, Manufacturer Center first' and release['text'].startswith('The held file: 6 ')
    s = approvals['summary']
    assert (s['waiting'], s['gating']) == (3, 3)
    assert s['why'] == '3 approvals stand between the record and what it can win back.'
