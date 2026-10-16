"""
Builds supply_ws_brand_2i.json: the Wiggle & Snug brand's catalog, feed and
retailer-prices, as supply serves them, from supply's committed 2F feed and
the recorded Oct 14 store read. See README.md, 2I.

    python tests/fixtures/console/build_ws_brand_2i.py \
        <parleo-supply-app>/truesync/demo/feeds/wiggle-and-snug-brand.csv

Shapes follow parleo-supply-app 868e8cf: truesync/feed/serve.py `catalog`
(/catalog for an external merchant), truesync/feed/store.py `sku_view`
(/feed rows) and truesync/fullloop/prices.py `_row` (/retailer-prices rows,
`role` from targets.py: brand_pdp -> own, retailer_pdp -> retailer).
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SLUG = 'wiggle-and-snug-brand'
OWN, RETAILER = 'wiggleandsnug.com', 'trueshopstore.com'


def main(csv_path):
    with open(csv_path, newline='') as fh:
        skus = list(csv.DictReader(fh))
    with open(os.path.join(HERE, 'supply_retailer_prices_ws.json')) as fh:
        store_reads = json.load(fh)['prices']
    with open(os.path.join(HERE, '..', '..', '..', '..', 'pipeline', 'tests', 'fixtures',
                           'wiggle_and_snug_catalog.json')) as fh:
        store_catalog = json.load(fh)['catalog']
    # The store's variant for a brand SKU: the same title ("Snug-Fit Diapers
    # Size 1 — Small Pack (96 ct)"); its newest read is the trueshopstore.com
    # page's price.
    store_id = {v['title']: v['variant_id'] for l in store_catalog['listings'] for v in l['variants']}
    newest = {}
    for row in store_reads:
        if row['variant_label'] not in newest:
            newest[row['variant_label']] = row

    feed_rows, prices, listings = [], [], {}
    for n, sku in enumerate(skus, start=2):
        key = f"sku:{sku['sku']}"
        urls = {OWN: sku[f'product_url_{OWN}'], RETAILER: sku[f'product_url_{RETAILER}']}
        feed_rows.append({
            'row_number': n, 'gtin': None, 'gtin14': None, 'product_name': sku['product_name'],
            'brand_name': sku['brand_name'], 'variant_label': sku['variant_label'],
            'pack_count': int(sku['pack_count']), 'multipack': None, 'size_value': None, 'size_unit': None,
            'price': None, 'currency': 'USD', 'description': sku['description'], 'image_url': sku['image_url'],
            'status': 'ready', 'messages': [], 'provenance': None,
            'retailers': [{'domain': d, 'url': u} for d, u in urls.items() if u],
            'sku': sku['sku'], 'variant_key': key,
        })
        listing = listings.setdefault(sku['product_name'], {
            'listing_id': 9000 + n, 'product_url': urls[OWN], 'published_at': '2026-10-12T16:00:00+00:00',
            'spec_version': 'sku-feed', 'product_id': f'feed:{SLUG}:{key}', 'title': sku['product_name'],
            'brand': sku['brand_name'], 'variants': []})
        listing['variants'].append({'variant_id': key, 'title': sku['variant_label'], 'size': None,
                                    'count': int(sku['pack_count']), 'attributes': {}, 'list_price': None,
                                    'currency': 'USD', 'gtin': None})
        read = newest[store_id[sku['variant_label']]]
        for domain, role in ((OWN, 'own'), (RETAILER, 'retailer')):
            row = {'variant_ref': f'feed_sku:{700 + n}', 'gtin': None, 'sku': sku['sku'],
                   'variant_label': sku['variant_label'], 'retailer_domain': domain, 'url': urls[domain],
                   'price': None, 'member_price': None, 'list_price': None, 'currency': None,
                   'availability': None, 'observed_at': None, 'reference_source': None, 'method': None,
                   'read_status': None, 'verifiable': False, 'unverifiable_reason': 'not read yet',
                   'reference_read_id': None, 'reference_run_id': None, 'offer_text': None,
                   'incentive_in_markup': None, 'incentive_in_text': None, 'role': role}
            if role == 'retailer':
                row.update({k: read[k] for k in ('price', 'member_price', 'list_price', 'currency', 'observed_at',
                                                 'reference_source', 'method', 'read_status', 'verifiable',
                                                 'unverifiable_reason', 'reference_read_id', 'reference_run_id')})
            prices.append(row)
    out = {
        '_note': ("Wiggle & Snug brand (customer-hosted, wiggleandsnug.com, retailer trueshopstore.com) as supply "
                  "serves it: catalog and feed from supply's 2F feed (truesync/demo/feeds/wiggle-and-snug-brand.csv, "
                  "no GTIN, no price), retailer-prices with one own and one retailer row per variant. Each "
                  "trueshopstore.com row carries the store page's recorded Oct 14 read "
                  "(supply_retailer_prices_ws.json, newest per variant); the own-site pages are not read yet. "
                  "Built by build_ws_brand_2i.py; see README.md, 2I."),
        'catalog': {'merchant': SLUG, 'listings': list(listings.values())},
        'feed': {'merchant': SLUG, 'version': {'id': 12, 'committed_at': '2026-10-12T16:00:00+00:00'},
                 'rows': feed_rows},
        'incentives': {'merchant': SLUG, 'program_name': None, 'tiers': [], 'listings': []},
        'retailer_prices': {'merchant': SLUG, 'kind': 'brand', 'as_of': None, 'prices': prices},
    }
    with open(os.path.join(HERE, 'supply_ws_brand_2i.json'), 'w') as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


if __name__ == '__main__':
    main(sys.argv[1])
