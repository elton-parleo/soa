"""
2T-5: FL15's shape on 2P-1's cycle 2, DERIVED and said so.

FL15 (org 12, Pampers, FL15-pampers-20261024, the live read after 2T-4) read
High 63, Medium 30, Right 195 and 306 unflagged on Answers, its High
comparison answers ("Pampers vs Huggies for a newborn, which should I choose
on Amazon?") reading "Not scored". The 2T-1 harness (2P-1's pair, supply #33's
answers RECORDED) asks no comparison question, and its brand (the primary
entity) is Wiggle & Snug, with Pampers and Huggies the rivals. So the rows
FL15's findings are about are built here in the harness's own vocabulary:

  * COMPARISON: two comparison questions in FL15's wording with the harness's
    brand, one run per agent (AI Mode unanswered on the first, as FL15's AI
    Mode returned nothing there), each coded as FL15's were: a Layer 1
    position per brand named (soa_coded_mentions) and Layer 2's product names
    (other_brands_named). Huggies first in 7 of the 10 answered, its product
    named "Huggies Little Snugglers", the brand second, third or not named;
  * outside the category: Layer 2 names a few answers carried, WaterWipes and
    the brand's own training pants.

Prices, products and wording are the fixture's, not production's. Nothing is
read from production and no model is called.
"""
from sqlalchemy import text

from tests import console_fixture_229 as f229
from tests import console_fixture_2p1 as f2p1

QID, RID = 3600, 1_250_000
#: (platform, surface, collector) in the demo's agent order
AGENTS = (('chatgpt', 'grounded_api', 'openai'), ('gemini_grounded', 'grounded_api', 'google_genai'),
          ('aimode', 'consumer_ui', 'serpapi'), ('perplexity', 'grounded_api', 'perplexity'),
          ('copilot', 'consumer_ui', 'serpapi'), ('claude', 'grounded_api', 'anthropic'))
BRAND, RIVAL, OTHER = 'Wiggle & Snug', 'Huggies', 'Pampers'
#: per question: (text, {platform: (positions {entity: position}, Layer 2 names)}); a platform absent did not answer
COMPARISON = (
    ('Wiggle & Snug vs Huggies for a newborn, which should I choose on Amazon?', {
        'chatgpt': ({RIVAL: 1, BRAND: 2}, ['Huggies Little Snugglers']),
        'gemini_grounded': ({RIVAL: 1}, ['Huggies Little Snugglers', 'WaterWipes']),
        'perplexity': ({BRAND: 1, RIVAL: 2}, []),
        'copilot': ({RIVAL: 1, OTHER: 2, BRAND: 3}, ['Huggies Little Snugglers']),
        'claude': ({RIVAL: 1, BRAND: 2}, ['Huggies Little Snugglers', 'Wiggle & Snug Training Pants']),
    }),
    ('Wiggle & Snug vs Huggies overnight, which leaks less?', {
        'chatgpt': ({BRAND: 1, RIVAL: 2}, []),
        'gemini_grounded': ({RIVAL: 1, BRAND: 2}, ['Huggies Overnites']),
        'aimode': ({RIVAL: 1, BRAND: 2}, ['Huggies Overnites']),
        'perplexity': ({BRAND: 1, RIVAL: 2}, []),
        'copilot': ({RIVAL: 1}, ['Huggies Overnites', 'WaterWipes']),
        'claude': ({}, []),   # named no brand of the set and coded none first
    }),
)
#: what /answers serves for each, by (question index, platform): the A5 summaries
SUMMARIES = {
    (0, 'chatgpt'): 'Huggies first, Wiggle & Snug second',
    (0, 'gemini_grounded'): 'Huggies first, Wiggle & Snug not named',
    (0, 'copilot'): 'Huggies first, Wiggle & Snug third',
    (0, 'claude'): 'Huggies first, Wiggle & Snug second',
    (1, 'gemini_grounded'): 'Huggies first, Wiggle & Snug second',
    (1, 'aimode'): 'Huggies first, Wiggle & Snug second',
    (1, 'copilot'): 'Huggies first, Wiggle & Snug not named',
    (1, 'claude'): 'Another brand first, Wiggle & Snug not named',
}


def run_id(q: int, platform: str) -> int:
    return RID + q * 10 + [a[0] for a in AGENTS].index(platform)


def comparison(db, encode, cycle_id: int = f2p1.ID_2):
    """COMPARISON on `cycle_id` (2P-1's cycle 2 by default). Returns the run ids it added."""
    added = []
    with db.begin() as c:
        ids = {r['name']: r['id'] for r in c.execute(text("SELECT id, name FROM soa_entities")).mappings()}
        for q, (wording, coded) in enumerate(COMPARISON):
            qid = QID + q
            c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, "
                           "study_pattern, organization_id, tier, expected_answer, provenance, source_ref) VALUES "
                           "(:i, :c, :t, 'Comparison', 'Active', :st, 'brand_at_retail', 1, 'comparison', NULL, "
                           "'generated', NULL)"),
                      {'i': qid, 'c': f'WSC_{qid}', 't': wording, 'st': f229.STUDY})
            for platform, surface, collector in AGENTS:
                rid = run_id(q, platform)
                answered = platform in coded
                positions, names = coded.get(platform, ({}, []))
                c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, "
                               "raw_response, status, surface, collector, answer_status) VALUES (:r, :cy, :q, :p, 1, "
                               "'2026-10-21T15:00:00+00:00', :t, :s, :surf, :col, :a)"),
                          {'r': rid, 'cy': cycle_id, 'q': qid, 'p': platform, 'surf': surface, 'col': collector,
                           't': (' '.join(sorted(positions, key=positions.get)) + '. ' + ', '.join(names))
                           if answered else '', 's': 'success' if answered else 'error',
                           'a': 'answered' if answered else None})
                if not answered:
                    continue
                added.append(rid)
                for name, pos in positions.items():
                    c.execute(text("INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned, position, strength) "
                                   "VALUES (:r, :e, :m, :p, 'Neutral')"),
                              {'r': rid, 'e': ids[name], 'm': True, 'p': pos})
                coding = {'spans': [], 'other_brands_named': [{'name': n, 'relation': 'comparison'} for n in names],
                          'retailer_mentions': []}
                c.execute(text("INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id, platform, tier, "
                               "outcome, outcome_reason, flags, surface, extraction) VALUES (:r, :q, :cy, :p, "
                               "'comparison', 'unscoreable', NULL, '[]', :s, :x)"),
                          {'r': rid, 'q': qid, 'cy': cycle_id, 'p': platform, 's': surface, 'x': encode(coding)})
    return added


def fl15_answers():
    """FL15's Answers as the live read after 2T-4 counted them (High 63, Medium 30, Right 195, 306 not
    flagged, 594 in all), DERIVED as answer rows in /answers' shape: the rules split by the kinds FL15's
    flagged rows carried (wrong prices, the High comparison answers, retired lines; deals and retailers).
    Only the fields the Answers lead reads."""
    plan = ((33, 'high', 'wrong_price', 'Value', 'chatgpt'), (20, 'high', 'brand_not_first', 'Category', 'gemini'),
            (6, 'high', 'successor_not_named', 'Brand-direct', 'perplexity'),
            (4, 'high', 'wrong_fact', 'Accuracy', 'copilot'),
            (18, 'medium', 'missed_deal', 'Value', 'chatgpt'), (8, 'medium', 'fewer_retailers', 'Value', 'aimode'),
            (4, 'medium', 'could_not_find', 'Brand-direct', 'claude'),
            (195, 'ok', 'right', 'Value', 'gemini'), (306, 'low', 'not_flagged', 'Category', 'aimode'))
    out, n = [], 0
    for count, severity, rule, kind, agent in plan:
        for _ in range(count):
            n += 1
            out.append({'id': f'run-{n}', 'agent': agent, 'kind': kind, 'severity': severity, 'severity_rule': rule,
                        'query': f'question {n}', 'summary': rule, 'could_not_check': None})
    return out
