"""
2O-5: the brand-page rows the fact index reads, from supply's RECORDED
pampers.com pages (parleo-supply-app tests/fixtures/reads/pampers-2026-10-20,
honest fetches made by supply's reader in reference run 11, 2026-10-20).

    python3 tests/fixtures/build_brand_pages_2o5.py /path/to/parleo-supply-app

For each of the three line pages supply recorded (Swaddlers, Zzz, Cruisers
360) it writes one retailer-prices row with role `own`, in the shape 2O-5
asks supply to serve on brand-page rows:

  url, final_url  the recording's .json sidecar
  page_title      the ProductGroup's name
  json_ld         the page's ProductGroup node, trimmed to name, description,
                  category, url, additionalProperty and hasVariant (each
                  variant's name, description, size, sku, gtin13); images,
                  reviews, ratings and offers left out
  size_chart      the chart supply's 2M-1 reader finds on the page text
                  (truesync/fullloop/weight.range_for_size), per size, never
                  the markup's "Baby Weight" property

Nothing is invented: every value is the recording's, or supply's reader's
reading of it. Nothing is read from production or the network.
"""
import gzip
import json
import os
import re
import sys

PAGES = {
    'swaddlers': 'pampers.com_037000749622__fetch__read72',
    'zzz': 'pampers.com_037000833970__fetch__read135',
    'cruisers_360': 'pampers.com_037000717379__fetch__read124',
}
SIZES = ['Preemie', 'Newborn', '1', '2', '3', '4', '5', '6', '7', '8']
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'brand_claim', 'pampers_brand_pages_2o5.json')


def _group(html):
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            node = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(node, dict) and node.get('@type') == 'ProductGroup':
            return node
    return None


def main(supply_root):
    sys.path.insert(0, supply_root)
    from truesync.fullloop import weight   # supply's 2M-1 reader

    reads = os.path.join(supply_root, 'tests', 'fixtures', 'reads', 'pampers-2026-10-20')
    rows = []
    for key, name in PAGES.items():
        html = gzip.open(os.path.join(reads, name + '.html.gz')).read().decode('utf8', 'replace')
        meta = json.load(open(os.path.join(reads, name + '.json')))
        group = _group(html)
        text = weight.page_view(html)[1].text
        chart = []
        for size in SIZES:
            found = weight.range_for_size(text, size if not size.isdigit() else f"Size {size}")
            if found and found[0]:
                chart.append({'size': size.lower() if not size.isdigit() else size, **found[0]})
        rows.append({
            'retailer_domain': 'pampers.com', 'role': 'own', 'variant_ref': None, 'price': None,
            'url': meta['url'], 'final_url': meta['final_url'], 'page_title': group['name'],
            'json_ld': {
                '@type': 'ProductGroup', 'name': group['name'], 'description': group.get('description'),
                'category': group.get('category'), 'url': group.get('url'),
                'additionalProperty': group.get('additionalProperty') or [],
                'hasVariant': [{k: v[k] for k in ('@type', 'name', 'description', 'size', 'sku', 'gtin13') if k in v}
                               for v in group.get('hasVariant') or []],
            },
            'size_chart': chart,
            'recording': f"parleo-supply-app tests/fixtures/reads/pampers-2026-10-20/{name}.html.gz",
        })
    body = {'_note': __doc__.strip().split('\n\n')[0], 'prices': rows}
    with open(OUT, 'w') as fh:
        json.dump(body, fh, indent=1, sort_keys=True)
        fh.write('\n')
    print(f"wrote {OUT}: {len(rows)} pages")


if __name__ == '__main__':
    main(sys.argv[1])
