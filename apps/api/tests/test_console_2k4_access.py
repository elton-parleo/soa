"""
2K-4 §B4: access identities named once.

FL13's Overview read "Access problems: Googlebot, Googlebot, bingbot, Parleo
(control)": two tokens share the display name Googlebot. rm.group_identities
names each display name once and counts its tokens ("Googlebot (2 tokens)"),
on /accessibility (`problem_identities`, which the Overview tile reads), the
Overview's access signal and Impact's Access line.
"""
import copy

from tests.test_console_2c3a import WS, _supply, db  # noqa: F401  (fixture)
from tests.test_console_2i9 import _fl12_money, _inputs
from tests.test_console_read_models import TOKEN_A, _fixture, as_, http, upstream  # noqa: F401  (fixtures)

WHO = 'Googlebot (2 tokens), bingbot, Parleo (control)'


def _two_googlebots(upstream):
    """The W&S access run with FL13's failures: two Googlebot tokens, bingbot, the control."""
    payload = copy.deepcopy(_fixture('supply_access_ws.json'))
    fail = {'ok': False, 'code': 'blocked', 'result': '0 of 1 pages answered'}
    payload['accessibility']['requests'] = [r for r in payload['accessibility']['requests'] if r['ok']] + [
        {'identity': 'Googlebot', 'vendor': 'gemini', 'agent': 'gemini', **fail},
        {'identity': 'Googlebot', 'vendor': 'gemini', 'agent': 'gemini', 'token': 'Google-Extended', **fail},
        {'identity': 'bingbot', 'vendor': 'copilot', 'agent': 'copilot', **fail},
        {'identity': 'Parleo (control)', 'vendor': 'other', 'agent': None, **fail}]
    upstream.answer('GET', f'{WS}/access', body=payload, token=TOKEN_A)


def test_the_accessibility_read_groups_the_problems_by_display_name(http, db, upstream):
    _supply(upstream)
    _two_googlebots(upstream)
    as_('op')
    body = http.get('/api/console/accessibility', params={'merchant': 'wiggle-and-snug', 'org': 10}).json()
    assert body['problem_identities'] == [
        {'identity': 'Googlebot', 'tokens': 2, 'label': 'Googlebot (2 tokens)'},
        {'identity': 'bingbot', 'tokens': 1, 'label': 'bingbot'},
        {'identity': 'Parleo (control)', 'tokens': 1, 'label': 'Parleo (control)'}]
    assert len(body['requests']) == 8                 # every token is still served


def test_the_overview_signal_and_impact_name_each_identity_once(http, db, upstream):
    cycle = _fl12_money(db)
    _supply(upstream)
    _two_googlebots(upstream)
    as_('op')
    over = http.get('/api/console/overview', params={'cycle': cycle, 'merchant': 'wiggle-and-snug', 'org': 10}).json()
    signal = next(s for s in over['by_surface']['all']['signals'] if s['id'] == 'access')
    assert signal['title'] == '3 agent identities could not read the pages.' and signal['count'] == 3
    assert signal['detail'] == f'{WHO}. From the last access run.'
    as_('alice')
    _inputs(http, 'PUT', json={'scope_value': 4e9})
    rev = http.get('/api/console/revenue', params={'cycle': cycle, 'merchant': 'wiggle-and-snug'}).json()
    assert rev['access']['measured'] == f'3 agent identities could not read the pages in the last access run: {WHO}.'
    assert (rev['access']['n'], rev['access']['tokens']) == (3, 4)
    assert rev['access']['identities'] == ['Googlebot', 'bingbot', 'Parleo (control)']
