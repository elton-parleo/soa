"""
2J-2: the FL12-shaped fixture (console_fixture_2i8: six agents, one run per
question) as a brand, as FL12 (Pampers, Oct 19) is one. 2I-8's fixture kept
229's store-shaped catalog tier: every price question asked at the store,
which is its own `you` column. A brand's `you` column is its own site, which
sets no price and no agent quotes, so its catalog tier asks at retailers.

  The study's merchant is a brand, `pampers` (own pampers.com, retailers
    walmart.com and amazon.com). Its 19 catalog questions are replaced by 20:
    10 variants x 2 retailers, each naming the retailer, as the generator's
    brand mode writes them (catalog_tiers._build_catalog_from_reads).
  4 of the 10 variants have no GTIN (Ultra, Pure, AMORE, Cruisers S5): their
    variant id is supply's GTIN-less variant key, `sku:<sku>`, and their
    retailer-prices rows' variant_ref is `feed_sku:<n>`, as supply serves a
    feed variant with no GTIN (supply_ws_brand_2i.json). The other 6 are
    keyed by GTIN-14.
  The study: 51 category-control, 11 brand-direct, 20 catalog, 6 value: 88
    questions, 87 asked (the 51st category-control question never ran).
  The cycle caches supply's retailer-prices read (`reference_prices`): per
    variant the brand's own page (role own, no price, not verifiable) and
    each retailer's page with the price read. Amazon reads $3.00 above
    Walmart: Swaddlers NB 84 is $24.97 at Walmart, $27.97 at Amazon.
  Each agent quotes the same way on every variant (QUOTES): ChatGPT the
    Walmart price at both retailers, Gemini and Perplexity the Amazon price
    at both, AI Mode each retailer's own, Claude no price, Copilot another
    brand's product (absent, other_brand). A quote is exact when it is the
    asked retailer's price, else wrong.

Prices and product names are the fixture's, not production's.
"""
import copy
from typing import Dict, List

from tests import console_fixture_2i8 as f2i8

CYCLE = f2i8.CYCLE
STUDY = f2i8.STUDY
MERCHANT = 'pampers'
OWN = 'pampers.com'
RETAILERS = ('walmart.com', 'amazon.com')
AMAZON_MARKUP = 3.00
#: (label, sku, gtin or None, Walmart price)
VARIANTS = (
    ('Swaddlers NB 84', 'PAM-SW-NB-84', '00037000863434', '24.97'),
    ('Swaddlers S1 96', 'PAM-SW-1-96', '00037000863441', '27.97'),
    ('Swaddlers S2 84', 'PAM-SW-2-84', '00037000863458', '27.97'),
    ('Baby Dry S3 136', 'PAM-BD-3-136', '00037000863465', '29.97'),
    ('Cruisers 360 S4 104', 'PAM-CR360-4-104', '00037000863472', '39.97'),
    ('Easy Ups S5 66', 'PAM-EU-5-66', '00037000863489', '34.97'),
    ('Ultra', 'PAM-ULTRA-120', None, '22.97'),
    ('Pure', 'PAM-PURE-2-74', None, '31.97'),
    ('AMORE', 'PAM-AMORE-3-60', None, '26.97'),
    ('Cruisers S5', 'PAM-CR-5-92', None, '37.97'),
)
GTINLESS = ('Ultra', 'Pure', 'AMORE', 'Cruisers S5')
#: agent -> asked retailer -> the retailer whose price it quotes (None: no price)
QUOTES = {
    'chatgpt': {'walmart.com': 'walmart.com', 'amazon.com': 'walmart.com'},
    'gemini_grounded': {'walmart.com': 'amazon.com', 'amazon.com': 'amazon.com'},
    'perplexity': {'walmart.com': 'amazon.com', 'amazon.com': 'amazon.com'},
    'aimode': {'walmart.com': 'walmart.com', 'amazon.com': 'amazon.com'},
    'claude': {'walmart.com': None, 'amazon.com': None},
    'copilot': {'walmart.com': None, 'amazon.com': None},
}
OTHER_BRAND = ('copilot',)
FEED_REF_BASE = 900


def variant_id(sku: str, gtin) -> str:
    """supply's variant key: the GTIN-14, else sku:<sku> (feed/serve.py)."""
    return gtin if gtin else f'sku:{sku}'


def price_at(walmart: str, retailer: str) -> str:
    return walmart if retailer == 'walmart.com' else f"{float(walmart) + AMAZON_MARKUP:.2f}"


def reference_prices() -> dict:
    """supply's retailer-prices read as the cycle caches it."""
    prices = []
    for n, (label, sku, gtin, walmart) in enumerate(VARIANTS):
        base = {'variant_ref': f'feed_sku:{FEED_REF_BASE + n}', 'gtin': gtin, 'sku': sku, 'variant_label': label}
        prices.append({**base, 'retailer_domain': OWN, 'url': f'https://www.{OWN}/{sku.lower()}', 'price': None,
                       'currency': None, 'observed_at': None, 'reference_source': None, 'method': None,
                       'read_status': None, 'verifiable': False, 'unverifiable_reason': 'not read yet', 'role': 'own'})
        for retailer in RETAILERS:
            prices.append({**base, 'retailer_domain': retailer, 'url': f'https://www.{retailer}/ip/{sku.lower()}',
                           'price': price_at(walmart, retailer), 'currency': 'USD',
                           'observed_at': '2026-10-19T14:00:00+00:00', 'reference_source': 'honest_fetch',
                           'method': 'json_ld', 'read_status': 'ok', 'verifiable': True, 'role': 'retailer'})
    return {'merchant': MERCHANT, 'kind': 'brand', 'as_of': '2026-10-19T14:00:00+00:00', 'prices': prices}


def feed() -> dict:
    """supply's GET /merchants/pampers/feed: one row per variant, as the 1B
    loader serves it (a GTIN-less row has gtin null and variant_key sku:<sku>)."""
    rows = []
    for n, (label, sku, gtin, _walmart) in enumerate(VARIANTS):
        rows.append({'row_number': n + 2, 'gtin': gtin, 'gtin14': gtin, 'sku': sku, 'variant_key': variant_id(sku, gtin),
                     'product_name': label, 'brand_name': 'Pampers', 'variant_label': label, 'pack_count': None,
                     'price': None, 'currency': 'USD', 'status': 'ready', 'messages': [],
                     'retailers': [{'domain': d, 'url': f'https://www.{d}/ip/{sku.lower()}'} for d in RETAILERS]})
    return {'merchant': MERCHANT, 'version': {'id': 3, 'version_number': 1, 'committed_at': '2026-10-18T16:00:00+00:00'},
            'rows': rows}


def catalog() -> dict:
    """supply's GET /merchants/pampers/catalog for the feed: one listing per
    variant, each variant keyed as supply keys it (variant_id)."""
    return {'merchant': MERCHANT, 'listings': [
        {'listing_id': 9100 + n, 'product_url': f'https://www.{OWN}/{sku.lower()}',
         'published_at': '2026-10-18T16:00:00+00:00', 'spec_version': 'sku-feed',
         'product_id': f'feed:{MERCHANT}:{variant_id(sku, gtin)}', 'title': label, 'brand': 'Pampers',
         'variants': [{'variant_id': variant_id(sku, gtin), 'title': label, 'size': None, 'count': None,
                       'attributes': {}, 'list_price': None, 'currency': 'USD', 'gtin': gtin}]}
        for n, (label, sku, gtin, _walmart) in enumerate(VARIANTS)]}


#: supply's GET /tenant entry and GET /merchants/pampers/retailers
TENANT_MERCHANT = {'slug': MERCHANT, 'name': 'Pampers', 'domain': OWN, 'own_domains': [OWN], 'kind': 'brand',
                   'hosting': 'external', 'has_record': True}
RETAILERS_RECORD = {'merchant': MERCHANT, 'own_domain': OWN, 'own_domains': [OWN], 'domains': list(RETAILERS)}


def build() -> Dict[str, List[dict]]:
    d = f2i8.build()
    job = d['generation_jobs'][0]
    job['syndicated_merchant'] = MERCHANT
    job['tier_config'] = {**job['tier_config'],
                          'merchant': {'slug': MERCHANT, 'brand': 'Pampers', 'study_brand': 'Pampers'}}
    for c in d['cycles']:
        if c['id'] == 229:
            c['reference_prices'] = reference_prices()

    catalog = [q for q in d['queries'] if q['tier'] == 'catalog_accuracy']
    template_q = catalog[0]
    dropped = {q['id'] for q in catalog}
    run_template = next(r for r in d['runs'] if r['cycle_id'] == 229 and r['query_id'] == template_q['id'])
    outcome_template = next(o for o in d['outcomes'] if o['tier'] == 'catalog_accuracy' and o['cycle_id'] == 229)
    dropped_runs = {r['id'] for r in d['runs'] if r['query_id'] in dropped}
    d['queries'] = [q for q in d['queries'] if q['id'] not in dropped]
    d['runs'] = [r for r in d['runs'] if r['id'] not in dropped_runs]
    d['outcomes'] = [o for o in d['outcomes'] if o['run_id'] not in dropped_runs]
    d['coded_mentions'] = [m for m in d['coded_mentions'] if m['run_id'] not in dropped_runs]

    qid, rid = 3000, 90000
    for label, sku, gtin, walmart in VARIANTS:
        for retailer in RETAILERS:
            qid += 1
            expected = {'type': 'price', 'amount': price_at(walmart, retailer), 'currency': 'USD',
                        'attributed_to': retailer}
            ref = {'merchant_slug': MERCHANT, 'variant_id': variant_id(sku, gtin), 'own_domain': OWN,
                   'merchant_kind': 'brand', 'retailer_list': list(RETAILERS)}
            if gtin:
                ref['gtin'] = gtin
            d['queries'].append({**copy.deepcopy(template_q), 'id': qid, 'query_code': f'PAM_{qid}',
                                 'query_text': f"What does the Pampers {label} cost at {retailer}?",
                                 'expected_answer': expected, 'source_ref': ref})
            for platform, surface, collector in f2i8.AGENTS:
                rid += 1
                d['runs'].append({**run_template, 'id': rid, 'query_id': qid, 'platform': platform, 'surface': surface,
                                  'collector': collector, 'status': 'success', 'raw_response': 'answer',
                                  'answer_status': 'answered'})
                quoted_at = QUOTES[platform][retailer]
                stated = price_at(walmart, quoted_at) if quoted_at else None
                outcome = ('absent' if stated is None else
                           'exact' if stated == expected['amount'] else 'wrong')
                claims = ([{'target': 'asked', 'stated': stated, 'outcome': outcome, 'variant_id': ref['variant_id']}]
                          if stated else [])
                d['outcomes'].append({**outcome_template, 'run_id': rid, 'query_id': qid, 'platform': platform,
                                      'surface': surface, 'expected_answer': expected, 'outcome': outcome,
                                      'claim_results': claims,
                                      'reason_code': 'other_brand' if platform in OTHER_BRAND else None})
    for c in d['cycles']:
        if c['id'] == 229:
            n = sum(1 for r in d['runs'] if r['cycle_id'] == 229)
            c.update({'total_runs_planned': n, 'completed_runs': n})
    return d


def load(engine, encode) -> None:
    """Into the console test database, as console_fixture_229.load does."""
    from tests import console_fixture_229 as f229
    f229.load(engine, encode, data=build())
