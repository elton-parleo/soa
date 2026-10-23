"""
2M-1: attribute accuracy, the weight range for the size asked, sqlite and Postgres.

The FL13 shape (2K-4's _fl13_shape) with 10 attribute questions added
(brand-direct, source_ref.intent 'attribute', as catalog_tiers.build_intent_
questions writes them: line, size, count and the brand truth), one run per
agent, AI Mode unanswered: 5 answers each, coded from the answer text
(attribute_accuracy.weight_from_answer; the extraction carries no coding, as
an outcome stored before the coder). Supply's /reference carries the ranges
(its `attributes`, parleo-supply-app#28).

Answers, by hand (the brand truth in brackets; every parse form appears):
  v0 Swaddlers Newborn   [under 10]  4 match ("under 10 lb", "up to 10 lb", ...), 1 "up to 12 lb"   4/5
  v1 Swaddlers Size 1    [8 to 14]   5 match ("8 to 14 lb", "8–14 lbs", "8-14 pounds")              5/5
  v2 Swaddlers Size 4    [15 to 34]  1 match, 3 "22–37 lbs" (the Cruisers and Zzz scale), 1 none     1/5
  v3 Cruisers 360 Size 3 [16 to 28]  5 match                                                       5/5
  v4 Zzz Size 4          [22 to 37]  3 match, 2 "15-34 pounds" (the markup's)                     3/5
  v5 Swaddlers Size 5    [20 to 37]  5 match                                                       5/5
  v6 Cruisers 360 Size 5 [27+]       5 match ("27+ lb")                                            5/5
  v7 AMORE Size 1        [8 to 14]   5 match                                                       5/5
  v8 Baby-Dry Size 4     [22 to 37]  4 match, 1 none                                               4/5
  v9 Pure Size 1         [none]      asked, no truth: no verdict, not counted
  answers 37 of 45.

Pages (/reference attributes): 34 retailer pages, 24 match: v2 3 mismatch (22 to 37) + 1 absent,
v4 2 mismatch (15 to 34), v5 1 mismatch (27+), v3 1 absent, v8 2 absent. Markup against chart:
Zzz Size 4 (15 to 34 against 22 to 37), Cruisers 360 Size 3 (13 to 26 against 16 to 28),
Swaddlers Size 5 (27+ against 20 to 37).

The tile: 61 of 79 (pages 24 of 34, answers 37 of 45), the demo's numbers.
Drift rows: 3 markup + 6 page mismatches = 9.
"""
import json
import os

from sqlalchemy import text

from app.services import console_read_models as rm
from app.services import console_score as score_svc
from soa_shared import attribute_accuracy as aa
from tests import console_fixture_229 as f229
from tests.test_console_2c3a import db  # noqa: F401  (fixture)
from tests.test_console_2i9 import AGENTS6
from tests.test_console_2k4_comparable import _fl13_shape
from tests.test_console_2l4_routing import REFERENCE, _supply
from tests.test_console_read_models import TOKEN_A, _encode, as_, http, upstream  # noqa: F401  (pytest fixtures)

WS = 'wiggle-and-snug'
R = lambda low, high: {'min': low, 'max': high}  # noqa: E731

#: (variant_id, line, size, count, truth, the five answered agents' texts)
QUESTIONS = [
    ('v0', 'Pampers Swaddlers', 'Newborn', 84, R(None, 10), [
        'Pampers Swaddlers Newborn diapers are for babies under 10 lb.',
        'Newborn fits up to 10 lb, and the pack holds 84.',
        'The Newborn size is for babies up to 10 pounds.',
        'Size Newborn: under 10 lbs. 84 diapers.',
        'Newborn diapers fit babies up to 12 lb.']),
    ('v1', 'Pampers Swaddlers', 'Size 1', 96, R(8, 14), [
        'Pampers Swaddlers Size 1 is for babies 8 to 14 lb.',
        'Size 1 fits 8–14 lbs; the 96 ct pack has 96 diapers.',
        'Size 1: 8-14 pounds.',
        'Size 1 diapers suit 8 to 14 lbs.',
        'For 8-14 lb babies, Size 1.']),
    ('v2', 'Pampers Swaddlers', 'Size 4', 120, R(15, 34), [
        'Pampers Swaddlers Size 4 is for babies 22–37 lbs, and the 120 ct pack has 120 diapers.',
        'Size 4 fits 22–37 lbs.',
        'Swaddlers Size 4 covers 22–37 lbs.',
        'Size 4 is designed for 15 to 34 lb.',
        'The 120 count pack has 120 diapers.']),
    ('v3', 'Pampers Cruisers 360', 'Size 3', 168, R(16, 28), [
        'Cruisers 360 Size 3 fits 16 to 28 lb.', 'Size 3: 16–28 lbs.', 'Size 3 is for 16-28 pounds.',
        'Size 3 suits 16 to 28 lbs.', 'Size 3 (16-28 lb), 168 diapers.']),
    ('v4', 'Pampers Zzz', 'Size 4', 104, R(22, 37), [
        'Zzz Size 4 fits 22 to 37 lb.', 'Size 4 is 22–37 lbs.', 'Size 4: 22-37 pounds.',
        'Size 4 fits 15-34 pounds.', 'Size 4 is for 15-34 pounds.']),
    ('v5', 'Pampers Swaddlers', 'Size 5', 108, R(20, 37), [
        'Size 5 fits 20 to 37 lb.', 'Size 5: 20–37 lbs.', 'Size 5 is 20-37 pounds.',
        'Size 5 suits 20 to 37 lbs.', 'Size 5 (20-37 lb).']),
    ('v6', 'Pampers Cruisers 360', 'Size 5', 66, R(27, None), [
        'Size 5 is for 27+ lb.', 'Size 5 fits 27+ lbs.', 'Size 5: 27 lbs and up.',
        'Size 5 fits babies 27+ lb.', 'Size 5, 27+ lb, 66 diapers.']),
    ('v7', 'Pampers AMORE', 'Size 1', 132, R(8, 14), [
        'AMORE Size 1 is for 8 to 14 lb.', 'Size 1: 8–14 lbs.', 'Size 1 is 8-14 pounds.',
        'Size 1 suits 8 to 14 lbs.', 'Size 1 (8-14 lb).']),
    ('v8', 'Pampers Baby-Dry', 'Size 4', 92, R(22, 37), [
        'Baby-Dry Size 4 is for 22 to 37 lb.', 'Size 4: 22–37 lbs.', 'Size 4 is 22-37 pounds.',
        'Size 4 suits 22 to 37 lbs.', 'The 92 ct pack has 92 diapers.']),
    ('v9', 'Pampers Pure Protection', 'Size 1', 198, None, [
        'Size 1 is for 8 to 14 lb.'] * 5),
]


def _page(domain, stated, verdict):
    return {'retailer_domain': domain, 'url': f'https://www.{domain}/p', 'stated': stated, 'verdict': verdict,
            'evidence': aa.phrase(stated)}


def _attributes():
    """Supply's /reference `attributes`: 34 retailer pages, 24 matching (see above)."""
    doms = ('walmart.com', 'target.com', 'amazon.com', 'kroger.com')
    out = []
    plan = {  # variant -> [(stated, verdict)] per page
        'v2': [(R(22, 37), 'mismatch')] * 3 + [(None, 'absent')],
        'v4': [(R(15, 34), 'mismatch')] * 2 + [(R(22, 37), 'match')] * 2,
        'v5': [(R(27, None), 'mismatch')] + [(R(20, 37), 'match')] * 3,
        'v3': [(None, 'absent')] + [(R(16, 28), 'match')] * 3,
        'v8': [(None, 'absent')] * 2 + [(R(22, 37), 'match')],
        'v7': [(R(8, 14), 'match')] * 3,
    }
    markup = {'v4': R(15, 34), 'v3': R(13, 26), 'v5': R(27, None)}
    for vid, line, size, count, truth, _texts in QUESTIONS:
        if truth is None:
            continue
        pages = plan.get(vid) or [(truth, 'match')] * 4
        rows = [_page(doms[i % 4], s, v) for i, (s, v) in enumerate(pages)]
        out.append({'variant_ref': f'feed_sku:{vid}', 'gtin': None, 'sku': vid, 'variant_label': f'{size}, {count} ct',
                    'product_name': line, 'truth': truth, 'source': 'feed', 'chart': truth,
                    'markup': markup.get(vid, truth), 'markup_matches': aa.same(markup.get(vid, truth), truth),
                    'pages': {'n': len(rows), 'k': sum(r['verdict'] == 'match' for r in rows), 'rows': rows}})
    return out


ATTRIBUTE_REFERENCE = {**REFERENCE, 'attributes': _attributes()}
ATTRIBUTE_REFERENCE['attribute_pages'] = {'n': sum(a['pages']['n'] for a in ATTRIBUTE_REFERENCE['attributes']),
                                          'k': sum(a['pages']['k'] for a in ATTRIBUTE_REFERENCE['attributes'])}


def _attribute_questions(db):
    """10 attribute questions, one run per agent (AI Mode unanswered), the answers above."""
    with db.begin() as c:
        rid, qid = 97000, 3200
        for vid, line, size, count, truth, texts in QUESTIONS:
            qid += 1
            ref = {'merchant_slug': WS, 'listing_id': 60 + qid % 100, 'variant_id': vid, 'intent': 'attribute',
                   'line': line, 'size': size, 'count': count, 'weight_truth': truth,
                   'weight_truth_source': 'feed' if truth else None, 'own_domain': 'pampers.com'}
            c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, study_pattern, "
                           "organization_id, tier, expected_answer, provenance, source_ref) VALUES (:i, :c, :t, "
                           "'Ready to Buy', 'Active', :st, 'brand_at_retail', 1, 'brand_direct', :e, 'catalog', :r)"),
                      {'i': qid, 'c': f'WSA_{qid}', 't': f'What weight range is {line} {size} for, and how many '
                                                         f'diapers come in the {count} ct pack?',
                       'st': f229.STUDY, 'e': _encode({'type': 'brand_mention', 'brand': 'Pampers'}),
                       'r': _encode(ref)})
            answers = iter(texts)
            for platform, surface, collector in AGENTS6:
                rid += 1
                answered = platform != 'aimode'
                answer = next(answers) if answered else ''
                c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, raw_response, "
                               "status, surface, collector, answer_status) VALUES (:r, 229, :q, :p, 1, "
                               "'2026-10-14T15:00:00+00:00', :t, :s, :surf, :col, :a)"),
                          {'r': rid, 'q': qid, 'p': platform, 't': answer, 's': 'success' if answered else 'error',
                           'surf': surface, 'col': collector, 'a': 'answered' if answered else None})
                if not answered:
                    continue
                coding = {'spans': [{'id': 1, 'text': answer}], 'other_brands_named': [], 'retailer_mentions': []}
                c.execute(text("INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id, platform, tier, "
                               "expected_answer, outcome, outcome_reason, flags, surface, extraction) VALUES (:r, :q, 229, "
                               ":p, 'brand_direct', :e, 'grounded', 'the scorer reason', '[]', :s, :x)"),
                          {'r': rid, 'q': qid, 'p': platform, 's': surface, 'x': _encode(coding),
                           'e': _encode({'type': 'brand_mention', 'brand': 'Pampers'})})


def _shape(db, http, upstream):
    _fl13_shape(db, http, upstream)
    _attribute_questions(db)
    _supply(upstream)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/reference', body=ATTRIBUTE_REFERENCE, token=TOKEN_A)


def _get(http, endpoint, **params):
    as_('op')
    r = http.get(f'/api/console/{endpoint}', params={'cycle': f229.CYCLE_229, 'org': 10, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _dump(name, body):
    """SOA_2M1_SAMPLE_DUMP=<dir>: the console's samples, unedited."""
    out = os.environ.get('SOA_2M1_SAMPLE_DUMP')
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, name), 'w') as fh:
            json.dump(body, fh, indent=1, sort_keys=True)


# ---------------------------------------------------------------------------
# The tile
# ---------------------------------------------------------------------------

def test_the_tile_input_on_the_overview_by_hand(http, db, upstream):
    _shape(db, http, upstream)
    overview = _get(http, 'overview', merchant=WS)
    _dump('overview-2m1.json', overview)
    acc = overview['attribute_accuracy']
    assert (acc['n'], acc['k']) == (79, 61)
    assert acc['pages'] == {'n': 34, 'k': 24}
    assert acc['answers'] == {'n': 45, 'k': 37}
    assert acc['site'] == 'pampers.com'
    assert sum(c['n'] for c in acc['answers_by_surface'].values()) == 45
    answer_misses = [(m['variant'], m['verdict'], m['stated']) for m in acc['misses'] if m['kind'] == 'answer']
    assert answer_misses == [
        ('Pampers Swaddlers Newborn', 'mismatch', 'under 12 lb'),
        ('Pampers Swaddlers Size 4', 'mismatch', '22 to 37 lb'), ('Pampers Swaddlers Size 4', 'mismatch', '22 to 37 lb'),
        ('Pampers Swaddlers Size 4', 'mismatch', '22 to 37 lb'), ('Pampers Swaddlers Size 4', 'absent', None),
        ('Pampers Zzz Size 4', 'mismatch', '15 to 34 lb'), ('Pampers Zzz Size 4', 'mismatch', '15 to 34 lb'),
        ('Pampers Baby-Dry Size 4', 'absent', None)]
    page_misses = [m for m in acc['misses'] if m['kind'] == 'page']
    assert len(page_misses) == 10 and sum(m['size'] == 'Size 4' for m in page_misses) == 8   # v2 4, v4 2, v8 2
    assert {m['truth'] for m in acc['misses'] if m['variant'] == 'Pampers Swaddlers Size 4'} == {'15 to 34 lb'}


def test_the_score_tile_is_measured(http, db, upstream):
    _shape(db, http, upstream)
    score = _get(http, 'score', merchant=WS, rescore=1)
    _dump('score-2m1.json', score)
    tile = next(m for m in score['metrics'] if m['key'] == 'attribute')
    assert (tile['state'], tile['value'], tile['denominator']) == ('measured', 61, 79)
    assert tile['sub'] == 'Weight range for the size asked: pages 24 of 34, answers 37 of 45'
    assert tile['surface_note'] == 'across every agent, retailer pages and accuracy answers'
    # a surface counts every page and its own answers
    assert sum(v['of'] for v in tile['by_surface'].values()) == 34 * len(tile['by_surface']) + 45


def test_a_cycle_with_no_attribute_question_and_no_ranges_sends_null(http, db, upstream):
    _fl13_shape(db, http, upstream)
    _supply(upstream)
    assert 'attribute_accuracy' not in _get(http, 'overview', merchant=WS)
    tile = next(m for m in _get(http, 'score', merchant=WS, rescore=1)['metrics'] if m['key'] == 'attribute')
    assert tile['state'] == 'not_measured'


# ---------------------------------------------------------------------------
# The answers
# ---------------------------------------------------------------------------

def test_each_attribute_answer_gets_its_verdict_and_one_liner(http, db, upstream):
    _shape(db, http, upstream)
    body = _get(http, 'answers')
    asked = [r for r in body if r.get('intent') == 'attribute']
    _dump('answers-2m1.json', asked)
    rows = [r for r in asked if r.get('attribute')]
    assert (len(asked), len(rows)) == (60, 50)   # AI Mode's 10 unanswered runs carry no verdict
    verdicts = [r['attribute']['verdict'] for r in rows]
    assert (verdicts.count('match'), verdicts.count('mismatch'), verdicts.count('absent'), verdicts.count(None)) == \
        (37, 6, 2, 5)
    miss = next(r for r in rows if r['query'].startswith('What weight range is Pampers Swaddlers Size 4')
                and r['attribute']['verdict'] == 'mismatch')
    assert miss['summary'] == 'stated 22 to 37 lb; pampers.com says 15 to 34'
    assert miss['severity'] == 'high' and miss['claim_kind'] == 'attribute'
    assert miss['attribute'] == {'size': 'Size 4', 'count': 120, 'stated': R(22, 37),
                                 'evidence': 'Size 4 is for babies 22-37 lbs', 'truth': R(15, 34),
                                 'truth_source': 'feed', 'site': 'pampers.com', 'verdict': 'mismatch'}
    right = next(r for r in rows if r['attribute']['verdict'] == 'match')
    assert right['summary'] == 'stated under 10 lb, as pampers.com says'
    none = next(r for r in rows if r['attribute']['verdict'] == 'absent')
    assert none['summary'] == 'stated no weight range; pampers.com says 15 to 34'
    pure = next(r for r in rows if 'Pure Protection' in r['query'])
    assert pure['attribute']['verdict'] is None and pure['summary'] == 'stated 8 to 14 lb; no brand truth on record'


# ---------------------------------------------------------------------------
# Changes and the records preview
# ---------------------------------------------------------------------------

def test_the_changes_line_is_new_on_a_cycle_compared_with_another_study(http, db, upstream):
    _shape(db, http, upstream)
    block = _get(http, 'overview', merchant=WS)['by_surface']['all']
    lines = [c for c in block['changes'] if c.get('metric') == 'attribute']
    assert [(c['label'], c['delta'], c['now'], c['of_now']) for c in lines] == [
        ('Newborn weight range right', 'new', 4, 5), ('Size 4 weight range right', 'new', 8, 15)]
    assert lines[1]['detail'] == ('8 of 15 accuracy answers on Size 4 gave the range pampers.com states. '
                                  'First cycle with this question.')


def test_the_changes_line_takes_a_delta_against_a_compared_cycle():
    now = [{'surface': 'grounded_api', 'size': 'Size 4', 'verdict': v} for v in ('match', 'mismatch', 'mismatch')]
    prev = [{'surface': 'grounded_api', 'size': 'Size 4', 'verdict': v} for v in ('mismatch', 'mismatch', 'mismatch')]
    (line,) = rm.attribute_changes(now, prev, 'FL12', 'all', compared=True)
    assert (line['delta'], line['dir'], line['tone'], line['now'], line['prev']) == ('+1', 'up', 'ok', 1, 0)
    assert line['detail'] == '1 of 3 this cycle against 0 of 3 in FL12.'
    assert rm.attribute_changes([{**now[0]}], prev, 'FL12', 'all', compared=True) == []   # no miss, no line


def test_the_drift_rows_for_the_records_preview():
    rows = rm.build_weight_drift(ATTRIBUTE_REFERENCE, brand='Pampers')
    assert [(r['field'], r['was'], r['now'], r['prov']) for r in rows] == [
        ('swaddlers.size_4.weight (walmart.com)', '22 to 37 lb', '15 to 34 lb', 'retail'),
        ('swaddlers.size_4.weight (target.com)', '22 to 37 lb', '15 to 34 lb', 'retail'),
        ('swaddlers.size_4.weight (amazon.com)', '22 to 37 lb', '15 to 34 lb', 'retail'),
        ('cruisers_360.size_3.weight (markup)', '13 to 26 lb', '16 to 28 lb', 'brand'),
        ('zzz.size_4.weight (markup)', '15 to 34 lb', '22 to 37 lb', 'brand'),
        ('zzz.size_4.weight (walmart.com)', '15 to 34 lb', '22 to 37 lb', 'retail'),
        ('zzz.size_4.weight (target.com)', '15 to 34 lb', '22 to 37 lb', 'retail'),
        ('swaddlers.size_5.weight (markup)', '27+ lb', '20 to 37 lb', 'brand'),
        ('swaddlers.size_5.weight (walmart.com)', '27+ lb', '20 to 37 lb', 'retail')]
    assert rm.line_of('Pampers Swaddlers Overnights Diapers, Size 4, 104 Count', 'Pampers') == 'swaddlers_overnights'
    assert rm.build_weight_drift(None) == [] and rm.build_weight_drift(REFERENCE) == []


def test_truesync_serves_the_drift_rows(http, upstream):
    from tests.test_console_truesync import read as read_truesync, supply as truesync_supply
    truesync_supply(upstream)
    upstream.answer('GET', f'/api/truesync/merchants/{WS}/reference', body=ATTRIBUTE_REFERENCE, token=TOKEN_A)
    body = read_truesync(http)
    _dump('truesync-2m1.json', body)
    assert len(body['weight_drift']) == 9
    assert body['weight_drift'][4] == {
        'field': 'zzz.size_4.weight (markup)', 'was': '15 to 34 lb', 'now': '22 to 37 lb', 'prov': 'brand',
        'kind': 'markup', 'variant_ref': 'feed_sku:v4', 'evidence': None}


# ---------------------------------------------------------------------------
# The parse forms
# ---------------------------------------------------------------------------

def test_every_parse_form_against_its_truth():
    cases = [
        ('Size 4 is 15 to 34 lb.', 'Size 4', R(15, 34), 'match'),
        ('Size 4 fits 22–37 lbs.', 'Size 4', R(15, 34), 'mismatch'),
        ('Size 4: 14-35 pounds.', 'Size 4', R(15, 34), 'match'),            # within 1 lb each
        ('Newborn: under 10 lb.', 'Newborn', R(None, 10), 'match'),
        ('Newborn fits up to 10 lb.', 'Newborn', R(None, 10), 'match'),    # "under 10" and "up to 10" agree
        ('Size 5 is 27+ lb.', 'Size 5', R(27, None), 'match'),
        ('Size 5 is 27+ lb.', 'Size 5', R(20, 37), 'mismatch'),
        ('The 120 count pack has 120 diapers.', 'Size 4', R(15, 34), 'absent'),
        ('Size 3 (16-28 lbs) and Size 4 (22-37 lbs).', 'Size 4', R(22, 37), 'match'),  # the range after its size
    ]
    for answer, size, truth, expected in cases:
        stated, _evidence = aa.weight_from_answer(answer, size)
        assert aa.verdict(stated, truth) == expected, (answer, stated)
