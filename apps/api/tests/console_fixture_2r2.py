"""
2R-2: supply's answers for a brand at retail (manufacturer mode), on 2P-1's
week-over-week pair (console_fixture_2p1: cycle 229 Oct 14, cycle 230 Oct 21,
FL14's and FL15's shapes: the attribute questions, Pure retired with AMORE its
successor, the cheapest-place questions and their deals).

SYNTHETIC, to the shapes 2R-2's brief writes for supply 2R-1. When this was
written (Oct 25) parleo-supply-app had no `claude/2r1-manufacturer-mode`
branch and no open 2R-1 PR, so there were no 2R-1 tests whose output could be
recorded. Where supply already serves a shape it is supply's own (main): a
publication row (truesync/schema.py), Manufacturer Center's payload
(truesync/channels/manufacturer_center/compiler.py: products[].attributes),
ACP's items (truesync/channels/acp.py), a feed row (truesync/feed/store.py
sku_view, with its retailers). What 2R-1 adds is written here and in
docs/console-read-models.md "2R-2":

  * /tenant: the merchant's `mode`, 'manufacturer'.
  * a publication's status `held_for_merchant`, and its `journal`: [{event:
    compiled | held_for_merchant | sent_by_merchant, at, by, note, sent_at,
    channel}]; a refused one's `spec_clause`.
  * GET  /merchants/{slug}/rules -> {merchant, rules: [{code, name, detail, on,
    scope, audience, outcome, approval: {state, by, at, note}}]}
  * PUT  /merchants/{slug}/rules/{code} {on?, approval?, note?, by}
  * POST /merchants/{slug}/publications/sent {channel, sent_at, by, note,
    stated_by, event, publication_ids} -> {journaled: [...]}
  * GET  /merchants/{slug}/artifacts/{channel}[?publication_id=] -> the file
  * /reference attributes[].markup_gtin: the GTIN the brand page's markup states.

The merchant is the pair's tenant (wiggle-and-snug, org 10), named P&G with
pampers.com its own site, so the copy reads as the demo's.
"""
import copy

from soa_shared import retailers as retailer_names
from tests import test_console_2m1_attribute as t2m1
from tests.test_console_read_models import TOKEN_A

WS = 'wiggle-and-snug'
BASE = f'/api/truesync/merchants/{WS}'
COMPILED_AT = '2026-10-13T16:00:00+00:00'
BRAND_PAGE_READ = '2026-10-13T14:00:00+00:00'
SENT_AT = '2026-10-17'

TENANT = {'slug': WS, 'merchants': [
    {'slug': WS, 'name': 'P&G', 'domain': 'pampers.com', 'kind': 'brand', 'hosting': 'external',
     'has_record': True, 'mode': 'manufacturer'}]}
RETAILER_LIST = {'merchant': WS, 'own_domain': 'pampers.com', 'own_domains': ['pampers.com'],
                 'domains': ['walmart.com', 'target.com', 'amazon.com']}

#: (variant id, gtin as the record holds it)
GTINS = {'v0': '00037000762591', 'v1': '00037000762607', 'v2': '00037000799818', 'v3': '00037000862215',
         'v4': '00037000874317', 'v5': '00037000762638', 'v6': '00037000862246', 'v7': '00030772244425',
         'v8': '00037000841326', 'v9': '00037000889946'}
#: the brand page markup's GTIN where it is not one as written: AMORE's lost its leading zero
MARKUP_GTINS = {'v7': '30772244425'}
#: the feed's GTIN as given where it is not one: Baby-Dry's 11 digits
FEED_GTINS = {'v8': '37000799818'}

CHANNELS = [
    {'slug': 'schema_org', 'name': 'schema.org', 'is_active': True, 'spec_version': 'schema.org-29'},
    {'slug': 'manufacturer_center', 'name': 'Google Manufacturer Center', 'is_active': True,
     'spec_version': 'manufacturers-v1-2026-10-05', 'connected': False},
    {'slug': 'acp', 'name': 'OpenAI product feed', 'is_active': True, 'spec_version': 'acp-2026-09-29'},
    {'slug': 'ucp_uip', 'name': 'UCP', 'is_active': True, 'spec_version': 'ucp-2026-04-08'},
]


def listings():
    out = []
    for i, (vid, line, size, count, _truth, _texts) in enumerate(t2m1.QUESTIONS):
        out.append({'listing_id': 40 + i, 'product_id': f'pg-{vid}', 'title': line, 'brand': 'Pampers',
                    'product_url': f'https://www.pampers.com/{vid}',
                    'variants': [{'variant_id': vid, 'sku': vid, 'gtin': GTINS[vid], 'title': f'{size}, {count} ct'}]})
    return out


CATALOG = {'merchant': WS, 'brand': 'Pampers', 'listings': listings()}


def _mc_payload(listing):
    v = listing['variants'][0]
    size, count = v['title'].split(', ')
    return {'apiVersion': 'v1', 'products': [{'name': f"US:en:{v['gtin']}", 'attributes': {
        'gtin': [v['gtin']], 'brand': 'Pampers', 'title': f"{listing['title']} {v['title']}",
        'productName': listing['title'], 'count': {'value': count.split(' ')[0], 'unit': 'ct'}, 'size': size,
        'productDetail': [{'sectionName': 'Specs', 'attributeName': 'Weight range', 'attributeValue': '15 to 34 lb'}],
        'productPageUrl': listing['product_url']}}]}


def _acp_payload(listing):
    v = listing['variants'][0]
    return {'items': [{'item_id': f"{listing['listing_id']}:{v['variant_id']}", 'title': listing['title'],
                       'url': listing['product_url'], 'brand': 'Pampers', 'availability': 'unknown',
                       'gtin': v['gtin'], 'seller_name': 'Walmart, Target, Amazon'}]}


def _journal(pid, channel, sent=None):
    rows = [{'event': 'compiled', 'at': COMPILED_AT, 'by': 'parleo', 'channel': channel, 'publication_id': pid},
            {'event': 'held_for_merchant', 'at': COMPILED_AT, 'by': 'parleo', 'channel': channel, 'publication_id': pid,
             'note': "held: the brand's own team sends it"}]
    if sent:
        rows.append({'event': 'sent_by_merchant', 'at': '2026-10-17T18:00:00+00:00', 'sent_at': sent,
                     'by': "P&G's Manufacturer Center team", 'stated_by': 'op@test', 'channel': channel,
                     'publication_id': pid, 'note': 'uploaded through the Manufacturer Center UI'})
    return rows


def publications(*, sent=None, acp='held', ucp=False):
    """Manufacturer Center held for each of the ten records, the ACP feed held (or refused, `acp='blocked'`),
    UCP live only when `ucp`."""
    out = []
    for listing in CATALOG['listings']:
        lid = listing['listing_id']
        out.append({'id': 8000 + lid, 'listing_id': lid, 'channel_slug': 'manufacturer_center',
                    'status': 'held_for_merchant', 'compiled_at': COMPILED_AT, 'published_at': None,
                    'payload': _mc_payload(listing), 'validation': {'ok': True, 'errors': []}, 'expressiveness': [],
                    'spec_version': 'manufacturers-v1-2026-10-05', 'error': None,
                    'journal': _journal(8000 + lid, 'manufacturer_center', sent)})
        row = {'id': 8100 + lid, 'listing_id': lid, 'channel_slug': 'acp', 'compiled_at': COMPILED_AT,
               'published_at': None, 'payload': _acp_payload(listing), 'validation': {'ok': True, 'errors': []},
               'expressiveness': [], 'spec_version': 'acp-2026-09-29', 'error': None, 'journal': []}
        if acp == 'blocked':
            row.update(status='failed', spec_clause='ACP product feed spec, price: required on every item. '
                                                    'A manufacturer sets no price, so the brand feed is refused',
                       error='price is required')
        else:
            row.update(status='compiled_not_published')
        out.append(row)
        if ucp:
            out.append({'id': 8200 + lid, 'listing_id': lid, 'channel_slug': 'ucp_uip', 'status': 'published',
                        'compiled_at': COMPILED_AT, 'published_at': '2026-10-13T16:05:00+00:00',
                        'spec_version': '2026-04-08', 'payload': {'capabilities': ['discount']},
                        'validation': {'ok': True, 'errors': []}, 'expressiveness': [], 'error': None})
    return out


RULES = {'merchant': WS, 'rules': [
    {'code': 'r1', 'name': "Never publish a retail price as P&G's",
     'detail': 'Retailer prices appear only as what a retailer charges, labeled with the retailer.', 'on': True,
     'scope': 'All records', 'audience': [{'name': 'All agents'}], 'outcome': 'No price set by P&G, anywhere',
     'approval': {'state': 'approved', 'by': 'legal@pg.test', 'at': '2026-10-02T12:00:00+00:00'}},
    {'code': 'r2', 'name': 'Retailers in the same order every time',
     'detail': 'Alphabetical, every retailer that carries the product, no favorites.', 'on': True,
     'scope': 'All records', 'audience': [{'name': 'All agents'}], 'outcome': 'Every carrier listed, clubs included',
     'approval': {'state': 'approved', 'by': 'legal@pg.test', 'at': '2026-10-02T12:00:00+00:00'}},
    {'code': 'r3', 'name': 'Manufacturer Center, not Merchant Center',
     'detail': "P&G publishes product content. Offers flow through retailers' own feeds.", 'on': True,
     'scope': 'Google', 'audience': [{'name': 'Google agents'}], 'outcome': 'Content live, prices from retailers',
     'approval': {'state': 'approved', 'by': 'legal@pg.test', 'at': '2026-10-02T12:00:00+00:00'}},
    {'code': 'r4', 'name': 'P&G-funded deals publish retailer-neutral',
     'detail': 'A deal P&G funds attaches to the product with its terms and end date, every honoring retailer '
               'listed the same way. Ships in the next release.', 'on': False,
     'scope': 'P&G-funded deals', 'audience': [{'name': 'Verified shopping agents'}], 'outcome': 'Needs Legal',
     'approval': {'state': 'needs_legal', 'by': None, 'at': None}},
    {'code': 'r5', 'name': 'One size chart per line',
     'detail': 'Each line carries its own chart from pampers.com.', 'on': True, 'scope': '6 lines',
     'audience': [{'name': 'All agents'}], 'outcome': 'Swaddlers Size 4 resolves to 15 to 34 lb everywhere',
     'approval': {'state': 'approved', 'by': 'legal@pg.test', 'at': '2026-10-02T12:00:00+00:00'}},
    {'code': 'r6', 'name': 'Retired products carry a successor',
     'detail': 'Pure Protection points at AMORE, the way pampers.com already redirects it.', 'on': True,
     'scope': '2 records', 'audience': [{'name': 'All agents'}], 'outcome': 'Pure stops being sold as current',
     'approval': {'state': 'approved', 'by': 'legal@pg.test', 'at': '2026-10-02T12:00:00+00:00'}},
]}

_DOMAINS = {name: domain for domain, name in retailer_names.RETAILER_NAMES.items()}


def feed(named, override=None):
    """The brand's feed: each SKU's retailer list is the stores the agents named for it (`named`, the
    cycle's), except `override` {variant id: [domains]}; Baby-Dry's GTIN as given has 11 digits."""
    rows = []
    for vid, line, size, count, _truth, _texts in t2m1.QUESTIONS:
        domains = (override or {}).get(vid)
        if domains is None:
            domains = [_DOMAINS.get(n, n) for n in named.get(vid) or [] if _DOMAINS.get(n, n) != 'pampers.com']
        rows.append({'sku': vid, 'product_name': line, 'brand_name': 'Pampers', 'variant_label': f'{size}, {count} ct',
                     'gtin': FEED_GTINS.get(vid, GTINS[vid]), 'gtin14': GTINS[vid], 'status': 'active',
                     'retailers': [{'domain': d, 'url': f'https://www.{d}/{vid}'} for d in domains]})
    return {'merchant': WS, 'version': {'id': 3}, 'rows': rows}


def reference(base):
    """supply's /reference with the brand page's markup GTINs and its own-page row's read time."""
    out = copy.deepcopy(base)
    for v in out.get('attributes') or []:
        vid = v.get('sku')
        if vid in MARKUP_GTINS:
            v['markup_gtin'] = MARKUP_GTINS[vid]
    out['rows'] = list(out.get('rows') or []) + [
        {'retailer_domain': 'pampers.com', 'read_status': 'ok', 'price': None, 'variant_ref': 'v2',
         'observed_at': BRAND_PAGE_READ, 'role': 'own'}]
    return out


ARTIFACT = b'{"apiVersion": "v1", "products": []}\n'
ARTIFACT_HEADERS = {'Content-Type': 'application/json',
                    'Content-Disposition': 'attachment; filename="pampers-manufacturer-center-2026-10-13.json"'}


def answer(upstream, *, base_reference, named=None, override=None, sent=None, acp='held', ucp=False):
    """Supply for the brand at retail, on top of the pair's own answers."""
    upstream.answer('GET', '/api/truesync/tenant', body=TENANT, token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/retailers', body=RETAILER_LIST, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/channels', body=CHANNELS, token=TOKEN_A)
    upstream.answer('GET', '/api/truesync/publications', body=publications(sent=sent, acp=acp, ucp=ucp), token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/catalog', body=CATALOG, token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/provenance', body={'merchant': WS, 'merchant_source': 'published',
                                                       'listings': {'scrape': 0, 'published': 10}}, token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/verifications', body={'merchant': WS, 'listings': []}, token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/rules', body=RULES, token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/feed', body=feed(named or {}, override), token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/reference', body=reference(base_reference), token=TOKEN_A)
    upstream.answer('GET', f'{BASE}/artifacts/manufacturer_center', body=ARTIFACT, token=TOKEN_A,
                    headers=ARTIFACT_HEADERS)
