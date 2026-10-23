"""
2M-1 (B1, B2, B5): the attribute questions, the coder and the narratives' facts.

  generator   one "What weight range is <line> <size> for, and how many
              diapers come in the <count> ct pack?" per sampled variant that
              names a diaper size, at most ATTRIBUTE_CAP (10), naming no store,
              its source_ref carrying the brand truth: supply's (the
              retailer-prices rows' `attribute.truth`, the truth /reference
              summarises), else the feed's range on the variant, else none
              (and the question is still asked). Added to the study, never
              absorbed by the stage counts.
  coder       expectation_scorer.code_attribute: the answer's range for the
              asked size on the extraction (weight_range, weight_evidence).
  narratives  an attribute miss is a flagged answer; its facts carry the
              stated range and the truth; its prompt is the demo's.
"""
import filecmp
import os

from generation import catalog_tiers as ct
from scoring.expectation_scorer import code_attribute
from soa_shared import attribute_accuracy as aa
from soa_shared import narratives as nv
from soa_shared.catalog_snapshot import build_snapshot, merge_reads

R = lambda low, high: {'min': low, 'max': high}  # noqa: E731


def _pampers(variants=None):
    """A Pampers-shaped external brand: four lines, ten variants."""
    variants = variants or [
        ('Pampers Swaddlers', 'Newborn, 84 ct', 84, 'sw-nb', R(None, 10)),
        ('Pampers Swaddlers', 'Size 1, 96 ct', 96, 'sw-1', None),
        ('Pampers Swaddlers', 'Size 4, 120 ct', 120, 'sw-4', R(15, 34)),
        ('Pampers Zzz', 'Size 4, 104 ct', 104, 'zzz-4', None),
        ('Pampers Cruisers 360', 'Size 3, 168 ct', 168, 'cr-3', R(16, 28)),
        ('Pampers Cruisers 360', 'Size 5, 66 ct', 66, 'cr-5', R(27, None)),
        ('Pampers AMORE', 'Size 1, 132 ct', 132, 'am-1', R(8, 14)),
        ('Pampers Baby-Dry', 'Size 4, 92 ct', 92, 'bd-4', R(22, 37)),
        ('Pampers Pure Protection', 'Size 1, 198 ct', 198, 'pp-1', None),
        ('Pampers Swaddlers', 'Size 5, 108 ct', 108, 'sw-5', R(20, 37)),
    ]
    listings = {}
    for line, label, count, vid, weight in variants:
        listings.setdefault(line, []).append({'variant_id': vid, 'title': label, 'count': count, 'list_price': '29.99',
                                              'currency': 'USD', 'weight_range': weight})
    catalog = {'merchant': 'pampers', 'listings': [
        {'listing_id': i + 1, 'title': line, 'brand': 'Pampers', 'variants': vs}
        for i, (line, vs) in enumerate(listings.items())]}
    snap = build_snapshot(catalog, merchants=[{'slug': 'pampers', 'display_name': 'Pampers', 'domain': 'pampers.com'}],
                          merchant_slug='pampers')
    snap.brand = snap.brand or 'Pampers'
    return snap


def _questions(snap):
    rows, report = ct.build_intent_questions(snap, category='Baby Care', persona='Value-Conscious Parent',
                                             study_pattern='brand_at_retail')
    return [r for r in rows if r['source_ref']['intent'] == ct.ATTRIBUTE], report


def test_one_attribute_question_per_sampled_variant_in_the_demo_s_words():
    rows, report = _questions(_pampers())
    assert report['attribute'] == len(rows) == 10
    texts = [r['query_text'] for r in rows]
    assert 'What weight range is Pampers Swaddlers Size 4 for, and how many diapers come in the 120 ct pack?' in texts
    assert 'What weight range is Pampers Swaddlers Newborn for, and how many diapers come in the 84 ct pack?' in texts
    for r in rows:
        assert (r['tier'], r['stage'], r['soa_focus'], r['expected_answer']['type']) == \
            ('brand_direct', 'Ready to Buy', 'Accuracy', 'brand_mention')
    sw4 = next(r for r in rows if r['source_ref']['variant_id'] == 'sw-4')['source_ref']
    assert (sw4['line'], sw4['size'], sw4['count'], sw4['weight_truth'], sw4['weight_truth_source']) == \
        ('Pampers Swaddlers', 'Size 4', 120, R(15, 34), 'feed')
    # a variant with no truth is still asked, and listed
    assert sorted(report['no_truth']) == ['pp-1', 'sw-1', 'zzz-4']


def test_supply_s_truth_wins_over_the_feed_s_and_the_brand_page_fills_in():
    snap = _pampers()
    merge_reads(snap, {'prices': [
        # the brand page's chart for Zzz Size 4, served on supply's own row
        {'variant_ref': 'feed_sku:9', 'sku': None, 'gtin': None, 'variant_label': 'zzz-4', 'role': 'own',
         'retailer_domain': 'pampers.com', 'attribute': {'truth': R(22, 37), 'truth_source': 'brand_page'}},
        {'variant_label': 'sw-4', 'role': 'retailer', 'retailer_domain': 'walmart.com',
         'attribute': {'truth': R(15, 34), 'truth_source': 'feed'}, 'weight_range': R(15, 34)},
    ]})
    rows, report = _questions(snap)
    refs = {r['source_ref']['variant_id']: r['source_ref'] for r in rows}
    assert (refs['zzz-4']['weight_truth'], refs['zzz-4']['weight_truth_source']) == (R(22, 37), 'brand_page')
    assert refs['sw-4']['weight_truth'] == R(15, 34)
    assert 'zzz-4' not in report['no_truth']


def test_a_product_with_no_diaper_size_is_not_asked():
    snap = _pampers([('Pampers Wipes', 'Sensitive, 56 ct', 56, 'wipes', None),
                     ('Pampers Swaddlers', 'Size 2, 112 ct', 112, 'sw-2', R(10, 22))])
    rows, report = _questions(snap)
    assert [r['source_ref']['variant_id'] for r in rows] == ['sw-2'] and report['no_size'] == ['wipes']


def test_the_attribute_questions_add_to_the_study_and_are_capped():
    assert ct.ABSORBED_INTENTS == ('where_to_buy', 'cheapest_place')
    assert ct.intent_count(_pampers()) == 2 * 10   # the absorbed ones only
    many = [(f'Pampers Line {i}', f'Size {1 + i % 6}, 50 ct', 50, f'v{i}', None) for i in range(25)]
    rows, report = _questions(_pampers(many))
    assert report['attribute'] == ct.ATTRIBUTE_CAP == 10


def test_the_api_copies_are_identical():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ('attribute_accuracy.py', 'catalog_tiers.py', 'catalog_snapshot.py', 'narratives.py'):
        assert filecmp.cmp(os.path.join(here, '..', 'soa_shared', name),
                           os.path.join(here, '..', '..', 'api', 'soa_shared', name), shallow=False), name


# ---------------------------------------------------------------------------
# The coder
# ---------------------------------------------------------------------------

def test_the_coder_writes_the_range_on_the_extraction_of_an_attribute_run_only():
    ref = {'intent': 'attribute', 'size': 'Size 4'}
    x = code_attribute(ref, {'spans': []}, 'Pampers Swaddlers Size 4 is for babies 22–37 lbs; the pack has 120.')
    assert x['weight_range'] == R(22, 37) and x['weight_evidence'] == 'Size 4 is for babies 22-37 lbs'
    assert code_attribute(ref, {}, 'The 120 ct pack has 120 diapers.') == {'weight_range': None, 'weight_evidence': None}
    assert code_attribute({'intent': 'where_to_buy'}, {'spans': []}, 'Size 4 is 22-37 lbs') == {'spans': []}
    # a classify-only rescore with no answer text keeps the stored coding
    stored = {'weight_range': R(15, 34), 'weight_evidence': 'Size 4 15 to 34 lb'}
    assert code_attribute(ref, stored, None) == stored


def test_the_parse_forms():
    for answer, expected in [('Size 4: 15 to 34 lb', R(15, 34)), ('Size 4: 15–34 lbs', R(15, 34)),
                             ('Size 4: 15-34 pounds', R(15, 34)), ('Size 4 is under 34 lb', R(None, 34)),
                             ('Size 4 is 22+ lb', R(22, None)), ('Size 4 fits up to 34 lb', R(None, 34)),
                             ('Size 4 is 22 lbs and up', R(22, None))]:
        assert aa.weight_from_answer(answer, 'Size 4')[0] == expected, answer
    # beyond 80 characters of the size, or another size's: none
    far = 'Size 4 ' + 'is a very popular choice among parents who want a dry night for their little ones ' + '15-34 lb'
    assert aa.weight_from_answer(far, 'Size 4') == (None, None)


# ---------------------------------------------------------------------------
# The narratives
# ---------------------------------------------------------------------------

def _run(text, truth=R(15, 34)):
    return {'id': 1, 'platform': 'chatgpt', 'surface': 'grounded_api', 'answer_status': 'answered',
            'tier': 'brand_direct', 'raw_response': text,
            'query_text': 'What weight range is Pampers Swaddlers Size 4 for, and how many diapers come in the 120 ct pack?',
            'source_ref': {'intent': 'attribute', 'line': 'Pampers Swaddlers', 'size': 'Size 4', 'count': 120,
                           'weight_truth': truth, 'own_domain': 'pampers.com'}}


SCALES = [{'product': 'Pampers Swaddlers', 'size': 'Size 4', 'truth': R(15, 34)},
          {'product': 'Pampers Cruisers 360', 'size': 'Size 4', 'truth': R(22, 37)},
          {'product': 'Pampers Zzz', 'size': 'Size 4', 'truth': R(22, 37)}]


def test_an_attribute_miss_is_a_flagged_answer_with_stated_and_truth():
    merchant = nv.Merchant(name='Pampers', kind='brand', terms=('Pampers',))
    outcome = {'outcome': 'grounded', 'extraction': {'weight_range': R(22, 37), 'weight_evidence': 'Size 4 22-37 lbs'}}
    facts = nv.answer_facts(_run('Size 4 is 22-37 lbs.'), outcome, [], merchant, {}, SCALES)
    assert facts['why'] == ['attribute_mismatch']
    assert (facts['weight_range_stated'], facts['weight_range_brand'], facts['brand_site']) == \
        ('22 to 37 lb', '15 to 34 lb', 'pampers.com')
    assert facts['same_as'] == ['Pampers Cruisers 360', 'Pampers Zzz']
    assert nv.system_prompt(facts) == nv.ATTRIBUTE_PROMPT
    assert 'the Cruisers and Zzz scale, where pampers.com says 15 to 34' in nv.ATTRIBUTE_PROMPT
    # a line in the demo's shape passes the checks on these facts
    line = 'ChatGPT gave 22 to 37 lb, the Pampers Cruisers 360 and Pampers Zzz scale, where pampers.com says 15 to 34 lb.'
    assert nv.check(line, facts) is None


def test_a_right_range_is_not_flagged_and_an_absent_one_is():
    merchant = nv.Merchant(name='Pampers', kind='brand', terms=('Pampers',))
    right = {'outcome': 'grounded', 'extraction': {'weight_range': R(15, 34), 'weight_evidence': 'x'}}
    assert nv.answer_facts(_run('Size 4 is 15-34 lbs.'), right, [], merchant, {}, SCALES) is None
    none = {'outcome': 'grounded', 'extraction': {'weight_range': None, 'weight_evidence': None}}
    facts = nv.answer_facts(_run('It holds 120.'), none, [], merchant, {}, SCALES)
    assert facts['why'] == ['attribute_absent'] and 'weight_range_stated' not in facts
    # the other answers' prompt is unchanged
    assert nv.system_prompt({'kind': nv.ANSWER, 'why': ['wrong_price']}) == nv.SYSTEM_PROMPT
