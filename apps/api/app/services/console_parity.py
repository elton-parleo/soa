"""
2C-2: the console's demo blocks, filled from data soa already stores.

Pivots and summaries over what the 2B/2C/2C-1 read models already read:
the per-run outcomes, the mention coding, the True Value cells, the 2A
reference and access reads, the publication journal and the owned
incentives. Nothing new is measured, nothing is modeled and no model is
called: every sentence here is a template filled from counts, and each
template is written down once (TEMPLATES) so docs/console-read-models.md
can quote it.

Two rules hold everywhere:
  * 2I-8: counts are shown for every agent together by default, as the
    console demo shows them: the pseudo-surface `all` (soa_shared/surfaces.py
    ALL), every run in the cycle, listed first and read by default. Each
    surface's own count (api, grounded_api, consumer_ui) sits beside it, for
    the console's surface filter, exactly as before. A per-agent split sits
    beneath each. The score pools surfaces by score, never by count
    (console_score.py, unchanged).
  * `unverifiable` is counted on its own and never sits in an accuracy.

House copy rules for every template: no em dashes, no semicolons.

Pure functions over rows (the loaders at the bottom do the SQL), so each
rule is tested without a database.
"""
import json
import re
from collections import Counter
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

from soa_shared import claim_kinds, cycle_compare, surfaces

from app.services import console_claims
from app.services import console_read_models as rm
from clients.truesync_client import INCENTIVE_FLAGS, carries_incentive_fields, incentive_in_markup

AGENT_NAMES = rm.AGENT_NAMES
ALL = surfaces.ALL
_on = surfaces.on_surface
_json = rm._json

# ─── vocabulary ────────────────────────────────────────────────────────────

#: Studio's stage order, the order prompts are read in.
STAGE_ORDER = ('Awareness', 'Research', 'Comparison', 'Ready to Buy')
STAGE_LABELS = {'Awareness': 'Awareness', 'Research': 'Research', 'Comparison': 'Comparison',
                'Ready to Buy': 'Ready to buy'}
UNPROMPTED = rm.VIS_UNPROMPTED
#: 2K-1: the brand-choice set, unprompted plus the comparison tier (soa_shared/unprompted.is_brand_choice)
BRAND_CHOICE = rm.VIS_BRAND_CHOICE
SCORED = rm.SUMMARY_SCORED
#: Grounding supports (the sources behind a grounded answer) are stored from
#: Oct 14 2026 on (#104). A fabricated brand-direct verdict on a cycle that
#: started earlier was judged without them.
GROUNDING_SOURCES_FROM = date(2026, 10, 14)

#: Every sentence the console shows from this module, by rule. `{n}`-style
#: fields only; plural forms are chosen by `_n()`.
TEMPLATES = {
    'agent.other_brand': "Answered {n} price {questions} with another brand's price.",
    'agent.wrong': "Wrong on {n} {prices}.",
    'agent.unknown': "Did not know the brand {n} {times}.",
    'agent.right': "Right on {exact} of {scored} prices.",
    'agent.none': "No price scored.",
    'product.other_brand': "Priced another brand's product in {n} of {runs} {runs_word}.",
    'product.wrong': "Quoted a wrong price in {n} of {runs} {runs_word}.",
    # 2Q-2 (B2): and the most common wrong amount, never the most quoted (FL15's was an exact one)
    'product.wrong_quote': "Quoted a wrong price in {n} of {runs} {runs_word}, most often {quote} against {live}.",
    # 2Q-1 (B4): the wrong quotes were for another pack, the reason the price check already has
    'product.wrong_pack': "Quoted {quote} for a {pack} ct pack against {live} for the {asked} in {n} of {runs} {runs_word}.",
    # 2R-2 (B5): the quotes named another variant the record does not have (variant_clash)
    'product.wrong_clash': "Quoted {quote} for {named} against {live} for the {asked} in {n} of {runs} {runs_word}.",
    'product.left_out': "No price quoted in {n} of {runs} {runs_word}.",
    'product.unverifiable': "The page could not be read, so {n} of {runs} {runs_word} are not scored.",
    # 2N-1: after the issue, the retailers whose every quote could not be checked
    'product.walled': "{retailers} could not be read.",
    'product.right': "Right in {n} of {runs} {runs_word}.",
    'product.not_asked': "Not asked on this surface this cycle.",
    'signal.other_brand': ("Answered {n} price {questions} with another brand's price.",
                           "{n} of {asked} price answers {on}. {split}."),
    'signal.fabricated': ("{n} brand answers stated facts {brand} never published.",
                          "{n} of {asked} brand-direct answers {on}. {split}."),
    # 2K-1 (A9): the second line, the fabricated answers that stated no attribute (claim_kind recommendation_only)
    'signal.fabricated_recommended': "{n} recommended {brand} without stating a fact.",
    'signal.fabricated_caveat': "Sources were not captured before Oct 14, so some of these may rest on a page we did not see.",
    'signal.wrong_product': ("Wrong price on {product} in {n} runs.",
                             "Quoted {quote} against {live}. {split}."),
    # 2Q-1 (B4): FL15's "Quoted $44.99 against $44.99." was a quote for the 58 ct pack
    'signal.wrong_product_pack': "Quoted {quote} for a {pack} ct pack against {live} for the {asked}. {split}.",
    # 2R-2 (B5): FL15's "most often $44.99 against $44.99" was ChatGPT's quote for Zzz Size 3, 116-count
    'signal.wrong_product_clash': "Quoted {quote} for {named} against {live} for the {asked}. {split}.",
    'signal.unverifiable': ("{n} {prices} could not be checked.",
                            "The page blocked both readers. These are counted on their own and never in an accuracy. {split}."),
    'signal.access': ("{n} agent {identities} could not read the pages.",
                      "{who}. From the last access run."),
    'summary.visibility_named': "Named in {named} of {n} {answers} and first in {first}.",
    'summary.visibility_lead': "First in {first} of {n} {answers}, ahead of every other brand.",
    'summary.rivals': "{lead} first in {k}{rest}.",
    'summary.accuracy': "Prices right in {exact} of {scored} scored answers, {other} answered with another brand's price.",
    'summary.accuracy_unverifiable': "Prices right in {exact} of {scored} scored answers, {other} answered with another brand's price, {u} not checked.",
    'summary.no_price': "No price was scored on this surface.",
    'summary.no_price_all': "No price was scored by any agent.",
    'summary.no_signal': "No signal crossed its threshold this cycle.",
    'changes.first_cycle': "First cycle. Changes appear from the next one.",
    'changes.not_comparable_subset': "Not comparable: {code} ran {agents} only on this surface.",
    'changes.not_comparable': "Not comparable: {code} ran {prev} on this surface, this cycle ran {now}.",
    'changes.not_comparable_tier': "Not comparable: {code} asked no unprompted questions on this surface.",
    # 2I-8: the same on `all`, every agent together
    'changes.not_comparable_subset_all': "Not comparable: {code} ran {agents} only.",
    'changes.not_comparable_all': "Not comparable: {code} ran {prev}, this cycle ran {now}.",
    'changes.not_comparable_tier_all': "Not comparable: {code} asked no unprompted questions.",
    # 2K-1: this cycle reads brand-choice answers (it asked comparison questions) and the previous asked none
    'changes.not_comparable_comparison': "Not comparable: {code} asked no comparison questions on this surface.",
    'changes.not_comparable_comparison_all': "Not comparable: {code} asked no comparison questions.",
    'changes.detail': "{a} of {of_now} this cycle against {b} of {of_prev} in {code}.",
    'headline.gap': "Named in {named} of {n} {answers}.{rivals}",
    'headline.lead': "First in {first} of {n} {answers}.",
    'catalog.read': "{ok} of {pages} pages read{rest}.",
    'catalog.incentive': "Incentive in markup: {pages} of {of} pages",
    'catalog.incentive_unscanned': "Incentive in markup: not checked, no read scanned yet",
    'catalog.incentive_none': "Incentive in markup: not measured, supply does not serve it yet",
}


def _n(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _agent(a: Optional[str]) -> str:
    return AGENT_NAMES.get(a or '', a or 'Unknown agent')


def _surface_label(s: Optional[str]) -> str:
    return {'api': 'the model-only API', 'grounded_api': 'the grounded API',
            'consumer_ui': 'the consumer UI', ALL: 'every agent'}.get(s or '', s or 'an unlabelled surface')


def _on_words(s: Optional[str]) -> str:
    """Where a count was taken, as a signal's detail says it: 'on the grounded
    API', or (2I-8) 'across every agent'."""
    return 'across every agent' if s == ALL else f"on {_surface_label(s)}"


def _rule(key: str, surface: Optional[str]) -> str:
    """2I-8: a template's `all` wording where it has one."""
    return f"{key}_all" if surface == ALL and f"{key}_all" in TEMPLATES else key


def _split(counts: Dict[str, int]) -> str:
    """'ChatGPT 4, Gemini 2', agents in name order, zero agents left out."""
    return ', '.join(f"{_agent(a)} {n}" for a, n in sorted(counts.items(), key=lambda kv: _agent(kv[0])) if n)


def _surface_of(row: dict) -> str:
    """A run's surface, read exactly as Visibility reads it (the run's own,
    else its platform's), so every Overview count sits on the same surface."""
    return row.get('surface') or surfaces.surface_of(row.get('platform')) or 'unlabelled'


#: The tiers a price is asked in.
PRICE_TIERS = ('catalog_accuracy', 'value_incentives')


def _surface_rank(s: str) -> int:
    return rm._SURFACE_RANK.get(s, 0)


def ordered_surfaces(keys: Iterable[str]) -> List[str]:
    return sorted(set(keys), key=lambda s: (-_surface_rank(s), s))


def _day(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _short_day(value) -> str:
    d = _day(value)
    return f"{d.strftime('%b')} {d.day}" if d else 'date not recorded'


# ─── Visibility extras ─────────────────────────────────────────────────────

def _tier_for_reads(rows: List[dict]) -> str:
    """BRAND_CHOICE when the cycle asked any comparison question (2K-1),
    else UNPROMPTED when it asked any unprompted question, else 'all'.
    2I-7: a row is unprompted by its `unprompted` (build_visibility, the
    soa_shared/unprompted.py rule: category control counts, a question
    naming the brand does not); a row built without it, by its tier."""
    if any(r.get('tier') == rm.COMPARISON for r in rows):
        return BRAND_CHOICE
    return UNPROMPTED if any(_unprompted(r) for r in rows) else 'all'


def _brand_choice(row: dict) -> bool:
    """2K-1: unprompted, or a comparison question (build_visibility's `brand_choice`)."""
    return row['brand_choice'] if 'brand_choice' in row else (_unprompted(row) or row.get('tier') == rm.COMPARISON)


def _unprompted(row: dict) -> bool:
    return row['unprompted'] if 'unprompted' in row else row.get('tier') == UNPROMPTED


def _in_tier(row: dict, tier: str) -> bool:
    """Whether a Visibility row counts toward named/first under `tier`."""
    if tier == BRAND_CHOICE:
        return _brand_choice(row)
    return tier == 'all' or (_unprompted(row) if tier == UNPROMPTED else row.get('tier') == tier)


def _tier_words(tier: str) -> str:
    # 2P-1: one name for the answers a first pick counts, whatever set they are
    return {UNPROMPTED: 'brand-choice', BRAND_CHOICE: 'brand-choice'}.get(tier, '')


def _answers(tier: str) -> str:
    """'brand-choice answers' over the unprompted set or the brand-choice set
    (2K-1: unprompted plus comparison), else 'answers'. 2P-1: the console's
    copy names both the one way; with no comparison question asked the two
    sets are the same answers."""
    return {UNPROMPTED: 'brand-choice answers', BRAND_CHOICE: 'brand-choice answers'}.get(tier, 'answers')


def _picks(rows: List[dict]) -> Dict[str, dict]:
    """name -> {named, first, you} over answered runs."""
    out: Dict[str, dict] = {}
    for r in rows:
        for n in r.get('named') or []:
            out.setdefault(n['name'], {'named': 0, 'first': 0, 'you': n.get('you', False)})['named'] += 1
        f = r.get('first')
        if f:
            out.setdefault(f['name'], {'named': 0, 'first': 0, 'you': f.get('you', False)})['first'] += 1
    return out


def visibility_headline(rows: List[dict], surface: str, ours: Optional[str]) -> dict:
    """The gap sentence for one surface: unprompted answers when the cycle
    asked any, else every answered run."""
    tier = _tier_for_reads(rows)
    mine = [r for r in rows if r.get('answered') and _on(r.get('surface'), surface) and _in_tier(r, tier)]
    n = len(mine)
    picks = _picks(mine)
    me = picks.get(ours or '', {'named': 0, 'first': 0})
    others = sorted(((k, v['first']) for k, v in picks.items() if not v['you'] and v['first'] > 0),
                    key=lambda kv: (-kv[1], kv[0]))
    words = _tier_words(tier)
    tier_text = f"{words} " if words else ''
    if n and me['first'] and (not others or me['first'] > others[0][1]):
        text_ = TEMPLATES['headline.lead'].format(first=me['first'], n=n, answers=_answers(tier))
    else:
        rivals = ''
        if others:
            lead, k = others[0]
            rest = f", {others[1][0]} in {others[1][1]}" if len(others) > 1 else ''
            rivals = ' ' + TEMPLATES['summary.rivals'].format(lead=lead, k=k, rest=rest)
        text_ = TEMPLATES['headline.gap'].format(named=me['named'], n=n, answers=_answers(tier), rivals=rivals)
    return {'text': ' '.join(text_.split()), 'tier': tier, 'denom': n, 'named': me['named'], 'first': me['first'],
            'rivals': [{'name': k, 'first': v} for k, v in others[:3]], 'tier_text': tier_text.strip()}


def _demo_order(agents: Iterable[str]) -> List[str]:
    """2I-8: the demo's column order (ChatGPT, Gemini, AI Mode, Perplexity,
    Copilot, then Claude: AGENT_NAMES), any other agent after, by name."""
    order = list(AGENT_NAMES)
    return sorted(set(agents), key=lambda a: (order.index(a) if a in order else 99, a))


def visibility_matrix(rows: List[dict], surface: str) -> dict:
    """Prompt x agent first pick on one surface, prompts in stage order. A
    cell is the first pick most of the question's runs gave (ties to ours,
    then by name), with every pick counted beside it. 2I-8: on `all`, one
    column per agent across the surfaces, in the demo's order; a question an
    agent did not run has no cell for it."""
    mine = [r for r in rows if _on(r.get('surface'), surface)]
    agents = _demo_order(r['agent'] for r in mine) if surface == ALL else sorted({r['agent'] for r in mine})
    questions: Dict[str, dict] = {}
    for r in mine:
        key = r.get('query_code') or r.get('q')
        q = questions.setdefault(key, {'q': r.get('q'), 'query_code': r.get('query_code'), 'stage': r.get('stage'),
                                       'tier': r.get('tier'), 'type': r.get('type'), 'cells': {}})
        cell = q['cells'].setdefault(r['agent'], {'runs': 0, 'answered': 0, 'picks': Counter(), 'you': {}})
        cell['runs'] += 1
        if r.get('answered'):
            cell['answered'] += 1
            if r.get('first'):
                cell['picks'][r['first']['name']] += 1
                cell['you'][r['first']['name']] = bool(r['first'].get('you'))
    out_rows = []
    for q in questions.values():
        cells = {}
        for a, c in q['cells'].items():
            picks = c['picks']
            if picks:
                top = max(picks.items(), key=lambda kv: (kv[1], c['you'].get(kv[0], False), [-ord(ch) for ch in kv[0]]))
                first = {'name': top[0], 'you': c['you'].get(top[0], False), 'runs': top[1]}
            else:
                first = None
            cells[a] = {'first': first, 'runs': c['runs'], 'answered': c['answered'], 'picks': dict(picks)}
        out_rows.append({**{k: v for k, v in q.items() if k != 'cells'}, 'cells': cells})
    stage_rank = {s: i for i, s in enumerate(STAGE_ORDER)}
    out_rows.sort(key=lambda q: (stage_rank.get(q.get('stage'), len(STAGE_ORDER)),
                                 rm.VIS_TIER_ORDER.index(q['tier']) if q.get('tier') in rm.VIS_TIER_ORDER else 9,
                                 q.get('query_code') or ''))
    return {'surface': surface, 'agents': agents, 'rows': out_rows}


def visibility_by_stage(rows: List[dict], surface: str) -> dict:
    """First-pick share per stage and per tier on one surface: answered runs,
    ours named and first, and the brand first most often."""
    mine = [r for r in rows if _on(r.get('surface'), surface) and r.get('answered')]

    def block(subset):
        picks = _picks(subset)
        you = next((v for v in picks.values() if v['you']), {'named': 0, 'first': 0})
        top = max(((k, v['first']) for k, v in picks.items() if v['first']), key=lambda kv: (kv[1], kv[0]), default=None)
        return {'answered': len(subset), 'named': you['named'], 'first': you['first'],
                'top': {'name': top[0], 'first': top[1], 'you': picks[top[0]]['you']} if top else None}

    stages = [s for s in STAGE_ORDER if any(r.get('stage') == s for r in mine)]
    stages += sorted({r.get('stage') for r in mine if r.get('stage') and r.get('stage') not in STAGE_ORDER})
    tiers = [t for t in rm.VIS_TIER_ORDER if any(r.get('tier') == t for r in mine)]

    def by_stage(subset):
        return [{'stage': s, 'label': STAGE_LABELS.get(s, s), **block([r for r in subset if r.get('stage') == s])}
                for s in stages if any(r.get('stage') == s for r in subset)]
    # 2C-2a: the stage table follows the tier the reader picked (by_tier.<tier>,
    # 'all' for every tier); the tier table keeps every tier by definition.
    return {
        'surface': surface,
        'stages': by_stage(mine),
        'stages_by_tier': {'all': by_stage(mine), **{t: by_stage([r for r in mine if r.get('tier') == t]) for t in tiers}},
        'tiers': [{'tier': t, 'label': rm.VIS_TIER_LABELS.get(t, t), **block([r for r in mine if r.get('tier') == t])}
                  for t in tiers],
    }


def extend_visibility(body: dict, ours: Optional[str]) -> dict:
    """2C-2: headline, matrix and by_stage, per surface, beside 2C-1's read.
    2I-8: `all` first (body['surfaces'] lists it), and the default."""
    rows = body.get('byQuestion') or []
    surface_list = [s['surface'] for s in body.get('surfaces') or []]
    default = (body.get('ranking') or {}).get('surface')
    heads = {s: visibility_headline(rows, s, ours) for s in surface_list}
    body['headline'] = (heads.get(default) or {}).get('text', '')
    body['headlines'] = heads
    body['matrix'] = {s: visibility_matrix(rows, s) for s in surface_list}
    body['by_stage'] = {s: visibility_by_stage(rows, s) for s in surface_list}
    # 2N-1: a brand's ranking opens on its brand-choice answers, and the stage table can follow it
    if (body.get('ranking') or {}).get('default_tier') == rm.VIS_BRAND_CHOICE:
        for s in surface_list:
            mine = [r for r in rows if _on(r.get('surface'), s) and r.get('answered') and _brand_choice(r)]
            body['by_stage'][s]['stages_by_tier'][rm.VIS_BRAND_CHOICE] = visibility_by_stage(mine, s)['stages']
    return body


# ─── Overview ──────────────────────────────────────────────────────────────

def _empty_agent() -> dict:
    return {'answers': 0, 'named': 0, 'first': 0, 'named_of': 0, 'exact': 0, 'scored': 0, 'wrong': 0, 'stale': 0,
            'price_answered': 0,
            'partial': 0, 'unverifiable': 0, 'other_brand': 0, 'left_out': 0, 'unknown': 0, 'fabricated': 0,
            'brand_scored': 0,
            # 2K-1 (A9): `fabricated` counts the answers that stated an attribute (or whose
            # extraction cannot say); these stated none (soa_shared/claim_kinds.py)
            'recommended': 0}


def surface_metrics(rows: List[dict], vis_rows: List[dict], surface: str, *, tier: Optional[str] = None) -> dict:
    """Every count the Overview reads for one surface, in total and per agent.
    rows: one per run with tier, query_text, outcome, reason_code (load_overview_rows);
    vis_rows: Visibility's byQuestion. `tier` forces the named/first tier
    (the Changes block reads both cycles on the current cycle's); by default
    unprompted when the cycle asked any, else every answered run.

    Denominators, one per metric: named and first over answered runs of that
    tier (`named_of`); prices right and wrong over scored (exact, partial,
    stale, wrong); another brand's price over answered price questions
    (`price_answered`), since those runs are absent and never scored."""
    tier = tier or _tier_for_reads(vis_rows)
    total, per = _empty_agent(), {}
    comparison_answers = 0
    agents = set()
    for v in vis_rows:
        if not _on(v.get('surface'), surface) or not v.get('answered'):
            continue
        agents.add(v['agent'])
        for bucket in (total, per.setdefault(v['agent'], _empty_agent())):
            bucket['answers'] += 1
            if bucket is total and v.get('tier') == rm.COMPARISON:
                comparison_answers += 1
            if _in_tier(v, tier):
                bucket['named_of'] += 1
                bucket['named'] += int(any(n.get('you') for n in v.get('named') or []))
                bucket['first'] += int(bool((v.get('first') or {}).get('you')))
    for r in rows:
        if not _on(_surface_of(r), surface):
            continue
        agent = surfaces.agent_of(r.get('platform')) or r.get('platform')
        o, t = r.get('outcome'), r.get('tier')
        answered = r.get('answer_status') == surfaces.ANSWERED
        for bucket in (total, per.setdefault(agent, _empty_agent())):
            if t == 'brand_direct':
                if r.get('intent'):
                    continue   # 2N-1: a catalog-built question is outside the brand-claim counts
                if o in ('grounded', 'echoed', 'misattributed', 'fabricated', 'acknowledged_unknown'):
                    bucket['brand_scored'] += 1
                recommends = r.get('claim_kind') == claim_kinds.RECOMMENDATION_ONLY
                bucket['fabricated'] += int(o == 'fabricated' and not recommends)
                bucket['recommended'] += int(o == 'fabricated' and recommends)
                bucket['unknown'] += int(o == 'acknowledged_unknown')
                continue
            if t not in PRICE_TIERS:
                continue
            bucket['price_answered'] += int(answered)
            if o in SCORED:
                bucket['scored'] += 1
                bucket['exact'] += int(o == 'exact')
                bucket['wrong'] += int(o == 'wrong')
                bucket['stale'] += int(o == 'stale')
                bucket['partial'] += int(o == 'partial')
            elif o == 'unverifiable':
                bucket['unverifiable'] += 1
            elif o == 'absent':
                bucket['left_out'] += 1
                bucket['other_brand'] += int(r.get('reason_code') == 'other_brand')
    return {'tier': tier, 'total': total, 'agents': per, 'agent_set': sorted(agents),
            # 2K-1: answered comparison questions here, for the Changes rule
            'comparison_answers': comparison_answers}


def agent_note(m: dict) -> tuple:
    """(rule, sentence): the agent's highest-count problem, else how it did.
    Ties go to the order the rules are listed in."""
    problems = [('agent.other_brand', m['other_brand']), ('agent.wrong', m['wrong']), ('agent.unknown', m['unknown'])]
    rule, n = max(problems, key=lambda p: p[1])
    if n > 0:
        return rule, TEMPLATES[rule].format(n=n, questions=_n(n, 'question', 'questions'), prices=_n(n, 'price', 'prices'),
                                            times=_n(n, 'time', 'times'))
    if m['scored']:
        return 'agent.right', TEMPLATES['agent.right'].format(exact=m['exact'], scored=m['scored'])
    return 'agent.none', TEMPLATES['agent.none']


def _delta(now: int, prev: Optional[int]) -> tuple:
    if prev is None:
        return '', None
    d = now - prev
    return (f"+{d}" if d > 0 else str(d) if d < 0 else '0'), ('up' if d > 0 else 'down' if d < 0 else 'flat')


def build_agents(metrics: dict, prev: Optional[dict], status: str = 'compared') -> List[dict]:
    """AgentWeek per agent on the surface. 2C-2b: the per-agent change follows
    the Changes block's rule: a delta only when the two cycles are compared
    on this surface (changes_status), first picks over the same denominator
    as the block (named_of); otherwise `delta` is empty and `delta_status`
    says why ('first_cycle' | 'not_comparable')."""
    out = []
    for agent in sorted(metrics['agents'], key=lambda a: list(AGENT_NAMES).index(a) if a in AGENT_NAMES else 99):
        m = metrics['agents'][agent]
        rule, note = agent_note(m)
        p = ((prev or {}).get('agents') or {}).get(agent) if status == 'compared' else None
        delta, direction = _delta(m['first'], p['first'] if p else None)
        out.append(rm.compact({
            'agent': agent, 'answers': m['answers'], 'named': m['named'], 'first': m['first'],
            'pricesRight': f"{m['exact']} of {m['scored']}", 'wrong': m['wrong'], 'note': note,
            'delta': delta, 'dir': direction,
            # beside the typed fields
            'named_of': m['named_of'], 'exact': m['exact'], 'scored': m['scored'], 'stale': m['stale'],
            'unverifiable': m['unverifiable'], 'answered_with_other_brand': m['other_brand'],
            'did_not_know': m['unknown'], 'note_rule': rule,
            'delta_status': status if p is None or status != 'compared' else 'compared',
            'delta_detail': (TEMPLATES['changes.detail'].format(a=m['first'], of_now=m['named_of'], b=p['first'],
                                                                of_prev=p['named_of'], code=(prev or {}).get('code'))
                             if p else None),
        }, ('dir', 'delta_detail')))
    return out


def _money_text(value) -> Optional[str]:
    return rm.money(value) if value not in (None, '', '—') else None


def quote_groups(quotes: List[dict]) -> List[dict]:
    """2C-2b: the runs behind a product row, grouped by what they quoted (a
    sibling variant's price named), the runs with no price last. Every run
    is in exactly one group, so the groups sum to the row's runs."""
    # 2C-2c: a sibling is grouped by its resolved variant id, named once by
    # its record name, however each agent wrote it
    groups: Dict[tuple, Counter] = {}
    names: Dict[tuple, Optional[str]] = {}
    for q in quotes:
        sib = (q.get('swap_variant') or q.get('swap_product')) if q.get('stated') else None
        key = (q.get('stated'), sib)
        groups.setdefault(key, Counter())[q.get('agent') or 'unknown'] += 1
        names.setdefault(key, q.get('swap_product') if sib else None)
    out = [{'stated': stated, 'swap_product': names[(stated, sib)], 'swap_variant': sib if sib else None,
            'runs': sum(agents.values()), 'agents': dict(agents)}
           for (stated, sib), agents in groups.items()]
    out.sort(key=lambda g: (g['stated'] is None, -g['runs'], str(g['stated'])))
    return out


def _quoted_text(quotes: List[dict]) -> str:
    """Every distinct quote with the runs behind it and their agents, then
    the runs with no price, so the detail accounts for every run the issue
    counts. A price stated for a sibling variant names it (2C-2c: once, by
    its record name): "$6.99 for Snug-Fit Trial Pack, 3 of 6 runs (Gemini 3)"."""
    n = len(quotes)
    if not n:
        return 'Not asked'
    parts = []
    for g in quote_groups(quotes):
        who = ', '.join(f"{_agent(a)} {c}" for a, c in sorted(g['agents'].items(), key=lambda kv: _agent(kv[0])))
        what = 'No price' if g['stated'] is None else rm.money(g['stated']) + (f" for {g['swap_product']}" if g['swap_product'] else '')
        parts.append(f"{what}, {g['runs']} of {n} {_n(n, 'run', 'runs')} ({who})")
    return '. '.join(parts)


_SOURCE_WORDS = {'honest_fetch': 'our own fetch', 'hosted_render': 'a hosted render', 'record': 'the record'}


def _live_text(cell: dict, domain: str) -> str:
    """The reference beside a quote: the newest page read when one exists,
    else the record, saying which."""
    live = cell.get('live')
    if live in (None, '', '—'):
        return 'No reference read'
    if live == 'unverifiable':
        return f"Could not be read at {domain}"
    if live == rm.NOT_PRICED:
        return f"No price set at {domain}, the brand's own site, {_short_day(cell.get('observed_at'))}"
    how = _SOURCE_WORDS.get(cell.get('reference_source') or '', (cell.get('reference_source') or 'a read').replace('_', ' '))
    if cell.get('live_basis') == 'record' or cell.get('reference_source') == 'record':
        return f"{live} at {domain}, the record of {_short_day(cell.get('observed_at'))}, no page read yet"
    return f"{live} at {domain}, {how}, {_short_day(cell.get('observed_at'))}"


#: ProductWeek.status from the cell's status (types.ts has four).
PRODUCT_STATUS = {'exact': 'exact', 'wrong': 'wrong', 'stale': 'wrong', 'partial': 'partial',
                  'missed': 'none', 'none': 'none', 'unverifiable': 'none'}


_ASKED_PACK = re.compile(r"(\d+)\s*(?:ct|count)\b", re.I)


def pack_mismatch(quotes: List[dict], product: Optional[str]) -> Optional[dict]:
    """2Q-1 (B4): {quote, pack, asked, live, n} when most of the wrong quotes
    were for another pack (the price check's own reason, the quote's `pack`):
    the most common such quote, its pack, the asked pack ("104 ct", from the
    row's name, else "pack asked about") and the reference it was judged
    against. None otherwise."""
    wrong = [q for q in quotes if q.get('outcome') in ('wrong', 'stale')]
    packed = [q for q in wrong if q.get('pack') and q.get('stated') not in (None, '')]
    if not packed or len(packed) * 2 <= len(wrong):
        return None
    (stated, pack, live), n = Counter((q['stated'], q['pack'], q.get('live')) for q in packed).most_common(1)[0]
    counts = _ASKED_PACK.findall(product or '')
    return {'quote': rm.money(stated), 'pack': pack, 'asked': f"{counts[-1]} ct" if counts else 'pack asked about',
            'live': live if isinstance(live, str) and live.startswith('$') else 'the reference', 'n': n}


def wrong_quote(quotes: List[dict]) -> Optional[dict]:
    """2Q-2 (B2): {quote, live, n}, the most common wrong amount among the
    quotes and the reference it was judged against, or None (no wrong quote
    stated an amount). FL15's lead signal read "Quoted $44.99 against
    $44.99.": the cell's most quoted amount, an exact one (Amazon's), while
    the wrong quotes were $25, $27.97 and $23.79."""
    wrong = [q for q in quotes if q.get('outcome') in ('wrong', 'stale') and q.get('stated') not in (None, '')]
    if not wrong:
        return None
    (stated, live), n = Counter((q['stated'], q.get('live')) for q in wrong).most_common(1)[0]
    return {'quote': rm.money(stated), 'live': live if isinstance(live, str) and live.startswith('$') else 'the reference',
            'n': n}


_SIZE_WORDS = re.compile(r"\b(size\s*\d+\+?|newborn|preemie)\b", re.I)
_COUNT_WORDS = re.compile(r"(\d+)\s*-?\s*(?:ct|count)\b", re.I)


def variant_words(text: Optional[str]) -> Optional[str]:
    """2R-2 (B5): "Pampers ZZZ Size 3, 116-count" -> "Size 3, 116 ct": the size
    and the count a product's words name, None when they name neither."""
    size = _SIZE_WORDS.search(text or '')
    count = _COUNT_WORDS.findall(text or '')
    words = []
    if size:
        word = re.sub(r'\s+', ' ', size.group(1))
        words.append('Size ' + word[4:].strip() if word.lower().startswith('size') else word.capitalize())
    if count:
        words.append(f"{count[-1]} ct")
    return ', '.join(words) or None


def variant_clash(quotes: List[dict], product: Optional[str]) -> Optional[dict]:
    """2R-2 (B5): {quote, named, asked, live, n} when the top wrong quote
    (wrong_quote's amount) was judged wrong because it named a variant the
    record does not have (reason variant_clash, the claim's own words on the
    quote's `clash`): the variant it named ("Size 3, 116 ct"), the variant
    asked about from the row's name ("Size 4, 104 ct", else "variant asked
    about"). None otherwise; a quote for another pack is pack_mismatch's."""
    top = wrong_quote(quotes)
    if top is None:
        return None
    wrong = [q for q in quotes if q.get('outcome') in ('wrong', 'stale') and q.get('stated') not in (None, '')]
    (stated, live), _n = Counter((q['stated'], q.get('live')) for q in wrong).most_common(1)[0]
    group = [q for q in wrong if (q['stated'], q.get('live')) == (stated, live)]
    clashed = [q for q in group if q.get('clash')]
    if not clashed or len(clashed) * 2 <= len(group):
        return None
    named, n = Counter(q['clash'] for q in clashed).most_common(1)[0]
    return {'quote': top['quote'], 'named': variant_words(named) or named,
            'asked': variant_words(product) or 'variant asked about', 'live': top['live'], 'n': n}


def _pack_field(quotes: List[dict], product: Optional[str]) -> dict:
    """{'pack_mismatch': ...} beside a product's typed fields, only when there
    is one; 2Q-2 (B2): and {'wrong_quote': ...}, the signal's amount; 2R-2
    (B5): and {'variant_clash': ...} when the top wrong quote named another
    variant (never beside a pack_mismatch, which reads first)."""
    pack, wrong = pack_mismatch(quotes, product), wrong_quote(quotes)
    clash = None if pack else variant_clash(quotes, product)
    return {**({'pack_mismatch': pack} if pack else {}), **({'wrong_quote': wrong} if wrong else {}),
            **({'variant_clash': clash} if clash else {})}


def product_issue(quotes: List[dict], product: Optional[str] = None) -> tuple:
    """(rule, issue sentence). 2N-1: product.unverifiable only when every
    retailer the row was asked at could not be read; otherwise the rule over
    the quotes at the retailers that were, those that were not named after
    it ("Right in 12 of 12 runs. Target could not be read.")."""
    runs = len(quotes)
    if not runs:
        return 'product.not_asked', TEMPLATES['product.not_asked']
    by: Dict[str, List[dict]] = {}
    for q in quotes:
        by.setdefault(str(q.get('retailer')), []).append(q)
    walled = sorted(r for r, qs in by.items() if all(q.get('outcome') == 'unverifiable' for q in qs))
    checked = [q for q in quotes if str(q.get('retailer')) not in walled]
    if not checked:
        n = sum(1 for q in quotes if q.get('outcome') == 'unverifiable')
        return 'product.unverifiable', TEMPLATES['product.unverifiable'].format(n=n, runs=runs, runs_word=_n(runs, 'run', 'runs'))
    counts = {
        'product.other_brand': sum(1 for q in checked if q.get('outcome') == 'absent' and q.get('reason') == 'other_brand'),
        'product.wrong': sum(1 for q in checked if q.get('outcome') in ('wrong', 'stale')),
        'product.left_out': sum(1 for q in checked if q.get('outcome') == 'absent' and q.get('reason') != 'other_brand'),
    }
    rule, n = max(counts.items(), key=lambda kv: kv[1])
    asked = len(checked)
    word = _n(asked, 'run', 'runs')
    pack = pack_mismatch(checked, product) if rule == 'product.wrong' and n else None
    clash = variant_clash(checked, product) if rule == 'product.wrong' and n and not pack else None
    if pack:
        # the runs quoted for the other pack, never every wrong run beside them
        issue = TEMPLATES['product.wrong_pack'].format(**pack, runs=asked, runs_word=word)
    elif clash:
        # 2R-2 (B5): the runs that quoted it for the variant they named
        issue = TEMPLATES['product.wrong_clash'].format(**clash, runs=asked, runs_word=word)
    elif n:
        wrong = wrong_quote(checked) if rule == 'product.wrong' else None
        issue = (TEMPLATES['product.wrong_quote'].format(n=n, runs=asked, runs_word=word, quote=wrong['quote'], live=wrong['live'])
                 if wrong else
                 TEMPLATES[rule].format(n=n, runs=asked, runs_word=word))
    else:
        rule = 'product.right'
        right = sum(1 for q in checked if q.get('outcome') == 'exact')
        issue = TEMPLATES['product.right'].format(n=right, runs=asked, runs_word=word)
    names = [r for r in walled if r != 'None']
    if names:
        issue += ' ' + TEMPLATES['product.walled'].format(retailers=_retailers_text(names))
    return rule, issue


#: 2N-1: the CHECK column's status follows the row's issue rule, never a
#: worse cell's: a row whose issue is "No price quoted in 12 of 18 runs" reads
#: No price, not Wrong price. A right row keeps its cells' exact or partial.
RULE_STATUS = {'product.wrong': 'wrong', 'product.other_brand': 'wrong', 'product.left_out': 'none',
               'product.unverifiable': 'none', 'product.not_asked': 'none'}


def status_for(rule: str, cell_status: str) -> str:
    if rule in RULE_STATUS:
        return RULE_STATUS[rule]
    status = PRODUCT_STATUS.get(cell_status, 'none')
    return status if status in ('exact', 'partial') else 'exact'


def _retailers_text(domains: List[str]) -> str:
    names = sorted({rm._retailer_name(d) for d in domains})
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def _quoted_across_text(quotes: List[dict]) -> str:
    """2J-2: _quoted_text for a product read across retailers: each quote
    names the retailers it was quoted at, "Walmart $24.97, 2 of 12 runs
    (ChatGPT 1, Google AI Mode 1). Amazon and Walmart $27.97, ...". The runs
    with no price are last and name no retailer."""
    n = len(quotes)
    if not n:
        return 'Not asked'
    parts = []
    for g in quote_groups(quotes):
        sib = g['swap_variant'] or g['swap_product']
        at = [q['retailer'] for q in quotes if q.get('stated') == g['stated']
              and ((q.get('swap_variant') or q.get('swap_product')) if q.get('stated') else None) == sib]
        who = ', '.join(f"{_agent(a)} {c}" for a, c in sorted(g['agents'].items(), key=lambda kv: _agent(kv[0])))
        what = ('No price' if g['stated'] is None else
                f"{_retailers_text(at)} {rm.money(g['stated'])}" + (f" for {g['swap_product']}" if g['swap_product'] else ''))
        parts.append(f"{what}, {g['runs']} of {n} {_n(n, 'run', 'runs')} ({who})")
    return '. '.join(parts)


#: worst first: a product read across retailers takes its worst cell's status
_PRODUCT_SEVERITY = {'wrong': 0, 'partial': 1, 'none': 2, 'exact': 3}


def build_products(true_value: dict, vis_rows: List[dict], surface: str, *, variant_of_run: Dict[str, str],
                   reason_of_run: Dict[str, Optional[str]]) -> List[dict]:
    """ProductWeek per True Value row asked about on this surface: named and
    first from the mention coding of the runs that asked about it, the
    quotes per agent, the live price with its source, the cell's status
    (TV_CELL_RULE) and the issue.

    2J-2: the row reads its `you` cell when that cell has quotes on the
    surface. A brand's `you` cell is its own site, which no agent quotes
    (it sets no price), so with none there the row reads the retailer cells
    together: every quote, each naming its retailer; `live` each retailer's
    live price; the status the worst cell's; the issue over every quote.
    A store's `you` cell (the store) has the quotes and reads as before."""
    retailer_cols = true_value.get('retailer_columns') or true_value.get('columns') or []
    you_col = next((c['id'] for c in retailer_cols if c.get('you')), None)
    vis_by_run = {v['run']: v for v in vis_rows}

    def quotes_of(cell, col):
        return [{**q, 'reason': reason_of_run.get(q.get('run')), 'retailer': col, 'live': cell.get('live')}
                for q in cell.get('quotes') or [] if _on(q.get('surface'), surface)]

    def counts(quotes):
        runs = [vis_by_run[q['run']] for q in quotes if q.get('run') in vis_by_run]
        answered = [v for v in runs if v.get('answered')]
        return answered, {
            'named': sum(1 for v in answered if any(n.get('you') for n in v.get('named') or [])),
            'first': sum(1 for v in answered if (v.get('first') or {}).get('you')),
        }

    out = []
    for row in true_value.get('rows') or []:
        # 2C-2a: with agent columns, the product reads its one-retailer cell
        cells_by = row.get('retailer_cells') or row['cells']
        if you_col in cells_by and not quotes_of(cells_by[you_col], you_col):
            across = [(col, cell, quotes_of(cell, col)) for col, cell in cells_by.items() if col != you_col]
            across = [(col, cell, qs) for col, cell, qs in across if qs]
            if across:
                out.append(_product_across(row, across, surface, counts))
            continue
        cols = [you_col] if you_col in cells_by else list(cells_by)
        for col in cols:
            cell = cells_by[col]
            quotes = quotes_of(cell, col)
            if not quotes:
                continue
            sc = (cell.get('by_surface') or {}).get(surface) or {}
            answered, nf = counts(quotes)
            rule, issue = product_issue(quotes, row['product'])
            status = sc.get('status') or 'none'
            out.append({
                'name': row['product'], 'sku': row['sku'],
                'named': nf['named'], 'first': nf['first'],
                'quoted': _quoted_text(quotes), 'live': _live_text(cell, col),
                'status': status_for(rule, status), 'issue': issue, 'route': 'true-value',
                # beside the typed fields
                'cell_status': status, 'quote': sc.get('quoted'), 'retailer': col, 'runs': len(quotes),
                'answered': len(answered), 'issue_rule': rule,
                'wrong_runs': sum(1 for q in quotes if q.get('outcome') in ('wrong', 'stale')),
                'reference_source': cell.get('reference_source'), 'observed_at': cell.get('observed_at'),
                'live_price': cell.get('live'),
                # 2T-4 (3): the page read after the one the runs were judged against, its own line
                **({'live_later': cell['later']['text']} if cell.get('later') else {}),
                'answer_ids': [q['run'] for q in quotes if q.get('run')],
                'quote_groups': quote_groups(quotes),
                **_pack_field(quotes, row['product']),
            })
    out.sort(key=lambda p: (_PRODUCT_SEVERITY.get(p['status'], 4), -p['wrong_runs'], -p['named'], p['name']))
    return out


def _product_across(row: dict, across: List[tuple], surface: str, counts) -> dict:
    """2J-2: one ProductWeek over a row's retailer cells (col, cell, quotes),
    for a `you` cell no agent quoted. `retailer` and the reference fields
    beside the typed ones are the worst cell's; `retailers` lists each
    cell's quote, status and live price."""
    def status_of(cell):
        return ((cell.get('by_surface') or {}).get(surface) or {}).get('status') or 'none'

    worst_col, worst_cell, _ = min(across, key=lambda a: _PRODUCT_SEVERITY.get(PRODUCT_STATUS.get(status_of(a[1]), 'none'), 4))
    quotes = [q for _col, _cell, qs in across for q in qs]
    answered, nf = counts(quotes)
    rule, issue = product_issue(quotes, row['product'])
    status = status_of(worst_cell)
    return {
        'name': row['product'], 'sku': row['sku'],
        'named': nf['named'], 'first': nf['first'],
        'quoted': _quoted_across_text(quotes),
        'live': '. '.join(_live_text(cell, col) for col, cell, _qs in across),
        'status': status_for(rule, status), 'issue': issue, 'route': 'true-value',
        # beside the typed fields
        'cell_status': status, 'quote': ((worst_cell.get('by_surface') or {}).get(surface) or {}).get('quoted'),
        'retailer': worst_col, 'runs': len(quotes), 'answered': len(answered), 'issue_rule': rule,
        'wrong_runs': sum(1 for q in quotes if q.get('outcome') in ('wrong', 'stale')),
        'reference_source': worst_cell.get('reference_source'), 'observed_at': worst_cell.get('observed_at'),
        'live_price': worst_cell.get('live'),
        'answer_ids': [q['run'] for q in quotes if q.get('run')],
        'quote_groups': quote_groups(quotes),
        **_pack_field(quotes, row['product']),
        'read_across': True,
        # 2T-4 (3): each retailer's later page read, named, when one exists
        **({'live_later': '. '.join(f"{rm._retailer_name(col)}: {cell['later']['text']}"
                                    for col, cell, _qs in across if cell.get('later'))}
           if any(cell.get('later') for _col, cell, _qs in across) else {}),
        'retailers': [{'retailer': col, 'name': rm._retailer_name(col), 'runs': len(qs),
                       'quote': ((cell.get('by_surface') or {}).get(surface) or {}).get('quoted'),
                       'cell_status': status_of(cell), 'live_price': cell.get('live'),
                       'reference_source': cell.get('reference_source'), 'observed_at': cell.get('observed_at'),
                       **({'live_later': cell['later']['text']} if cell.get('later') else {})}
                      for col, cell, qs in across],
    }


def build_signals(metrics: dict, products: List[dict], *, surface: str, brand: str, cycle_start,
                  access_problems: List[dict]) -> List[dict]:
    """At most four, from fixed rules in priority order: another brand's
    price (>= 5), fabricated brand-direct facts (>= 5), wrong prices on one
    product (>= 3), any unverifiable price, any access problem."""
    t, per = metrics['total'], metrics['agents']
    where = _on_words(surface)
    out = []
    if t['other_brand'] >= 5:
        title, detail = TEMPLATES['signal.other_brand']
        asked = t['scored'] + t['left_out'] + t['unverifiable']
        out.append({'id': 'other_brand', 'title': title.format(n=t['other_brand'], questions=_n(t['other_brand'], 'question', 'questions')),
                    'detail': detail.format(n=t['other_brand'], asked=asked, on=where,
                                            split=_split({a: m['other_brand'] for a, m in per.items()})),
                    'tag': 'Lost pool', 'tone': 'bad', 'route': 'answers', 'rule': 'other_brand', 'count': t['other_brand']})
    if t['fabricated'] >= 5:
        title, detail = TEMPLATES['signal.fabricated']
        text_ = detail.format(n=t['fabricated'], asked=t['brand_scored'], on=where,
                              split=_split({a: m['fabricated'] for a, m in per.items()}))
        start = _day(cycle_start)
        if start is None or start < GROUNDING_SOURCES_FROM:
            text_ += ' ' + TEMPLATES['signal.fabricated_caveat']
        signal = {'id': 'fabricated', 'title': title.format(n=t['fabricated'], brand=brand), 'detail': text_,
                  'tag': 'Missed pool', 'tone': 'bad', 'route': 'answers', 'rule': 'fabricated', 'count': t['fabricated']}
        if t.get('recommended'):
            # 2K-1: the classifier's `fabricated` also holds answers that only recommended the
            # brand; counted apart, on a second line, and never in the headline
            signal['recommended'] = {'count': t['recommended'],
                                     'line': TEMPLATES['signal.fabricated_recommended'].format(n=t['recommended'], brand=brand)}
        out.append(signal)
    worst = max(products, key=lambda p: (p['wrong_runs'], p['name']), default=None)
    if worst and worst['wrong_runs'] >= 3:
        title, detail = TEMPLATES['signal.wrong_product']
        pack, wrong = worst.get('pack_mismatch'), worst.get('wrong_quote') or {}
        clash = worst.get('variant_clash')
        out.append({'id': f"wrong:{worst['sku']}", 'title': title.format(product=worst['name'], n=worst['wrong_runs']),
                    # 2Q-1 (B4): a quote for another pack says so, with both packs
                    'detail': TEMPLATES['signal.wrong_product_pack'].format(**pack, split=worst['quoted']) if pack else
                    # 2R-2 (B5): a quote for a variant the record does not have says which
                    TEMPLATES['signal.wrong_product_clash'].format(**clash, split=worst['quoted']) if clash else
                    # 2Q-2 (B2): the most common wrong amount, never the most quoted one
                    detail.format(quote=wrong.get('quote') or 'a price', live=wrong.get('live') or 'the reference',
                                  split=worst['quoted']),
                    'tag': 'Missed pool', 'tone': 'bad', 'route': 'true-value', 'rule': 'wrong_product',
                    'count': worst['wrong_runs'], **({'answerId': worst['answer_ids'][0]} if worst['answer_ids'] else {})})
    if t['unverifiable'] > 0:
        title, detail = TEMPLATES['signal.unverifiable']
        out.append({'id': 'unverifiable', 'title': title.format(n=t['unverifiable'], prices=_n(t['unverifiable'], 'price', 'prices')),
                    'detail': detail.format(split=_split({a: m['unverifiable'] for a, m in per.items()})),
                    'tag': 'Access', 'tone': 'warn', 'route': 'true-value', 'rule': 'unverifiable', 'count': t['unverifiable']})
    if access_problems:
        title, detail = TEMPLATES['signal.access']
        # 2K-4 (B4): each display name once, its tokens counted ("Googlebot (2 tokens)")
        groups = rm.group_identities(access_problems)
        n = len(groups)
        out.append({'id': 'access', 'title': title.format(n=n, identities=_n(n, 'identity', 'identities')),
                    'detail': detail.format(who=', '.join(g['label'] for g in groups)),
                    'tag': 'Access', 'tone': 'bad', 'route': 'accessibility', 'rule': 'access', 'count': n})
    return out[:4]


def build_summary(metrics: dict, headline: dict, signals: List[dict], surface: Optional[str] = None) -> dict:
    """Three or four sentences: visibility (and the rivals), accuracy, then
    the top signal the sentences before it have not already stated. When
    every signal is already stated, there is no last sentence."""
    t = metrics['total']
    words = _answers(headline['tier'])
    if headline['first'] and not any(r['first'] >= headline['first'] for r in headline['rivals']):
        vis = TEMPLATES['summary.visibility_lead'].format(first=headline['first'], n=headline['denom'], answers=words)
    else:
        vis = TEMPLATES['summary.visibility_named'].format(named=headline['named'], n=headline['denom'],
                                                          first=headline['first'], answers=words)
        if headline['rivals']:
            r = headline['rivals']
            rest = f", {r[1]['name']} in {r[1]['first']}" if len(r) > 1 else ''
            vis += ' ' + TEMPLATES['summary.rivals'].format(lead=r[0]['name'], k=r[0]['first'], rest=rest)
    stated = set()
    if not t['scored'] and not t['unverifiable']:
        acc = TEMPLATES[_rule('summary.no_price', surface)]
    elif t['unverifiable']:
        acc = TEMPLATES['summary.accuracy_unverifiable'].format(exact=t['exact'], scored=t['scored'], other=t['other_brand'],
                                                                u=t['unverifiable'])
        stated |= {'other_brand', 'unverifiable'}
    else:
        acc = TEMPLATES['summary.accuracy'].format(exact=t['exact'], scored=t['scored'], other=t['other_brand'])
        stated |= {'other_brand'}
    lines = [vis, acc]
    fresh = [s for s in signals if s.get('rule') not in stated]
    if fresh:
        lines.append(fresh[0]['title'])
    elif not signals:
        lines.append(TEMPLATES['summary.no_signal'])
    return {'lines': lines, 'text': ' '.join(lines), 'signal': fresh[0].get('id') if fresh else None}


#: The metrics compared cycle to cycle: (key, label, better when it goes up,
#: the denominator). One denominator rule per metric, the same in both cycles.
CHANGE_METRICS = (
    ('named', 'Named', True, 'named_of'), ('first', 'First pick', True, 'named_of'),
    ('exact', 'Prices right', True, 'scored'),
    ('other_brand', "Answered with another brand's price", False, 'price_answered'),
    ('wrong', 'Wrong prices', False, 'scored'),
)


def _agents_text(agents: Iterable[str]) -> str:
    names = [_agent(a) for a in sorted(agents, key=_agent)]
    return ' and '.join(names) if len(names) < 3 else ', '.join(names[:-1]) + ' and ' + names[-1]


def changes_status(now: dict, prev: Optional[dict], prev_code: Optional[str],
                   surface: Optional[str] = None) -> tuple:
    """('first_cycle' | 'not_comparable' | 'compared', note). Two cycles are
    compared on a surface only when the same agents answered there and both
    read named/first over the same tier; otherwise the block says why and
    shows no delta. 2I-8: on `all`, when the same agents answered in both
    cycles, whatever their surfaces; the note then names no surface.

    2K-4 (B1): soa_shared/cycle_compare.cycles_comparable decides, as it does
    for the score and the revenue history: first the study (a metrics dict
    carries `study` and `questions` when build_overview was given them),
    then the agents, then the set the first-pick numbers read."""
    return changes_check(now, prev, prev_code, surface)[:2]


def changes_check(now: dict, prev: Optional[dict], prev_code: Optional[str],
                  surface: Optional[str] = None) -> tuple:
    """changes_status with the condition that failed (cycle_compare's), or None."""
    if prev is None:
        return 'first_cycle', TEMPLATES['changes.first_cycle'], None
    ok, condition, reason = cycle_compare.cycles_comparable(
        comparison_facts('this cycle', now), comparison_facts(prev_code, prev, measured=True),
        on='' if surface == ALL else ' on this surface', agent_name=_agent)
    return ('compared', None, None) if ok else ('not_comparable', reason, condition)


def comparison_facts(code: Optional[str], metrics: dict, *, measured: bool = False) -> dict:
    """2K-4: a surface_metrics dict as cycle_compare reads it: its study
    and questions (when given), 2P-1: the version its outcomes compare under
    (console_score.outcomes_version, when given), the agents that answered, the set it reads
    and, for the earlier cycle, how many answers it has in each set."""
    return cycle_compare.facts(code or 'the previous cycle', study=metrics.get('study'), questions=metrics.get('questions'),
                               scorer_version=metrics.get('scorer_version'),
                               agents={'here': metrics['agent_set']}, reads=metrics['tier'],
                               measured={UNPROMPTED: metrics['total']['named_of'],
                                         'comparison': metrics.get('comparison_answers', 0)} if measured else None)


def build_changes(now: dict, prev: Optional[dict], prev_code: Optional[str],
                  surface: Optional[str] = None) -> List[dict]:
    """Each metric this cycle against the previous scored one, both on the
    same surface and agent set, each over its own denominator (CHANGE_METRICS).
    [] unless changes_status says 'compared'."""
    if changes_status(now, prev, prev_code, surface)[0] != 'compared':
        return []
    out = []
    for key, label, up_good, denom in CHANGE_METRICS:
        a, b = now['total'][key], prev['total'][key]
        delta, direction = _delta(a, b)
        tone = 'neu' if direction == 'flat' else ('ok' if (direction == 'up') == up_good else 'bad')
        out.append({'label': label, 'delta': delta, 'dir': direction, 'tone': tone,
                    'detail': TEMPLATES['changes.detail'].format(a=a, of_now=now['total'][denom], b=b,
                                                                 of_prev=prev['total'][denom], code=prev_code),
                    'route': 'visibility' if key in ('named', 'first') else 'true-value',
                    'metric': key, 'now': a, 'prev': b, 'of_now': now['total'][denom], 'of_prev': prev['total'][denom]})
    return out


def build_overview(cycle: dict, *, rows: List[dict], visibility: dict, true_value: dict, brand: str,
                   access: Optional[dict] = None, previous: Optional[dict] = None,
                   scored_cycles: int = 1, read_errors: Optional[Dict[str, str]] = None,
                   study_questions: Optional[int] = None, study: Optional[dict] = None) -> dict:
    """
    GET /api/console/overview: This week's blocks for one cycle, per surface.
    2I-8: `all` first (every agent together, as the demo counts them) and the
    default; each surface's blocks beside it, for the console's filter.

    rows: load_overview_rows (one per run). visibility: the 2C-1 read with
    extend_visibility applied. true_value: build_true_value. access: supply's
    access payload, or None. previous: {'code', 'rows', 'visibility'} for the
    newest earlier scored cycle, or None. 2K-4: study ({'study',
    'questions'}) and previous['study'] feed the comparability rule.
    """
    vis_rows = visibility.get('byQuestion') or []
    surface_list = surfaces.with_all(ordered_surfaces({_surface_of(r) for r in rows} | {v['surface'] for v in vis_rows}))
    default = (visibility.get('ranking') or {}).get('surface') or (surface_list[0] if surface_list else None)
    variant_of_run = {f"run-{r['run_id']}": r.get('variant_id') for r in rows}
    reason_of_run = {f"run-{r['run_id']}": r.get('reason_code') for r in rows}
    requests = ((access or {}).get('accessibility') or access or {}).get('requests') or []
    access_problems = [r for r in requests if not r.get('ok') and _measured(r)]
    by_surface = {}
    for s in surface_list:
        metrics = surface_metrics(rows, vis_rows, s)
        prev_metrics = (surface_metrics(previous['rows'], previous['visibility'].get('byQuestion') or [], s, tier=metrics['tier'])
                        if previous else None)
        metrics.update(study or {})
        if prev_metrics is not None:
            prev_metrics.update(previous.get('study') or {})
        # 2T-7 (2): the copy names the previous cycle by its day (rm.cycle_label's name)
        prev_name = (previous or {}).get('name') or (previous or {}).get('code')
        status, note, condition = changes_check(metrics, prev_metrics, prev_name, s)
        if prev_metrics is not None:
            prev_metrics['code'] = prev_name
        head = visibility_headline(vis_rows, s, next((r['name'] for r in (visibility.get('ranking') or {}).get('rows') or [] if r.get('you')), None))
        products = build_products(true_value, vis_rows, s, variant_of_run=variant_of_run, reason_of_run=reason_of_run)
        signals = build_signals(metrics, products, surface=s, brand=brand, cycle_start=cycle.get('start_date'),
                                access_problems=access_problems)
        by_surface[s] = {
            'agents': build_agents(metrics, prev_metrics, status),
            'products': products,
            'signals': signals,
            'summary': build_summary(metrics, head, signals, s),
            'changes': build_changes(metrics, prev_metrics, prev_name, s),
            'changes_status': status,
            'changes_note': note,
            # 2P-1: the condition cycle_compare named, when not comparable
            'changes_condition': condition,
            'totals': metrics['total'],
            'tier': metrics['tier'],
        }
    answered = [v for v in vis_rows if v.get('answered')]
    # 2C-2b, one rule for every count on the Overview: runs are the rows the
    # cycle executed (an errored run included), answers the runs with an
    # answer; the tier and agent tables count answers.
    return {
        'cycle': cycle['cycle_code'],
        'started': rm._iso(cycle.get('start_date')),
        'surface': default,
        'surfaces': [{'surface': s, 'label': surfaces.SURFACE_LABELS.get(s, s)} for s in surface_list],
        'by_surface': by_surface,
        'scored_cycles': scored_cycles,
        'previous_cycle': (previous or {}).get('code'),
        # 2T-7 (2): the previous cycle's label for the console's headers ("Against Oct 14"), rm.cycle_label
        'previous_label': (previous or {}).get('label'),
        'changes_note': None if previous else TEMPLATES['changes.first_cycle'],
        'ranking': visibility.get('ranking'),
        # 2C-2c: questions is the study's count, the one Studies shows; asked
        # is how many of them this cycle ran
        'coverage': {'questions': study_questions if study_questions is not None else len({r.get('query_code') for r in rows}),
                     'asked': len({r.get('query_code') for r in rows}), 'agents': len({surfaces.agent_of(r.get('platform')) or r.get('platform') for r in rows}),
                     'runs': len(rows), 'answers': sum(1 for r in rows if r.get('answer_status') == surfaces.ANSWERED),
                     'unprompted': sum(1 for v in answered if _unprompted(v)),
                     # 2K-1: with a comparison question, the brand-choice answers the first picks count over
                     **({'brand_choice': sum(1 for v in answered if _brand_choice(v))}
                        if any(v.get('tier') == rm.COMPARISON for v in answered) else {})},
        'access_run': (access or {}).get('access_run'),
        'read_errors': read_errors or {},
        'rules': {k: v for k, v in TEMPLATES.items()},
    }


# ─── Accessibility checks ──────────────────────────────────────────────────

def _measured(request: dict) -> bool:
    """An identity whose probe was never configured is not measured, which
    is not a problem: it never counts as one (rm.access_measured)."""
    return rm.access_measured(request)


def _check(name, got, of, *, good_when_zero=False, unit='pages', key=None):
    if not of:
        return {'name': name, 'value': f"no {unit} read", 'status': 'not_checked', 'checked': False, 'key': key}
    if good_when_zero:
        status = 'ok' if got == 0 else 'bad' if got == of else 'partial'
    else:
        status = 'ok' if got == of else 'bad' if got == 0 else 'partial'
    return {'name': name, 'value': f"{got} of {of}", 'status': status, 'checked': True, 'got': got, 'of': of, 'key': key}


NOT_CHECKED = [
    ('robots', 'robots.txt names answer-time agents',
     "supply's access payload carries no robots roll-up (a supply before #21)"),
    ('signed_agents', 'Edge lets signed agents in', 'no domain checks on a cycle for this merchant yet'),
    ('protocol', 'Protocol profile (UCP, MCP, llms.txt)', 'no domain checks on a cycle for this merchant yet'),
]
_CHECK_NAMES = {key: name for key, name, _ in NOT_CHECKED}

#: 2E: the signed-agent probe's outcomes (apps/pipeline/scoring/domain_checks.py), as the row reads them.
SIGNED_PROBE = {
    'both_in': ('signed and unsigned both read', 'ok'),
    'signed_only': ('signed read, unsigned refused', 'ok'),
    'unsigned_only': ('signed refused, unsigned read', 'bad'),
    'neither': ('signed and unsigned both refused', 'bad'),
}
_PROTOCOL_WORDS = {'pass': 'yes', 'fail': 'no', 'na': 'not verified'}


def _not_checked(key: str, why: str) -> dict:
    return {'name': _CHECK_NAMES[key], 'value': 'not checked', 'status': 'not_checked', 'checked': False,
            'key': key, 'basis': why}


def robots_check(roll_up: Optional[list], own_domains: Optional[List[str]]) -> dict:
    """'robots.txt names answer-time agents: N of M' on the merchant's own
    domain, from supply #21's robots_by_domain (N: answer-time tokens with
    their own User-agent group, M: the run's answer-time tokens)."""
    key = 'robots'
    if roll_up is None:
        return _not_checked(key, dict((k, w) for k, _, w in NOT_CHECKED)[key])
    if not roll_up:
        return _not_checked(key, 'no access run yet')
    own = [d for d in own_domains or [] if d]
    entry = next((e for d in own for e in roll_up if (e.get('retailer_domain') or '').removeprefix('www.') == d), None)
    if entry is None and not own and len(roll_up) == 1:
        entry = roll_up[0]
    if entry is None:
        where = ', '.join(own) or "the merchant's own domain"
        return _not_checked(key, f"the access run read no robots.txt on {where}")
    domain = entry.get('retailer_domain')
    if entry.get('named') is None or not entry.get('total'):
        return _not_checked(key, f"robots.txt on {domain} was {entry.get('robots_status') or 'not read'}, so it was not checked")
    n, m = entry['named'], entry['total']
    value = f"{n} of {m}" + (', wildcard only' if entry.get('wildcard_only') else '')
    return {'name': _CHECK_NAMES[key], 'value': value, 'status': 'ok' if n == m else 'bad' if n == 0 else 'partial',
            'checked': True, 'got': n, 'of': m, 'key': key,
            'basis': f"{entry.get('robots_url') or domain}: answer-time tokens with their own User-agent group, "
                     f"of the access run's answer-time tokens"}


def signed_agents_check(record: Optional[dict], cycle_code: Optional[str]) -> dict:
    """'Edge lets signed agents in', from the domain checks' signed probe:
    the merchant's product page fetched signed (Web Bot Auth) and unsigned,
    the same UA. Not an Audit dimension, never in the score."""
    key = 'signed_agents'
    probe = (record or {}).get('signed_probe')
    if not isinstance(probe, dict):
        return _not_checked(key, dict((k, w) for k, _, w in NOT_CHECKED)[key])
    if probe.get('outcome') not in SIGNED_PROBE:
        return _not_checked(key, probe.get('reason') or 'the probe did not run')
    value, status = SIGNED_PROBE[probe['outcome']]
    when = str((record or {}).get('checked_at') or '')[:10]
    return {'name': _CHECK_NAMES[key], 'value': value, 'status': status, 'checked': True, 'key': key,
            'basis': f"{probe.get('url')} fetched once signed (Web Bot Auth) and once unsigned, the same UA, "
                     f"for cycle {cycle_code} on {when}"}


def protocol_check(record: Optional[dict], cycle_code: Optional[str]) -> dict:
    """'Protocol profile (UCP, MCP, llms.txt)': the Audit's Protocol & Feed
    sub-checks on the scored domain, from the domain checks."""
    from app.services.lite_pillars import _protocol_feed_checks

    key = 'protocol'
    dim = (record or {}).get('protocol_feed')
    if not isinstance(dim, dict):
        return _not_checked(key, dict((k, w) for k, _, w in NOT_CHECKED)[key])
    evidence = list(dim.get('evidence') or [])
    if dim.get('coverage') == 'na':
        return {**_not_checked(key, evidence[0] if evidence else 'not applicable'), 'value': 'not applicable'}
    checks = {c['code']: c['state'] for c in _protocol_feed_checks(evidence)}
    value = ', '.join(f"{label} {_PROTOCOL_WORDS.get(checks.get(code), 'no')}"
                      for code, label in (('ucp', 'UCP'), ('mcp', 'MCP'), ('llms_txt', 'llms.txt')))
    passed = sum(1 for v in checks.values() if v == 'pass')
    verifiable = sum(1 for v in checks.values() if v in ('pass', 'fail'))
    status = 'ok' if verifiable and passed == verifiable else 'bad' if passed == 0 else 'partial'
    return {'name': _CHECK_NAMES[key], 'value': value, 'status': status, 'checked': True, 'got': passed,
            'of': verifiable, 'key': key,
            'basis': f"the Audit's Protocol & Feed checks on {(record or {}).get('scored_domain')}, "
                     f"for cycle {cycle_code} on {str((record or {}).get('checked_at') or '')[:10]}"}


def build_access_checks(reference: Optional[dict], *, robots: Optional[list] = None,
                        own_domains: Optional[List[str]] = None, domain_checks: Optional[dict] = None,
                        domain_cycle: Optional[str] = None) -> List[dict]:
    """The merchant-level checks, from the latest 2A reference read: one row
    per page read. A check the reads cannot answer is 'not_checked' with the
    reason, so the list keeps the demo's shape without claiming a result.
    2E: robots from supply #21's roll-up, the signed probe and the protocol
    profile from the newest cycle's domain checks."""
    rows = (reference or {}).get('rows') or []
    pages = [r for r in rows if r.get('read_status') in ('ok', 'empty')]
    with_markup = [r for r in pages if r.get('method') == 'json_ld']
    # 2C-2a: over every page read, like the other markup checks. A page has
    # its GTIN in markup when its record carries one, it was read with
    # structured data and no gtin_missing_on_page finding says otherwise.
    gtin_ok = [r for r in pages if r.get('gtin') and not any(
        f.get('finding') in ('no_structured_data', 'gtin_missing_on_page') for f in r.get('findings') or [])]
    member = [r for r in pages if r.get('member_price') not in (None, '')]
    hosted = [r for r in rows if r.get('reference_source') == 'hosted_render']
    out = [
        dict(_check('Product markup on product pages', len(with_markup), len(pages), key='markup'), basis="reads with method json_ld"),
        dict(_check('GTIN in markup', len(gtin_ok), len(pages), key='gtin'),
             basis="pages read whose record carries a GTIN, read with structured data, without a gtin_missing_on_page finding, over every page read"),
        dict(_check('Program price in markup', len(member), len(pages), key='member_price'), basis="reads with member_price present"),
        dict(_check('Needs a hosted render', len(hosted), len(rows), good_when_zero=True, key='hosted_render'),
             basis="reads that came from the hosted renderer. 0 is the good answer"),
    ]
    out.insert(0, robots_check(robots, own_domains))
    out.append(signed_agents_check(domain_checks, domain_cycle))
    out.append(protocol_check(domain_checks, domain_cycle))
    return out


def extend_accessibility(body: dict, reference: Optional[dict], reference_error: Optional[str] = None, *,
                         robots: Optional[list] = None, own_domains: Optional[List[str]] = None,
                         domain_checks: Optional[dict] = None, domain_cycle: Optional[str] = None) -> dict:
    """2C-2: `checks` become the merchant-level checks; supply's per-agent
    robots/probe lines move to `agent_checks`. Each request carries
    `measured` (an unconfigured identity is not measured, never a problem)."""
    body = dict(body)
    body['agent_checks'] = body.get('checks') or []
    body['checks'] = build_access_checks(reference, robots=robots, own_domains=own_domains,
                                         domain_checks=domain_checks, domain_cycle=domain_cycle)
    body['domain_checks'] = ({'cycle': domain_cycle, 'checked_at': domain_checks.get('checked_at'),
                              'scored_domain': domain_checks.get('scored_domain')} if domain_checks else None)
    body['requests'] = [{**r, 'measured': _measured(r)} for r in body.get('requests') or []]
    body['problems'] = sum(1 for r in body['requests'] if r['measured'] and not r.get('ok'))
    if reference_error:
        body.setdefault('read_errors', {})['reference'] = reference_error
    return body


# ─── True Value: the ladder and the receipt ───────────────────────────────

def _price(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read_member_price(reads: Optional[List[dict]], variant: dict) -> Optional[dict]:
    """2C-2b: the newest readable page read of this variant that states a
    member price (production's W&S record states none; 7 of 19 pages do)."""
    hits = [r for r in reads or [] if r.get('read_status') in ('ok', 'empty') and _price(r.get('member_price')) is not None
            and rm.reference_matches(r, {'variant_id': variant.get('variant_id'), 'gtin': variant.get('gtin')})]
    return max(hits, key=lambda r: str(r.get('observed_at') or '')) if hits else None


def member_price_source(listing_entry: Optional[dict], variant: dict, reads: Optional[List[dict]]) -> Optional[dict]:
    """2C-2b, one source order wherever a member price is shown (the ladder,
    the receipt, the record's variants): the record's variant (supply's
    member_prices / entitled_member_price, or a catalog variant's
    member_price), else the newest page read that states one, else None (the
    incentive text then says "stated without a price"). The tier a page
    price belongs to is the tier the record's offers name for the variant."""
    vid = variant.get('variant_id')
    entry = next((v for v in (listing_entry or {}).get('variants') or [] if v.get('variant_id') == vid), None)
    record = [(mp.get('price'), mp.get('tier_name') or mp.get('program_name')) for mp in (entry or {}).get('member_prices') or []]
    record += [((entry or {}).get('entitled_member_price'), (entry or {}).get('entitled_tier_name')),
               (variant.get('member_price'), variant.get('member_tier_name') or variant.get('member_tier'))]
    record = [(p_, t_) for p_, t_ in record if _price(p_) is not None]
    if record:
        price, tier = min(record, key=lambda x: _price(x[0]))
        return {'price': _price(price), 'tier': tier or 'Member', 'source': 'record', 'observed_at': None,
                'note': 'from the record'}
    read = _read_member_price(reads, variant)
    if read:
        tier = next((inc.get('tier_name') for inc in (listing_entry or {}).get('incentives') or []
                     if inc.get('tier_name') and inc.get('eligibility_kind') in ('tier', 'member')
                     and ('*' in (inc.get('variant_scope') or ['*']) or vid in (inc.get('variant_scope') or []))), None)
        return {'price': _price(read['member_price']), 'tier': tier or 'Member', 'source': 'reference_read',
                'observed_at': read.get('observed_at'), 'note': f"from the page read {_short_day(read.get('observed_at'))}"}
    return None


def ladder_steps(listing_entry: Optional[dict], variant: dict, owned: Optional[List[dict]],
                 reads: Optional[List[dict]] = None) -> tuple:
    """(steps, unpriced) for one variant: every price the record states for
    it below its list price (member prices with their tier, a first-order
    price the record states), then the owned incentives' member prices.
    `unpriced` names the discounts the record states without a price: they
    get no step, since a computed price is not a stated one."""
    vid = variant.get('variant_id')
    stated, unpriced = [], []
    entry = next((v for v in (listing_entry or {}).get('variants') or [] if v.get('variant_id') == vid), None)
    # 2C-2a: the variant's own member prices first (what the generator asks
    # about: supply's per-variant member_prices and entitled_member_price, or
    # a member_price on the catalog variant). The offers' text is read only
    # when the variant states no member price.
    listed = [(mp.get('price'), mp.get('tier_name') or mp.get('program_name'), mp.get('basis') or 'member_price', 'record', None)
              for mp in (entry or {}).get('member_prices') or []]
    listed.append(((entry or {}).get('entitled_member_price'), (entry or {}).get('entitled_tier_name'), 'member_price', 'record', None))
    listed.append((variant.get('member_price'), variant.get('member_tier_name') or variant.get('member_tier'), 'member_price', 'record', None))
    listed = [(p_, t_ or 'Member', b_, s_, o_) for p_, t_, b_, s_, o_ in listed if _price(p_) is not None]
    if not listed:
        # 2C-2b: no member price in the record: the newest page read's, named
        src = member_price_source(listing_entry, variant, reads)
        if src:
            listed.append((src['price'], src['tier'], 'member_price', src['source'], src['observed_at']))
    priced_tiers = set()
    for price, tier, basis, source, observed in listed:
        stated.append((_price(price), tier, source, basis, observed))
        priced_tiers.add(rm._norm_tier(tier))
    for inc in (listing_entry or {}).get('incentives') or []:
        scope = inc.get('variant_scope') or ['*']
        if '*' not in scope and vid not in scope:
            continue
        value = inc.get('value') or {}
        kind = inc.get('eligibility_kind')
        net = _price(value.get('effective_net_price'))
        if kind in ('tier', 'member', 'new_customer') and value.get('discount_percent') and net is None \
                and not (inc.get('tier_name') and rm._norm_tier(inc['tier_name']) in priced_tiers):
            who = inc.get('tier_name') or inc.get('promo_code') or (kind or '').replace('_', ' ')
            unpriced.append(f"{who} {str(value['discount_percent']).rstrip('0').rstrip('.')}% off")
        if kind == 'new_customer' and net is not None:
            code = inc.get('promo_code')
            stated.append((net, f"First order{', ' + code if code else ''}", 'record', 'effective_net_price', None))
        elif listed:
            continue
        elif inc.get('mechanic') == 'member_price' and _price(value.get('member_price')) is not None:
            stated.append((_price(value['member_price']), inc.get('tier_name') or inc.get('program_name') or 'Member',
                           'record', 'member_price', None))
        elif kind == 'tier' and net is not None:
            stated.append((net, inc.get('tier_name') or 'Member', 'record', 'effective_net_price', None))
    gt = rm._gtin14(variant.get('gtin'))
    for inc in owned or []:
        mp = _price(inc.get('member_price'))
        hits = inc.get('applies_to_gtins') or []
        if mp is not None and (not hits or (gt and gt in {rm._gtin14(g) for g in hits})):
            stated.append((mp, inc.get('tier_name') or inc.get('name') or 'Member', 'owned_incentive', 'member_price', None))
    return stated, sorted(set(unpriced))


SOURCE_TAGS = {'record': 'Stated by the record', 'owned_incentive': 'Owned incentive', 'reference_read': 'On the page'}


def _step_note(source: str, observed) -> str:
    return {'record': 'from the record', 'owned_incentive': 'from an owned incentive'}.get(
        source, f"from the page read {_short_day(observed)}")


def program_lines(catalog: Optional[dict], incentives: Optional[dict], value_outcomes: List[dict], *,
                  reads: Optional[List[dict]] = None) -> Dict[str, dict]:
    """2G: True Value's caption under each product, the demo's "First Autoship
    $47.99 (Purina ladder). Quoted by 0 of 5 agents." Per record variant: its
    program price by the ladder's own source rule (member_price_source: the
    record, else the newest page read with a member price), and per surface
    the agents asked a member-price question about it in the value tier and
    the ones that quoted it right (an exact outcome). A variant with neither
    a program price nor a question has no caption. 2I-8: `all` first, every
    agent asked, the demo's caption."""
    entries = {l.get('listing_id'): l for l in (incentives or {}).get('listings') or []}
    asked: Dict[str, List[dict]] = {}
    for o in value_outcomes or []:
        expected = rm._json(o.get('expected_answer')) or {}
        vid = (rm._json(o.get('source_ref')) or {}).get('variant_id')
        if vid and expected.get('type') == 'member_price':
            asked.setdefault(str(vid), []).append({**o, 'tier_name': expected.get('tier_name')})
    out: Dict[str, dict] = {}
    for listing in (catalog or {}).get('listings') or []:
        entry = entries.get(listing.get('listing_id'))
        for v in listing.get('variants') or []:
            vid = str(v.get('variant_id'))
            src = member_price_source(entry, v, reads)
            runs = asked.get(vid, [])
            if not src and not runs:
                continue
            tier = (src or {}).get('tier') or next((r['tier_name'] for r in runs if r.get('tier_name')), None) or 'Member'
            cur = v.get('currency') or 'USD'
            amount = rm.money(f"{src['price']:.2f}", cur) if src else None
            price = f"{tier} {amount} ({src['note']})." if src else f"{tier}: no price stated in the record or on the page."
            by_surface = {}
            for sf in surfaces.with_all(sorted({r.get('surface') or 'unlabelled' for r in runs})):
                mine = [r for r in runs if _on(r.get('surface') or 'unlabelled', sf)]
                agents = sorted({surfaces.agent_of(r.get('platform')) or r.get('platform') for r in mine})
                quoted = sorted({surfaces.agent_of(r.get('platform')) or r.get('platform') for r in mine
                                 if r.get('outcome') == 'exact'})
                by_surface[sf] = {'asked': agents, 'quoted': quoted,
                                  'line': f"{price} Quoted by {len(quoted)} of {len(agents)} {_n(len(agents), 'agent', 'agents')}."}
            out[vid] = {'price': (src or {}).get('price'), 'tier': tier, 'source': (src or {}).get('source'),
                        'note': (src or {}).get('note'), 'by_surface': by_surface,
                        'line': f"{price} Not asked this cycle." if not by_surface else None}
    return out


def build_ladder(catalog: Optional[dict], incentives: Optional[dict], owned: Optional[List[dict]],
                 scored: List[dict], *, own_domain: Optional[str], reads: Optional[List[dict]] = None,
                 member_reads: Optional[List[dict]] = None) -> tuple:
    """(ladder, receipt) for the merchant's primary product: the variant this
    cycle asked about most (ties to the catalog's order). Steps are the
    record's list price, then each lower price stated for it, lowest last:
    the record's or an owned incentive's, and (2C-2b) when the record states
    no member price, the newest page read's (member_price_source). Each step
    says where it came from. Only stated prices, never a computed or modeled
    one. (None, None) when there is nothing to show."""
    listings = (catalog or {}).get('listings') or []
    variants = [(l, v) for l in listings for v in l.get('variants') or []]
    if not variants:
        return None, None
    asked = Counter(s.get('variant_id') for s in scored if s.get('variant_id'))
    order = {v.get('variant_id'): i for i, (_, v) in enumerate(variants)}
    listing, variant = max(variants, key=lambda lv: (asked.get(lv[1].get('variant_id'), 0), -order[lv[1].get('variant_id')]))
    lp = _price(variant.get('list_price'))
    if lp is None:
        return None, None
    cur = variant.get('currency') or 'USD'
    entry = next((l for l in (incentives or {}).get('listings') or [] if l.get('listing_id') == listing.get('listing_id')), None)
    # 2C-2c: the member price is looked for in every read (supply's history)
    # when supply sends it, else in the newest read per page (/reference).
    stated, unpriced = ladder_steps(entry, variant, owned, reads=member_reads if member_reads is not None else reads)
    steps = [{'label': 'List', 'value': rm.money(f"{lp:.2f}", cur), 'pct': 100, 'kind': 'ink', 'source': 'record',
              'amount': f"{lp:.2f}", 'note': 'from the record'}]
    seen = set()
    for mp, label, src, basis, observed in sorted(stated, key=lambda x: (-x[0], x[1])):
        if (mp, label) in seen or mp >= lp:
            continue
        seen.add((mp, label))
        steps.append({'label': label, 'value': rm.money(f"{mp:.2f}", cur), 'pct': round(mp / lp * 100), 'kind': 'b',
                      'source': src, 'basis': basis, 'amount': f"{mp:.2f}", 'observed_at': observed,
                      'note': _step_note(src, observed)})
    title = variant.get('title') or listing.get('title') or variant.get('variant_id')
    n = asked.get(variant.get('variant_id'), 0)
    sub = (f"The product this cycle asked about most, in {n} {_n(n, 'run', 'runs')}." if n
           else "The first product in the record.")
    note = 'Only stated prices. No discount is computed here.' if len(steps) > 1 else \
        'Nothing states a price below the list price for this product.'
    if unpriced:
        note += f" Stated without a price, so not drawn: {', '.join(unpriced)}."
    ladder = {'title': title, 'sub': sub, 'steps': steps, 'note': note,
              'variant_id': variant.get('variant_id'), 'listing_id': listing.get('listing_id'), 'unpriced': unpriced}
    rows = [{'k': 'List price', 'v': steps[0]['value'], 'tag': own_domain or 'the record'}]
    if len(steps) > 1:
        best = steps[-1]
        off = f"{lp - float(best['amount']):.2f}"
        rows.append({'k': f"{best['label']}, {best['note']}", 'v': f"-{rm.money(off, cur)}", 'kind': 'minus',
                     'tag': SOURCE_TAGS.get(best['source'], best['source'])})
        rows.append({'k': 'The lowest stated price', 'v': best['value'], 'kind': 'big'})
    receipt = {'title': 'What a shopper pays', 'sub': title, 'rows': rows}
    return ladder, receipt


# ─── Offer record ──────────────────────────────────────────────────────────

def _availability_words(value) -> str:
    """schema.org's 'InStock' (or its URL), 'in_stock': 'In stock'."""
    v = str(value).rsplit('/', 1)[-1].replace('_', ' ')
    v = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', v).strip()
    return v[:1].upper() + v[1:].lower() if v else v


#: Owned-incentive mechanics in words.
MECHANIC_WORDS = {'member_price': 'Member price', 'code': 'Code', 'percent_off': 'Percent off', 'amount_off': 'Amount off',
                  'promo_code': 'Promo code', 'points': 'Points', 'points_multiplier': 'Points multiplier',
                  'free_shipping': 'Free shipping', 'subscription': 'Subscription'}


def offer_fields(record: dict, *, owned: Optional[List[dict]], reference_rows: List[dict],
                 verifications: List[dict], listing: dict, price_rows: Optional[List[dict]] = None) -> List[dict]:
    """The offer fields the demo's record shows that this record holds: each
    owned incentive (name, mechanic, terms, ends), availability when a read
    or the record states it, last verified, shipping and returns only when
    the record carries them. A field the record does not hold is left out."""
    prov = next((f['prov'] for f in record.get('fields') or [] if f.get('k') == 'Name'), 'unknown')
    out = []
    gtins = {rm._gtin14(v.get('gtin')) for v in listing.get('variants') or [] if v.get('gtin')}
    for inc in owned or []:
        scope = {rm._gtin14(g) for g in inc.get('applies_to_gtins') or []}
        if scope and not (scope & gtins):
            continue
        name = inc.get('name') or inc.get('tier_name') or inc.get('code') or MECHANIC_WORDS.get(inc.get('mechanic'), 'Incentive')
        out.append(rm.compact({'k': f"Incentive · {name}", 'v': rm._program_terms(inc), 'prov': prov,
                               'note': ' · '.join(x for x in (MECHANIC_WORDS.get(inc.get('mechanic'), (inc.get('mechanic') or '').replace('_', ' ')),
                                                              f"ends {str(inc['valid_until'])[:10]}" if inc.get('valid_until') else 'no end date') if x),
                               'mechanic': inc.get('mechanic'), 'ends': str(inc['valid_until'])[:10] if inc.get('valid_until') else None,
                               'source': 'owned_incentive'}, ('ends',)))
    avail = sorted({str(v.get('availability')) for v in listing.get('variants') or [] if v.get('availability')})
    # 2G: else the newest read: supply's /reference rows do not carry
    # availability, its retailer-prices rows (`prices`) do, one per page
    reads = [r for r in list(reference_rows) + list(price_rows or []) if r.get('availability')]
    newest = max((str(r.get('observed_at') or '') for r in reads), default=None)
    read_avail = sorted({_availability_words(r['availability']) for r in reads if str(r.get('observed_at') or '') == newest})
    if avail:
        out.append({'k': 'Availability', 'v': ', '.join(_availability_words(a) for a in avail), 'prov': prov})
    elif read_avail:
        out.append({'k': 'Availability', 'v': ', '.join(read_avail), 'prov': 'parleo',
                    'note': f"as the newest page read found it, {_short_day(newest)}" if newest else 'as the newest page read found it'})
    for key, label in (('shipping', 'Shipping'), ('returns', 'Returns')):
        if listing.get(key):
            out.append({'k': label, 'v': str(listing[key]), 'prov': prov})
    seen = [r.get('observed_at') for r in reference_rows if r.get('observed_at')] + \
        [v.get('created_at') for v in verifications if v.get('created_at')]
    if seen:
        last = max(str(x) for x in seen)
        out.append({'k': 'Last verified', 'v': last[:10], 'prov': 'parleo',
                    'note': 'the newest reference read or channel check of this product'})
    return out


HISTORY_EVENTS = {
    ('publication', 'published'): 'Published', ('publication', 'compiled'): 'Compiled, not published',
    ('publication', 'validated'): 'Compiled, not published', ('publication', 'failed'): 'Publish failed',
    ('publication', 'withdrawn'): 'Withdrawn',
    ('verification', 'fetch_probe'): 'Page checked after publish', ('verification', 'live_fetch'): 'Page checked after publish',
    ('verification', 'gmc_diagnostics'): 'Merchant Center read back', ('verification', 'mc_acceptance'): 'Manufacturer Center read back',
    ('reference', 'read'): 'Page read for the study',
}


def record_history(listing_id, *, publications: List[dict], verifications: List[dict], reference_rows: List[dict],
                   channel_names: Dict[str, str]) -> List[dict]:
    """history[]: the publication journal, the channel checks and the
    reference reads of this product, newest first."""
    out = []
    for p in publications or []:
        if p.get('listing_id') != listing_id:
            continue
        at = p.get('published_at') or p.get('compiled_at')
        out.append({'at': rm._iso(at), 'event': HISTORY_EVENTS.get(('publication', p.get('status')), (p.get('status') or 'publication').replace('_', ' ')),
                    'surface': channel_names.get(p.get('channel_slug'), p.get('channel_slug')), 'channel': p.get('channel_slug'),
                    'kind': 'publication', 'status': p.get('status'), 'tone': 'bad' if p.get('status') == 'failed' else 'ok' if p.get('status') == 'published' else 'neu'})
    for v in verifications or []:
        drift = v.get('drift') or {}
        findings = drift.get('findings') if isinstance(drift.get('findings'), list) else None
        detail = (f"{len(findings)} {_n(len(findings), 'field differs', 'fields differ')}" if findings else 'matches what was sent') \
            if findings is not None else (v.get('outcome') or '').replace('_', ' ')
        out.append({'at': rm._iso(v.get('created_at')), 'event': HISTORY_EVENTS.get(('verification', v.get('method')), (v.get('method') or 'check').replace('_', ' ')),
                    'surface': channel_names.get(v.get('channel_slug'), v.get('channel_slug')), 'channel': v.get('channel_slug'),
                    'kind': 'verification', 'detail': detail or None, 'tone': 'warn' if findings else 'neu'})
    for r in reference_rows:
        if not r.get('observed_at'):
            continue
        out.append({'at': rm._iso(r.get('observed_at')), 'event': HISTORY_EVENTS[('reference', 'read')],
                    'surface': r.get('retailer_domain'), 'channel': None, 'kind': 'reference',
                    'detail': f"{_SOURCE_WORDS.get(r.get('reference_source'), r.get('reference_source') or 'a read')}, {r.get('read_status') or 'status not recorded'}",
                    'tone': 'neu'})
    out.sort(key=lambda e: e['at'] or '', reverse=True)
    return out


def record_surfaces(product: Optional[dict], channels: List[dict]) -> List[dict]:
    """surfaces[]: per channel, the TrueSync matrix cell's publish state and
    page check, reused from build_truesync's product (never recomputed)."""
    if not product:
        return []
    out = []
    for c in channels:
        cell = (product.get('cells') or {}).get(c['id'])
        if cell is None:
            continue
        out.append({'channel': c['id'], 'name': c.get('name') or c['id'], 's': cell.get('s'), 'd': cell.get('d'),
                    'n': cell.get('n'), 'at': cell.get('at'), 'acceptance': cell.get('acceptance'),
                    'published_at': cell.get('published_at'), 'note': cell.get('note')})
    return out


ISSUE_IMPACT = {'blocked': 0, 'dropped': 1, 'conflict': 2, 'approx': 3, 'info': 4}


def group_issues(issues: List[dict], *, published_channels: Iterable[str],
                 channel_names: Optional[Dict[str, str]] = None) -> dict:
    """Issues by channel with a count, every note kept. The three with the
    most impact (a dropped mechanic on a channel the merchant publishes to
    first, then a failed publish, a validation conflict, an approximation)
    are named in `expanded`; the rest stay collapsed."""
    live = set(published_channels)
    groups: Dict[str, dict] = {}
    for i, issue in enumerate(issues):
        ch = issue.get('channel') or 'record'
        names = channel_names or {}
        g = groups.setdefault(ch, {'channel': ch, 'count': 0, 'issues': [],
                                   'label': ', '.join(names.get(c, c) for c in ch.split(','))})
        g['count'] += 1
        g['issues'].append({**issue, 'index': i})
    ranked = sorted(range(len(issues)), key=lambda i: (
        0 if issues[i].get('verdict') == 'dropped' and (issues[i].get('channel') in live) else 1,
        ISSUE_IMPACT.get(issues[i].get('verdict'), 5), i))
    return {'groups': sorted(groups.values(), key=lambda g: (-g['count'], g['channel'])), 'expanded': ranked[:3],
            'total': len(issues)}


def extend_record(record: dict, *, listing: dict, owned: Optional[List[dict]], reference: Optional[dict],
                  publications: List[dict], verifications: Dict[str, dict], channels: List[dict],
                  truesync_product: Optional[dict], truesync_channels: List[dict],
                  prices: Optional[List[dict]] = None) -> dict:
    """2C-2: the offer fields, history, surfaces and grouped issues beside
    2C-1's record."""
    lid = listing.get('listing_id')
    refs = [r for r in (reference or {}).get('rows') or []
            if any(rm.reference_matches(r, v, listing) for v in listing.get('variants') or [{}])]
    ver = [v for env in (verifications or {}).values() for e in (env or {}).get('listings') or []
           if e.get('listing_id') == lid for v in e.get('verifications') or []]
    names = {c.get('slug'): c.get('name') or c.get('slug') for c in channels or []}
    record = dict(record)
    mine = [r for r in prices or [] if any(rm.reference_matches(r, v, listing) for v in listing.get('variants') or [{}])]
    record['offer_fields'] = offer_fields(record, owned=owned, reference_rows=refs, verifications=ver, listing=listing,
                                          price_rows=mine)
    record['history'] = record_history(lid, publications=publications, verifications=ver, reference_rows=refs,
                                       channel_names=names)
    record['surfaces'] = record_surfaces(truesync_product, truesync_channels)
    published = [s for s, c in (record.get('channels') or {}).items() if c.get('status') == 'published']
    record['issue_groups'] = group_issues(record.get('issues') or [], published_channels=published, channel_names=names)
    return record


# ─── Catalog: stages and the retailers read ───────────────────────────────

STAGES = ('measured', 'published', 'verified')


def catalog_row_keys(row: dict) -> List[str]:
    """2J-2: the keys a catalog row's quotes can be filed under, in order: a
    hosted row's variant_id, a feed row's variant_key (supply's: the GTIN-14,
    or sku:<sku> for a row with no GTIN), the GTIN-14, sku:<sku>. A question
    carries the variant's id as its variant_id; a feed row has no variant_id,
    so a GTIN-less row was keyed by nothing and never read as measured."""
    keys = [row.get('variant_id'), row.get('variant_key'), rm._gtin14(row.get('gtin')),
            f"sku:{row['sku']}" if row.get('sku') else None]
    return list(dict.fromkeys(str(k) for k in keys if k))


def catalog_stages(rows: List[dict], *, quoted_variants: Dict[str, dict], published_listings: Iterable,
                   ) -> List[dict]:
    """Per catalog row: `measured` when a scored cycle quoted it, `published`
    when any channel published it, `verified` when the latest scored cycle's
    prices for it all agree with the record (and at least one was scored).
    A row's quotes are found under any of its keys (catalog_row_keys)."""
    pub = set(published_listings)
    out = []
    for row in rows:
        keys = catalog_row_keys(row)
        key = keys[0] if keys else None
        q = next((quoted_variants[k] for k in keys if k in quoted_variants), {})
        stage = []
        if q.get('quoted'):
            stage.append('measured')
        if row.get('listing_id') in pub or row.get('published'):
            stage.append('published')
        if 'published' in stage and q.get('scored') and q.get('exact') == q.get('scored'):
            stage.append('verified')
        out.append({**row, 'stage': stage[-1] if stage else None, 'stages': stage,
                    'quoted_runs': q.get('quoted', 0), 'scored': q.get('scored', 0), 'exact': q.get('exact', 0), 'key': key})
    return out


#: 2G: the demo's four stages (Setup's StageLadder), in order, each with its line.
STAGES = (
    (0, 'not_measured', 'Not measured', 'Connect a catalog and pick prompts'),
    (1, 'measured', 'Measured', 'Weekly check runs, record compiled'),
    (2, 'published', 'Published', 'Offer object live on every surface'),
    (3, 'verified', 'Verified', 'Next check proves the move'),
)


def stage_ladder(rows: List[dict]) -> dict:
    """The demo's stage ladder from the per-product stages (catalog_stages):
    how many products reached each stage (a product counts at every stage it
    reached; Not measured is a product no scored cycle quoted), and `here`,
    the highest stage any product has reached. No rankings: the demo's are
    modeled."""
    counts = {key: 0 for _, key, _, _ in STAGES}
    for r in rows:
        stages = r.get('stages') or []
        if 'measured' not in stages:
            counts['not_measured'] += 1
        for s in stages:
            if s in counts:
                counts[s] += 1
    reached = [n for n, key, _, _ in STAGES if n and counts[key]]
    here = max(reached) if reached else 0
    return {'here': here, 'total': len(rows),
            'stages': [{'n': n, 'key': key, 'name': name, 'line': line, 'products': counts[key]}
                       for n, key, name, line in STAGES]}


def retailers_read(reference: Optional[dict]) -> List[dict]:
    """'Retailers read for the study': per domain, the pages read, how
    (method), the hosted renders, the last read and a note from the read
    statuses."""
    by: Dict[str, List[dict]] = {}
    for r in (reference or {}).get('rows') or []:
        by.setdefault(r.get('retailer_domain') or 'unknown', []).append(r)
    out = []
    for domain, rows in by.items():
        ok = [r for r in rows if r.get('read_status') in ('ok', 'empty')]
        methods = Counter(r.get('method') for r in ok if r.get('method'))
        statuses = Counter(r.get('read_status') or 'not read' for r in rows if r.get('read_status') not in ('ok', 'empty'))
        rest = ''.join(f", {n} {s.replace('_', ' ')}" for s, n in sorted(statuses.items()))
        # 2E: supply #21's incentive_in_markup, over the reads it scanned
        scanned = [m for m in (incentive_in_markup(r) for r in ok) if m and m['json_ld_scanned']]
        with_fields = carries_incentive_fields(rows)
        incentive = ({'pages': sum(1 for m in scanned if any(m[f] for f in INCENTIVE_FLAGS)), 'of': len(scanned)}
                     if scanned else None)
        out.append({'domain': domain, 'pages': len(rows), 'read': len(ok),
                    'incentive_in_markup': incentive,
                    'incentive_note': (TEMPLATES['catalog.incentive'].format(**incentive) if incentive else
                                       TEMPLATES['catalog.incentive_unscanned'] if with_fields else
                                       TEMPLATES['catalog.incentive_none']),
                    'method': ', '.join(f"{m.replace('_', ' ')} {n}" for m, n in methods.most_common()) or 'none',
                    'hosted_render': sum(1 for r in rows if r.get('reference_source') == 'hosted_render'),
                    'last_read': max((str(r['observed_at']) for r in rows if r.get('observed_at')), default=None),
                    'note': TEMPLATES['catalog.read'].format(ok=len(ok), pages=len(rows), rest=rest)})
    return sorted(out, key=lambda d: (-d['pages'], d['domain']))


# ─── Studies ───────────────────────────────────────────────────────────────

def prompt_counts(prompts: List[dict]) -> dict:
    branded = sum(1 for p in prompts if p.get('branded'))
    return {'branded': branded, 'unbranded': len(prompts) - branded, 'prompts': len(prompts)}


# ─── loaders ───────────────────────────────────────────────────────────────

def answered(run_status, has_text, answer_status) -> bool:
    """2Q-2: an answer arrived and the surface returned it, the scorer's own
    test (expectation_scorer._answered): a run with none is scored absent on
    every coder version, so the coder that stamped it says nothing."""
    return run_status == 'success' and bool(has_text) and answer_status not in surfaces.NO_ANSWER_STATUSES


def load_overview_rows(conn, cycle: dict, features: Optional[List[str]] = None) -> List[dict]:
    """features (2K-3): the merchant's catalog feature terms, which extend
    claim_kind's fact lexicon (app/services/console_claims.py). None, the
    score's read, is 2K-1's rule exactly."""
    rows = []
    for r in conn.execute(text("""
        SELECT r.id AS run_id, r.platform, r.surface, r.answer_status,
               r.status AS run_status, (r.raw_response IS NOT NULL AND TRIM(r.raw_response) <> '') AS has_text,
               q.tier, q.stage, q.query_code, q.query_text, q.source_ref, o.outcome, o.reason_code, o.extraction
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        LEFT JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c
    """), {'c': cycle['id']}).mappings():
        row = dict(r)
        # 2Q-2: whether an answer arrived (a wall, an empty answer or a failed run did not)
        row['answered'] = answered(row.pop('run_status', None), row.pop('has_text', None), row.get('answer_status'))
        ref = _json(row.pop('source_ref')) or {}
        row['variant_id'] = ref.get('variant_id')
        # 2N-1: a catalog-built brand-direct question carries its own verdict, never the brand-claim rule's
        row['intent'] = claim_kinds.catalog_intent(ref)
        # 2K-1 (A9): whether a brand-direct answer stated an attribute, from its stored extraction
        extraction = _json(row.pop('extraction', None))
        row['claim_kind'] = (console_claims.claim_kind(extraction, features)
                             if claim_kinds.is_brand_claim(row.get('tier'), ref) else None)
        # 2O-1: the brand-claim coder that scored a brand-direct row (None: one call, before 2O-1)
        if row.get('tier') == 'brand_direct':
            coder = (extraction or {}).get('coder') if isinstance(extraction, dict) else None
            row['coder_version'] = coder.get('version') if isinstance(coder, dict) else None
        rows.append(row)
    # 2K-1: a price attributed to the brand's own page, which sets none, is not scored
    unpriced = rm.brand_sets_no_price_runs(conn, cycle)
    return [rm.not_priced(r, unpriced) for r in rows]


def previous_scored_cycle(conn, cycle: dict, org_sql: str) -> tuple:
    """(the newest scored cycle of the same org before this one, how many
    scored cycles the org has). A cycle is scored when any of its runs has
    an outcome."""
    rows = [dict(c) for c in conn.execute(text(f"""
        SELECT c.* FROM soa_cycles c
        WHERE {org_sql} = :org AND c.status = 'complete'
          AND EXISTS (SELECT 1 FROM soa_expectation_outcomes o WHERE o.cycle_id = c.id)
        ORDER BY c.start_date DESC, c.id DESC
    """), {'org': cycle['customer_org_id']}).mappings()]
    ids = [c['id'] for c in rows]
    earlier = [c for c in rows if c['id'] != cycle['id'] and (ids.index(c['id']) > ids.index(cycle['id']) if cycle['id'] in ids else True)]
    return (earlier[0] if earlier else None), len(rows)
