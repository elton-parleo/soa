"""
2R-2a: supply's answers for a brand at retail, RECORDED from parleo-supply-app
PR #33 (2R-1 and 2R-1a), not hand-written: tests/fixtures/console/supply_2r1/
(PROVENANCE.md there says how, from which commit). The merchant is #33's own,
`pampers-2r1` ("Pampers 2R-1", kind brand, mode manufacturer): four records
compiled from its feed (Swaddlers, Pure Protection, AMORE, Zzz), held on
schema_org and Manufacturer Center and blocked on ACP; Manufacturer Center 2 of
4 valid (Pure and AMORE carry no GTIN).

On the soa side, 2P-1's pair (cycle 229 Oct 14, cycle 230 Oct 21), its study
pointed at that merchant (`retag`), and its own supply answers (the /reference
attributes the weight rows read, the deals) served for it too (`alias`): they
are not 2R-1's routes, so nothing of #33's replaces them.

One composition, of #33's own values: `alias` above. The retailer-prices rows
are #33's as recorded: its own-domain rows carry the brand page as 2O-6
serves it (json_ld, size_chart, bullets on the row, beside its observed_at),
which is what soa reads (manu.row_brand_page). 2S-1: before, this harness
put brand-pages.json on those rows under a `brand_page` key no supply route
serves, so the tests read a brand page production never sent.
"""
import base64
import copy
import json
import os
import re

from sqlalchemy import text

from tests import console_fixture_229 as f229
from tests.test_console_read_models import TOKEN_A, _encode

HERE = os.path.join(os.path.dirname(__file__), 'fixtures', 'console', 'supply_2r1')
SLUG = 'pampers-2r1'
PAIR_SLUG = 'wiggle-and-snug'
BASE = f'/api/truesync/merchants/{SLUG}'
SENT_ON = {'2026-10-17': 'sent-20261017.json', '2026-10-23': os.path.join('sent-20261023', 'sent.json')}


def recorded(name):
    """{status, headers, body | body_base64} as #33 answered it."""
    with open(os.path.join(HERE, name if name.endswith('.json') else f'{name}.json')) as fh:
        return json.load(fh)


def body(name):
    return recorded(name)['body']


def content(name) -> bytes:
    return base64.b64decode(recorded(name)['body_base64'])


def mine(rows):
    return [r for r in rows if str(r.get('record_ref') or '').startswith(f'feed:{SLUG}:')]


def retailer_prices():
    """#33's retailer-prices, as recorded."""
    return copy.deepcopy(body('retailer-prices'))


def retag(db):
    """2P-1's study, generated for #33's merchant."""
    with db.begin() as c:
        for job_id, config in c.execute(text("SELECT id, tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                                        {'st': f229.STUDY}).all():
            config = json.loads(config) if isinstance(config, str) else dict(config or {})
            config['merchant'] = {**(config.get('merchant') or {}), 'slug': SLUG}
            c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = :t, syndicated_merchant = NULL "
                           "WHERE id = :i"), {'t': _encode(config), 'i': job_id})


def alias(upstream):
    """The pair's own supply answers (its merchant's paths) served for #33's merchant too."""
    old, new = f'/merchants/{PAIR_SLUG}/', f'/merchants/{SLUG}/'
    routes = upstream.routes
    for (method, path, token), answer in list(routes.items()):
        if old in path:
            routes[(method, path.replace(old, new), token)] = answer
    if hasattr(routes, 'by_date'):   # 2P-1's /deals by read date
        routes.path = routes.path.replace(old, new)


def answer(upstream, *, sent=None):
    """#33's recorded answers. The fake supply answers by path, not query: /artifacts is Manufacturer Center's
    file and /publish the real compile; a test that wants ACP's 409 or the dry run answers that path again.
    `sent`: the day the brand stated it sent the Manufacturer Center file ('2026-10-17' or '2026-10-23'),
    else nothing stated yet."""
    later = 'sent-20261023/' if sent == '2026-10-23' else ''
    tenant = body(f'{later}tenant-sent') if sent else body('tenant-held')
    publications = body(f'{later}publications-sent') if sent else body('publications-held')
    upstream.answer('GET', '/api/truesync/tenant', body=tenant, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=publications, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/channels', body=body('channels'), token=TOKEN_A)
    for name in ('catalog', 'feed', 'retailers', 'rules'):
        upstream.answer('GET', f'{BASE}/{name}', body=body(name), token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/retailer-prices', body=retailer_prices(), token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/verifications', body={'merchant': SLUG, 'listings': []}, token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/provenance', body={'merchant': SLUG, 'listings': {}}, token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/artifacts', body=content('artifact-manufacturer_center'), token=TOKEN_A,
                    headers=recorded('artifact-manufacturer_center')['headers'])
    # its filename ends in the publication's id ("…-00037000833970-11.json")
    pub_id = int(re.search(r'-(\d+)\.json', recorded('artifact-publication')['headers']['content-disposition']).group(1))
    upstream.answer('GET', f'/api/truesync/publications/{pub_id}/artifact', body=content('artifact-publication'),
                    token=TOKEN_A, headers=recorded('artifact-publication')['headers'])
    upstream.answer('PUT', f'{BASE}/rules/r4', body=body('rule-put-r4'), token=TOKEN_A)
    upstream.answer('POST', f'{BASE}/publications/sent', body=body(SENT_ON.get(sent, 'sent-20261017.json')), token=TOKEN_A)
    upstream.answer('POST', f'{BASE}/publish', body=body('publish'), token=TOKEN_A)
    return pub_id
