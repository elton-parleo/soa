"""Builds apps/pipeline/tests/fixtures/verdict_golden/*.json.

verdict_before: main's comparator (git show main:...), the classifier as it
stood before 2B, over the same stored inputs. verdict_after: this branch's.
Run from apps/pipeline:
    git show main:apps/pipeline/scoring/expectation_comparator.py > /tmp/old_comparator.py
    python3 scripts/build_verdict_golden.py /tmp/old_comparator.py
"""
import importlib.util, json, os, sys
sys.path.insert(0, os.getcwd())
from clients.truesync_catalog import build_snapshot
from scoring import expectation_comparator as new
from scoring import record_variants as rv
from scoring.retailer_reference import ReferenceSet
from soa_shared import expected_answers as ea

spec = importlib.util.spec_from_file_location('old_cmp', sys.argv[1])
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)

FIX = 'tests/fixtures'
OUT = os.path.join(FIX, 'verdict_golden')
os.makedirs(OUT, exist_ok=True)
ATTR = 'claude-reviewed, elton-pending'

def ext(prices=(), member=(), mentions=None, sources=()):
    d = {'prices': list(prices), 'codes': [], 'pack_counts': [], 'gtins': [],
         'member_prices': list(member), 'points': [], 'brand_mentioned': True,
         'sources_cited': list(sources), 'extraction_confident': True, 'extraction_note': None}
    if mentions is not None:
        d['retailer_mentions'] = mentions
    return d

def p(amount, product, currency=None):
    return {'amount': amount, 'currency': currency, 'attributed_product': product}

S3 = {'merchant_slug': 'wiggle-and-snug', 'listing_id': 90, 'variant_id': 'snug-fit-diapers-s3-small',
      'attribution': ['Size 3', 'small pack'],
      'attribution_rivals': ['big pack', 'Size 1', 'Size 2', 'Size 4', 'Size 5', 'Size 6']}
S1 = {'merchant_slug': 'wiggle-and-snug', 'listing_id': 90, 'variant_id': 'snug-fit-diapers-s1-small',
      'attribution': ['Size 1', 'small pack'],
      'attribution_rivals': ['big pack', 'Size 2', 'Size 3', 'Size 4', 'Size 5', 'Size 6']}
ACME = {'merchant_slug': 'acme-baby', 'variant_id': '00012345678905', 'gtin': '00012345678905',
        'own_domain': 'acmebaby.example', 'merchant_kind': 'brand',
        'retailer_list': ['target.com', 'walmart.com']}
ACME120 = {**ACME, 'variant_id': '00012345678912', 'gtin': '00012345678912'}
ORALB_CATALOG = {'merchant': 'fictional-toothbrush-co', 'listings': [{
    'listing_id': 1, 'title': 'Oral-B iO', 'brand': 'Oral-B', 'published_at': '2026-10-01T00:00:00+00:00',
    'variants': [
        {'variant_id': 'io-6', 'title': 'Oral-B iO Series 6', 'size': 'Series 6', 'count': 1,
         'attributes': {}, 'list_price': '99.99', 'currency': 'USD'},
        {'variant_id': 'io-9', 'title': 'Oral-B iO Series 9', 'size': 'Series 9', 'count': 1,
         'attributes': {}, 'list_price': '219.99', 'currency': 'USD'}]}]}
IO6 = {'merchant_slug': 'fictional-toothbrush-co', 'listing_id': 1, 'variant_id': 'io-6',
       'attribution': ['Series 6'], 'attribution_rivals': ['Series 9']}

# WIG_171 (cycle 20260915-113207-wiggle-snug-full): the soa_queries source_ref
# and the stored extraction's classifier-read fields, verbatim. Spans and
# brand_claims are left out; the comparator does not read them.
OVERNIGHT_S3 = {'merchant_slug': 'wiggle-and-snug', 'listing_id': 91, 'product_id': 'catalog_product:28',
                'published_at': '2026-08-28T18:00:56.111443Z', 'variant_id': 'snug-fit-overnight-s3',
                'attribution': ['Size 3'], 'attribution_rivals': ['Size 4', 'Size 5', 'Size 6']}
RUN_10758 = {
    'prices': [{'amount': '25', 'currency': 'USD', 'attributed_product': 'a large box (e.g., 100-120 diapers)'},
               {'amount': '35', 'currency': 'USD', 'attributed_product': 'a large box (e.g., 100-120 diapers)'}],
    'codes': [], 'pack_counts': [{'value': 100, 'attributed_product': 'a large box (e.g., 100-120 diapers)'},
                                 {'value': 120, 'attributed_product': 'a large box (e.g., 100-120 diapers)'}],
    'gtins': [],
    'member_prices': [{'amount': '2', 'tier': 'Costco Executive Members',
                       'attributed_product': 'eligible purchases made at Costco'}],
    'points': [{'value': '2', 'per_dollar': False, 'program': 'annual reward'}],
    'brand_mentioned': True, 'sources_cited': ['Costco.com'], 'recommended_retailers': ['Costco warehouse'],
    'retailer_mentions': [{'name': 'Costco.com', 'role': 'source'},
                          {'name': 'Costco warehouse', 'role': 'recommendation'}],
    'extraction_confident': True, 'extraction_note': None}
RUN_10759 = {
    'prices': [{'amount': '11.00', 'currency': 'USD',
                'attributed_product': 'a pack of 28 Wiggle & Snug Snug-Fit Overnight Diapers Size 3'},
               {'amount': '12.00', 'currency': 'USD',
                'attributed_product': 'a pack of 28 Wiggle & Snug Snug-Fit Overnight Diapers Size 3'},
               {'amount': '9.90', 'currency': 'USD', 'attributed_product': 'an $11.00 pack'}],
    'codes': [], 'pack_counts': [{'value': 28, 'attributed_product': 'Wiggle & Snug Snug-Fit Overnight Diapers Size 3'}],
    'gtins': [],
    'member_prices': [{'amount': '9.90', 'tier': 'Everyday Extra', 'attributed_product': 'an $11.00 pack'}],
    'points': [], 'brand_mentioned': True, 'sources_cited': [], 'recommended_retailers': ['Woolworths'],
    'retailer_mentions': [{'name': 'Woolworths', 'role': 'recommendation'}],
    'extraction_confident': True, 'extraction_note': None}

ROWS = [
 ('r01', '§3 rule 1', 'W&S catalog fixture; the brief\'s "about $18" for 17.99',
  ea.price('17.99'), S1, ext([p('18', 'Size 1 small pack')]), None, None),
 ('r02', '§3 rule 1', 'engine example, checks.ts compareQuote: "$241" for $240.99',
  ea.price('240.99'), {'variant_id': 'x'}, ext([p('241', 'the drill')]), None, None),
 ('r03', '§3 rule 4', 'W&S catalog fixture: whole-dollar member price',
  ea.member_price('16.84', 'Member+'), S3,
  ext(member=[{'amount': '17', 'tier': 'Member+', 'attributed_product': 'Size 3 small pack'}]), None, None),
 ('r04', '§3 rule 2 (pack number)', 'engine packNumbers; W&S "168 ct" is the Size 3 Big Pack',
  ea.price('22.99'), S3, ext([p('39.99', 'Snug-Fit Diapers 168 ct')]), None, None),
 ('r05', '§3 rule 2 (model/size number)', 'engine modelNumberClash: "Size 1" against "Size 3"',
  ea.price('22.99'), S3, ext([p('17.99', 'Size 1 small pack')]), None, None),
 ('r06', '§3 rule 2 (variant marker)', 'engine VARIANT_MARKERS + 2B "overnight"',
  ea.price('22.99'), S3, ext([p('23.99', 'Snug-Fit Overnight Diapers Size 3')]), None, None),
 ('r07', '§3 rule 2 (variant_clash)', 'a pack count the record does not have',
  ea.price('22.99'), S3, ext([p('22.99', 'Snug-Fit Diapers 300 ct')]), None, None),
 ('r08', '§3 rule 2 guard', 'catalog_tiers._discriminators: a volunteered wrong count keeps its price',
  ea.price('22.99'), S3, ext([p('22.99', 'Size 3 small pack (92 ct)')]), None, None),
 ('r09', '§3 rule 2 (model number, engine example)', 'engine: "iO9" meets "iO Series 9" and clashes with "iO Series 6"',
  ea.price('99.99'), IO6, ext([p('219.99', 'Oral-B iO9')]), ORALB_CATALOG, None),
 ('r10', '§3 rule 3', 'engine canBeWrong: "wrong" needs the agent to have named the item',
  ea.price('22.99'), S3, ext([p('19.49', None)]), None, None),
 ('r11', '§3 rule 3 guard', 'an unnamed exact match stays exact',
  ea.price('22.99'), S3, ext([p('22.99', None)]), None, None),
 ('r12', '§2 retailer_price exact', 'fictional acme-baby, Target page price',
  ea.price('24.99', attributed_to='target.com'), ACME, ext([p('21.49', 'Acme Swaddle Size 3')]), None, 'ref'),
 ('r13', '§2 retailer_price stale', 'previous cycle\'s cached Target price',
  ea.price('24.99', attributed_to='target.com'), ACME, ext([p('22.99', 'Acme Swaddle Size 3')]), None, 'ref'),
 ('r14', '§2 retailer_price unverifiable', 'Target blocked both reference sources (120 ct)',
  ea.price('29.99', attributed_to='target.com'), ACME120, ext([p('27.97', 'Acme Swaddle Size 3 120 ct')]), None, 'ref'),
 ('r15', '§2 fabricated_availability', 'brand with two retailers; the answer places it at Amazon',
  ea.price('24.99', attributed_to='walmart.com'), ACME,
  ext([p('17.99', 'Acme Swaddle Size 3')], mentions=[{'name': 'Amazon', 'role': 'recommendation'},
                                                    {'name': 'Walmart', 'role': 'source'}]), None, 'ref'),
 ('r16', '§3 rule 2 guard (size, not count)', 'W&S catalog fixture: "4 oz" is the 4 oz Bum Balm, not a different pack',
  ea.price('12.99'), {'merchant_slug': 'wiggle-and-snug', 'variant_id': 'bum-balm-4oz'},
  ext([p('12.99', 'Wiggle & Snug Bum Balm 4 oz')]), None, None),
 ('r17', 'any-tier attribution guard (member_price)',
  'WIG_171 run 10758: "2% annual reward on eligible purchases made at Costco", tier Costco Executive Members',
  ea.member_price('17.79', 'Member+'), OVERNIGHT_S3, RUN_10758, None, None),
 ('r18', 'any-tier attribution guard (member_price)',
  'WIG_171 run 10759: "$9.90" for "an $11.00 pack", tier Everyday Extra',
  ea.member_price('17.79', 'Member+'), OVERNIGHT_S3, RUN_10759, None, None),
 ('r19', 'attribution guard (price twin of r17)',
  'r17\'s claim on the list-price path: never judged against the asked variant, so it is a '
  '\u00a73 rule 2 clash, not a wrong Size 3 price',
  ea.price('23.99'), OVERNIGHT_S3, ext([p('2', 'eligible purchases made at Costco')]), None, None),
]

def jload(*parts):
    with open(os.path.join(FIX, *parts)) as fh:
        return json.load(fh)

ws = jload('wiggle_and_snug_catalog.json')
ws_snap = build_snapshot(ws['catalog'], merchants=ws['merchants'], incentives=ws['incentives'],
                         price_history=ws['price_history'])
reference = ReferenceSet(jload('retailer_prices', 'acme_baby_as_of_cycle2.json'),
                         prior_payload=jload('retailer_prices', 'acme_baby_as_of_cycle1.json'),
                         prior_cycle_code='ACME-C1')
for name in os.listdir(OUT):
    if name.endswith('.json'):
        os.remove(os.path.join(OUT, name))
for rid, rule, source, expectation, ref, extraction, catalog, refname in ROWS:
    snap = build_snapshot(catalog) if catalog else ws_snap
    variants = rv.from_snapshot(snap)
    before = old.compare(expectation, extraction, source_ref=ref)
    after = new.compare(expectation, extraction, source_ref=ref, record_variants=variants,
                        reference=reference if refname else None)
    row = {'id': rid, 'rule': rule, 'source': source, 'attribution': ATTR,
           'expectation': expectation, 'source_ref': ref, 'extraction': extraction,
           'catalog': catalog, 'reference': 'retailer_prices/acme_baby_as_of_cycle{2,1}.json' if refname else None,
           'verdict_before': before.outcome, 'verdict_after': after.outcome,
           'reason_code_after': after.reason_code, 'flags_after': after.flag_names,
           'reason_after': after.reason}
    with open(os.path.join(OUT, f'{rid}.json'), 'w') as fh:
        json.dump(row, fh, indent=2, sort_keys=False); fh.write('\n')
    print(f"{rid}  {rule:<40} {before.outcome:>11} -> {after.outcome:<12} {after.reason_code or ''} {after.flag_names}")
