"""
2L-2: "Retired product named" on Visibility and the Overview, sqlite and Postgres.

The FL13-shaped fixture (2K-4's _fl13_shape: FL12's 2I-8 shape, its previous
cycle another study) with the demo's story written into it: the study's record
says Pampers Pure Protection is retired and Pampers AMORE replaced it
(tier_config.merchant.retired, as the generator writes it), and the answers
below say what the counts are. 102 answered brand-choice answers (17 unbranded
category questions x 6 agents); in run order:

  0-3    "Pampers Pure Protection"         Pure            (0 also "Pampers AMORE")
  4-6    "Pampers Pure"                    Pure
  7-9    "Pure Protection"                 Pure
  10-11  "made with pure cotton"           neither: "pure" alone is not the line
  12     "AMORE"                           AMORE
  13     "amore"                           AMORE (case does not matter)
  14     "Amorepacific"                    neither: not the whole word

Pure named in 10 of 102, AMORE in 3. The brand-direct question about Pure
("Is Pampers Pure Protection still sold, and what replaced it?"), one run per
agent, the AI Mode one unanswered: 5 answers, 2 naming AMORE.
"""
import json
import os

from sqlalchemy import text

from app.services import console_read_models as rm
from soa_shared import retired_lines as rl
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i9 import AGENTS6
from tests.test_console_2k4_comparable import _fl13_shape
from tests.test_console_read_models import TOKEN_A, _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

PURE = {'listing_id': 41, 'variant_ids': ['sku:sku_pg_pure_s1'], 'product_name': 'Pampers Pure Protection',
        'line': 'Pure Protection', 'label': 'Pure', 'terms': rl.terms('Pampers Pure Protection', 'Pampers'),
        'successor': {'variant_id': 'sku:sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132',
                      'product_name': 'Pampers AMORE', 'line': 'AMORE', 'label': 'AMORE',
                      'terms': rl.terms('Pampers AMORE', 'Pampers')}}
ANSWERS = (['Try Pampers Pure Protection, or Pampers AMORE.']
           + ['Pampers Pure Protection is gentle.'] * 3
           + ['Pampers Pure is a good pick.'] * 3
           + ['Pure Protection diapers fit well.'] * 3
           + ['Look for one made with pure cotton.'] * 2
           + ['AMORE is the new line.', 'pampers amore is softer.', 'Amorepacific makes skincare.'])
BRAND_DIRECT = ['It was replaced by Pampers AMORE.', 'Yes, still sold widely.', 'AMORE replaced it.',
                'Still at Walmart.', 'Yes.']
QUESTION = 3001


def _retired(db, line=PURE):
    """The study's job says the line is retired; the answers say the rest."""
    with db.begin() as c:
        job_id, config = c.execute(text("SELECT id, tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                                   {'st': f229.STUDY}).one()
        config = json.loads(config) if isinstance(config, str) else dict(config or {})
        config['merchant'] = {**(config.get('merchant') or {}), 'own_domain': 'pampers.com',
                              'retired': [line] if line else []}
        c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = :t WHERE id = :i"),
                  {'t': _encode(config), 'i': job_id})
        runs = c.execute(text("""
            SELECT r.id FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
            WHERE r.cycle_id = 229 AND q.tier = 'category_control' AND q.query_text NOT LIKE 'Is Wiggle & Snug right%'
              AND r.answer_status = 'answered' ORDER BY r.id""")).scalars().all()
        assert len(runs) == 102
        for run_id, answer in zip(runs, ANSWERS):
            c.execute(text("UPDATE soa_runs SET raw_response = :t WHERE id = :i"), {'t': answer, 'i': run_id})
        ref = {'merchant_slug': 'pampers', 'listing_id': 41,
               'retired_line': {'variant_ids': PURE['variant_ids'], 'line': PURE['line']}}
        expected = {'type': 'brand_mention', 'brand': 'Pampers', 'domain': 'pampers.com',
                    'successor': {k: PURE['successor'][k] for k in ('variant_id', 'sku', 'product_name', 'line', 'label')}}
        c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, study_pattern, "
                       "organization_id, tier, expected_answer, provenance, source_ref) VALUES (:i, 'WSF_3001', :t, "
                       "'Research', 'Active', :st, 'brand_at_retail', 1, 'brand_direct', :e, 'catalog', :r)"),
                  {'i': QUESTION, 't': rl.question_text(PURE, 'Pampers'), 'st': f229.STUDY, 'e': _encode(expected), 'r': _encode(ref)})
        answers = iter(BRAND_DIRECT)
        for n, (platform, surface, collector) in enumerate(AGENTS6):
            answered = platform != 'aimode'
            c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, raw_response, "
                           "status, surface, collector, answer_status) VALUES (:r, 229, :q, :p, 1, "
                           "'2026-10-14T15:00:00+00:00', :t, :s, :surf, :col, :a)"),
                      {'r': 95000 + n, 'q': QUESTION, 'p': platform, 't': next(answers) if answered else '',
                       's': 'success' if answered else 'error', 'surf': surface, 'col': collector,
                       'a': 'answered' if answered else None})


def _get(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'cycle': f229.CYCLE_229, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_counts_on_the_fl13_shape_by_hand(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _retired(db)
    block = _get(http, 'visibility')['retired_named']
    (line,) = block['lines']
    assert (line['label'], line['line'], line['successor']['label']) == ('Pure', 'Pure Protection', 'AMORE')
    every = line['brand_choice']['all']
    assert (every['answers'], every['named'], every['successor_named'], every['no_text']) == (102, 10, 3, 0)
    # each surface's own counts add up to every agent together
    parts = [v for s, v in line['brand_choice'].items() if s != 'all']
    assert sum(p['answers'] for p in parts) == 102
    assert sum(p['named'] for p in parts) == 10 and sum(p['successor_named'] for p in parts) == 3
    assert line['brand_direct'] == {'answers': 5, 'named_successor': 2, 'still_sold': None}
    assert line['headline'] == 'Pure named in 10 of 102 brand-choice answers, AMORE in 3.'
    assert line['sentence'] == ('Agents named Pure, which pampers.com retired, 10 times in 102 category answers '
                                'and AMORE, its successor, 3 times.')
    assert block['retired_by'] == 'pampers.com'
    assert block['still_sold_note'] == rm.RETIRED_STILL_SOLD_NOTE


def test_the_overview_carries_the_same_block(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _retired(db)
    vis = _get(http, 'visibility')['retired_named']
    assert _get(http, 'overview')['retired_named'] == vis


def test_no_retired_line_no_block(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _retired(db, line=None)
    assert 'retired_named' not in _get(http, 'visibility')
    assert 'retired_named' not in _get(http, 'overview')


def test_a_study_from_before_2l2_has_no_block(http, db, upstream):
    _fl13_shape(db, http, upstream)
    assert 'retired_named' not in _get(http, 'visibility')


# ═══ the chip's data: catalog, True Value, record ═════════════════════════

#: supply's /feed rows as 2L-2 serves them: lifecycle and successor_variant_key on a retired row only
FEED_ROWS = [
    {'row_number': 2, 'sku': 'sku_pg_swd_nb_84', 'variant_key': 'sku:sku_pg_swd_nb_84', 'gtin14': None,
     'product_name': 'Pampers Swaddlers', 'brand_name': 'Pampers', 'variant_label': 'Newborn, 84 ct'},
    {'row_number': 3, 'sku': 'sku_pg_pure_s1', 'variant_key': 'sku:sku_pg_pure_s1', 'gtin14': None,
     'product_name': 'Pampers Pure Protection', 'brand_name': 'Pampers', 'variant_label': 'Size 1',
     'lifecycle': 'retired', 'successor_variant_key': 'sku:sku_pg_amore_s1_132'},
    {'row_number': 4, 'sku': 'sku_pg_amore_s1_132', 'variant_key': 'sku:sku_pg_amore_s1_132', 'gtin14': None,
     'product_name': 'Pampers AMORE', 'brand_name': 'Pampers', 'variant_label': 'Size 1, 132 ct'},
]
AMORE_VIEW = {'successor': {'variant_id': 'sku:sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132',
                            'product_name': 'Pampers AMORE', 'label': 'AMORE'}}
#: supply's catalog listing for Pure, as 2L-2 serves it
PURE_LISTING = {'listing_id': 41, 'title': 'Pampers Pure Protection', 'brand': 'Pampers', 'variants': [
    {'variant_id': 'sku:sku_pg_pure_s1', 'title': 'Size 1', 'status': 'retired',
     'successor': {'variant_id': 'sku:sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132', 'gtin': None,
                   'product_name': 'Pampers AMORE', 'title': 'Size 1, 132 ct'}}]}


def test_the_catalog_marks_a_retired_feed_row_with_its_successor():
    body = rm.build_catalog('pampers', feed={'version': {'id': 1}, 'rows': FEED_ROWS}, history=[], hosted_catalog=None)
    rows = {r['sku']: r for r in body['rows']}
    assert rows['sku_pg_pure_s1']['retired'] == AMORE_VIEW
    assert 'retired' not in rows['sku_pg_amore_s1_132'] and 'retired' not in rows['sku_pg_swd_nb_84']


def test_a_retired_row_with_no_successor_is_retired_alone():
    rows = [dict(FEED_ROWS[1], successor_variant_key=None)]
    body = rm.build_catalog('pampers', feed={'version': {'id': 1}, 'rows': rows}, history=[], hosted_catalog=None)
    assert body['rows'][0]['retired'] == {'successor': None}


def test_a_hosted_catalog_reads_the_variants_status():
    body = rm.build_catalog('pampers', feed=None, history=[], hosted_catalog={'listings': [PURE_LISTING]})
    assert body['rows'][0]['retired'] == AMORE_VIEW


def test_true_value_rows_carry_retired_from_the_feed_and_from_retailer_prices():
    reference = {'prices': [
        {'variant_ref': 'feed_sku:3', 'sku': 'sku_pg_pure_s1', 'gtin': None, 'variant_label': 'Size 1',
         'retailer_domain': 'amazon.com', 'price': '66.34', 'verifiable': True,
         'status': 'retired', 'successor': PURE_LISTING['variants'][0]['successor']},
        {'variant_ref': 'feed_sku:4', 'sku': 'sku_pg_amore_s1_132', 'gtin': None, 'variant_label': 'Size 1, 132 ct',
         'retailer_domain': 'amazon.com', 'price': '49.99', 'verifiable': True, 'status': 'active', 'successor': None}]}
    for feed in (FEED_ROWS, None):
        body = rm.build_true_value(reference, [], own_domain='pampers.com', record_variants=[], feed_rows=feed,
                                   brands={'sku:sku_pg_amore_s1_132': 'Pampers'})
        rows = {r['feed_sku']: r for r in body['rows']}
        assert rows['sku_pg_pure_s1']['retired']['successor']['label'] == 'AMORE', feed
        assert 'retired' not in rows['sku_pg_amore_s1_132']


def test_the_record_says_the_line_is_retired_and_links_its_successor():
    record = rm.build_record('pampers', PURE_LISTING, merchant_record={'kind': 'brand', 'hosting': 'external'},
                             publications=[], channels=[], provenance=None, reference=None, incentives=None)
    assert record['retired'] == AMORE_VIEW
    listing = {**PURE_LISTING, 'variants': [dict(PURE_LISTING['variants'][0], status='active', successor=None)]}
    assert rm.build_record('pampers', listing, merchant_record=None, publications=[], channels=[],
                           provenance=None, reference=None, incentives=None)['retired'] is None
    listed = rm.build_record_list('pampers', {'listings': [PURE_LISTING, listing]}, merchant_record=None,
                                  publications=[], channels=[], provenance=None, reference=None)
    assert [p.get('retired') for p in listed['products']] == [AMORE_VIEW, None]


# ═══ the endpoints, end to end; and the console's samples ════════════════
#
# SOA_2L2_SAMPLE_DUMP=<dir> writes each response below, unedited, for the
# console's fixtures (apps/console/src/data/fixtures/console-read-models).

DUMP = os.getenv('SOA_2L2_SAMPLE_DUMP')
SUPPLY = '/api/truesync/merchants/wiggle-and-snug'
with open(os.path.join(os.path.dirname(__file__), '..', '..', 'pipeline', 'tests', 'fixtures',
                       'wiggle_and_snug_catalog.json')) as fh:
    WS_CATALOG = json.load(fh)['catalog']
AMORE_LISTING = {'listing_id': 42, 'product_id': 'pampers-amore', 'title': 'Pampers AMORE', 'brand': 'Pampers',
                 'published_at': '2026-10-20T13:05:00+00:00', 'variants': [
                     {'variant_id': 'sku:sku_pg_amore_s1_132', 'title': 'Size 1, 132 ct', 'count': 132,
                      'list_price': '49.99', 'currency': 'USD', 'gtin': None, 'status': 'active', 'successor': None}]}
PURE_PUBLISHED = {**PURE_LISTING, 'product_id': 'pampers-pure-protection', 'published_at': '2026-10-20T13:05:00+00:00',
                  'variants': [dict(PURE_LISTING['variants'][0], count=None, list_price=None, currency='USD', gtin=None)]}
#: supply's retailer-prices rows as 2L-2 serves them: Pure still on Amazon (its remaining stock), AMORE on pampers.com
REFERENCE = {'merchant': 'wiggle-and-snug', 'as_of': '2026-10-20T13:05:00+00:00', 'prices': [
    {'variant_ref': 'feed_sku:3', 'gtin': None, 'sku': 'sku_pg_pure_s1', 'variant_label': 'Size 1',
     'retailer_domain': 'amazon.com', 'url': 'https://www.amazon.com/dp/PURE-S1-198', 'price': '66.34',
     'currency': 'USD', 'verifiable': True, 'role': 'retailer', 'read_status': 'ok',
     'status': 'retired', 'successor': PURE_LISTING['variants'][0]['successor']},
    {'variant_ref': 'feed_sku:4', 'gtin': None, 'sku': 'sku_pg_amore_s1_132', 'variant_label': 'Size 1, 132 ct',
     'retailer_domain': 'amazon.com', 'url': 'https://www.amazon.com/dp/AMORE-S1-132', 'price': '49.99',
     'currency': 'USD', 'verifiable': True, 'role': 'retailer', 'read_status': 'ok', 'status': 'active',
     'successor': None}]}


def _dump(name, body):
    if DUMP:
        os.makedirs(DUMP, exist_ok=True)
        with open(os.path.join(DUMP, f'{name}-2l2.json'), 'w') as fh:
            json.dump(body, fh, indent=2, sort_keys=True)


def test_the_endpoints_serve_the_retired_line_end_to_end(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _retired(db)
    vis, over = _get(http, 'visibility'), _get(http, 'overview', merchant='wiggle-and-snug')
    assert vis['retired_named']['lines'][0]['brand_choice']['all']['named'] == 10
    assert over['retired_named'] == vis['retired_named']
    _dump('visibility', vis)
    _dump('overview', over)

    upstream.answer('GET', f'{SUPPLY}/catalog', body={**WS_CATALOG, 'listings': WS_CATALOG['listings'] +
                                                       [PURE_PUBLISHED, AMORE_LISTING]}, token=TOKEN_A)
    as_('op')
    catalog = http.get('/api/console/catalog', params={'merchant': 'wiggle-and-snug', 'org': 10}).json()
    retired = [r for r in catalog['rows'] if r.get('retired')]
    assert [(r['sku'], r['retired']) for r in retired] == [('sku_pg_pure_s1', AMORE_VIEW)]
    _dump('catalog', catalog)
    listed = http.get('/api/console/record/list', params={'merchant': 'wiggle-and-snug', 'org': 10}).json()
    assert [p['sku'] for p in listed['products'] if p.get('retired')] == ['pampers-pure-protection']
    _dump('record-list', listed)
    record = http.get('/api/console/record', params={'merchant': 'wiggle-and-snug', 'product': 'pampers-pure-protection',
                                                     'org': 10}).json()
    assert record['retired'] == AMORE_VIEW
    _dump('record', record)

    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET reference_prices = :r WHERE id = 229"), {'r': _encode(REFERENCE)})
    tv = http.get('/api/console/true-value', params={'cycle': f229.CYCLE_229, 'merchant': 'wiggle-and-snug',
                                                     'org': 10}).json()
    rows = {r['feed_sku']: r for r in tv['rows']}
    assert rows['sku_pg_pure_s1']['retired']['successor']['label'] == 'AMORE'
    assert 'retired' not in rows['sku_pg_amore_s1_132']
    _dump('true-value', tv)
