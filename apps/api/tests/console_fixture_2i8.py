"""
2I-8: a fixture shaped like FL12 (Oct 19, Pampers' first loop) on two
surfaces and six agents, built from cycle 229 (console_fixture_229), as 2I-7
stood FL12 in with 229's questions. FL12 has no recorded sample here.

  50 category-control questions (the brand box on): 33 name the brand, 17 do
    not. 11 brand-direct, 19 catalog, 6 value, as 229. One run per question.
  Six agents: ChatGPT, Gemini, Perplexity and Claude on the grounded API,
    AI Mode and Copilot on the consumer UI. 86 questions x 6 = 516 runs.
  Unprompted (the 17 unbranded): 102 answered runs, 68 grounded and 34
    consumer. Ours first on each agent's first k questions (OURS_FIRST:
    22 grounded, 11 consumer, 33 of 102), Pampers on the rest of the first
    10 (18 and 9), Huggies on the next 5 (20 and 10), nobody on the last 2.
    Ours is named second on the 3 questions after its own firsts.
  One AI Mode run errored with no answer: a control question naming the
    brand (WSF_1018), so the 102 hold.
  Catalog: 229's ChatGPT outcomes for every agent, except AI Mode and
    Copilot, which quote the first 5 of 229's wrong prices right: the
    surfaces' accuracies differ, so a pooled accuracy is not their mean.
  The previous cycle, 178, ran ChatGPT only: not comparable on any surface.
"""
from typing import Dict, List

from tests import console_fixture_229 as f229

CYCLE = f229.CYCLE_229
STUDY = f229.STUDY
WS, HUGGIES, PAMPERS = f229.WS, f229.HUGGIES, f229.PAMPERS
#: (platform, surface, collector), in the demo's column order where it has one
AGENTS = (('chatgpt', 'grounded_api', 'openai'), ('gemini_grounded', 'grounded_api', 'google_genai'),
          ('aimode', 'consumer_ui', 'serpapi'), ('perplexity', 'grounded_api', 'perplexity'),
          ('copilot', 'consumer_ui', 'serpapi'), ('claude', 'grounded_api', 'anthropic'))
UNBRANDED = 17
#: ours first on the first n unbranded questions, per agent
OURS_FIRST = {'chatgpt': 7, 'gemini_grounded': 6, 'perplexity': 5, 'claude': 4, 'aimode': 6, 'copilot': 5}
ERRORED = 'WSF_1018'


def build() -> Dict[str, List[dict]]:
    d = f229.build()
    d['generation_jobs'][0]['tier_config'] = {
        'merchant': {'slug': 'wiggle-and-snug', 'brand': 'Wiggle & Snug', 'study_brand': 'Wiggle & Snug'},
        'category_control': {'enabled': True, 'count': 50}}
    stage = [q for q in d['queries'] if q['tier'] is None]
    for i, q in enumerate(stage):
        q['tier'] = 'category_control'
        if UNBRANDED <= i < 50:
            q['query_text'] = f"Is Wiggle & Snug right for question {q['id']}?"
    unbranded = {q['id']: i for i, q in enumerate(stage[:UNBRANDED])}
    by_id = {q['id']: q for q in d['queries']}

    templates = [r for r in d['runs'] if r['cycle_id'] == 229 and r['platform'] == 'chatgpt' and r['run_number'] == 1]
    outcome_of = {o['run_id']: o for o in d['outcomes'] if o['cycle_id'] == 229}
    mentions_of: Dict[int, List[dict]] = {}
    for m in d['coded_mentions']:
        mentions_of.setdefault(m['run_id'], []).append(m)
    keep_runs = [r for r in d['runs'] if r['cycle_id'] != 229]
    keep_outcomes = [o for o in d['outcomes'] if o['cycle_id'] != 229]
    runs, outcomes, mentions = [], [], []
    rid = 70000
    wrong_seen: Dict[str, int] = {}
    for t in templates:
        q = by_id[t['query_id']]
        for platform, surface, collector in AGENTS:
            rid += 1
            errored = platform == 'aimode' and q['query_code'] == ERRORED
            runs.append({**t, 'id': rid, 'platform': platform, 'surface': surface, 'collector': collector,
                         'status': 'error' if errored else 'success', 'raw_response': '' if errored else 'answer',
                         'answer_status': None if errored else 'answered'})
            if errored:
                continue
            o = outcome_of.get(t['id'])
            if o is not None:
                outcome = o['outcome']
                if surface == 'consumer_ui' and o['tier'] == 'catalog_accuracy' and outcome == 'wrong':
                    wrong_seen[platform] = wrong_seen.get(platform, 0) + 1
                    if wrong_seen[platform] <= 5:
                        outcome = 'exact'
                outcomes.append({**o, 'run_id': rid, 'platform': platform, 'surface': surface, 'outcome': outcome})
            if q['id'] in unbranded:
                i = unbranded[q['id']]
                k = OURS_FIRST[platform]
                if i < k:
                    coded = [(WS, 1), (PAMPERS, 2)]
                elif i < 10:
                    coded = [(PAMPERS, 1)] + ([(WS, 2)] if i < k + 3 else [])
                elif i < 15:
                    coded = [(HUGGIES, 1), (PAMPERS, 2)]
                else:
                    coded = []
                mentions += [{'run_id': rid, 'entity_id': e, 'mentioned': True, 'position': p, 'strength': 'Positive'}
                             for e, p in coded]
            else:
                mentions += [{**m, 'run_id': rid} for m in mentions_of.get(t['id'], [])]
    d['runs'] = keep_runs + runs
    d['outcomes'] = keep_outcomes + outcomes
    kept = {r['id'] for r in keep_runs}
    d['coded_mentions'] = [m for m in d['coded_mentions'] if m['run_id'] in kept] + mentions
    for c in d['cycles']:
        if c['id'] == 229:
            c.update({'platforms': [a for a, _, _ in AGENTS], 'runs_per_query': 1,
                      'total_runs_planned': len(runs), 'completed_runs': len(runs)})
    return d


def load(engine, encode) -> None:
    """Into the console test database, as console_fixture_229.load does."""
    f229.load(engine, encode, data=build())
