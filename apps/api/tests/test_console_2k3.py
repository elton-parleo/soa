"""
2K-3: five small data and copy items that show in a run's output, on the
FL12-shaped brand fixture (console_fixture_2j2), sqlite and Postgres. API
only: no migration, no LLM, nothing stored changes, no pipeline file.

B1. True Value rows for variants with no GTIN carried supply's reference
    (`feed_sku:<n>`) as their `sku`. They now carry the merchant's own code
    from its feed (PAM-ULTRA-120), joined as the Catalog screen joins it;
    every row carries `gtin` (None without one) and `feed_sku` beside it.
B2. /answers carries each answer's question code and stage (the drawer's
    "Q13").
B3. 2K-1's drawer line is two sentences (house rule: no semicolons), and so
    is a note the scorer stored in 2K-1's wording.
B4. claim_kind's fact lexicon gains the merchant's catalog features and the
    endorsement words (app/services/console_claims.py). On 2K-1's 16
    FL12-shaped answers: the two misses read `attribute`, the five true
    recommendations stay `recommendation_only`, none moves the other way.
B5. `start_date_local` beside the UTC start_date on the Overview, the full
    loop and the cycle list: a cycle created 04:26 UTC Oct 20 started Oct 19
    in Los Angeles.
"""
import ast
import json
import os
from datetime import datetime, timezone

import pytest
import soa_pg_harness
from sqlalchemy import text

from app.services import console_claims as cc
from app.services import console_parity as parity
from app.services import console_read_models as rm
from soa_shared import claim_kinds, local_time
from tests import console_fixture_2j2 as f2j2
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2j2 import _brand, _get, pampers_tenant  # noqa: F401  (fixture)
from tests.test_console_read_models import TOKEN_A, _encode, as_, http, upstream  # noqa: F401  (fixtures)

#: 04:26 UTC on Oct 20 is 21:26 PDT on Oct 19
CREATED = datetime(2026, 10, 20, 4, 26, tzinfo=timezone.utc)
BASE = f'/api/truesync/merchants/{f2j2.MERCHANT}'
GTINLESS_SKUS = {label: sku for label, sku, gtin, _p in f2j2.VARIANTS if not gtin}

with open(os.path.join(os.path.dirname(soa_pg_harness.__file__), 'fixtures', 'brand_direct_fl12_2k1.json')) as _fh:
    ROWS = json.load(_fh)['rows']
#: 2K-1's rule read these as recommendation_only (test_console_2k1_claim_kinds.py)
RECOMMENDATION_ONLY_2K1 = {'fl12-bd-01', 'fl12-bd-02', 'fl12-bd-03', 'fl12-bd-11', 'fl12-bd-12', 'fl12-bd-14',
                           'fl12-bd-16'}
#: a reader's recommendations: the five true ones
READER_RECOMMENDATIONS = {'fl12-bd-01', 'fl12-bd-03', 'fl12-bd-12', 'fl12-bd-14', 'fl12-bd-16'}


@pytest.fixture(autouse=True)
def _no_env_zone(monkeypatch):
    monkeypatch.delenv(local_time.TIMEZONE_ENV, raising=False)


def fl12_catalog() -> dict:
    """supply's GET /merchants/pampers/catalog with the attributes a diaper
    record publishes: FL12's shape (sizes, weight ranges, the features)."""
    body = f2j2.catalog()
    sizes = ['Newborn', 'Size 1', 'Size 2', 'Size 3', 'Size 4', 'Size 5', 'Size 4', 'Size 2', 'Size 3', 'Size 5']
    weights = ['up to 10 lb', '8-14 lb', '12-18 lb', '16-28 lb', '22-37 lb', '27+ lb', '22-37 lb', '12-18 lb',
               '16-28 lb', '27+ lb']
    for listing, size, weight in zip(body['listings'], sizes, weights):
        for v in listing['variants']:
            v['size'] = size
            v['attributes'] = {'brand': 'Pampers', 'label': v['title'], 'wetness_indicator': True,
                               'hypoallergenic': True, 'features': ['fragrance free', 'stretchy waistband'],
                               'protection': '12-hour', 'weight_range': weight}
    return body


# ═══ B1: the feed SKU on True Value rows ══════════════════════════════════

def _rows(body):
    return {r['product']: r for r in body['rows']}


def test_gtin_less_rows_carry_the_feed_sku(http, db):
    rows = _rows(_get(http, 'true-value', cycle=_brand(db)))
    for label, sku in GTINLESS_SKUS.items():
        row = rows[label]
        assert row['variant_id'].startswith('feed_sku:')                 # the key is unchanged
        assert (row['sku'], row['feed_sku'], row['gtin']) == (sku, sku, None)
    # a GTIN row keeps its GTIN as its sku (the key an answer joins its row by), its feed SKU beside it
    nb = rows['Swaddlers NB 84']
    assert (nb['sku'], nb['gtin'], nb['feed_sku']) == ('00037000863434', '00037000863434', 'PAM-SW-NB-84')


def test_the_feed_join_finds_the_sku_when_the_reference_carries_none(http, db, upstream):
    """With ?merchant=, supply's feed rows are joined as the Catalog screen
    joins them (here on the variant's label: the cached read has no sku)."""
    cycle = _brand(db)
    reference = f2j2.reference_prices()
    for p in reference['prices']:
        p.pop('sku')
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET reference_prices = :r WHERE id = 229"), {'r': _encode(reference)})
    assert {r['sku'] for r in _rows(_get(http, 'true-value', cycle=cycle)).values()} >= {'feed_sku:906'}
    upstream.answer('GET', f'{BASE}/feed', body=f2j2.feed(), token=TOKEN_A)
    body = _get(http, 'true-value', cycle=cycle, merchant=f2j2.MERCHANT)
    rows = _rows(body)
    assert {label: rows[label]['sku'] for label in GTINLESS_SKUS} == GTINLESS_SKUS
    assert 'feed' not in body['read_errors']


def test_a_hosted_catalog_row_carries_its_sku():
    body = rm.build_catalog('pampers', feed=None, history=[], hosted_catalog=f2j2.catalog())
    by = {r['product_name']: r for r in body['rows']}
    assert by['Ultra']['sku'] == 'PAM-ULTRA-120' and by['Swaddlers NB 84']['sku'] is None


# ═══ B2: the question code on answers ═════════════════════════════════════

def test_every_answer_carries_its_question_code_and_stage(http, db):
    cycle = _brand(db)
    with db.connect() as c:
        questions = {f"run-{r['id']}": (r['query_code'], r['stage']) for r in c.execute(text(
            "SELECT r.id, q.query_code, q.stage FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id "
            "WHERE r.cycle_id = 229")).mappings()}
    answers = _get(http, 'answers', cycle=cycle)
    assert len(answers) == len(questions)
    for a in answers:
        assert (a['query_code'], a['stage']) == questions[a['id']]
        assert a['query_code']


# ═══ B3: no semicolons ═════════════════════════════════════════════════════

def test_the_no_price_line_is_two_sentences():
    assert rm.BRAND_SETS_NO_PRICE_NOTE == "The brand's site sets no price. The agent priced it anyway."
    assert not any(';' in v for t in parity.TEMPLATES.values() for v in ([t] if isinstance(t, str) else t))


def test_a_note_stored_in_2k1_s_wording_reads_in_two_sentences():
    old = "the brand's site sets no price; the agent priced it anyway"
    row = {'run_id': 1, 'outcome': 'unscoreable', 'outcome_reason': old,
           'claim_results': json.dumps([{'target': 'asked', 'outcome': 'unscoreable', 'reason': old}])}
    out = rm.not_priced(row, set())
    assert out['outcome_reason'] == rm.BRAND_SETS_NO_PRICE_NOTE
    assert out['claim_results'][0]['reason'] == rm.BRAND_SETS_NO_PRICE_NOTE


def test_no_console_template_string_carries_a_semicolon():
    """Every string the console's read models serve as copy (docstrings, SQL
    and the contract notes for readers of this repo aside)."""
    here = os.path.join(os.path.dirname(__file__), '..', 'app')
    found = []
    for rel in ('services/console_parity.py', 'services/console_prompts.py', 'services/console_revenue.py',
                'services/console_claims.py', 'routers/console.py', 'routers/console_ops.py'):
        tree = ast.parse(open(os.path.join(here, rel)).read())
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and ';' in n.value and id(n) not in docs \
                    and not any(k in n.value.upper() for k in ('SELECT ', 'UPDATE ', 'INSERT ')):
                found.append((rel, n.lineno, n.value))
    assert found == []


# ═══ B4: the fact lexicon ═════════════════════════════════════════════════

def _features():
    return cc.feature_terms(fl12_catalog(), ['Pampers', 'Swaddlers', 'Cruisers 360', 'Baby Dry'])


def test_the_catalog_s_features_are_its_attributes_not_its_names():
    terms = _features()
    for t in ('wetness indicator', 'hypoallergenic', 'fragrance free', 'stretchy waistband', '12-hour', 'size 1',
              '8-14 lb', 'newborn size', 'size newborn'):
        assert t in terms
    # the product's names are not features, and a bare size word is a size only as a size
    assert not {'pampers', 'brand', 'label', 'newborn', 'swaddlers nb 84'} & set(terms)


def test_precision_on_2k1_s_16_answers():
    features = _features()
    kinds = {r['id']: cc.claim_kind(r['extraction'], features) for r in ROWS}
    rec = {k for k, v in kinds.items() if v == claim_kinds.RECOMMENDATION_ONLY}
    assert rec == READER_RECOMMENDATIONS                                   # the five true recommendations stay
    assert kinds['fl12-bd-02'] == kinds['fl12-bd-11'] == claim_kinds.ATTRIBUTE   # the two misses now read attribute
    moved_back = [k for k in kinds if claim_kinds.claim_kind(next(r for r in ROWS if r['id'] == k)['extraction'])
                  == claim_kinds.ATTRIBUTE and kinds[k] != claim_kinds.ATTRIBUTE]
    assert moved_back == []                                                # none moves the other way
    assert sum(1 for r in ROWS if kinds[r['id']] == r['reader_label']) == 16
    assert cc.counts((r['extraction'] for r in ROWS), features) == {'attribute': 11, 'recommendation_only': 5,
                                                                     'undecided': 0}


def test_which_word_decides_each_miss():
    by = {r['id']: r['extraction'] for r in ROWS}
    assert 'endorsement' in cc.answer_attributes(by['fl12-bd-02'], [])     # "most popular ... in US hospitals"
    assert cc.answer_attributes(by['fl12-bd-11'], []) == []                # needs the merchant's record
    assert cc.answer_attributes(by['fl12-bd-11'], _features()) == ['feature']


def test_no_features_is_2k1_s_rule_exactly():
    for r in ROWS:
        assert cc.claim_kind(r['extraction'], None) == claim_kinds.claim_kind(r['extraction'])
    assert {r['id'] for r in ROWS if cc.claim_kind(r['extraction']) == claim_kinds.RECOMMENDATION_ONLY} == \
        RECOMMENDATION_ONLY_2K1


@pytest.mark.parametrize('span, kind', [
    ('Pediatricians recommend Pampers.', 'attribute'),
    ("It's the #1 diaper brand.", 'attribute'),
    ('A best-selling pick.', 'attribute'),
    ('An award-winning diaper.', 'attribute'),
    ('Clinically proven to be gentle.', 'attribute'),
    ('Our fragrance-free formula.', 'attribute'),                             # a hyphen matches the feature's space
    ('Lasts 12 hours, 12 hour protection.', 'attribute'),
    ('Pampers is my favourite.', 'recommendation_only'),
    ('Great for a newborn.', 'recommendation_only'),
])
def test_the_lexicon_edges(span, kind):
    assert cc.claim_kind({'span_labels': [{'text': span}]}, _features()) == kind


def _with_fixture_extractions(db) -> dict:
    with db.begin() as c:
        runs = [r[0] for r in c.execute(text(
            "SELECT run_id FROM soa_expectation_outcomes WHERE cycle_id = 229 AND tier = 'brand_direct' "
            "AND outcome = 'fabricated' ORDER BY run_id"))]
        assigned = {}
        for i, run in enumerate(runs):
            row = ROWS[i % len(ROWS)]
            assigned[run] = row['id']
            c.execute(text("UPDATE soa_expectation_outcomes SET extraction = :x WHERE run_id = :r"),
                      {'x': _encode(row['extraction']), 'r': run})
    return assigned


def test_the_overview_signal_and_the_chip_read_the_merchant_s_catalog(http, db, upstream):
    cycle = _brand(db)
    assigned = _with_fixture_extractions(db)
    upstream.answer('GET', f'{BASE}/catalog', body=fl12_catalog(), token=TOKEN_A)
    recommended = sum(1 for rid in assigned.values() if rid in READER_RECOMMENDATIONS)
    stated = len(assigned) - recommended
    every = _get(http, 'overview', cycle=cycle)['by_surface']['all']
    assert (every['totals']['fabricated'], every['totals']['recommended']) == (stated, recommended)
    signal = next(s for s in every['signals'] if s['id'] == 'fabricated')
    assert signal['title'] == f"{stated} brand answers stated facts Wiggle & Snug never published."   # the fixture's entity
    assert signal['recommended']['line'] == f"{recommended} recommended Wiggle & Snug without stating a fact."
    answers = {a['id']: a for a in _get(http, 'answers', cycle=cycle)}
    for run, row_id in assigned.items():
        want = 'recommendation_only' if row_id in READER_RECOMMENDATIONS else 'attribute'
        assert answers[f'run-{run}']['claim_kind'] == want


def test_a_failed_catalog_read_keeps_the_endorsement_words_and_is_named(http, db, upstream):
    cycle = _brand(db)
    _with_fixture_extractions(db)
    upstream.answer('GET', f'{BASE}/catalog', status=502, body={'detail': 'down'}, token=TOKEN_A)
    body = _get(http, 'overview', cycle=cycle)
    assert 'catalog' in body['read_errors']


# ═══ B5: the local start date ═════════════════════════════════════════════

def _created(db):
    cycle = _brand(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_cycles SET created_at = :t, start_date = '2026-10-20' WHERE id = 229"),
                  {'t': CREATED})
    return cycle


def test_a_cycle_created_04_26_utc_oct_20_started_oct_19(http, db, pampers_tenant):
    cycle = _created(db)
    over = _get(http, 'overview', cycle=cycle)
    assert over['started'] == '2026-10-20'                                     # UTC, as before
    assert (over['start_date_local'], over['created_at_local'], over['timezone']) == \
        ('2026-10-19', '2026-10-19T21:26:00-07:00', 'America/Los_Angeles')
    runs = {r['id']: r for r in _get(http, 'runs', merchant=f2j2.MERCHANT)}
    assert runs[cycle]['start_date_local'] == '2026-10-19'
    with db.begin() as c:
        c.execute(text("""INSERT INTO soa_full_loop_requests (organization_id, merchant_slug, study_type, platforms,
            runs_per_query, status, cycle_id, created_by, created_at, updated_at)
            VALUES (10, :m, :st, '["chatgpt"]', 1, 'scored', 229, 'op', :t, :t)"""),
                  {'m': f2j2.MERCHANT, 'st': f2j2.STUDY, 't': CREATED})
    loop = _get(http, 'full-loop/latest', merchant=f2j2.MERCHANT)
    assert (loop['cycle']['start_date'], loop['cycle']['start_date_local']) == ('2026-10-20', '2026-10-19')


def test_the_merchant_s_zone_decides_the_day():
    cycle = {'created_at': CREATED, 'start_date': '2026-10-20'}
    assert rm.cycle_dates(cycle, 'Europe/Stockholm')['start_date_local'] == '2026-10-20'
    assert rm.cycle_dates(cycle)['start_date_local'] == '2026-10-19'
    assert rm.cycle_dates({'start_date': '2026-10-20'})['start_date_local'] is None    # never guessed


def test_studies_and_prompts_carry_the_last_run_s_local_day(http, db, pampers_tenant):
    _created(db)
    prompts = _get(http, 'prompts', merchant=f2j2.MERCHANT)
    assert (prompts['last_run'], prompts['last_run_local']) == ('2026-10-20', '2026-10-19')
    [study] = [s for s in _get(http, 'studio/studies', merchant=f2j2.MERCHANT) if s['id'] == f2j2.STUDY]
    assert (study['lastRun'], study['last_run_local']) == ('2026-10-20', '2026-10-19')


def test_nothing_stored_changes(http, db, pampers_tenant):
    cycle = _created(db)
    with db.connect() as c:
        before = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one())
    for endpoint in ('overview', 'answers', 'true-value'):
        _get(http, endpoint, cycle=cycle)
    with db.connect() as c:
        assert dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one()) == before
