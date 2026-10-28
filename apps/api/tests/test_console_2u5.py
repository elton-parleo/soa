"""
2U-5 (B): what the Oct 27 evening compiles showed.

On 2U-2's harness with supply's answers RECORDED from parleo-supply-app on
the Pampers feed as committed to production (tests/fixtures/console/
supply_2u5/, PROVENANCE.md there): ten SKUs in seven lines, the recorded
reads of Oct 19, rules r1, r2, r5 and r6 on and approved, r3 off, r4
waiting. The recording's merchant is `pampers-2u1`; it is served here as
the harness's `pampers-2r1` (`_rename`), so 2P-1's pair and its cycles read it.
"""
import json
import os

from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import _pair
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG = f2r2.SLUG
RECORDED_SLUG = 'pampers-2u1'
HERE = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2u5')


def _rename(value):
    return json.loads(json.dumps(value).replace(RECORDED_SLUG, SLUG))


def recorded(name):
    with open(os.path.join(HERE, f'{name}.json')) as fh:
        return _rename(json.load(fh)['body'])


def _shape(db, http, upstream, *, publish='publish'):
    _pair(db, http, upstream)
    f2r2.retag(db)
    f2r2.alias(upstream)
    f2r2.answer(upstream)
    for name in ('feed', 'catalog', 'retailers', 'retailer-prices', 'rules'):
        upstream.answer('GET', f'{f2r2.BASE}/{name}', body=recorded(name), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/tenant', body=recorded('tenant-held'), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=recorded('publications-held'), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/channels', body=recorded('channels'), token=TOKEN_A)
    upstream.answer('POST', f'{f2r2.BASE}/publish', body=recorded(publish), token=TOKEN_A)


def _read(http, endpoint, status=200, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'merchant': SLUG, 'org': 10, **params})
    assert r.status_code == status, r.text
    return r.json()


def _dump(name, body):
    """SOA_2U5_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2U5_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


# ─── B3: dates in the workspace's timezone ────────────────────────────────

def test_a_compile_at_night_in_los_angeles_reads_its_local_day(http, db, upstream):
    _shape(db, http, upstream)
    compiled_at = recorded('tenant-held')['merchants'][0]['held']['compiled_at']
    assert compiled_at.startswith('2026-10-28T03:'), 'the press was the evening of Oct 27 in Los Angeles'
    ts = _read(http, 'truesync')
    _dump('truesync-2u5.json', ts)
    assert ts['release']['day'] == 'Oct 27'
    assert {c['id']: c['line'] for c in ts['channels']}['manufacturer_center'].endswith('· Oct 27')
    pub = _read(http, 'publishing')
    assert 'Oct 28' not in json.dumps(pub['surfaces']) + json.dumps(pub['preview'])
    assert pub['preview']['note'].startswith('Compiled Oct 27 ')


def test_the_day_formatter_reads_stamps_in_the_zone_and_dates_as_they_are(monkeypatch):
    from app.services import console_days
    monkeypatch.delenv('SOA_DEFAULT_TIMEZONE', raising=False)
    console_days.use_zone(None)
    assert console_days.zone() == 'America/Los_Angeles'
    assert console_days.short_day('2026-10-28T03:05:00') == 'Oct 27', 'naive stamps are UTC'
    assert console_days.short_day('2026-10-28T03:05:00+00:00') == 'Oct 27'
    assert console_days.short_day('2026-10-24') == 'Oct 24', 'a date has no time to convert'
    console_days.use_zone('Europe/London')
    assert console_days.short_day('2026-10-28T03:05:00') == 'Oct 28'
    console_days.use_zone(None)


# ─── B1: a press clears the org's supply cache ────────────────────────────

def _supply_reads(upstream, path):
    return sum(1 for c in upstream.calls if c['method'] == 'GET' and c['path'].endswith(path))


def test_a_compile_drops_the_org_s_kept_supply_reads(http, db, upstream, monkeypatch):
    from app.services import console_cache
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '1')
    console_cache.clear()
    _shape(db, http, upstream)
    retailers = f'{f2r2.BASE}/retailers'
    _read(http, 'truesync')
    first = _supply_reads(upstream, retailers)
    assert first >= 1
    _read(http, 'truesync')
    assert _supply_reads(upstream, retailers) == first, 'warm: kept per org (2Q-1)'
    assert any(k[0] == 'supply' and k[1] == 10 for k in console_cache._entries)
    as_('op')
    r = http.post('/api/console/publishing/compile', params={'merchant': SLUG, 'org': 10})
    assert r.status_code == 200, r.text
    body = r.json()
    _dump('publishing-2u5-compile.json', body)
    # the answer carries the fresh /tenant record and TrueSync re-read after the press
    assert body['tenant']['slug'] == SLUG and body['tenant']['held']['compiled_at']
    assert body['truesync']['release']['day'] == 'Oct 27' and body['truesync']['workspace']
    after_press = _supply_reads(upstream, retailers)
    assert after_press > first, 'the re-read after the press asked supply again'
    _read(http, 'truesync')
    assert _supply_reads(upstream, retailers) == after_press, 'and is kept again from there'
    console_cache.clear()


def test_forget_org_drops_only_that_org(monkeypatch):
    from app.services import console_cache
    monkeypatch.setenv('SOA_CONSOLE_CACHE', '1')
    console_cache.clear()
    console_cache._put(('supply', 12, 'get_retailers', ('pampers',), ()), (200, {}, None), 300)
    console_cache._put(('supply', 13, 'get_retailers', ('other',), ()), (200, {}, None), 300)
    console_cache._put(('value', 'kind', 12, 'pampers'), 'brand', 300)
    console_cache._put(('cycle', 'visibility', (1,), 'x'), {}, 300)
    assert console_cache.forget_org(12) == 2
    assert {k[0] for k in console_cache._entries} == {'supply', 'cycle'}
    assert all(k[1] != 12 for k in console_cache._entries if k[0] == 'supply')
    console_cache.clear()



# ─── B2: counts in SKUs; B4: one Site markup label ────────────────────────

def test_every_count_on_the_release_page_is_skus(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    w = ts['workspace']
    # ten SKUs in seven lines, on five channels in this pass (schema_org, Manufacturer Center, ACP, UCP, MCP)
    assert (w['records'], w['lines']) == (10, 7)
    assert w['compiled'] == {'n': 40, 'of': 50}
    assert (w['published'], w['blocked']) == (10, 10), 'MCP serves 10; ACP blocks 4 SKUs, UCP 6'
    assert (ts['release']['name'], ts['release']['products']) == ('Ten records, Manufacturer Center first', 10)
    lines = {c['id']: c['line'] for c in ts['channels']}
    assert lines['schema_org'] == lines['manufacturer_center'] == '10 of 10 SKUs held · Oct 27'
    assert lines['acp'] == '6 of 10 SKUs held · 4 blocked · Oct 27'
    assert lines['ucp_uip'] == '4 of 10 SKUs held · 6 blocked · Oct 27'
    assert lines['mcp'] == '10 records served · verified Oct 27 at mcp.parleo.example'
    release = {s['channel']: s['status'] for s in ts['release']['surfaces']}
    assert release['acp'] == 'Compiled, held · 6 of 10 SKUs held · 4 blocked · Oct 27'
    assert release['manufacturer_center'] == 'Compiled, held · 10 of 10 SKUs held · Oct 27'


def test_publishing_counts_skus_and_says_what_valid_counted(http, db, upstream):
    _shape(db, http, upstream)
    pub = _read(http, 'publishing')
    _dump('publishing-2u5.json', pub)
    assert pub['preview']['title'] == 'Ten Pampers records, Manufacturer Center first'
    mfc = next(s for s in pub['surfaces'] if s['channel'] == 'manufacturer_center')
    # before 2U-5: valid *lines* (3: a Manufacturer Center file without a GTIN does not validate) over supply's SKUs
    assert (mfc['lines_valid'], mfc['records_valid'], mfc['records_total']) == (3, 6, 10)
    assert mfc['records'] == '6 of 10 valid'
    assert '6 of 10 valid' in pub['preview']['note']


def test_site_markup_reads_held_first_and_the_drift_as_its_qualifier(http, db, upstream):
    _shape(db, http, upstream)
    words = 'Compiled, held · 10 of 10 SKUs held · Oct 27 · site still drifts (read Oct 19)'
    ts = _read(http, 'truesync')
    assert next(s['status'] for s in ts['release']['surfaces'] if s['channel'] == 'schema_org') == words
    pub = _read(http, 'publishing')
    markup = next(s for s in pub['surfaces'] if s['channel'] == 'schema_org')
    assert (markup['status'], markup['site_status']) == ('held', 'drift')
    assert f"Compiled, held · {markup['last']}" == words, 'Publishing and the release card never disagree'
    assert markup['note'] and 'markup' in markup['note'], 'the drift is still explained'

