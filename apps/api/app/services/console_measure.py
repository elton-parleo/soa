"""
2T-5: the Measure read models (Answers, Visibility, True Value, Accessibility)
in the console demo's shape for a brand at retail.

The spec is the demo (parleohq/truesync console-demo, apps/console/src/data/
pg.ts and v2_pg.ts, screens/Leads.tsx): each lead there is drawn from data the
screen already shows, and each block here builds that lead from the data soa
already serves, by rule. A demo field with no source in soa is served `null`
beside a `*_reason` that says why, never a guess. No model call, no new read
of production; the blocks are pure functions over the bodies the endpoints
already build, so a test can feed them any shape.

House rules (as console_brand_overview): sentences, no semicolons, no dashes.
"""
from collections import Counter
from typing import Dict, Iterable, List, Optional

from app.services import console_read_models as rm
from soa_shared import severity as sev

AGENT_ORDER = list(rm.AGENT_NAMES)

MEASURE_TEMPLATES = {
    # Answers (A1, A2)
    'answers.hero': '{high} of {flagged} flagged',
    'answers.claim.none': 'No answer flagged.',
    # Visibility (V1, V2)
    'vis.headline.named': '{brand} is named in {named} of {of} category answers and put first in {first}.',
    'vis.headline.rival': '{rival} goes first in {rival_first}, and {k} of {n} agents lead the {question} question '
                          'with {product}.',
    'vis.headline.rival_only': '{rival} goes first in {rival_first}.',
    'vis.gap.behind': '{n} first {picks} behind {rival}',
    'vis.gap.ahead': '{n} first {picks} ahead of {rival}',
    'vis.gap.level': 'Level with {rival} on first picks',
    'vis.gap.close': 'Named almost as often as {rival}, picked first {how} often',
    'vis.gap.far': '{rival} is picked first in {rival_first}, {brand} in {first}',
    'vis.gap.level_line': "Level with {rival} on first picks, named {named} to {rival_s} {rival_named}",
    'vis.outside': '{names} {verb} named too, outside the category.',
    # True Value (TV1, TV5, TV6, TV9)
    'tv.hero.sub': '{n} of {read} prices read are wrong or missing',
    'tv.hero.claim': '{wrong} off the live page, and {left} left out',
    'tv.line.deals': '{deals} {verb} live. {named} of {asked} cheapest-place answers named {which}.',
    'tv.line.weight': 'Weight right in {k} of {n}.',
    'tv.anatomy.title': 'Anatomy of a {brand} pack',
    'tv.anatomy.sub': '{product} on {retailer}, {day}',
}
T = MEASURE_TEMPLATES


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _join(items: List[str], word: str = 'and') -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return ''.join(items)
    if len(items) == 2:
        return f"{items[0]} {word} {items[1]}"
    return f"{', '.join(items[:-1])}, {word} {items[-1]}"


# ─── Answers ─────────────────────────────────────────────────────────────

#: A High answer's rule -> the noun the hero's clause lists, in the demo's order
HIGH_NOUNS = (
    ((sev.WRONG_PRICE,), 'a wrong price'),
    ((sev.RETIRED_CURRENT, sev.NO_SUCCESSOR), 'the wrong product'),
    ((sev.WRONG_FACT, sev.FABRICATED), 'a wrong fact'),
    ((sev.CLUB_ELSEWHERE,), 'the wrong store'),
)
#: A Medium answer's rule -> its clause, when no answer is High
MEDIUM_CLAUSES = (
    ((sev.MISSED_DEAL,), 'leave out a live deal'),
    ((sev.FEWER_RETAILERS,), "name fewer than two of the brand's retailers"),
    ((sev.NO_WEIGHT,), 'give no weight range'),
    ((sev.PARTIAL_PRICE,), 'give a price near the page, not on it'),
    ((sev.COULD_NOT_FIND,), 'say they could not find the product'),
)
KIND_ORDER = {k: i for i, k in enumerate(rm.ANSWER_KINDS)}


def _agent_rank(agent: Optional[str]) -> int:
    return AGENT_ORDER.index(agent) if agent in AGENT_ORDER else len(AGENT_ORDER)


def high_claim(answers: List[dict], brand: Optional[str]) -> Optional[str]:
    """A2: "63 answers give a wrong price, the wrong product, or leave Pampers out where it should be first",
    the clauses the kinds actually present."""
    high = [a for a in answers if a.get('severity') == sev.HIGH]
    if not high:
        return None
    rules = {a.get('severity_rule') for a in high}
    one = len(high) == 1
    parts = [noun for keys, noun in HIGH_NOUNS if rules & set(keys)]
    if parts:
        parts[0] = f"{'gives' if one else 'give'} {parts[0]}"
    if sev.BRAND_NOT_FIRST in rules:
        parts.append(f"{'leaves' if one else 'leave'} {brand or 'the brand'} out where it should be first")
    if not parts:   # a High rule the clauses do not list
        parts = ['gets it wrong' if one else 'get it wrong']
    return f"{_plural(len(high), 'answer', 'answers')} {_join(parts, 'or')}"


def medium_claim(answers: List[dict]) -> Optional[str]:
    med = [a for a in answers if a.get('severity') == sev.MEDIUM]
    if not med:
        return None
    rules = {a.get('severity_rule') for a in med}
    clauses = [c for keys, c in MEDIUM_CLAUSES if rules & set(keys)]
    if len(med) == 1:
        clauses = [c.replace('leave ', 'leaves ', 1).replace('name ', 'names ', 1).replace('give ', 'gives ', 1)
                   .replace('say they', 'says it', 1) for c in clauses]
    return f"{len(med)} {'answer' if len(med) == 1 else 'answers'} {_join(clauses, 'or')}"


def worst_answer(answers: List[dict]) -> Optional[dict]:
    """The worst flagged answer: High first, then the rule the hero lists first, then the demo's tab order."""
    rule_rank = {r: i for i, (keys, _n) in enumerate(HIGH_NOUNS + MEDIUM_CLAUSES) for r in keys}
    rule_rank.setdefault(sev.BRAND_NOT_FIRST, len(HIGH_NOUNS))
    flagged = [a for a in answers if sev.is_flagged(a.get('severity'))]
    if not flagged:
        return None
    return min(enumerate(flagged), key=lambda e: (sev.ORDER.get(e[1]['severity'], 9),
                                                  rule_rank.get(e[1].get('severity_rule'), 99),
                                                  KIND_ORDER.get(e[1].get('kind'), 9), e[0]))[1]


def chips(answers: List[dict]) -> List[dict]:
    """A3: one chip per flagged answer, by agent (the demo's column order), then severity."""
    flagged = [(i, a) for i, a in enumerate(answers) if sev.is_flagged(a.get('severity'))]
    flagged.sort(key=lambda e: (_agent_rank(e[1].get('agent')), sev.ORDER.get(e[1]['severity'], 9), e[0]))
    return [{'id': a['id'], 'agent': a.get('agent'), 'kind': a.get('kind'), 'severity': a['severity'],
             'rule': a.get('severity_rule'), 'query': a.get('query'), 'summary': a.get('summary')}
            for _i, a in flagged]


def answers_lead(answers: List[dict], brand: Optional[str]) -> dict:
    """A1 to A3: {flagged, hero, worst_answer_id, chips, kinds} over the answers /answers serves."""
    tally = sev.tally(answers)
    claim = high_claim(answers, brand) or medium_claim(answers)
    n = tally['high'] or tally['medium']
    sub = f"of {tally['flagged']} flagged"
    worst = worst_answer(answers)
    return {
        'flagged': {'total': tally['flagged'], 'high': tally['high'], 'medium': tally['medium'],
                    'right': tally['right'], 'of': tally['shown']},
        'hero': {'n': n, 'sub': sub, 'claim': claim or T['answers.claim.none'], 'high': tally['high'],
                 'text': f"{T['answers.hero'].format(high=n, flagged=tally['flagged'])} · {claim}" if claim
                 else T['answers.claim.none']},
        'worst_answer_id': worst['id'] if worst else None,
        'chips': chips(answers),
        'kinds': {k: {'answers': sum(1 for a in answers if a.get('kind') == k),
                      'flagged': sum(1 for a in answers if a.get('kind') == k and sev.is_flagged(a.get('severity')))}
                  for k in rm.ANSWER_KINDS},
    }

