"""
2O-5: "fabricated" means contradicted by what the brand publishes; the index
covers the line, not the pilot.

FL14 under 2O-4 (fl14-v14-run2.txt): fabricated 170 of 258, "by the fact
missing: price 60, retailer 48, name 48, size 26, count 21, attribute 58",
against a 58-fact index of the 10-SKU pilot. A claim was fabricated whenever
it named anything the pilot did not.

  * a contradiction per slot: a (line, size) weight range, a line's weight
    with no size against its complete chart, its sizes, its counts, its
    status (the feed's, a redirect's), an attribute its own page states the
    opposite of, a line off the brand's served line list; each with the
    drawer line;
  * absent is unverified, per fact type; a price is never fabricated here,
    a store off the list never either;
  * the index from supply's recorded pampers.com pages (fixtures/brand_claim/
    pampers_brand_pages_2o5.json, built by fixtures/build_brand_pages_2o5.py):
    the Swaddlers page's JSON-LD lists its sizes and counts, the Zzz page's
    chart (22-37 for Size 4) is the truth and its markup's "Baby Weight"
    list (15-34) is not, as 2M-1 asserts in supply;
  * two runs identical;
  * FL14's 170 fabricated, shaped from the printout's breakdown (fixtures/
    brand_claim/fl14_fabricated_2o5.json, built by fixtures/build_fl14_
    fabricated_2o5.py, which recorded each answer's 2O-4 verdict by running
    2O-4's code): what each bucket becomes, on the pilot alone and with the
    three line pages;
  * the printout's lines.

Nothing here is read from production, and nothing calls a model.
"""
import copy
import json
import os
from collections import Counter

import pytest

from scoring import brand_claim_selector as sel
from scoring import brand_fact_index as bfi
from scripts import rescore_cycle
from soa_shared import expected_answers as ea

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, 'fixtures', 'brand_claim')
FL13 = json.load(open(os.path.join(FIXTURES, 'fl13_record_pages.json')))
PAGES = json.load(open(os.path.join(FIXTURES, 'pampers_brand_pages_2o5.json')))
FL14 = json.load(open(os.path.join(FIXTURES, 'fl14_fabricated_2o5.json')))
EXPECTATION = ea.brand_mention('Pampers', 'pampers.com')
OWN = ['pampers.com']
STUDY = {'terms': ['Pampers'], 'product_names': [], 'rivals': ['Huggies', 'Luvs']}
R = lambda low, high: {'min': low, 'max': high}  # noqa: E731


def pilot():
    """The FL14-shaped pilot (the builder's): FL13's record and rows, its own
    pages as supply serves them today (no JSON-LD, no chart)."""
    rows = [{k: v for k, v in r.items() if not (r.get('role') == 'own' and k in ('json_ld', 'size_chart'))}
            for r in FL13['reference']['prices']]
    return copy.deepcopy(FL13['facts']), {**FL13['reference'], 'prices': rows}


def index(pages=True, **extra):
    facts, reference = pilot()
    rows = reference['prices'] + (copy.deepcopy(PAGES['prices']) if pages else [])
    return bfi.build(facts, {**reference, 'prices': rows, **extra})


def vocab():
    return sel.vocabulary('Pampers', facts=pilot()[0], study=STUDY)


def judge(answer, question='Tell me about Pampers diapers.', idx=None):
    record = sel.select(answer, question=question, vocab=vocab(), own_domains=OWN)
    return sel.decide(record, EXPECTATION, index=idx or index(), own_domains=OWN)


def read(decided):
    """The outcome as the console reads it."""
    return ea.UNVERIFIED if decided['reason_code'] == ea.UNVERIFIED else decided['outcome']


# ── contradicted, per slot ────────────────────────────────────────────────

@pytest.mark.parametrize('question,answer,reason', [
    # weight for (line, size): the chart and hasVariant say under 10 lb for Swaddlers Newborn
    ('What weight range is Pampers Swaddlers Newborn for?', 'Pampers Swaddlers Newborn fits babies 2 to 9 lbs.',
     "fabricated: '2 to 9 lbs' for Swaddlers Newborn — pampers.com's chart says under 10 lb"),
    # the size from the question when the sentence names none
    ('What weight range is Pampers Swaddlers Size 4 for?', 'Pampers Swaddlers fit babies 22-37 lbs.',
     "fabricated: '22-37 lbs' for Swaddlers Size 4 — pampers.com's chart says 15 to 34 lb"),
    # Zzz: the chart's 22-37, never the markup's Baby Weight list (15-34), as 2M-1 found
    ('What weight range is Pampers Zzz Size 4 for?', 'Pampers Zzz Size 4 is for babies 15-34 lbs.',
     "fabricated: '15-34 lbs' for Zzz Size 4 — pampers.com's chart says 22 to 37 lb"),
    # a line's sizes: hasVariant and the Size Range property list Preemie to 8
    ('Is Pampers good?', 'Pampers Swaddlers come in Size 9.',
     "fabricated: 'Size 9' for Swaddlers — pampers.com's size list says Preemie, Newborn, Size 1, Size 2, "
     "Size 3, Size 4, Size 5, Size 6, Size 7, Size 8"),
    # a line's counts: the Zzz page's Pack Count property
    ('Is Pampers good?', 'Pampers Zzz come in a 99 count pack.',
     "fabricated: '99 count' for Zzz — pampers.com's pack counts says 72, 88, 104, 116"),
    # a line's status: the feed says current
    ('Is Pampers good?', 'Pampers Swaddlers were discontinued last year.',
     "fabricated: 'discontinued' for Swaddlers — pampers.com's line status says current"),
])
def test_a_contradicted_fact_is_fabricated_and_the_drawer_line_names_both_values(question, answer, reason):
    decided = judge(answer, question)
    assert (decided['outcome'], decided['reason_code'], decided['reason']) == ('fabricated', 'fact_contradicted',
                                                                                reason)
    span = decided['brand_claim']['spans'][decided['brand_claim']['decided_by']]
    fact = span['facts_missing'][0]
    assert fact['slot'] in ('ranges', 'sizes', 'counts', 'status') and fact['claimed'] and fact['published']


def test_a_weight_for_a_line_with_no_size_is_checked_against_its_complete_chart():
    decided = judge('Pampers Swaddlers fit babies 2-9 lbs.')
    assert decided['outcome'] == 'fabricated'
    assert decided['reason'].startswith("fabricated: '2-9 lbs' for Swaddlers — pampers.com's chart says "
                                        "Preemie under 6 lb; Newborn under 10 lb; Size 1 8 to 14 lb;")
    assert read(judge('Pampers Swaddlers fit babies 8-14 lbs.')) == 'grounded'
    # the pilot alone has no chart for Swaddlers (the feed's three sizes are a sample): unverified
    assert read(judge('Pampers Swaddlers fit babies 2-9 lbs.', idx=index(pages=False))) == ea.UNVERIFIED


def test_a_feed_range_alone_is_the_brands_record():
    decided = judge('Pampers Baby Dry Size 3 fits babies 10-12 lbs.', idx=index(pages=False))
    assert decided['reason'] == "fabricated: '10-12 lbs' for Baby Dry Size 3 — Pampers' record says 16 to 28 lb"


def test_a_retired_line_from_the_feed_and_from_a_redirect():
    facts, reference = pilot()
    facts['variants'] = facts['variants'] + [
        {'title': 'Size 1', 'line': 'Pampers Pure Protection', 'size': '1', 'status': 'retired',
         'successor': {'product_name': 'Pampers AMORE', 'title': 'Size 1, 132 ct'}}]
    idx = bfi.build(facts, reference)
    decided = judge('Pampers Pure Protection is still available at most stores.', idx=idx)
    assert decided['reason'] == ("fabricated: 'still available' for Pure Protection — pampers.com's line status "
                                 "says retired, succeeded by Pampers AMORE")
    assert read(judge('Pampers Pure Protection was discontinued.', idx=idx)) == 'grounded'
    assert [f['value'] for f in bfi.facts_in('Swaddlers have not been discontinued.', 'Pampers')
            if f['type'] == 'status'] == ['current']
    assert read(judge('Pampers Pure Protection has not been discontinued.', idx=idx)) == 'fabricated'
    # the Easy Ups page redirected to the Cruisers 360 page: Easy Ups is retired, succeeded by it
    cruisers = copy.deepcopy(PAGES['prices'][2])
    cruisers.update(url='https://www.pampers.com/en-us/products/pampers-easy-ups',
                    variant_label='Easy Ups S5 66')
    idx = bfi.build(facts, {**reference, 'prices': reference['prices'] + [cruisers]})
    assert (idx.lines['easy ups'].status, idx.lines['easy ups'].successor) == ('retired', 'Cruisers 360')
    assert read(judge('Pampers Easy Ups are still sold everywhere.', idx=idx)) == 'fabricated'


def test_an_attribute_the_lines_own_page_states_the_opposite_of():
    page = copy.deepcopy(PAGES['prices'][0])
    page['bullets'] = ['Hypoallergenic and fragrance-free', 'Free of parabens and latex']
    facts, reference = pilot()
    idx = bfi.build(facts, {**reference, 'prices': reference['prices'] + [page]})
    assert {'fragrance free', 'paraben free', 'latex free'} <= idx.lines['swaddler'].attributes
    decided = judge('Pampers Swaddlers are lightly scented.', idx=idx)
    assert decided['reason'] == "fabricated: 'scented' for Swaddlers — pampers.com's page says fragrance free"
    # "free of fragrance" states fragrance free: grounded on the same page
    assert read(judge('Pampers Swaddlers are free of fragrance.', idx=idx)) == 'grounded'
    # another line's page says nothing about Zzz
    assert read(judge('Pampers Zzz are lightly scented.', idx=idx)) == ea.UNVERIFIED


def test_a_line_off_the_brands_served_line_list():
    lines = ['Pampers Swaddlers', 'Pampers Zzz', 'Pampers Cruisers 360', 'Pampers Baby Dry', 'Pampers Pure Protection',
             'Pampers Ninjamas', 'Pampers Easy Ups', 'Pampers Splashers', 'Pampers AMORE']
    idx = index(brand_lines=lines)
    answer = 'Pampers Swaddlers and Pampers Little Movers are both popular.'
    decided = judge(answer, idx=idx)
    assert decided['outcome'] == 'fabricated'
    assert decided['reason'].startswith("fabricated: 'Little Movers' — not a Pampers line; pampers.com's line list "
                                        "is Pampers Swaddlers, Pampers Zzz")
    assert read(judge('Pampers Swaddlers and Pampers Ninjamas are both popular.', idx=idx)) == 'grounded'
    # without the list, a line the pages did not read is unverified, never fabricated
    assert read(judge(answer)) == ea.UNVERIFIED
    # a rival's line written as the brand's is still misattributed
    assert judge('Huggies Little Movers are popular. Pampers Little Movers fit 22-37 lbs.', idx=idx)['outcome'] == \
        'misattributed'


# ── absent, not contradicted ──────────────────────────────────────────────

@pytest.mark.parametrize('answer', [
    'Pampers Swaddlers cost $38.49 a box.',                     # price: the price tier's
    'You can also buy Pampers Swaddlers at Walgreens.',         # a store off the list: coverage's
    'Pampers Swaddlers and Pampers Ninjamas are both popular with parents.',   # a line not read
    'Pampers Ninjamas also come in Size 6.',                   # a size, for a line the index does not hold
    'Pampers Swaddlers are dermatologist tested.',              # an attribute no page read states
])
def test_absent_is_unverified(answer):
    decided = judge(answer)
    assert (decided['outcome'], decided['reason_code']) == ('unscoreable', ea.UNVERIFIED)
    assert decided['reason'].endswith(f"— {ea.UNVERIFIED_NOTE}")
    span = decided['brand_claim']['spans'][decided['brand_claim']['decided_by']]
    assert span['verdict'] == 'unverified' and span['facts_missing'] == [] and span['facts_unverified']


@pytest.mark.parametrize('answer', [
    'Pampers Swaddlers cost $24.97 at Walmart.',   # a price on the index: still not a fact this tier judges
    'Pampers Swaddlers cost $99.99.',              # a price no page states
    'Pampers Swaddlers Newborn cost $0.33 per diaper.',
])
def test_a_price_is_never_fabricated_here(answer):
    decided = judge(answer)
    assert decided['outcome'] != 'fabricated'
    for span in decided['brand_claim']['spans']:
        assert not [f for f in span['facts_missing'] if f['type'] in ('price', 'unit_price')]
        assert not [f for f in span['facts_found'] if f['type'] in ('price', 'unit_price')]


def test_the_answers_verdict_order():
    # grounded beats unverified, fabricated beats grounded, misattributed beats fabricated
    assert read(judge('Pampers Swaddlers cost $38.49. Pampers Swaddlers come in Size 7.')) == 'grounded'
    assert read(judge('Pampers Swaddlers come in Size 7. Pampers Swaddlers come in Size 9.')) == 'fabricated'
    assert read(judge('Pampers is the brand hospitals trust.', 'Is Pampers the brand hospitals trust?')) == 'echoed'
    # unverified beats echoed
    assert read(judge('Pampers is the brand hospitals trust. Pampers Swaddlers cost $38.49.',
                      'Is Pampers the brand hospitals trust?')) == ea.UNVERIFIED


# ── the index from the recorded pages ─────────────────────────────────────

def test_the_index_from_the_recorded_pampers_pages():
    idx = index()
    swaddlers, zzz, cruisers = idx.lines['swaddler'], idx.lines['zzz'], idx.lines['cruiser 360']
    # the Swaddlers page's JSON-LD: hasVariant and the Size Range property, Preemie to 8
    assert sorted(swaddlers.sizes) == ['0', '1', '2', '3', '4', '5', '6', '7', '8', 'p'] and swaddlers.sizes_complete
    assert len(swaddlers.gtins) == 10 and '037000772552' in swaddlers.gtins
    assert {'19', '120', '148', '198'} <= swaddlers.counts and len(swaddlers.counts) == 25
    # every size's range: the chart and hasVariant agree
    assert swaddlers.ranges['0'] == [R(None, 10.0)] and swaddlers.ranges['5'] == [R(20.0, 37.0)]
    assert swaddlers.ranges['8'] == [R(30.0, None)]
    # Zzz: the chart is the truth; the markup's "Baby Weight" list (15-34 among it) is on no size
    assert zzz.ranges['4'] == [R(22.0, 37.0)] and sorted(zzz.sizes) == ['3', '4', '5', '6']
    assert R(15.0, 34.0) in idx.weights      # on the index as text, so "15-34 lbs" alone is found
    assert cruisers.ranges['3'] == [R(16.0, 28.0)] and cruisers.name == 'Cruisers 360'
    assert (swaddlers.status, zzz.status) == ('current', 'current')


def test_the_index_size_by_source_and_its_slots():
    alone, read_ = index(pages=False), index()
    assert (alone.size(), alone.by_source) == (90, {'record': 3, 'catalog': 34, 'brand_pages': 53})
    assert (read_.size(), read_.by_source) == (195, {'record': 3, 'catalog': 34, 'brand_pages': 158})
    slots = read_.slots()
    # the pilot's eight lines and Zzz; a status from the three pages (the FL13 feed rows carry none)
    assert (slots['lines'], slots['status'], slots['brand_lines']) == (9, 3, None)
    assert slots['sizes']['Swaddlers'] == 10 and slots['sizes']['Zzz'] == 4 and slots['sizes']['Cruisers 360'] == 6
    assert slots['counts'] == {'Cruisers 360': 18, 'Swaddlers': 25, 'Zzz': 4}
    assert slots['sizes_complete'] == ['Cruisers 360', 'Swaddlers', 'Zzz']
    assert slots['ranges_per_size']['Size 4'] == 3 and slots['ranges_per_size']['Preemie'] == 1


# ── two runs ──────────────────────────────────────────────────────────────

def _fl14(idx):
    v = vocab()
    out = []
    for a in FL14['answers']:
        record = sel.select(a['answer'], question=a['question'], vocab=v, own_domains=OWN)
        out.append(sel.decide(record, EXPECTATION, index=idx, own_domains=OWN))
    return out


def test_two_runs_are_identical():
    assert index().digest() == index().digest() and index().as_dict() == index().as_dict()
    one, two = _fl14(index()), _fl14(index())
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


# ── FL14's 170 fabricated, from the printout's breakdown ──────────────────

def test_the_fixture_is_the_printouts_fabricated_under_2o4():
    assert FL14['printout'] == {'answers': 258, 'fabricated': 170,
                                'missing': {'price': 60, 'retailer': 48, 'name': 48, 'size': 26, 'count': 21,
                                            'attribute': 58}}
    assert len(FL14['answers']) == 170 and {a['v14']['outcome'] for a in FL14['answers']} == {'fabricated'}
    missing = Counter(kind for a in FL14['answers'] for kind in a['v14']['missing'])
    assert missing == Counter(FL14['printout']['missing'])


def _buckets(idx):
    return Counter(('+'.join(a['kinds']), read(d)) for a, d in zip(FL14['answers'], _fl14(idx)))


def test_what_each_fabricated_bucket_becomes_on_the_pilot_alone():
    """B1 alone, on the pilot as supply serves it today: nothing in the
    fixture is a value the brand states otherwise, and the pilot holds none
    of it, so all 170 are unverified."""
    assert Counter(read(d) for d in _fl14(index(pages=False))) == Counter({ea.UNVERIFIED: 170})


def test_what_each_fabricated_bucket_becomes_with_the_line_pages():
    """B1 and B2, with the three recorded line pages: what the pages state
    (Swaddlers Size 7, a 148 count box, Zzz in Size 6) grounds; prices,
    stores off the list, lines not read and attribute words the JSON-LD
    does not state stay unverified. Nothing is fabricated: the fixture holds
    no contradicted value (its builder's docstring); FL14's real answers may."""
    assert _buckets(index()) == Counter({
        ('price', ea.UNVERIFIED): 20, ('retailer', ea.UNVERIFIED): 18,
        ('name', 'grounded'): 7, ('name', ea.UNVERIFIED): 13,                  # Zzz read; Ninjamas, Splashers not
        ('size', 'grounded'): 6, ('count', 'grounded'): 5, ('attribute', ea.UNVERIFIED): 10,
        ('price+retailer', ea.UNVERIFIED): 25, ('price+attribute', ea.UNVERIFIED): 15,
        ('retailer+attribute', ea.UNVERIFIED): 5, ('name+attribute', ea.UNVERIFIED): 18,
        ('name+size', 'grounded'): 4, ('name+size', ea.UNVERIFIED): 6,          # Zzz Size 6; Ninjamas Size 6
        ('size+count', 'grounded'): 10, ('count+attribute', 'grounded'): 6,
        ('attribute+attribute', ea.UNVERIFIED): 2})
    assert Counter(read(d) for d in _fl14(index())) == Counter({ea.UNVERIFIED: 132, 'grounded': 38})


def test_the_printout_on_the_fixture():
    rows = []
    for d in _fl14(index()):
        rows.append(({'selector': {}, 'brand_claim': d['brand_claim']}, d['outcome'], d['reason_code']))
    report = rescore_cycle.selection_report(rows)
    text_ = rescore_cycle._render_selection(report, {'compared': 170, 'changed': 0})
    assert '    fact index           195 facts (record 3, catalog 34, brand pages 158); v2 ' in text_
    assert "    index slots          lines 9 (status known 3, retired: none; the brand's line list not served)" \
        in text_
    assert '      sizes per line     Cruisers 360 6, Swaddlers 10, Zzz 4  (complete: Cruisers 360, Swaddlers, Zzz)' \
        in text_
    assert ('      ranges per size    Preemie 1, Newborn 1, Size 1 1, Size 2 1, Size 3 4, Size 4 3, Size 5 5, '
            'Size 6 3, Size 7 2, Size 8 2') in text_
    assert '      counts per line    Cruisers 360 18, Swaddlers 25, Zzz 4  (complete: Cruisers 360, Swaddlers, Zzz)' \
        in text_
    assert '    split                grounded 38, unverified 132  (' in text_
    assert '    fabricated, by the slot contradicted: none' in text_
    # per answer, each fact type left unverified in the deciding sentence once
    assert ('    unverified, by the fact left unverified: attribute 50, name 31, price 60, retailer 48, size 6'
            in text_)


def test_the_facts_cache_carries_each_variants_line_and_status():
    """2O-5: BrandFactsCache hands the index each variant's line (its
    product's title) and the feed's status and successor (2L-2)."""
    from clients.truesync_catalog import build_snapshot
    from scoring.expectation_scorer import BrandFactsCache
    from tests.test_retired_lines_2l2 import PAMPERS

    class Catalog:
        def snapshot(self, *_a, **_k):
            snap = build_snapshot(PAMPERS)
            snap.brand = 'Pampers'
            return snap

    facts = BrandFactsCache(Catalog()).for_merchant('pampers')
    pure = next(v for v in facts['variants'] if v['line'] == 'Pampers Pure Protection')
    assert (pure['title'], pure['status'], pure['successor']['product_name']) == ('Size 1', 'retired', 'Pampers AMORE')
    idx = bfi.build(facts)
    assert (idx.lines['pure protection'].status, idx.lines['pure protection'].successor) == ('retired', 'Pampers AMORE')
    assert idx.lines['swaddler'].status == 'current'
