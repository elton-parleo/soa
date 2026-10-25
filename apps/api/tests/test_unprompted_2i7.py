"""
2I-7 §1: category-control questions are unprompted, and a question naming the
brand is not (console scorer 9, soa_shared/unprompted.py).

FL12 (Oct 19, Pampers' first loop) was generated with the syndicated-brand
box on, so its stage questions carry the tier category_control. The scorer
counted only untiered runs as unprompted, found none, and left Visibility
not measured; and 13 of its first 25 category-control questions named the
brand. FL12 is a production cycle with no recorded sample here, so its shape
is cycle 229 (the recorded W&S full loop, console_fixture_229) with its 50
stage questions tagged category_control and 13 of them rewritten to name the
brand: 2I-6's way of standing in for FL7. 229 as recorded (untiered stage
questions, FL8's shape) scores as before. On sqlite and a local Postgres.
"""
import json

from sqlalchemy import bindparam, text

from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import unprompted
from tests.score_2l4 import retailer_rows
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import _cycle_229, _get, _supply, db  # noqa: F401
from tests.test_console_read_models import as_, http, upstream  # noqa: F401  (pytest fixtures)

BRAND = 'Wiggle & Snug'
#: what FL12's branded control questions looked like, in 229's brand: the
#: name in its spellings, and a product line from the catalog
BRANDED_TEXTS = [
    'What Wiggle & Snug diaper line should I start with for a newborn?',
    'What is the difference between Wiggle & Snug Snug-Fit and Overnight diapers?',
    'Are wiggle and snug diapers good for sensitive skin?',
    'Is Wiggle & Snug worth it for a first-time parent?',
    'Which Wiggle & Snug size fits a 12 pound baby?',
    "Do Wiggle & Snug's overnight diapers stop leaks?",
    'Where is Wiggle & Snug cheapest right now?',
    'WIGGLE & SNUG vs store brand diapers for daycare?',
    'Are Snug-Fit Diapers good for a newborn?',            # product name alone
    'How do Snug-Fit Diapers run on sizing?',
    'Wiggle & Snug wipes or water wipes for a newborn?',
    'Is the Wiggle & Snug subscription worth it?',
    'What do parents say about Wiggle & Snug?',
]
PRODUCT_NAMES = ['Snug-Fit Diapers', 'Cloud Wipes']


def _stage_question_ids(db):
    with db.connect() as c:
        return [r[0] for r in c.execute(text(
            "SELECT id FROM soa_queries WHERE study_type = :st AND tier IS NULL ORDER BY id"), {'st': f229.STUDY})]


def _fl12(db, *, branded=13, all_branded=False):
    """229 with the brand box on: the stage questions tagged category_control,
    `branded` of the asked ones (from the second on, the never-asked 87th is a
    copy of the first) naming the brand, and the catalog's product names on
    the study's tier_config as the generator now stores them."""
    _cycle_229(db)
    ids = _stage_question_ids(db)
    asked = ids[:50]
    with db.begin() as c:
        c.execute(text("UPDATE soa_queries SET tier = 'category_control' WHERE study_type = :st AND tier IS NULL"),
                  {'st': f229.STUDY})
        targets = asked if all_branded else asked[1:1 + branded]
        for i, qid in enumerate(targets):
            c.execute(text("UPDATE soa_queries SET query_text = :t WHERE id = :i"),
                      {'t': BRANDED_TEXTS[i % len(BRANDED_TEXTS)], 'i': qid})
        config = {'merchant': {'slug': 'wiggle-and-snug', 'brand': BRAND, 'study_brand': BRAND,
                               'product_names': PRODUCT_NAMES},
                  'category_control': {'enabled': True, 'count': 50}}
        c.execute(text("UPDATE soa_query_generation_jobs SET tier_config = :c WHERE study_type = :st"),
                  {'c': json.dumps(config), 'st': f229.STUDY})
    return asked


def _dims(body, code):
    return next(d for p in body['pillars'] for d in p['dimensions'] if d['code'] == code)


def _score(http):
    r = _get(http, rescore=1)
    assert r.status_code == 200, r.text
    return r.json()


def _old_rule_counts(db, surface='grounded_api'):
    """Visibility's inputs by the rule before 2I-7: answered untiered runs."""
    with db.connect() as c:
        row = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one())
        runs, mentions = score_svc.load_score_runs(c, row), score_svc.load_score_mentions(c, row)
    keep = [{**r, 'tier': r['tier'] or 'brand_direct'} if r.get('tier') == 'category_control' else r for r in runs]
    untiered = {r['run_id'] for r in runs if not r.get('tier') and r.get('answer_status') == 'answered'
                and (r.get('surface') or '') == surface}
    return keep, mentions, untiered


# ═══ the predicate ══════════════════════════════════════════════════════

def test_the_rule():
    terms = unprompted.brand_terms('Pampers', ['P&G Pampers'], ['Pampers Swaddlers', 'Cruisers 360'])
    assert terms == ['Pampers', 'P&G Pampers', 'Pampers Swaddlers', 'Cruisers 360']
    assert unprompted.is_unprompted({'tier': None, 'query_text': 'Best diapers for a newborn'}, terms)
    assert unprompted.is_unprompted({'tier': 'category_control', 'query_text': 'Best diapers for a newborn'}, terms)
    assert not unprompted.is_unprompted({'tier': 'category_control',
                                         'query_text': 'What Pampers diaper line should I start with?'}, terms)
    assert not unprompted.is_unprompted({'tier': 'category_control', 'query_text': 'Are cruisers 360 worth it?'}, terms)
    # whole words, any case: a brand called Bum is not named by 'album'
    assert unprompted.is_unprompted({'tier': None, 'query_text': 'A baby photo album'}, ['Bum'])
    assert not unprompted.is_unprompted({'tier': None, 'query_text': 'is BUM any good'}, ['Bum'])
    # a branded tier is never unprompted, and with no terms the tier decides
    assert not unprompted.is_unprompted({'tier': 'brand_direct', 'query_text': 'Best diapers'}, terms)
    assert unprompted.is_unprompted({'tier': 'category_control', 'query_text': 'Pampers?'}, [])
    assert unprompted.names_any('Pampers Swaddlers or Huggies?', terms) == ['Pampers', 'Pampers Swaddlers']


def test_the_terms_are_the_entity_its_aliases_and_the_stored_product_names(http, db):
    _fl12(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_entities SET aliases = :a WHERE id = (SELECT entity_id FROM soa_cycle_entities "
                       "WHERE cycle_id = 229 AND role = 'primary')"), {'a': json.dumps(['W&S'])})
    with db.connect() as c:
        row = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one())
        assert rm.load_brand_terms(c, row) == [BRAND, 'W&S', *PRODUCT_NAMES]


# ═══ FL12's shape: Visibility measured over the unbranded control answers ═══

def test_fl12_measures_visibility_over_the_37_unbranded_control_questions(http, db, upstream):
    asked = _fl12(db)
    _supply(upstream)
    body = _score(http)
    assert body['scorer_version'] == '17'
    assert body['unprompted'] == {'questions': 37, 'named_the_brand': 13, 'category_control': 50}
    som, rec = _dims(body, 'share_of_mentions'), _dims(body, 'recommendation_strength')
    assert som['state'] == 'measured' and rec['state'] == 'measured'
    assert 'share_of_mentions' in body['measured'] and 'recommendation_strength' in body['measured']

    # the denominator is the mentions on the runs of the 37, and only those
    with db.connect() as c:
        branded = {r[0] for r in c.execute(text(
            "SELECT r.id FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = 229 "
            "AND q.tier = 'category_control' AND q.id IN :ids").bindparams(bindparam('ids', expanding=True)),
            {'ids': asked[1:14]})}
        counted = {r[0] for r in c.execute(text(
            "SELECT r.id FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = 229 "
            "AND q.tier = 'category_control' AND r.surface = 'grounded_api' AND r.answer_status = 'answered'"))} - branded
        mentions = c.execute(text(
            "SELECT cm.run_id FROM soa_coded_mentions cm JOIN soa_runs r ON r.id = cm.run_id "
            "JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.entity_id = cm.entity_id "
            "WHERE r.cycle_id = 229 AND cm.mentioned = :y"), {'y': True}).fetchall()
    part = som['parts'][0]
    assert len(counted) == 222                                   # 37 questions, 6 answered runs each
    assert (part['numerator'], part['denominator']) == (0, sum(1 for (rid,) in mentions if rid in counted))
    assert part['denominator'] == 26
    # 229's brand is named in none of its answers, so both are a measured 0;
    # under scorer 8 this cycle scored 60 of 37 applicable with Visibility's
    # 32 points not measured (FL12's tile), now 32 of 69
    assert (body['score'], body['earned'], body['applicable_max']) == (32, 22.3, 69.0)

    # the screens count the same answers: Visibility's headline, the
    # Overview's tiles and agent table, the study list
    as_('op')
    params = {'cycle': f229.CYCLE_229, 'merchant': 'wiggle-and-snug', 'org': 10}
    vis = http.get('/api/console/visibility', params=params).json()
    rows = [r for r in vis['byQuestion'] if r['surface'] == 'grounded_api' and r['answered']]
    assert sum(1 for r in rows if r['unprompted']) == 222
    assert all(r['tier'] == 'category_control' for r in rows if r['unprompted'])
    assert vis['headlines']['grounded_api']['tier'] == 'unprompted'
    assert vis['headlines']['grounded_api']['denom'] == 222
    over = http.get('/api/console/overview', params=params).json()
    grounded = over['by_surface']['grounded_api']
    assert grounded['tier'] == 'unprompted' and grounded['totals']['named_of'] == 222
    assert sum(a['named_of'] for a in grounded['agents']) == 222
    assert over['coverage']['unprompted'] == 222
    assert body['metric_counts']['grounded_api']['first']['of'] == 222
    tiles = {m['key']: m for m in retailer_rows(score_svc.with_previous(body, None, None))}
    assert tiles['first']['surface_note'].endswith('brand-choice answers')
    [study] = [s for s in http.get('/api/console/studio/studies', params={'org': 10}).json()
               if s['id'] == f229.STUDY]
    # 11 brand-direct + 19 catalog + 6 value + 13 control naming the brand;
    # 37 + the never-asked copy of the first (unbranded)
    assert study['prompt_counts'] == {'branded': 49, 'unbranded': 38, 'prompts': 87}


def test_the_recompute_line_names_the_change_on_fl12(http, db, upstream):
    _fl12(db)
    _supply(upstream)
    body = _score(http)
    old = {'scorer_version': '8', 'score': (body['score'] or 0) + 7}
    assert score_svc.recompute_line(old, body, 'stale') == 'scorer 8 → 17: category-control questions count as unprompted'
    assert score_svc.SCORER_CHANGES['9'] == 'category-control questions count as unprompted'


def test_every_control_question_naming_the_brand_leaves_visibility_unmeasured_and_says_why(http, db, upstream):
    _fl12(db, all_branded=True)
    _supply(upstream)
    body = _score(http)
    som = _dims(body, 'share_of_mentions')
    assert som['state'] == 'not_measured'
    assert som['reason'] == ('no unprompted question answered on this surface: every category-control question '
                             'names the brand (300 answered), and a question that names it is not counted')
    assert body['unprompted']['questions'] == 0 and body['verdict'] is None
    # the screens fall back to every answered question, as for a cycle with none
    as_('op')
    over = http.get('/api/console/overview', params={'cycle': f229.CYCLE_229, 'merchant': 'wiggle-and-snug',
                                                      'org': 10}).json()
    assert over['by_surface']['grounded_api']['tier'] == 'all'


# ═══ FL8's shape and 229: unchanged ═════════════════════════════════════

def test_229_untiered_scores_as_before_but_for_the_version(http, db, upstream):
    """229's stage questions are untiered (FL8's shape, the box off): the
    same Visibility inputs as the rule before 2I-7, the same score."""
    _cycle_229(db)
    _supply(upstream)
    body = _score(http)
    # main (scorer 8) scores 229 at 32, 22.3 of 69.0
    assert (body['score'], body['earned'], body['applicable_max'], body['scorer_version']) == (32, 22.3, 69.0, '17')
    assert body['unprompted'] == {'questions': 50, 'named_the_brand': 0, 'category_control': 0}
    keep, mentions, untiered = _old_rule_counts(db)
    with db.connect() as c:
        row = dict(c.execute(text("SELECT * FROM soa_cycles WHERE id = 229")).mappings().one())
        terms = rm.load_brand_terms(c, row)
    now = score_svc.visibility_inputs(keep, mentions, 'grounded_api', terms)
    assert now['runs'] == len(untiered) == 300 and now['named_the_brand'] == 0
    part = _dims(body, 'share_of_mentions')['parts'][0]
    assert (part['numerator'], part['denominator']) == (0, 154)
    # a v8 score of the same number reads the plain version line: the change does not apply
    assert score_svc.recompute_line({'scorer_version': '8', 'score': 50}, body, 'stale') == 'scorer 8 → 17'


def test_a_branded_untiered_question_is_left_out_too(http, db, upstream):
    """FL8's shape with one stage question naming the brand: it is not
    unprompted either, whatever its tier."""
    _cycle_229(db)
    ids = _stage_question_ids(db)
    with db.begin() as c:
        c.execute(text("UPDATE soa_queries SET query_text = 'Is Wiggle & Snug any good?' WHERE id = :i"), {'i': ids[1]})
    _supply(upstream)
    body = _score(http)
    assert body['unprompted'] == {'questions': 49, 'named_the_brand': 1, 'category_control': 0}
    assert _dims(body, 'share_of_mentions')['state'] == 'measured'
