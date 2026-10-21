"""
2L-2: retired lines in the catalog snapshot, and the question the generator asks.

Supply's catalog serves `status` and `successor` on every variant. The snapshot
keeps them; a line (a catalog product) whose variants are all retired is a
retired line; the generator keeps its variants in catalog accuracy (agents
still price them) and asks one brand-direct question about it, expecting its
successor; tier_config.merchant.retired records the lines for the read model.
"""
import copy
import filecmp
import os

import pytest

from clients.truesync_catalog import build_snapshot
from generation import catalog_tiers as ct
from soa_shared import retired_lines as rl
from tests.test_syndicated_study import ALL_ON, _build, payloads  # noqa: F401  (fixture)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

AMORE = {'variant_id': 'sku:sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132', 'gtin': None,
         'product_name': 'Pampers AMORE', 'title': 'Size 1, 132 ct'}
PAMPERS = {'merchant': 'pampers', 'listings': [
    {'listing_id': 1, 'title': 'Pampers Swaddlers', 'brand': 'Pampers', 'variants': [
        {'variant_id': 'sku:sku_pg_swd_nb_84', 'title': 'Newborn, 84 ct', 'list_price': '29.99', 'status': 'active',
         'successor': None}]},
    {'listing_id': 3, 'title': 'Pampers Pure Protection', 'brand': 'Pampers', 'variants': [
        {'variant_id': 'sku:sku_pg_pure_s1', 'title': 'Size 1', 'list_price': '45.99', 'status': 'retired',
         'successor': AMORE}]},
    {'listing_id': 4, 'title': 'Pampers AMORE', 'brand': 'Pampers', 'variants': [
        {'variant_id': 'sku:sku_pg_amore_s1_132', 'title': 'Size 1, 132 ct', 'list_price': '49.99',
         'status': 'active', 'successor': None}]},
]}


def test_the_two_copies_are_identical():
    for name in ('retired_lines.py', 'catalog_snapshot.py', 'catalog_tiers.py'):
        assert filecmp.cmp(os.path.join(ROOT, 'apps', 'api', 'soa_shared', name),
                           os.path.join(ROOT, 'apps', 'pipeline', 'soa_shared', name), shallow=False), name


# ── the snapshot ──────────────────────────────────────────────────────────

def test_the_snapshot_keeps_status_and_successor():
    snap = build_snapshot(PAMPERS)
    _, pure = snap.find_variant('sku:sku_pg_pure_s1')
    assert (pure.status, pure.successor) == ('retired', AMORE)
    _, amore = snap.find_variant('sku:sku_pg_amore_s1_132')
    assert (amore.status, amore.successor) == ('active', None)


def test_a_record_from_before_2l2_reads_as_active():
    old = copy.deepcopy(PAMPERS)
    for listing in old['listings']:
        for variant in listing['variants']:
            del variant['status'], variant['successor']
    snap = build_snapshot(old)
    assert {v.status for _, v in snap.variants()} == {'active'}
    assert rl.retired_lines(snap) == []


# ── naming a line ─────────────────────────────────────────────────────────

def test_the_line_its_label_and_its_terms():
    assert rl.line_name('Pampers Pure Protection', 'Pampers') == 'Pure Protection'
    assert rl.label('Pampers Pure Protection', 'Pampers') == 'Pure'
    assert rl.terms('Pampers Pure Protection', 'Pampers') == ['Pampers Pure Protection', 'Pure Protection', 'Pampers Pure']
    assert rl.terms('Pampers AMORE', 'Pampers') == ['Pampers AMORE', 'AMORE']
    assert rl.line_name('Snug-Fit Diapers', 'Pampers') == 'Snug-Fit Diapers'   # no brand in front


@pytest.mark.parametrize('text, named', [
    ('Try Pampers Pure Protection for newborns.', True),
    ('pampers pure is gentle', True),
    ('Pure Protection, size 1', True),
    ('Look for one made with pure cotton.', False),        # "pure" alone is not the line
    ('Pampers Swaddlers are the pick.', False),
])
def test_an_answer_names_pure_only_by_its_terms(text, named):
    assert rl.names(text, rl.terms('Pampers Pure Protection', 'Pampers')) is named


@pytest.mark.parametrize('text, named', [('AMORE is new', True), ('pampers amore', True), ('Amorepacific', False)])
def test_an_answer_names_amore_as_a_whole_word(text, named):
    assert rl.names(text, rl.terms('Pampers AMORE', 'Pampers')) is named


def test_the_retired_lines_of_the_pampers_record():
    (line,) = rl.retired_lines(build_snapshot(PAMPERS))
    assert {k: line[k] for k in ('listing_id', 'variant_ids', 'product_name', 'line', 'label')} == {
        'listing_id': 3, 'variant_ids': ['sku:sku_pg_pure_s1'], 'product_name': 'Pampers Pure Protection',
        'line': 'Pure Protection', 'label': 'Pure'}
    assert {k: line['successor'][k] for k in ('variant_id', 'sku', 'product_name', 'label')} == {
        'variant_id': 'sku:sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132', 'product_name': 'Pampers AMORE',
        'label': 'AMORE'}


def test_a_line_with_one_size_still_made_is_not_retired():
    mixed = copy.deepcopy(PAMPERS)
    mixed['listings'][1]['variants'].append({'variant_id': 'sku:sku_pg_pure_s2', 'title': 'Size 2', 'status': 'active'})
    assert rl.retired_lines(build_snapshot(mixed)) == []


# ── the question ──────────────────────────────────────────────────────────

def test_one_brand_direct_question_per_retired_line_expecting_its_successor():
    rows, report = ct.build_retired_line_questions(build_snapshot(PAMPERS), category='Baby Care',
                                                   persona='Value-Conscious Parent', study_pattern='brand_at_retail')
    (row,) = rows
    assert row['query_text'] == 'Is Pampers Pure Protection still sold, and what replaced it?'
    assert (row['tier'], row['provenance'], row['stage']) == ('brand_direct', 'catalog', 'Research')
    assert row['expected_answer']['type'] == 'brand_mention' and row['expected_answer']['brand'] == 'Pampers'
    assert row['expected_answer']['successor']['sku'] == 'sku_pg_amore_s1_132'
    assert row['source_ref']['retired_line'] == {'variant_ids': ['sku:sku_pg_pure_s1'], 'line': 'Pure Protection'}
    assert report == {'count': 1, 'lines': ['Pure Protection']}


def test_a_last_of_line_is_asked_whether_it_is_still_sold():
    alone = copy.deepcopy(PAMPERS)
    alone['listings'][1]['variants'][0]['successor'] = None
    (row,), _ = ct.build_retired_line_questions(build_snapshot(alone), category='Baby Care', persona=None,
                                                study_pattern='brand_at_retail')
    assert row['query_text'] == 'Is Pampers Pure Protection still sold?'
    assert 'successor' not in row['expected_answer']


def test_no_retired_line_no_question():
    current = copy.deepcopy(PAMPERS)
    current['listings'][1]['variants'][0].update(status='active', successor=None)
    assert ct.build_retired_line_questions(build_snapshot(current), category='Baby Care', persona=None,
                                           study_pattern='brand_at_retail') == ([], {'count': 0, 'lines': []})


# ── the study ─────────────────────────────────────────────────────────────

@pytest.fixture
def retired_snapshot(payloads):  # noqa: F811
    """W&S's catalog with its Overnight line retired, Snug-Fit Diapers Size 3 big named as successor."""
    catalog = copy.deepcopy(payloads['catalog'])
    overnight = next(l for l in catalog['listings'] if l['title'] == 'Snug-Fit Overnight Diapers')
    for variant in overnight['variants']:
        variant['status'] = 'retired'
        variant['successor'] = {'variant_id': 'snug-fit-diapers-s3-big', 'sku': None, 'gtin': None,
                                'product_name': 'Snug-Fit Diapers', 'title': 'Size 3 big pack'}
    return build_snapshot(catalog, merchants=payloads['merchants'], incentives=payloads['incentives'])


def test_the_study_asks_the_retired_line_question_and_still_prices_the_line(retired_snapshot):
    rows, _prov, config, _s, _b = _build(retired_snapshot, ALL_ON)
    # 50 stage + 12 brand-direct + 1 retired-line + 19 accuracy + 6 value
    assert len(rows) == 50 + 12 + 1 + 19 + 6
    asked = [r for r in rows if (r.get('source_ref') or {}).get('retired_line')]
    assert [r['query_text'] for r in asked] == [
        'Is Wiggle & Snug Snug-Fit Overnight Diapers still sold, and what replaced it?']
    assert config['brand_direct']['count'] == 13 + 38   # 2L-4: and 38 where-to-buy and cheapest-place
    assert config['brand_direct']['retired_lines'] == {'count': 1, 'lines': ['Snug-Fit Overnight Diapers']}
    # agents still price a retired line: its variants stay in catalog accuracy
    priced = {r['source_ref'].get('variant_id') for r in rows if r.get('tier') == 'catalog_accuracy'}
    assert {'snug-fit-overnight-s3', 'snug-fit-overnight-s4'} & priced
    (line,) = config['merchant']['retired']
    assert (line['line'], line['successor']['product_name']) == ('Snug-Fit Overnight Diapers', 'Snug-Fit Diapers')


def test_a_study_with_no_retired_line_is_unchanged(payloads):  # noqa: F811
    snap = build_snapshot(payloads['catalog'], merchants=payloads['merchants'], incentives=payloads['incentives'])
    rows, _prov, config, _s, _b = _build(snap, ALL_ON)
    assert len(rows) == 50 + 12 + 19 + 6
    assert config['merchant']['retired'] == []
    assert config['brand_direct']['retired_lines'] == {'count': 0, 'lines': []}
