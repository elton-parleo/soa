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


# ─── Visibility ──────────────────────────────────────────────────────────

def _choice_rows(vis: dict) -> List[dict]:
    """The answered brand-choice rows (category and comparison), the ranking's own rows."""
    return [v for v in vis.get('byQuestion') or [] if v.get('answered')
            and (v.get('brand_choice') if 'brand_choice' in v else v.get('unprompted'))]


def _ranking(vis: dict) -> dict:
    ranking = vis.get('ranking') or {}
    return ranking.get('brand_choice') or ranking


def rival_of(rows: List[dict]) -> Optional[dict]:
    """The rival with the most first picks (then the most named, then the ranking's order)."""
    rivals = [r for r in rows if not r.get('you')]
    if not rivals:
        return None
    return min(enumerate(rivals), key=lambda e: (-(e[1].get('first') or 0), -(e[1].get('named') or 0), e[0]))[1]


def rival_question(rows: List[dict], rival: str) -> Optional[dict]:
    """The question the rival leads most: {q, query_code, k (agents leading with it), n (agents answering),
    answers, product, product_source}. The product is the rival's first-named product in those answers
    (`named_products`, coded from Layer 2's names), else the rival's name."""
    by_q: Dict[str, List[dict]] = {}
    for v in rows:
        by_q.setdefault(v.get('q') or '', []).append(v)
    best = None
    for q, vs in by_q.items():
        led = [v for v in vs if (v.get('first') or {}).get('name') == rival]
        if led and (best is None or len(led) > len(best[1])):
            best = (q, led, vs)
    if best is None:
        return None
    q, led, vs = best
    products = Counter(next((p['name'] for p in v.get('named_products') or [] if p.get('brand') == rival), None)
                       for v in led)
    products.pop(None, None)
    product = min(products.items(), key=lambda kv: (-kv[1], kv[0]))[0] if products else None
    return {'q': q, 'query_code': led[0].get('query_code'), 'k': len({v.get('agent') for v in led}),
            'n': len({v.get('agent') for v in vs}), 'answers': len(led), 'product': product or rival,
            'product_source': 'named_products' if product else 'rival_name'}


def visibility_headline(vis: dict, brand: Optional[str]) -> Optional[dict]:
    """V1: "<Brand> is named in N of M category answers and put first in F. <Rival> goes first in R, and A
    of B agents lead the <question> question with <product>." The question is served whole: soa stores no
    short form of a question (`question_short` null, said so)."""
    ranking = _ranking(vis)
    rows = ranking.get('rows') or []
    you = next((r for r in rows if r.get('you')), None)
    if you is None:
        return None
    name = brand or you['name']
    text = T['vis.headline.named'].format(brand=name, named=you['named'], of=ranking.get('denom') or 0,
                                          first=you['first'])
    rival = rival_of(rows)
    lead = rival_question(_choice_rows(vis), rival['name']) if rival and rival.get('first') else None
    if rival and rival.get('first'):
        text += ' ' + (T['vis.headline.rival'].format(rival=rival['name'], rival_first=rival['first'], k=lead['k'],
                                                      n=lead['n'], question=f"“{lead['q']}”",
                                                      product=lead['product'])
                       if lead else T['vis.headline.rival_only'].format(rival=rival['name'],
                                                                         rival_first=rival['first']))
    return {'text': text, 'brand': name, 'named': you['named'], 'of': ranking.get('denom') or 0, 'first': you['first'],
            'rival': rival['name'] if rival else None, 'rival_first': rival['first'] if rival else None,
            'question': lead, 'question_short': None,
            'question_short_reason': 'soa stores no short form of a question, so it is served whole'}


def visibility_gap(vis: dict, brand: Optional[str], lost: Optional[dict] = None) -> Optional[dict]:
    """V2: {behind_or_ahead, n, rival, sentence, claim, dollars}, by the demo's rule (Leads.tsx
    VisibilityLead): "named almost as often" when the brand is named within 75% to 200% of the rival.
    `lost` is the revenue model's Lost pool ({dollars, reason}), its dollars beside."""
    rows = _ranking(vis).get('rows') or []
    you = next((r for r in rows if r.get('you')), None)
    rival = rival_of(rows)
    if you is None or rival is None:
        return None
    name, nm = brand or you['name'], rival['name']
    gap = (rival.get('first') or 0) - (you.get('first') or 0)
    close = you['named'] >= rival['named'] * 0.75 and you['named'] <= rival['named'] * 2
    side = 'level' if gap == 0 else 'behind' if gap > 0 else 'ahead'
    picks = 'pick' if abs(gap) == 1 else 'picks'
    head = (T['vis.gap.level'].format(rival=nm) if gap == 0 else
            T['vis.gap.behind' if gap > 0 else 'vis.gap.ahead'].format(n=abs(gap), picks=picks, rival=nm))
    if gap == 0:
        claim = T['vis.gap.level_line'].format(rival=nm, named=you['named'], rival_s=f"{nm}'s",
                                               rival_named=rival['named'])
    elif close:
        how = ('far less' if you['first'] * 2 <= rival['first'] else 'less') if you['first'] < rival['first'] else 'more'
        claim = T['vis.gap.close'].format(rival=nm, how=how)
    else:
        claim = T['vis.gap.far'].format(rival=nm, rival_first=rival['first'], brand=name, first=you['first'])
    return {'behind_or_ahead': side, 'n': abs(gap), 'rival': nm, 'claim': claim, 'sentence': f"{head} · {claim}",
            'dollars': (lost or {}).get('dollars'),
            'dollars_reason': None if (lost or {}).get('dollars') is not None else
            (lost or {}).get('reason') or 'no revenue model was read for this cycle'}


def visibility_footnote(vis: dict) -> Optional[dict]:
    """V3: the demo's one footnote, "One first pick each for ... N answers named no single first pick.
    <successor> was named in A of B, <retired> in C." (console_brand_overview.first_pick_footnote, the
    Overview's own), then the brand's own lines named outside the category, apart."""
    from app.services import console_brand_overview as bo
    out = bo.first_pick_footnote(vis, retired_named=vis.get('retired_named'))
    if out is None:
        return None
    outside = (vis.get('ranking') or {}).get('outside_category') or {}
    own = [o['name'] for o in outside.get('own') or []]
    if own:
        out['footnote'] += ' ' + T['vis.outside'].format(names=_join(own), verb='was' if len(own) == 1 else 'were')
    out['outside_category'] = outside
    return out


def visibility_lead(vis: dict, brand: Optional[str], lost: Optional[dict] = None) -> dict:
    """V1 to V3 for a brand at retail: `headline` is the demo's sentence (the every-agent line stays in
    `headlines`), `headline_detail` its parts, `gap`, `footnote`."""
    head = visibility_headline(vis, brand)
    return {'headline': head['text'] if head else vis.get('headline'), 'headline_detail': head,
            'gap': visibility_gap(vis, brand, lost), 'footnote': visibility_footnote(vis)}
