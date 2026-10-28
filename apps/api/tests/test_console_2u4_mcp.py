"""
2U-4 (B): the MCP cell and the release card read supply's readback against
the public server, every channel counts SKUs, and Approvals lists the rules a
blocked channel names.

On 2U-2's harness (tests/test_console_2u2_channels.py) with supply's answers
RECORDED from parleo-supply-app 2U-4 (tests/fixtures/console/supply_2u4/,
PROVENANCE.md there): the same merchant, feed and brand pages, its readback
now a client of the public server (a stand-in in supply's harness). Three
recordings of that readback: served (approved), a server without the tool
(disapproved, "tool not served at <url>") and a server that does not answer
(unavailable). The harness leaves the rules as seeded (off), so ACP and UCP
are blocked by r1 and r2, which their journals name. sqlite and Postgres.
"""
import json
import os

from app.services import console_fixes as fx
from app.services import console_release as rel
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import _pair
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG = f2r2.SLUG
HERE = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2u4')
HOST = 'mcp.parleo.example'


def recorded(name):
    with open(os.path.join(HERE, f'{name}.json')) as fh:
        return json.load(fh)['body']


def _mine_merchant(tenant):
    return next(m for m in tenant['merchants'] if m['slug'] == SLUG)


def _shape(db, http, upstream, *, tenant='tenant-held', publish='publish'):
    _pair(db, http, upstream)
    f2r2.retag(db)
    f2r2.alias(upstream)
    f2r2.answer(upstream)
    upstream.answer('GET', '/api/truesync/tenant', body=recorded(tenant), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=recorded('publications-held'), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/channels', body=recorded('channels'), token=TOKEN_A)
    upstream.answer('POST', f'{f2r2.BASE}/publish', body=recorded(publish), token=TOKEN_A)


def _read(http, endpoint, status=200, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'merchant': SLUG, 'org': 10, **params})
    assert r.status_code == status, r.text
    return r.json()


def _dump(name, body):
    """SOA_2U4_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2U4_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _mcp(channels):
    return next(c for c in channels if c['id'] == 'mcp')


def _release(ts, channel='mcp'):
    return next(s['status'] for s in ts['release']['surfaces'] if s['channel'] == channel)


# ─── the MCP cell and the release card ────────────────────────────────────

def test_verified_against_the_public_server_names_it(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    _dump('truesync-2u4.json', ts)
    mcp = _mcp(ts['channels'])
    assert (mcp['state'], mcp['check'], mcp['label']) == ('live', 'verified', 'Live')
    assert mcp['line'] == f'6 records served · verified Oct 27 at {HOST}', 'records are SKUs (supply S6)'
    assert mcp['check_reason'] is None
    assert _release(ts) == f'Live · 6 records served · verified Oct 27 at {HOST}'
    pub = _read(http, 'publishing')
    _dump('publishing-2u4.json', pub)
    surface = next(s for s in pub['surfaces'] if s['channel'] == 'mcp')
    assert (surface['status'], surface['label'], surface['check']) == ('live', 'Live', 'verified')


def test_a_server_without_the_tool_reads_tool_not_served(http, db, upstream):
    _shape(db, http, upstream, tenant='tenant-held-not-served', publish='publish-not-served')
    ts = _read(http, 'truesync')
    _dump('truesync-2u4-not-served.json', ts)
    mcp = _mcp(ts['channels'])
    assert (mcp['state'], mcp['check'], mcp['label']) == ('live', 'not_served', 'Tool not served')
    assert mcp['line'] == f'6 records published · {HOST} does not serve get_product_facts (Oct 27)'
    assert mcp['check_reason'] == f'tool not served at https://{HOST}'
    assert _release(ts) == f'Tool not served · 6 records published · {HOST} does not serve get_product_facts (Oct 27)'


def test_a_server_that_does_not_answer_reads_not_reachable(http, db, upstream):
    _shape(db, http, upstream, tenant='tenant-held-unreachable', publish='publish-unreachable')
    ts = _read(http, 'truesync')
    _dump('truesync-2u4-not-reachable.json', ts)
    mcp = _mcp(ts['channels'])
    served = _mine_merchant(recorded('tenant-held-unreachable'))['held']['published']['mcp']
    host = rel._host(served['server'])
    assert host.startswith('127.0.0.1:'), 'the recording asked a loopback port nothing listens on'
    assert (mcp['state'], mcp['check'], mcp['label']) == ('live', 'not_reachable', 'Not reachable')
    assert mcp['line'] == f'6 records published · {host} did not answer the check (Oct 27)'
    assert mcp['check_reason'].startswith(f"server not reachable at {served['server']}")
    assert _release(ts).startswith('Not reachable · 6 records published')
    assert 'Live' not in _release(ts), 'never Live while the public server is unverified'


def test_the_check_words_each_acceptance():
    assert rel.mcp_check({}) == 'unverified'
    assert rel.mcp_check({'verified_at': 'x', 'acceptance': 'approved'}) == 'verified'
    assert rel.mcp_check({'verified_at': 'x', 'acceptance': 'unavailable'}) == 'not_reachable'
    assert rel.mcp_check({'verified_at': 'x', 'acceptance': 'disapproved',
                          'reason': 'tool not served at https://mcp.parleo.io'}) == 'not_served'
    assert rel.mcp_check({'verified_at': 'x', 'acceptance': 'disapproved', 'reason': '1 SKU(s) not resolved'}) == \
        'disagrees'
    assert rel._host('https://mcp.parleo.io#get_product_facts') == 'mcp.parleo.io'


# ─── every channel counts SKUs ────────────────────────────────────────────

def test_every_held_channel_counts_skus(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    lines = {c['id']: c['line'] for c in ts['channels'] if c['state'] == 'held'}
    assert lines == {'schema_org': '6 of 6 SKUs held · Oct 27', 'manufacturer_center': '6 of 6 SKUs held · Oct 27'}


def test_the_compile_passes_supply_s_counts(http, db, upstream):
    _shape(db, http, upstream, publish='publish-dry-run')
    as_('op')
    r = http.post('/api/console/publishing/compile', params={'merchant': SLUG, 'org': 10, 'dry_run': 'true'})
    assert r.status_code == 200, r.text
    compiled = r.json()['compile']
    _dump('publishing-2u4-compile.json', r.json())
    assert compiled['counts']['records'] == {'schema_org': 6, 'manufacturer_center': 6, 'acp': 6, 'ucp_uip': 6,
                                             'mcp': 6}
    assert compiled['counts']['lines'] == {'schema_org': 4, 'manufacturer_center': 4, 'acp': 4, 'ucp_uip': 4,
                                           'mcp': 4}


# ─── Approvals: the rules a blocked channel names ─────────────────────────

def test_approvals_list_the_rules_that_gate_ucp_and_acp(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'approvals')
    _dump('approvals-2u4.json', body)
    by_code = {r['code']: r for r in body['requests']}
    for code in ('r1', 'r2'):
        req = by_code[code]
        assert (req['kind'], req['state'], req['writable'], req['fix']) == ('rule', 'pending', True, None)
        assert req['gates'] == ['ucp_uip', 'acp'] and req['gates_text'] == 'gates UCP and ACP prices'
        assert 'UCP and ACP stay blocked' in req['text']
    # still one request per rule, the release last
    codes = [r['code'] for r in body['requests']]
    assert len(codes) == len(set(codes)) and codes[-1] == 'release'


def test_blocked_rule_channels_reads_the_journal_and_an_older_clause():
    mine = f2r2.mine(recorded('publications-held'))
    assert fx.blocked_rule_channels(mine) == {'r1': ['ucp_uip', 'acp'], 'r2': ['ucp_uip', 'acp']}
    # a supply before 2U-4: no `rules` on the entry, the rule_off clause names them
    older = [{**r, 'journal': [{k: v for k, v in e.items() if k != 'rules'} for e in r.get('journal') or []]}
             for r in mine]
    assert fx.blocked_rule_channels(older) == {'r1': ['ucp_uip'], 'r2': ['ucp_uip']}
