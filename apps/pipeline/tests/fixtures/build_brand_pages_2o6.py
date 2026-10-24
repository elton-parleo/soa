"""
2O-6: the brand-page rows and the payload's line list as supply serves them
after 2O-6 (parleo-supply-app truesync/fullloop/brand_page.py and
prices.line_list), from supply's RECORDED pampers.com pages (tests/fixtures/
reads/pampers-2026-10-20, honest fetches made by supply's reader in reference
run 11, 2026-10-20).

    python3 tests/fixtures/build_brand_pages_2o6.py /path/to/parleo-supply-app [feed.csv]

For each of the three line pages supply recorded (Swaddlers, Zzz, Cruisers
360) it writes one retailer-prices row with role `own`, each field what
supply's reader returns for the page:

  url, final_url  the recording's .json sidecar
  page_title      the ProductGroup's name
  json_ld         brand_page.trimmed(): the ProductGroup, trimmed
  size_chart      brand_page.size_chart(): 2M-1's chart per size, with evidence
  bullets         brand_page.bullets(): the page's feature statements, verbatim

and, once, `brand_lines`, `brand_lines_complete` (false) and
`brand_line_sources`: prices.line_list() of the feed's product names and the
three pages' lines. The feed is the CSV given (Pampers' brand feed v3, the
file the FL14 merchant's feed was uploaded from), else the names recorded in
the last build. 2O-5's fixture (pampers_brand_pages_2o5.json) is left as it
was: the index before 2O-6.

Nothing is invented and nothing is read from production or the network.
"""
import csv
import gzip
import json
import os
import sys

PAGES = {
    'swaddlers': 'pampers.com_037000749622__fetch__read72',
    'zzz': 'pampers.com_037000833970__fetch__read135',
    'cruisers_360': 'pampers.com_037000717379__fetch__read124',
}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'brand_claim', 'pampers_brand_pages_2o6.json')


def main(supply_root, feed=None):
    sys.path.insert(0, supply_root)
    from truesync.fullloop import brand_page, prices   # supply's 2O-6 reader and line list

    if feed:
        with open(feed) as fh:
            names = list(dict.fromkeys(r['product_name'] for r in csv.DictReader(fh) if r.get('product_name')))
    else:
        names = json.load(open(OUT))['feed_product_names']
    reads = os.path.join(supply_root, 'tests', 'fixtures', 'reads', 'pampers-2026-10-20')
    rows, lines = [], []
    for key, name in PAGES.items():
        html = gzip.open(os.path.join(reads, name + '.html.gz')).read().decode('utf8', 'replace')
        meta = json.load(open(os.path.join(reads, name + '.json')))
        page = brand_page.read(html, ('Pampers', 'pampers'))
        lines.append((page['line'], page['linked_lines']))
        rows.append({
            'retailer_domain': 'pampers.com', 'role': 'own', 'variant_ref': None, 'price': None,
            'url': meta['url'], 'final_url': meta['final_url'], 'page_title': page['json_ld']['name'],
            'json_ld': page['json_ld'], 'size_chart': page['size_chart'], 'bullets': page['bullets'],
            'recording': f"parleo-supply-app tests/fixtures/reads/pampers-2026-10-20/{name}.html.gz",
        })
    body = {'_note': __doc__.strip().split('\n\n')[0], 'feed_product_names': names, 'prices': rows,
            **prices.line_list(names, lines)}
    with open(OUT, 'w') as fh:
        json.dump(body, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write('\n')
    print(f"wrote {OUT}: {len(rows)} pages, {len(body['brand_lines'])} lines")


if __name__ == '__main__':
    main(*sys.argv[1:3])
