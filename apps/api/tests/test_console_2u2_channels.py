"""
2U-2: /truesync in manufacturer mode lists every channel supply has, each
with a state and a reason the console can show, and the workspace, the
release card, the Overview's TrueSync card and Publishing read that one list
(console_release.channel_list).

On 2T-1's harness (2P-1's pair, #33's recorded supply answers), with the
three answers 2U-2 changes RECORDED from parleo-supply-app 2U-2
(tests/fixtures/console/supply_2u2/, PROVENANCE.md there): /tenant (its
`channels[]` plan and `held.published.mcp`), /publications (the mcp rows,
published) and /channels. Same merchant, same feed, same harness as #33's.
A state the recording did not produce (a blocked channel naming its rule, a
failed mcp publish) is derived from its rows in the test that needs it, and
says so. sqlite and Postgres.
"""
import copy
import json
import os

from app.services import console_release as rel
from tests import console_fixture_2p1 as f2p1
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2p1_two_cycles import _pair
from tests.test_console_read_models import TOKEN_A, as_, http, upstream  # noqa: F401  (pytest fixtures)

SLUG = f2r2.SLUG
HERE = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2u2')
MCP_REF = 'https://mcp.parleo.example#get_product_facts'


def recorded(name):
    with open(os.path.join(HERE, f'{name}.json')) as fh:
        return json.load(fh)['body']


def _shape(db, http, upstream, *, tenant=None, publications=None):
    _pair(db, http, upstream)
    f2r2.retag(db)
    f2r2.alias(upstream)
    f2r2.answer(upstream)
    upstream.answer('GET', '/api/truesync/tenant', body=tenant or recorded('tenant-held'), token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=publications or recorded('publications-held'),
                    token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/channels', body=recorded('channels'), token=TOKEN_A)
    upstream.answer('POST', f'{f2r2.BASE}/publish', body=recorded('publish'), token=TOKEN_A)


def _read(http, endpoint, status=200, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'merchant': SLUG, 'org': 10, **params})
    assert r.status_code == status, r.text
    return r.json()


def _dump(name, body):
    """SOA_2U2_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2U2_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


def _mine():
    return f2r2.mine(recorded('publications-held'))


EIGHT = [
    ('schema_org', 'held', 'Held', '4 of 4 compiled · Oct 27', 'held_for_merchant', None),
    ('merchant_center', 'not_for_brand', 'Not for a brand', "a seller's channel (rule r3)", 'not_for_brand', 'r3'),
    ('manufacturer_center', 'held', 'Held', '4 of 4 compiled · Oct 27', 'held_for_merchant', None),
    ('acp', 'blocked', 'Blocked', 'its spec refuses the record', 'held_for_merchant', None),
    ('ucp_uip', 'not_compiled', 'Not in this pass', 'not compiled in manufacturer mode (first pass)', 'not_compiled',
     None),
    ('deals_api', 'next', 'Next release', 'after rule r4', 'after_rule', 'r4'),
    ('mcp', 'live', 'Live', '4 records served · verified Oct 27', 'published_by_parleo', None),
    ('deal_directory', 'not_for_brand', 'Not for a brand', "a seller's channel (rule r3)", 'not_for_brand', 'r3'),
]


def test_the_matrix_lists_all_eight_channels_with_their_states(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    _dump('truesync-2u2.json', ts)
    assert [(c['id'], c['state'], c['label'], c['line'], c['reason'], c['rule']) for c in ts['channels']] == EIGHT
    # the column keeps what the seller matrix said about the channel (its full name, spec) beside its state
    mcp = next(c for c in ts['channels'] if c['id'] == 'mcp')
    assert (mcp['short'], mcp['spec'], mcp['note']) == ('MCP server', 'parleo-internal', MCP_REF)
    acp = next(c for c in ts['channels'] if c['id'] == 'acp')
    assert acp['note'] == next(r['spec_clause'] for r in _mine() if r['channel_slug'] == 'acp')
    assert ts['cell_states'] == ['held', 'published', 'live', 'blocked', 'next', 'not_for_brand', 'na']
    # cells per record follow the channel's state
    cells = {p['name']: {k: c['s'] for k, c in p['cells'].items()} for p in ts['products']}
    assert list(cells) == ['Pampers Swaddlers', 'Pampers Pure Protection', 'Pampers AMORE', 'Pampers Zzz']
    assert {tuple(c.items()) for c in cells.values()} == {(
        ('schema_org', 'held'), ('merchant_center', 'not_for_brand'), ('manufacturer_center', 'held'),
        ('acp', 'blocked'), ('ucp_uip', 'na'), ('deals_api', 'next'), ('mcp', 'live'),
        ('deal_directory', 'not_for_brand'))}
    zzz = next(p for p in ts['products'] if p['name'] == 'Pampers Zzz')
    assert zzz['cells']['deals_api']['note'] == 'after rule r4'
    assert zzz['cells']['mcp']['publication_id'] in {r['id'] for r in _mine() if r['channel_slug'] == 'mcp'}
    # the MCP server's row is a serve check: no compiler panel; the timeline says it is live
    assert 'mcp' not in {c['channel'] for c in zzz['compiler']}
    assert zzz['timeline'][-1]['what'] == ('Compiled in manufacturer mode. Held on Site markup and Manufacturer '
                                           'Center, blocked on ACP feed. Live on MCP server, which Parleo serves')
    # WebMCP is not a channel supply has, so it is not a column
    assert 'webmcp' not in {c['id'] for c in ts['channels']}


def test_workspace_release_card_and_overview_read_the_same_list(http, db, upstream):
    _shape(db, http, upstream)
    ts = _read(http, 'truesync')
    ws = ts['workspace']
    assert [(s['channel'], s['state'], s['line']) for s in ws['surfaces']] == [(c, s, line) for c, s, _l, line, *_ in
                                                                             EIGHT]
    assert ws['surfaces'] == [{k: v for k, v in c.items()} for c in rel.channel_list(
        pubs=_mine(), channels=recorded('channels'), plan=next(
            m for m in recorded('tenant-held')['merchants'] if m['slug'] == SLUG)['channels'],
        held=next(m for m in recorded('tenant-held')['merchants'] if m['slug'] == SLUG)['held'])]
    assert ws['channels'] == {'held': 2, 'blocked': 1, 'live': 1, 'next': 1, 'not_for_brand': 2, 'not_compiled': 1}
    assert (ws['published'], ws['live']) == (4, 4)
    release = ts['release']
    assert [(s['channel'], s['state'], s['status']) for s in release['surfaces']] == [
        ('schema_org', 'held', 'Compiled, held · Oct 27'),
        ('merchant_center', 'not_for_brand', "Not for a brand · a seller's channel (rule r3)"),
        ('manufacturer_center', 'held', 'Compiled, held · Oct 27'),
        ('acp', 'blocked', 'Blocked · Oct 27'),
        ('ucp_uip', 'not_compiled', 'Not in this pass'),
        ('deals_api', 'next', 'Next release · after rule r4'),
        ('mcp', 'live', 'Live · 4 records served · verified Oct 27'),
        ('deal_directory', 'not_for_brand', "Not for a brand · a seller's channel (rule r3)")]
    overview = _read(http, 'overview', cycle=f2p1.CYCLE_2)
    _dump('overview-2u2.json', overview)
    card = overview['truesync_card']
    assert card['surfaces'] == ws['surfaces'] and card['published'] == ws['published']


def test_publishing_lists_the_same_channels(http, db, upstream):
    _shape(db, http, upstream)
    pub = _read(http, 'publishing')
    _dump('publishing-2u2.json', pub)
    surfaces = {s['id']: s for s in pub['surfaces']}
    assert [(s['channel'], s['state']) for s in pub['surfaces']] == [(c, s) for c, s, *_ in EIGHT]
    assert list(surfaces) == ['markup', 'gmc', 'mfc', 'oai', 'ucp', 'coupons', 'mcp', 'directory']
    mcp = surfaces['mcp']
    assert (mcp['name'], mcp['status'], mcp['last'], mcp['external_ref']) == (
        'Parleo MCP server', 'live', '4 records served · verified Oct 27', MCP_REF)
    assert mcp['note'] == "Served by get_product_facts on Parleo's own server. Nothing is sent to anyone's account"
    assert (surfaces['mfc']['status'], surfaces['oai']['status'], surfaces['coupons']['status']) == \
        ('held', 'blocked', 'next')
    assert surfaces['directory']['label'] == 'Not for a brand'
    # nothing is held for the MCP server, so there is no file to download
    assert [a['channel'] for a in pub['artifacts']] == ['manufacturer_center', 'schema_org', 'acp']


def test_the_compile_passes_supply_s_readback_and_reasons(http, db, upstream):
    _shape(db, http, upstream)
    as_('op')
    r = http.post('/api/console/publishing/compile', params={'merchant': SLUG, 'org': 10})
    assert r.status_code == 200, r.text
    compiled = r.json()['compile']
    assert compiled['rows'] == 16 and compiled['by_channel']['mcp'] == {'published': 4}
    assert compiled['readback'] == recorded('publish')['readback'] and compiled['readback']['acceptance'] == 'approved'
    assert {s['channel']: s['reason'] for s in compiled['not_compiled']} == {
        'merchant_center': 'not_for_brand', 'ucp_uip': 'not_compiled', 'deals_api': 'after_rule',
        'deal_directory': 'not_for_brand'}


def test_the_record_lists_the_pass_and_mcp_live(http, db, upstream):
    _shape(db, http, upstream)
    body = _read(http, 'record', product='sku_pg_swd_nb_84')
    assert [(s['channel'], s['word']) for s in body['surfaces']] == [
        ('schema_org', 'Held in preview'), ('manufacturer_center', 'Held in preview'), ('acp', 'Blocked'),
        ('mcp', 'Live')]


# ── derived from the recorded rows ───────────────────────────────────────

def _plan():
    return next(m for m in recorded('tenant-held')['merchants'] if m['slug'] == SLUG)


def test_a_blocked_channel_names_its_rule():
    """Derived: the recording's rules are off, so the ACP row names no rule; with r1 on supply's compile writes
    "Manufacturer mode, rule r1: no price on any channel" on its price line (manufacturer_mode.rule_flags)."""
    rows = copy.deepcopy(_mine())
    for r in rows:
        if r['channel_slug'] == 'acp':
            r['expressiveness'] = [{'field': 'price', 'severity': 'dropped',
                                    'note': 'Manufacturer mode, rule r1: no price on any channel (no shelf price, no MSRP).'}]
    acp = next(c for c in rel.channel_list(pubs=rows, channels=recorded('channels'), plan=_plan()['channels'],
                                           held=_plan()['held']) if c['channel'] == 'acp')
    assert (acp['state'], acp['rule'], acp['line']) == ('blocked', 'r1', 'rule r1')
    assert rel.release_status(acp, 'Oct 27') == 'Blocked · rule r1 · Oct 27'


def test_a_failed_mcp_publish_is_not_live():
    """Derived: supply journals mcp `failed` without PARLEO_MCP_PUBLIC_URL (or a SKU that does not resolve)."""
    error = 'PARLEO_MCP_PUBLIC_URL is not set: the server\'s public URL is this publication\'s external_ref'
    rows = [{**r, 'status': 'failed', 'error': error, 'external_ref': None} if r['channel_slug'] == 'mcp' else r
            for r in copy.deepcopy(_mine())]
    held = {**_plan()['held'], 'published': {'mcp': {'records': 0, 'failed': 4}}}
    mcp = next(c for c in rel.channel_list(pubs=rows, channels=recorded('channels'), plan=_plan()['channels'],
                                           held=held) if c['channel'] == 'mcp')
    assert (mcp['state'], mcp['line']) == ('blocked', f'Not published: {error}')


def test_an_mcp_readback_that_disagrees_says_how_many_resolve():
    held = copy.deepcopy(_plan()['held'])
    held['published']['mcp'].update(acceptance='disapproved', verified_skus='5/6')
    mcp = next(c for c in rel.channel_list(pubs=_mine(), channels=recorded('channels'), plan=_plan()['channels'],
                                           held=held) if c['channel'] == 'mcp')
    assert (mcp['state'], mcp['line']) == ('live', '4 records served · 5 of 6 resolve (Oct 27)')


def test_a_supply_with_no_plan_reads_the_same_reasons():
    """A supply before 2U-2 serves no `channels[]`: the fallback plan gives the same reasons."""
    with_plan = rel.channel_list(pubs=_mine(), channels=recorded('channels'), plan=_plan()['channels'],
                                 held=_plan()['held'])
    without = rel.channel_list(pubs=_mine(), channels=recorded('channels'), plan=None, held=_plan()['held'])
    keep = ('channel', 'state', 'reason', 'rule')
    assert [{k: c[k] for k in keep} for c in without] == [{k: c[k] for k in keep} for c in with_plan]
