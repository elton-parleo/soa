"""
2K-1: FL12's six-agent shape (console_fixture_2i8) with a comparison tier.

FL12's comparison-stage questions ("Pampers vs Huggies for newborns") were
tagged category control and named the brand, so 2I-7 left them out of the
unprompted set and the generator now regenerates them away. Here 12 of 2I-8's
33 branded category-control questions become what 2K-1 writes instead:
comparison-tier questions naming the brand and a rival.

  Unprompted: the 17 unbranded control questions, as 2I-8 coded them: 102
    answered runs, ours first in 33, Pampers in 27, Huggies in 30, nobody in 12.
  Comparison: 12 questions x 6 agents = 72 answered runs (WSF_1018, the AI
    Mode run that errored, is not among them), the same coding per agent:
    questions 0-4 Pampers first (ours second), 5-8 ours first (Huggies
    second), 9-10 Huggies first (ours second), 11 no brand coded.
    Pampers first 30, ours 24, Huggies 12, nobody 6; ours named in 66.
  Brand choice: 102 + 72 = 174 answered runs. Lost: 57 + 30 + 12 = 99.
  The other 21 branded control questions stay as 2I-8 built them.
"""
from typing import Dict, List

from tests import console_fixture_2i8 as f2i8

CYCLE = f2i8.CYCLE
WS, HUGGIES, PAMPERS = f2i8.WS, f2i8.HUGGIES, f2i8.PAMPERS
COMPARISONS = 12
#: the stage questions turned comparison: the 12 after the errored one (index 17)
FIRST_INDEX = f2i8.UNBRANDED + 1


def coding(j: int) -> list:
    """(entity, position) for comparison question j, on every agent."""
    if j < 5:
        return [(PAMPERS, 1), (WS, 2)]
    if j < 9:
        return [(WS, 1), (HUGGIES, 2)]
    if j < 11:
        return [(HUGGIES, 1), (WS, 2)]
    return []


def build() -> Dict[str, List[dict]]:
    d = f2i8.build()
    stage = [q for q in d['queries'] if q['tier'] == 'category_control']
    chosen = {q['id']: j for j, q in enumerate(stage[FIRST_INDEX:FIRST_INDEX + COMPARISONS])}
    assert f2i8.ERRORED not in {q['query_code'] for q in stage if q['id'] in chosen}
    for q in d['queries']:
        if q['id'] in chosen:
            q['tier'] = 'comparison'
            q['stage'] = 'Comparison'
            q['query_text'] = f"Wiggle & Snug vs {'Pampers' if chosen[q['id']] % 2 else 'Huggies'} for question {q['id']}?"
    runs = {r['id']: chosen[r['query_id']] for r in d['runs'] if r['cycle_id'] == 229 and r['query_id'] in chosen}
    d['coded_mentions'] = [m for m in d['coded_mentions'] if m['run_id'] not in runs]
    for rid, j in runs.items():
        d['coded_mentions'] += [{'run_id': rid, 'entity_id': e, 'mentioned': True, 'position': p, 'strength': 'Positive'}
                                for e, p in coding(j)]
    return d


def load(engine, encode) -> None:
    from tests import console_fixture_229 as f229
    f229.load(engine, encode, data=build())
