"""
2T-4 (4): Accessibility's markup checks on the brand's own pages.

FL15's Accessibility read "Product markup on product pages 0 of 36" while
pampers.com's pages carry ProductGroup JSON-LD: the check counted reads with a
priced Offer (`method: json_ld`) over every page read, the retailers' included.
Brand mode (supply's mode manufacturer) serves the demo's six checks over the
brand's own pages, N the feed's distinct pages on its site; the retailer pages
keep their seven under `retailer_checks`; the hero comes from the data
(app/services/console_accessibility_brand.py).

On supply #33's RECORDED responses (console_fixture_2r2; tests/fixtures/
console/supply_2r1/PROVENANCE.md): its feed links 6 distinct pampers.com
pages, its retailer-prices rows read 2 of them on Oct 20 (Swaddlers and Zzz),
each a ProductGroup with a gtin13 on every variant and no Offer. A state the
recording does not hold is derived from its rows in the test that needs it,
and says so: an 11-digit GTIN (2R-2's own test does the same), a markup weight
the chart contradicts, the access run's per-token robots verdicts.
"""
import copy

from app.services import console_accessibility_brand as acc
from tests import console_fixture_2r2 as f2r2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)

RETAILERS = f2r2.body('retailers')
OWN = RETAILERS['own_domains']


def _build(prices=None, feed=None, reference=None, access=None):
    return acc.build(prices=prices if prices is not None else f2r2.retailer_prices()['prices'],
                     feed_rows=feed if feed is not None else f2r2.body('feed')['rows'],
                     reference=reference if reference is not None else f2r2.body('reference'),
                     access=access, robots=None, own_domains=OWN, retailers=RETAILERS['domains'], brand='Pampers')


def _by_key(out):
    return {c['key']: c for c in out['checks']}


def test_the_six_checks_on_the_recorded_brand_pages():
    out = _build()
    checks = _by_key(out)
    assert list(checks) == ['robots', 'html', 'product_group', 'prices', 'gtin', 'weight']
    assert out['brand_pages'] == {'domain': 'pampers.com', 'pages': 6, 'read': 2, 'plain_html': 2,
                                  'read_at': '2026-10-20T04:00:06.882849+00:00'}
    assert (checks['html']['value'], checks['html']['status']) == ('2 of 6', 'partial')
    # the ProductGroup is there: what fails is the Offer per retailer
    assert checks['product_group']['value'] == '0 of 6'
    assert checks['product_group']['basis'] == ('pages whose markup is a ProductGroup: 2 of 6. Every variant with a '
                                                'gtin13: 2. An Offer for each retailer the feed lists: 0')
    assert (checks['prices']['value'], checks['prices']['basis']) == \
        ('0 of 14', 'no variant in the markup carries a retailer price')
    assert (checks['gtin']['value'], checks['gtin']['status']) == ('14 of 14', 'ok')
    # no access run on #33's harness, no markup weight on its /reference: not checked, said why
    assert checks['robots']['status'] == checks['weight']['status'] == 'not_checked'
    assert checks['weight']['value'] == 'no weights in markup read'
    assert out['hero']['text'] == 'pampers.com served 2 of 6 product pages on Oct 20.'


def test_a_gtin_that_drops_its_leading_zero():
    """Derived: the AMORE page's markup as 2S-1 read FL15's, one gtin13 written with 11 digits."""
    prices = f2r2.retailer_prices()['prices']
    zzz = next(r for r in prices if r.get('role') == 'own' and 'zzz' in (r.get('url') or ''))
    amore = copy.deepcopy(zzz)
    amore.update(url='https://www.pampers.com/en-us/diapers-wipes/amore-diapers', sku='sku_pg_amore_s1_132')
    amore['json_ld'] = {**amore['json_ld'], 'name': 'Pampers® AMORE Diapers',
                        'hasVariant': [{**amore['json_ld']['hasVariant'][0], 'gtin13': '30772244425', 'size': '1'}]}
    checks = _by_key(_build(prices=prices + [amore]))
    assert (checks['gtin']['value'], checks['gtin']['status']) == ('14 of 15', 'partial')
    assert checks['gtin']['basis'] == 'AMORE drop the leading zero'


def test_a_markup_weight_the_chart_contradicts():
    """Derived: /reference's attributes with the markup ranges 2M-1 reads (Zzz Size 4's markup 15 to 34, its
    chart 22 to 37; Swaddlers Size 4 agreeing)."""
    reference = copy.deepcopy(f2r2.body('reference'))
    for a in reference['attributes']:
        if a['variant_ref'] == 'feed_sku:6':
            a.update(markup={'min': 15, 'max': 34}, chart={'min': 22, 'max': 37})
        if a['variant_ref'] == 'feed_sku:5':
            a.update(markup={'min': 15, 'max': 34}, chart={'min': 15, 'max': 34})
    weight = _by_key(_build(reference=reference))['weight']
    assert (weight['value'], weight['status']) == ('1 of 2 pages: Zzz', 'partial')


def _access(verdicts):
    """Derived: an access grid row per (page url, {token: verdict}), as supply's /access serves detail.tokens."""
    return {'accessibility': {'grid': {'rows': [
        {'name': url, 'source': url.split('/')[2], 'cells': [],
         'detail': {'url': url, 'tokens': [{'token': t, 'verdict': v, 'rule_source': 'token', 'matched_rule': None}
                                           for t, v in tokens.items()]}}
        for url, tokens in verdicts]}}}


SIX = ('OAI-SearchBot', 'ChatGPT-User', 'Googlebot', 'PerplexityBot', 'Perplexity-User', 'Claude-User')


def test_the_hero_when_every_page_is_served_and_the_blocks_by_retailer():
    """Derived: every feed page read (the recorded Swaddlers read copied to each), every agent allowed on
    pampers.com, Amazon's robots.txt disallowing four of six, three Walmart reads challenged."""
    prices = f2r2.retailer_prices()['prices']
    own = next(r for r in prices if r.get('role') == 'own' and r.get('json_ld'))
    for url in acc.feed_pages(f2r2.body('feed')['rows'], OWN):
        prices.append({**copy.deepcopy(own), 'url': 'https://www.' + url, 'observed_at': '2026-10-24T03:00:00+00:00'})
    prices += [{'retailer_domain': 'walmart.com', 'role': 'retailer', 'read_status': 'challenged', 'sku': f's{i}'}
               for i in range(3)]
    access = _access([('https://www.pampers.com/en-us/products/pampers-zzz', {t: 'allow' for t in SIX}),
                      ('https://www.amazon.com/dp/B0', {t: 'disallow' if i < 4 else 'allow' for i, t in enumerate(SIX)})])
    out = _build(prices=prices, access=access)
    checks = _by_key(out)
    assert (checks['robots']['value'], checks['robots']['status']) == ('6 of 6', 'ok')
    assert checks['html']['value'] == '6 of 6'
    assert out['hero']['lead'] == 'pampers.com served every product page on Oct 24. What agents find there is the problem.'
    assert [b['text'] for b in out['hero']['blocks']] == ["Amazon's robots.txt disallows 4 of 6 agents",
                                                          'Walmart challenged 3 page reads']
    assert out['hero']['text'].endswith("Amazon's robots.txt disallows 4 of 6 agents. Walmart challenged 3 page reads.")
    assert ';' not in out['hero']['text'] and '—' not in out['hero']['text']


def test_the_endpoint_in_brand_mode(http, db, upstream):
    from tests.test_console_2t1_overview_truesync import _read, _shape
    _shape(db, http, upstream)
    upstream.answer('GET', f'{f2r2.BASE}/reference', body=f2r2.body('reference'), token=f2r2.TOKEN_A)
    body = _read(http, 'accessibility')
    assert body['mode'] == 'manufacturer'
    assert [c['key'] for c in body['checks']] == ['robots', 'html', 'product_group', 'prices', 'gtin', 'weight']
    assert [c['key'] for c in body['retailer_checks']][:3] == ['robots', 'markup', 'gtin']
    assert body['brand_pages']['pages'] == 6 and body['hero']['lead'].startswith('pampers.com served 2 of 6')
