"""
2O-6: counts are an open set.

2O-5 checked pack counts per line against the brand page and flagged the
risk itself: a club-only pack (Swaddlers 210 ct at Sam's Club) is on no
pampers.com page and would read as fabricated. A count absent from the line's
page is unverified, never fabricated. The closed sets still contradict: a
line's sizes (its chart and hasVariant), a (line, size)'s weight range, a
line's status, and the brand's lines when the payload says its list is
complete. The attribute check reads the line page's `bullets` (supply 2O-6):
"Fragrance Free" on the Swaddlers page contradicts "scented", absent stays
unverified.

  * a count: off the page unverified (the club pack, a count no page lists),
    on it grounded, with the pilot alone unverified;
  * each closed set still contradicts, on the index as supply serves it now;
  * the line list as supply serves it (`brand_lines`, `brand_lines_complete`
    false): a line on it grounded, a line off it unverified; complete,
    fabricated;
  * the attribute check on the served bullets, and a word the page negates
    is never on the line ("Free of fragrance" is no fragrance);
  * the served rows are 2O-5's fixture's (supply's reader extracts the same
    variants and charts from the same recorded pages);
  * FL14's fixture split before (2O-5's served shape) and after (2O-6's);
  * two runs identical.

The index is built from fixtures/brand_claim/pampers_brand_pages_2o6.json
(fixtures/build_brand_pages_2o6.py: supply's brand_page reader on its recorded
pampers.com pages, and supply's line list). Nothing here is read from
production, and nothing calls a model.
"""
import copy
import json
import os
from collections import Counter

import pytest

from scoring import brand_fact_index as bfi
from scripts import rescore_cycle
from soa_shared import expected_answers as ea
from tests import test_brand_claim_2o5 as t5

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'brand_claim')
PAGES_2O6 = json.load(open(os.path.join(FIXTURES, 'pampers_brand_pages_2o6.json')))
PAYLOAD = ('brand_lines', 'brand_lines_complete', 'brand_line_sources')
judge, read = t5.judge, t5.read


def served(**extra):
    """The index from the pilot and the three pages as supply serves them after 2O-6."""
    facts, reference = t5.pilot()
    rows = reference['prices'] + copy.deepcopy(PAGES_2O6['prices'])
    return bfi.build(facts, {**reference, 'prices': rows, **{k: PAGES_2O6[k] for k in PAYLOAD}, **extra})


# ── counts: an open set ───────────────────────────────────────────────────

@pytest.mark.parametrize('question,answer', [
    # the club-only pack: on no pampers.com page
    ("Where can I buy Pampers Swaddlers in bulk?", "Sam's Club sells Pampers Swaddlers in a 210 count box."),
    ('Is Pampers good?', 'Pampers Swaddlers come in a 210 count box.'),
    # 2O-5 read this one fabricated (the Zzz page's Pack Count property says 72, 88, 104, 116)
    ('Is Pampers good?', 'Pampers Zzz come in a 99 count pack.'),
    ('Is Pampers good?', 'Pampers Cruisers 360 come in a 31 count pack.'),
])
@pytest.mark.parametrize('build', [t5.index, served])
def test_a_count_off_the_lines_page_is_unverified(question, answer, build):
    decided = judge(answer, question, idx=build())
    assert read(decided) == ea.UNVERIFIED and decided['outcome'] != 'fabricated'
    span = decided['brand_claim']['spans'][decided['brand_claim']['decided_by']]
    assert span['facts_missing'] == []
    assert [f['type'] for f in span['facts_unverified']].count('count') == 1


def test_the_count_check_says_what_the_page_lists():
    idx = served()
    fact = {'type': 'count', 'text': '210 count', 'value': '210'}
    out = bfi.check(fact, idx, line='Swaddlers')
    assert (out['status'], out['slot'], out['line']) == ('unverified', 'counts', 'Swaddlers')
    assert out['published'].startswith('19, 27, 29, 38') and out['published'].endswith('186, 198')
    assert bfi.check({**fact, 'text': '148 count', 'value': '148'}, idx, line='Swaddlers')['status'] == 'found'
    # another line's count grounds nothing about this one: 148 is Swaddlers', not Zzz's
    assert bfi.check({**fact, 'text': '148 count', 'value': '148'}, idx, line='Zzz')['status'] == 'unverified'


@pytest.mark.parametrize('answer', [
    'Pampers Zzz come in a 104 count pack.',
    'Pampers Swaddlers come in a 148 count box.',
    'Pampers Cruisers 360 come in a 132 count pack.',
])
def test_a_count_on_the_lines_page_is_grounded(answer):
    assert read(judge(answer, idx=served())) == 'grounded'


def test_with_the_pilot_alone_a_count_is_unverified():
    assert read(judge('Pampers Swaddlers come in a 210 count box.', idx=t5.index(pages=False))) == ea.UNVERIFIED


# ── the closed sets still contradict ──────────────────────────────────────

@pytest.mark.parametrize('question,answer,reason', [
    ('What weight range is Pampers Swaddlers Newborn for?', 'Pampers Swaddlers Newborn fits babies 2 to 9 lbs.',
     "fabricated: '2 to 9 lbs' for Swaddlers Newborn — pampers.com's chart says under 10 lb"),
    ('What weight range is Pampers Zzz Size 4 for?', 'Pampers Zzz Size 4 is for babies 15-34 lbs.',
     "fabricated: '15-34 lbs' for Zzz Size 4 — pampers.com's chart says 22 to 37 lb"),
    ('Is Pampers good?', 'Pampers Zzz come in Size 2.',
     "fabricated: 'Size 2' for Zzz — pampers.com's size list says Size 3, Size 4, Size 5, Size 6"),
    ('Is Pampers good?', 'Pampers Swaddlers were discontinued last year.',
     "fabricated: 'discontinued' for Swaddlers — pampers.com's line status says current"),
    ('Is Pampers good?', 'Pampers Swaddlers are lightly scented.',
     "fabricated: 'scented' for Swaddlers — pampers.com's page says fragrance free"),
])
def test_the_closed_sets_still_contradict(question, answer, reason):
    decided = judge(answer, question, idx=served())
    assert (decided['outcome'], decided['reason_code'], decided['reason']) == ('fabricated', 'fact_contradicted',
                                                                                reason)


# ── the brand's lines ─────────────────────────────────────────────────────

def test_the_line_list_as_supply_serves_it_is_open():
    idx = served()
    assert idx.brand_lines == PAGES_2O6['brand_lines'] and idx.brand_lines_complete is False
    assert {'Pampers Easy Ups', 'Pampers Swaddlers 360', 'Pampers Pure Protection'} <= set(idx.brand_lines)
    # a line on the list is grounded, though no page of it was read
    assert read(judge('Pampers Easy Ups and Pampers Swaddlers are both popular.', idx=idx)) == 'grounded'
    # a line off it (a real one: Ninjamas; an invented one: Little Movers) is unverified
    for answer in ('Pampers Swaddlers and Pampers Ninjamas are both popular.',
                   'Pampers Swaddlers and Pampers Little Movers are both popular.'):
        assert read(judge(answer, idx=idx)) == ea.UNVERIFIED
    # complete, the list is closed
    closed = served(brand_lines_complete=True)
    decided = judge('Pampers Swaddlers and Pampers Little Movers are both popular.', idx=closed)
    assert decided['outcome'] == 'fabricated' and decided['reason'].startswith(
        "fabricated: 'Little Movers' — not a Pampers line; pampers.com's line list is Pampers Swaddlers, ")
    # a line list served without the flag is open too: only `true` closes it
    assert served(brand_lines_complete=None).brand_lines_complete is False


# ── attributes from the bullets ───────────────────────────────────────────

def test_the_bullets_are_the_lines_attributes():
    idx = served()
    swaddlers, zzz, cruisers = idx.lines['swaddler'], idx.lines['zzz'], idx.lines['cruiser 360']
    assert {'fragrance free', 'hypoallergenic', 'wetness indicator', 'paraben free', 'latex free'} <= \
        swaddlers.attributes
    # "Free of fragrance, parabens and latex" negates the word: fragrance is not on the line
    assert 'fragrance' not in swaddlers.attributes
    assert 'leak guard' in zzz.attributes and 'stretchy waistband' in cruisers.attributes
    # on 2O-5's fixture (no bullets) the Swaddlers line held no fragrance word at all
    assert not {'fragrance free', 'fragrance'} & t5.index().lines['swaddler'].attributes


@pytest.mark.parametrize('answer,outcome', [
    ('Pampers Swaddlers are lightly scented.', 'fabricated'),
    ('Pampers Swaddlers contain fragrance.', 'fabricated'),
    ('Pampers Swaddlers are fragrance-free.', 'grounded'),
    ('Pampers Swaddlers have a wetness indicator.', 'grounded'),
    # no page of Cruisers 360 says fragrance free: another line's page says nothing about it
    ('Pampers Cruisers 360 are lightly scented.', ea.UNVERIFIED),
    ('Pampers Zzz are lightly scented.', ea.UNVERIFIED),
    # no page states it
    ('Pampers Swaddlers are dermatologist tested.', ea.UNVERIFIED),
])
def test_the_attribute_check_reads_the_bullets(answer, outcome):
    assert read(judge(answer, idx=served())) == outcome


def test_before_the_bullets_scented_is_unverified():
    assert read(judge('Pampers Swaddlers are lightly scented.', idx=t5.index())) == ea.UNVERIFIED


# ── the served rows are what 2O-5's fixture builder extracted ─────────────

def test_the_served_rows_match_2o5s_fixture():
    for new, old in zip(PAGES_2O6['prices'], t5.PAGES['prices']):
        assert (new['url'], new['final_url'], new['page_title']) == (old['url'], old['final_url'], old['page_title'])
        assert new['json_ld']['hasVariant'] == old['json_ld']['hasVariant']
        assert new['json_ld']['additionalProperty'] == old['json_ld']['additionalProperty']
        assert [{k: c[k] for k in ('size', 'min', 'max')} for c in new['size_chart']] == old['size_chart']
        assert new['bullets'] and all(isinstance(b, str) for b in new['bullets'])
    # the same line facts, read from either
    for key in ('swaddler', 'zzz', 'cruiser 360'):
        a, b = served().lines[key], t5.index().lines[key]
        assert (a.sizes, a.counts, a.ranges, a.gtins) == (b.sizes, b.counts, b.ranges, b.gtins)


# ── FL14's fixture, before and after ──────────────────────────────────────

def _split(idx):
    return Counter(read(d) for d in t5._fl14(idx))


def test_fl14s_split_before_and_after():
    """Before: 2O-5's served shape (pampers_brand_pages_2o5.json: json_ld and
    size_chart, no bullets, no line list). After: supply's 2O-6 rows (bullets)
    and its open line list. The fixture holds no count off the pages (its 21
    count answers all name a count a page lists), so the open count rule moves
    none of it; the bullets ground eight attribute answers ("fragrance free",
    "wetness indicator" on the Swaddlers page). Nothing is fabricated either
    way: the fixture holds no contradicted value."""
    before, after = _split(t5.index()), _split(served())
    assert before == Counter({ea.UNVERIFIED: 132, 'grounded': 38})
    assert after == Counter({ea.UNVERIFIED: 124, 'grounded': 46})
    moved = Counter(('+'.join(a['kinds']), read(b), read(c))
                    for a, b, c in zip(t5.FL14['answers'], t5._fl14(t5.index()), t5._fl14(served()))
                    if read(b) != read(c))
    assert moved == Counter({('attribute', ea.UNVERIFIED, 'grounded'): 2,
                             ('name+attribute', ea.UNVERIFIED, 'grounded'): 1,
                             ('price+attribute', ea.UNVERIFIED, 'grounded'): 4,
                             ('retailer+attribute', ea.UNVERIFIED, 'grounded'): 1})
    counts = [a for a in t5.FL14['answers'] if 'count' in a['kinds']]
    assert len(counts) == 21 and all(read(d) == 'grounded'
                                     for a, d in zip(t5.FL14['answers'], t5._fl14(served())) if a in counts)


def test_the_printout_after():
    rows = [({'selector': {}, 'brand_claim': d['brand_claim']}, d['outcome'], d['reason_code'])
            for d in t5._fl14(served())]
    text_ = rescore_cycle._render_selection(rescore_cycle.selection_report(rows), {'compared': 170, 'changed': 0})
    assert ("the brand's line list 10 lines, open: a line off it is unverified)" in text_)
    assert ("      counts per line    Cruisers 360 18, Swaddlers 25, Zzz 4  (the page's list: Cruisers 360, "
            "Swaddlers, Zzz; open: a count off it is unverified)") in text_
    assert '    split                grounded 46, unverified 124  (' in text_
    assert '    fabricated, by the slot contradicted: none' in text_


# ── two runs ──────────────────────────────────────────────────────────────

def test_two_runs_are_identical():
    assert served().digest() == served().digest() and served().as_dict() == served().as_dict()
    assert served().stamp()['version'] == bfi.INDEX_VERSION == 3
    one, two = t5._fl14(served()), t5._fl14(served())
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
    club = [judge("Sam's Club sells Pampers Swaddlers in a 210 count box.", idx=served()) for _ in range(2)]
    assert json.dumps(club[0], sort_keys=True) == json.dumps(club[1], sort_keys=True)
    assert club[0]['brand_claim']['version'] == ea.BRAND_CODER_VERSION == 8
