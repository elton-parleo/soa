"""
2K-4 (B1): whether two cycles can be compared, one rule for every reader.
Sync copies to apps/api/soa_shared/ and apps/pipeline/soa_shared/ (the
pipeline imports none of it: the copy is kept so the two trees stay alike).

On FL13 the Share of Algorithm tile read "-6 vs FL12-pampers-20261020" and
the metric tiles showed deltas while the Changes block said "Not comparable":
the score checked its scorer version, its measured surfaces and its agents,
the Changes block its agents and the tier it reads, and neither checked the
question set. FL12 and FL13 were different studies. Every reader that shows
a delta against the previous cycle now asks cycles_comparable: the score
tile's delta and the metric tiles' (console_score), the Overview's Changes
block (console_parity) and the revenue history's previous cycle.

A cycle is described by facts() and two are comparable when, in this order:

  1. version    both were scored under the same scorer version (only when
                both carry one: the score's)
  2. study      they ran the same study, or questions with identical codes
                and tiers
  3. surfaces   the same surfaces were measured (only when both carry them:
                the score's pooled surfaces)
  4. agents     the same agents answered on each surface compared
  5. measured   the earlier cycle measured the set this one reads: the
                unprompted questions, or (with a comparison question asked)
                the brand-choice set

The reason names the first condition that fails, in one sentence.
"""
from typing import Dict, Iterable, List, Optional, Tuple

VERSION, STUDY, SURFACES, AGENTS, MEASURED = 'version', 'study', 'surfaces', 'agents', 'measured'
CONDITIONS = (VERSION, STUDY, SURFACES, AGENTS, MEASURED)
#: the sets a cycle's first-pick numbers read (console_read_models.VIS_UNPROMPTED / VIS_BRAND_CHOICE)
UNPROMPTED, BRAND_CHOICE = 'unprompted', 'brand_choice'

TEMPLATES = {
    'version': 'Scored under v{version}, re-score to compare.',
    'study': 'Not comparable: {code} ran a different study ({study}).',
    'surfaces': 'Not comparable: {code} scored {prev}, this cycle scored {now}.',
    'agents_subset': 'Not comparable: {code} ran {agents} only{on}.',
    'agents': 'Not comparable: {code} ran {prev}{on}, this cycle ran {now}.',
    'measured_unprompted': 'Not comparable: {code} asked no unprompted questions{on}.',
    'measured_comparison': 'Not comparable: {code} asked no comparison questions{on}.',
}


def facts(code: str, *, study: Optional[str], questions: Optional[Dict[str, str]] = None,
          agents: Optional[Dict[str, Iterable[str]]] = None, scorer_version: Optional[str] = None,
          surfaces: Optional[Iterable[str]] = None, reads: Optional[str] = None,
          measured: Optional[Dict[str, int]] = None) -> dict:
    """One cycle as cycles_comparable reads it. questions: {query_code:
    tier} of its study. agents: {surface: the agents that answered there}.
    reads: the set its first-pick numbers read (UNPROMPTED | BRAND_CHOICE),
    measured: how many answers it has in each ({'unprompted': n,
    'comparison': n})."""
    return {'code': code, 'study': study, 'questions': dict(questions or {}),
            'agents': {s: sorted(set(a)) for s, a in (agents or {}).items()},
            'scorer_version': scorer_version, 'surfaces': None if surfaces is None else sorted(set(surfaces)),
            'reads': reads, 'measured': dict(measured or {})}


def _list(names: List[str]) -> str:
    return ' and '.join(names) if len(names) < 3 else ', '.join(names[:-1]) + ' and ' + names[-1]


def cycles_comparable(now: dict, prev: Optional[dict], *, on: Optional[str] = '',
                      agent_name=lambda a: a, surface_name=lambda s: s) -> Tuple[bool, Optional[str], Optional[str]]:
    """(comparable, the first failing condition, its reason). `prev` None is
    not a comparison (a first cycle): (False, None, None). `on` is the
    caller's words for where the agents were compared (" on this surface",
    "" for every agent); None names the surface that differs (the score's)."""
    if prev is None:
        return False, None, None
    code = prev['code']
    a_v, b_v = now.get('scorer_version'), prev.get('scorer_version')
    if a_v is not None and b_v is not None and str(a_v) != str(b_v):
        return False, VERSION, TEMPLATES['version'].format(version=b_v)
    if now.get('study') != prev.get('study') and (not now.get('questions') or now['questions'] != prev.get('questions')):
        return False, STUDY, TEMPLATES['study'].format(code=code, study=prev.get('study') or 'no study')
    a_s, b_s = now.get('surfaces'), prev.get('surfaces')
    if a_s is not None and b_s is not None and set(a_s) != set(b_s):
        words = lambda xs: ' and '.join(surface_name(x) for x in xs) or 'no surface'
        return False, SURFACES, TEMPLATES['surfaces'].format(code=code, prev=words(b_s), now=words(a_s))
    agents_now, agents_prev = now.get('agents') or {}, prev.get('agents') or {}
    for s in agents_now:
        x, y = set(agents_now[s]), set(agents_prev.get(s) or [])
        if x == y:
            continue
        where = f' on {surface_name(s)}' if on is None else on
        names = lambda xs: _list(sorted((agent_name(v) for v in xs), key=str))
        if y and y < x:
            return False, AGENTS, TEMPLATES['agents_subset'].format(code=code, agents=names(y), on=where)
        return False, AGENTS, TEMPLATES['agents'].format(code=code, prev=names(y) if y else 'no agent', on=where,
                                                         now=names(x) if x else 'no agent')
    reads, had = now.get('reads'), prev.get('measured') or {}
    if reads == UNPROMPTED and not had.get(UNPROMPTED):
        return False, MEASURED, TEMPLATES['measured_unprompted'].format(code=code, on=on or '')
    if reads == BRAND_CHOICE and not had.get('comparison'):
        return False, MEASURED, TEMPLATES['measured_comparison'].format(code=code, on=on or '')
    return True, None, None
