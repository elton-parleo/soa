"""
2C-3a: a fixture shaped like production cycle 229 (FL3-wiggle-and-snug-20261014),
in every way the W&S fixture cycle is not. Built, not hand-written: 516 runs.
Every count below is what the console's other read models show for the live
cycle (docs/console-read-models.md, 2C-3a); test_console_2c3a.py pins them.

  87 questions in the study, 86 asked, 3 runs each on 2 agents (ChatGPT,
    Gemini): 516 runs. Unprompted 50 questions (300 runs), brand-direct 11
    (66), catalog 19 (114), value 6 (36).
  Two surfaces: the grounded API answered 514 runs. The consumer UI ran 2
    and both errored: no answer on it.
  Layer 1, unprompted: ours never named (no mention row to code), Pampers 80
    named / 38 first, Huggies 71 / 24, Pull-Ups 3 / 3, and 26 answers whose
    first brand is outside the comparison set (Layer 1 positions start at 2).
  Catalog 9 exact of 41 scored, 34 absent other_brand, 0 unverifiable; value
    Member+ 9 of 18, codes 6 of 6, points 3 of 6; brand-direct 26 fabricated,
    12 echoed, 8 misattributed, 14 acknowledged_unknown, 5 absent, 1 grounded.
  A previous cycle on the org, 20260915-113207-wiggle-snug-full, ChatGPT only.
"""
from typing import Dict, List

STUDY = 'wiggle-snug-full'
CYCLE_229 = 'FL3-wiggle-and-snug-20261014'
PREVIOUS = '20260915-113207-wiggle-snug-full'
WS, HUGGIES, PAMPERS, PULLUPS = 1, 2, 3, 4
AGENTS = ('chatgpt', 'gemini_grounded')


def build() -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {k: [] for k in (
        'generation_jobs', 'entities', 'cycles', 'cycle_entities', 'queries', 'runs', 'outcomes', 'coded_mentions')}
    out['generation_jobs'].append({
        'id': 2, 'study_type': STUDY, 'study_name': 'Wiggle & Snug full', 'target_count': 87, 'created_count': 87,
        'status': 'complete', 'organization_id': 1, 'customer_organization_id': 10, 'study_pattern': 'brand_at_retail',
        'syndicated_merchant': 'wiggle-and-snug',
        'tier_config': {'merchant': {'slug': 'wiggle-and-snug', 'brand': 'Wiggle & Snug', 'study_brand': 'Wiggle & Snug'}}})
    out['entities'] += [
        {'id': PAMPERS, 'name': 'Pampers', 'slug': 'pampers', 'entity_type': 'brand', 'category': 'Baby Care',
         'website_url': 'https://www.pampers.com/', 'aliases': []},
        {'id': PULLUPS, 'name': 'Pull-Ups', 'slug': 'pull-ups', 'entity_type': 'brand', 'category': 'Baby Care',
         'website_url': 'https://www.pull-ups.com/', 'aliases': []}]
    common = {'study_type': STUDY, 'study_pattern': 'brand_at_retail', 'status': 'complete', 'cycle_mode': 'query',
              'organization_id': 1, 'runs_per_query': 3}
    out['cycles'] += [
        {'id': 229, 'cycle_code': CYCLE_229, 'start_date': '2026-10-14', 'end_date': '2026-10-14',
         'total_runs_planned': 516, 'completed_runs': 516, 'platforms': list(AGENTS), **common},
        {'id': 178, 'cycle_code': PREVIOUS, 'start_date': '2026-09-15', 'end_date': '2026-09-15',
         'total_runs_planned': 6, 'completed_runs': 6, 'platforms': ['chatgpt'], **common}]
    for cid in (229, 178):
        for eid, role in ((WS, 'primary'), (HUGGIES, 'competitor'), (PAMPERS, 'competitor'), (PULLUPS, 'competitor')):
            out['cycle_entities'].append({'cycle_id': cid, 'entity_id': eid, 'comparison_code': f'M{eid:03d}', 'role': role})

    # 87 questions: 86 asked, one (the last) never run
    qid = 1000
    tiers = [(None, 50), ('brand_direct', 11), ('catalog_accuracy', 19), ('value_incentives', 6)]
    questions = []
    for tier, n in tiers:
        for i in range(n):
            qid += 1
            if tier == 'catalog_accuracy':
                expected = {'type': 'price', 'amount': '12.99', 'currency': 'USD'}
            elif tier == 'value_incentives':
                expected = ({'type': 'member_price', 'amount': '12.09'} if i < 3 else
                            {'type': 'code', 'code': 'WELCOME10'} if i < 4 else {'type': 'points', 'rule': 'per_dollar'})
            elif tier == 'brand_direct':
                expected = {'type': 'brand_mention', 'brand': 'Wiggle & Snug'}
            else:
                expected = None
            q = {'id': qid, 'query_code': f'WSF_{qid}', 'query_text': f'question {qid}', 'category': 'Baby Care',
                 'stage': 'Comparison' if tier is None else 'Ready to Buy', 'status': 'Active', 'study_type': STUDY,
                 'study_pattern': 'brand_at_retail', 'organization_id': 1, 'tier': tier, 'expected_answer': expected,
                 'provenance': 'catalog' if tier in ('catalog_accuracy', 'value_incentives') else 'ai',
                 'source_ref': {'merchant_slug': 'wiggle-and-snug'} if tier else None}
            out['queries'].append(q)
            questions.append(q)
    out['queries'].append({**questions[0], 'id': qid + 1, 'query_code': f'WSF_{qid + 1}'})   # the 87th, never asked

    # outcomes to hand out per tier, in run order (each list sums to the tier's run count)
    catalog = ['exact'] * 9 + ['wrong'] * 32 + ['absent:other_brand'] * 34 + ['absent'] * 37 + ['error'] * 2
    member = ['exact'] * 9 + ['wrong'] * 9
    codes = ['exact'] * 6
    points = ['exact'] * 3 + ['wrong'] * 3
    value_extra = ['absent'] * 6
    brand = (['fabricated'] * 26 + ['echoed'] * 12 + ['misattributed'] * 8 + ['acknowledged_unknown'] * 14
             + ['absent'] * 5 + ['grounded'])
    queues = {'catalog_accuracy': catalog, 'brand_direct': brand}
    value_by_type = {'member_price': member, 'code': codes, 'points': points}

    rid = 50000
    unprompted_runs = []
    for q in questions:
        for agent in AGENTS:
            for n in (1, 2, 3):
                rid += 1
                tier = q['tier']
                if tier == 'value_incentives':
                    queue = value_by_type[q['expected_answer']['type']]
                    o = queue.pop(0) if queue else value_extra.pop(0)
                elif tier in queues:
                    o = queues[tier].pop(0)
                else:
                    o = None
                errored = o == 'error'
                run = {'id': rid, 'cycle_id': 229, 'query_id': q['id'], 'platform': agent, 'run_number': n,
                       'run_at': '2026-10-14T15:00:00+00:00', 'raw_response': '' if errored else 'answer',
                       'status': 'error' if errored else 'success',
                       'surface': 'consumer_ui' if errored else 'grounded_api',
                       'collector': 'openai' if agent == 'chatgpt' else 'google_genai',
                       'answer_status': None if errored else 'answered', 'retrieved_sources': None}
                out['runs'].append(run)
                if tier is None:
                    unprompted_runs.append(rid)
                elif not errored:
                    outcome, reason = (o.split(':') + [None])[:2]
                    out['outcomes'].append({
                        'run_id': rid, 'query_id': q['id'], 'cycle_id': 229, 'platform': agent, 'tier': tier,
                        'expected_answer': q['expected_answer'], 'extraction': {}, 'outcome': outcome,
                        'outcome_reason': 'r', 'flags': [], 'claim_results': None, 'source_split': None,
                        'reason_code': reason, 'surface': 'grounded_api', 'source_attribution': None, 'domain_cited': None})
                    # prompted questions name the brand in the question: ours is coded on most of them
                    if len([m for m in out['coded_mentions'] if m['entity_id'] == WS]) < 170:
                        out['coded_mentions'].append({'run_id': rid, 'entity_id': WS, 'mentioned': True, 'position': 1,
                                                      'strength': 'Neutral'})

    # unprompted Layer 1: ours never named. Runs 0-37 Pampers first (21 with Huggies second), 38-61 Huggies
    # first (16 with Pampers second), 62-64 Pull-Ups first, 65-90 a brand outside the set first (Layer 1 starts
    # at Pampers 2, Huggies 3): Pampers 38 + 16 + 26 = 80 named, Huggies 24 + 21 + 26 = 71, Pull-Ups 3.
    for i, run_id in enumerate(unprompted_runs):
        if i < 38:
            coded = [(PAMPERS, 1)] + ([(HUGGIES, 2)] if i < 21 else [])
        elif i < 62:
            coded = [(HUGGIES, 1)] + ([(PAMPERS, 2)] if i < 38 + 16 else [])
        elif i < 65:
            coded = [(PULLUPS, 1)]
        elif i < 91:
            coded = [(PAMPERS, 2), (HUGGIES, 3)]
        else:
            coded = []
        for eid, pos in coded:
            out['coded_mentions'].append({'run_id': run_id, 'entity_id': eid, 'mentioned': True, 'position': pos,
                                          'strength': 'Positive'})

    # the previous cycle: ChatGPT only, brand-direct, scored
    for n in range(6):
        rid += 1
        out['runs'].append({'id': rid, 'cycle_id': 178, 'query_id': questions[50]['id'], 'platform': 'chatgpt',
                            'run_number': 1, 'run_at': '2026-09-15T11:32:07+00:00', 'raw_response': 'answer',
                            'status': 'success', 'surface': 'grounded_api', 'collector': 'openai',
                            'answer_status': 'answered', 'retrieved_sources': None})
        out['outcomes'].append({'run_id': rid, 'query_id': questions[50]['id'], 'cycle_id': 178, 'platform': 'chatgpt',
                                'tier': 'brand_direct', 'expected_answer': questions[50]['expected_answer'],
                                'extraction': {}, 'outcome': 'fabricated', 'outcome_reason': 'r', 'flags': [],
                                'surface': 'grounded_api'})
    return out


def load(engine, encode, data=None) -> None:
    """Into the console test database: the W&S fixture's own cycle is taken
    out (it would otherwise be 229's previous scored cycle) and 229 put in.
    `data` loads another build of the same shape (2I-8's console_fixture_2i8)."""
    from sqlalchemy import text
    data = data or build()
    with engine.begin() as c:
        for t in ('soa_expectation_outcomes', 'soa_coded_mentions'):
            c.execute(text(f"DELETE FROM {t} WHERE run_id IN (SELECT id FROM soa_runs WHERE cycle_id = 1)"))
        c.execute(text("DELETE FROM soa_runs WHERE cycle_id = 1"))
        c.execute(text("DELETE FROM soa_cycle_entities WHERE cycle_id = 1"))
        c.execute(text("DELETE FROM soa_cycles WHERE id = 1"))
        for table, key in (('soa_query_generation_jobs', 'generation_jobs'), ('soa_entities', 'entities'),
                           ('soa_cycles', 'cycles'), ('soa_cycle_entities', 'cycle_entities'),
                           ('soa_queries', 'queries'), ('soa_runs', 'runs'),
                           ('soa_expectation_outcomes', 'outcomes'), ('soa_coded_mentions', 'coded_mentions')):
            for row in data[key]:
                cols = list(row)
                c.execute(text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + k for k in cols)})"),
                          {k: encode(v) for k, v in row.items()})
