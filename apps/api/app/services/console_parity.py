"""
2C-2: the console's demo blocks, filled from data soa already stores.

Pivots and summaries over what the 2B/2C/2C-1 read models already read:
the per-run outcomes, the mention coding, the True Value cells, the 2A
reference and access reads, the publication journal and the owned
incentives. Nothing new is measured, nothing is modeled and no model is
called: every sentence here is a template filled from counts, and each
template is written down once (TEMPLATES) so docs/console-read-models.md
can quote it.

Two rules from 2C hold everywhere:
  * counts are per surface (api, grounded_api, consumer_ui), never pooled;
    a per-agent split sits beneath each surface.
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

from soa_shared import surfaces

from app.services import console_read_models as rm
from clients.truesync_client import INCENTIVE_FLAGS, carries_incentive_fields, incentive_in_markup

AGENT_NAMES = rm.AGENT_NAMES
_json = rm._json

# ─── vocabulary ────────────────────────────────────────────────────────────

#: Studio's stage order, the order prompts are read in.
STAGE_ORDER = ('Awareness', 'Research', 'Comparison', 'Ready to Buy')
STAGE_LABELS = {'Awareness': 'Awareness', 'Research': 'Research', 'Comparison': 'Comparison',
                'Ready to Buy': 'Ready to buy'}
UNPROMPTED = rm.VIS_UNPROMPTED
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
    'product.left_out': "No price quoted in {n} of {runs} {runs_word}.",
    'product.unverifiable': "The page could not be read, so {n} of {runs} {runs_word} are not scored.",
    'product.right': "Right in {n} of {runs} {runs_word}.",
    'product.not_asked': "Not asked on this surface this cycle.",
    'signal.other_brand': ("Answered {n} price {questions} with another brand's price.",
                           "{n} of {asked} price answers on {surface}. {split}."),
    'signal.fabricated': ("{n} brand answers stated facts {brand} never published.",
                          "{n} of {asked} brand-direct answers on {surface}. {split}."),
    'signal.fabricated_caveat': "Sources were not captured before Oct 14, so some of these may rest on a page we did not see.",
    'signal.wrong_product': ("Wrong price on {product} in {n} runs.",
                             "Quoted {quote} against {live}. {split}."),
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
    'summary.no_signal': "No signal crossed its threshold this cycle.",
    'changes.first_cycle': "First cycle. Changes appear from the next one.",
    'changes.not_comparable_subset': "Not comparable: {code} ran {agents} only on this surface.",
    'changes.not_comparable': "Not comparable: {code} ran {prev} on this surface, this cycle ran {now}.",
    'changes.not_comparable_tier': "Not comparable: {code} asked no unprompted questions on this surface.",
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
            'consumer_ui': 'the consumer UI'}.get(s or '', s or 'an unlabelled surface')


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
    return UNPROMPTED if any(r.get('tier') == UNPROMPTED for r in rows) else 'all'


def _tier_words(tier: str) -> str:
    return 'unprompted' if tier == UNPROMPTED else ''


def _answers(tier: str) -> str:
    """'unprompted answers' when the cycle asked any, else 'answers'."""
    return 'unprompted answers' if tier == UNPROMPTED else 'answers'


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
    mine = [r for r in rows if r.get('answered') and r.get('surface') == surface
            and (tier == 'all' or r.get('tier') == tier)]
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


def visibility_matrix(rows: List[dict], surface: str) -> dict:
    """Prompt x agent first pick on one surface, prompts in stage order. A
    cell is the first pick most of the question's runs gave (ties to ours,
    then by name), with every pick counted beside it."""
    mine = [r for r in rows if r.get('surface') == surface]
    agents = sorted({r['agent'] for r in mine})
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
    mine = [r for r in rows if r.get('surface') == surface and r.get('answered')]

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
    """2C-2: headline, matrix and by_stage, per surface, beside 2C-1's read."""
    rows = body.get('byQuestion') or []
    surface_list = [s['surface'] for s in body.get('surfaces') or []]
    default = (body.get('ranking') or {}).get('surface')
    heads = {s: visibility_headline(rows, s, ours) for s in surface_list}
    body['headline'] = (heads.get(default) or {}).get('text', '')
    body['headlines'] = heads
    body['matrix'] = {s: visibility_matrix(rows, s) for s in surface_list}
    body['by_stage'] = {s: visibility_by_stage(rows, s) for s in surface_list}
    return body


# ─── Overview ──────────────────────────────────────────────────────────────

def _empty_agent() -> dict:
    return {'answers': 0, 'named': 0, 'first': 0, 'named_of': 0, 'exact': 0, 'scored': 0, 'wrong': 0, 'stale': 0,
            'price_answered': 0,
            'partial': 0, 'unverifiable': 0, 'other_brand': 0, 'left_out': 0, 'unknown': 0, 'fabricated': 0,
            'brand_scored': 0}


def surface_metrics(rows: List[dict], vis_rows: List[dict], surface: str, *, tier: Optional[str] = None) -> dict:
    """Every count the Overview reads for one surface, in total and per agent.
    rows: one per run with tier, outcome, reason_code (load_overview_rows);
    vis_rows: Visibility's byQuestion. `tier` forces the named/first tier
    (the Changes block reads both cycles on the current cycle's); by default
    unprompted when the cycle asked any, else every answered run.

    Denominators, one per metric: named and first over answered runs of that
    tier (`named_of`); prices right and wrong over scored (exact, partial,
    stale, wrong); another brand's price over answered price questions
    (`price_answered`), since those runs are absent and never scored."""
    tier = tier or _tier_for_reads(vis_rows)
    total, per = _empty_agent(), {}
    agents = set()
    for v in vis_rows:
        if v.get('surface') != surface or not v.get('answered'):
            continue
        agents.add(v['agent'])
        for bucket in (total, per.setdefault(v['agent'], _empty_agent())):
            bucket['answers'] += 1
            if tier == 'all' or v.get('tier') == tier:
                bucket['named_of'] += 1
                bucket['named'] += int(any(n.get('you') for n in v.get('named') or []))
                bucket['first'] += int(bool((v.get('first') or {}).get('you')))
    for r in rows:
        if _surface_of(r) != surface:
            continue
        agent = surfaces.agent_of(r.get('platform')) or r.get('platform')
        o, t = r.get('outcome'), r.get('tier')
        answered = r.get('answer_status') == surfaces.ANSWERED
        for bucket in (total, per.setdefault(agent, _empty_agent())):
            if t == 'brand_direct':
                if o in ('grounded', 'echoed', 'misattributed', 'fabricated', 'acknowledged_unknown'):
                    bucket['brand_scored'] += 1
                bucket['fabricated'] += int(o == 'fabricated')
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
    return {'tier': tier, 'total': total, 'agents': per, 'agent_set': sorted(agents)}


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
    how = _SOURCE_WORDS.get(cell.get('reference_source') or '', (cell.get('reference_source') or 'a read').replace('_', ' '))
    if cell.get('live_basis') == 'record' or cell.get('reference_source') == 'record':
        return f"{live} at {domain}, the record of {_short_day(cell.get('observed_at'))}, no page read yet"
    return f"{live} at {domain}, {how}, {_short_day(cell.get('observed_at'))}"


#: ProductWeek.status from the cell's status (types.ts has four).
PRODUCT_STATUS = {'exact': 'exact', 'wrong': 'wrong', 'stale': 'wrong', 'partial': 'partial',
                  'missed': 'none', 'none': 'none', 'unverifiable': 'none'}


def product_issue(quotes: List[dict]) -> tuple:
    runs = len(quotes)
    if not runs:
        return 'product.not_asked', TEMPLATES['product.not_asked']
    counts = {
        'product.other_brand': sum(1 for q in quotes if q.get('outcome') == 'absent' and q.get('reason') == 'other_brand'),
        'product.wrong': sum(1 for q in quotes if q.get('outcome') in ('wrong', 'stale')),
        'product.left_out': sum(1 for q in quotes if q.get('outcome') == 'absent' and q.get('reason') != 'other_brand'),
        'product.unverifiable': sum(1 for q in quotes if q.get('outcome') == 'unverifiable'),
    }
    rule, n = max(counts.items(), key=lambda kv: kv[1])
    word = _n(runs, 'run', 'runs')
    if n:
        return rule, TEMPLATES[rule].format(n=n, runs=runs, runs_word=word)
    right = sum(1 for q in quotes if q.get('outcome') == 'exact')
    return 'product.right', TEMPLATES['product.right'].format(n=right, runs=runs, runs_word=word)


def build_products(true_value: dict, vis_rows: List[dict], surface: str, *, variant_of_run: Dict[str, str],
                   reason_of_run: Dict[str, Optional[str]]) -> List[dict]:
    """ProductWeek per True Value row asked about on this surface: named and
    first from the mention coding of the runs that asked about it, the
    quotes per agent, the live price with its source, the cell's status
    (TV_CELL_RULE) and the issue."""
    retailer_cols = true_value.get('retailer_columns') or true_value.get('columns') or []
    you_col = next((c['id'] for c in retailer_cols if c.get('you')), None)
    vis_by_run = {v['run']: v for v in vis_rows}
    out = []
    for row in true_value.get('rows') or []:
        # 2C-2a: with agent columns, the product reads its one-retailer cell
        cells_by = row.get('retailer_cells') or row['cells']
        cols = [you_col] if you_col in cells_by else list(cells_by)
        for col in cols:
            cell = cells_by[col]
            quotes = [{**q, 'reason': reason_of_run.get(q.get('run'))} for q in cell.get('quotes') or []
                      if q.get('surface') == surface]
            if not quotes:
                continue
            sc = (cell.get('by_surface') or {}).get(surface) or {}
            runs = [vis_by_run[q['run']] for q in quotes if q.get('run') in vis_by_run]
            answered = [v for v in runs if v.get('answered')]
            rule, issue = product_issue(quotes)
            status = sc.get('status') or 'none'
            out.append({
                'name': row['product'], 'sku': row['sku'],
                'named': sum(1 for v in answered if any(n.get('you') for n in v.get('named') or [])),
                'first': sum(1 for v in answered if (v.get('first') or {}).get('you')),
                'quoted': _quoted_text(quotes), 'live': _live_text(cell, col),
                'status': PRODUCT_STATUS.get(status, 'none'), 'issue': issue, 'route': 'true-value',
                # beside the typed fields
                'cell_status': status, 'quote': sc.get('quoted'), 'retailer': col, 'runs': len(quotes),
                'answered': len(answered), 'issue_rule': rule,
                'wrong_runs': sum(1 for q in quotes if q.get('outcome') in ('wrong', 'stale')),
                'reference_source': cell.get('reference_source'), 'observed_at': cell.get('observed_at'),
                'live_price': cell.get('live'),
                'answer_ids': [q['run'] for q in quotes if q.get('run')],
                'quote_groups': quote_groups(quotes),
            })
    severity = {'wrong': 0, 'partial': 1, 'none': 2, 'exact': 3}
    out.sort(key=lambda p: (severity.get(p['status'], 4), -p['wrong_runs'], -p['named'], p['name']))
    return out


def build_signals(metrics: dict, products: List[dict], *, surface: str, brand: str, cycle_start,
                  access_problems: List[dict]) -> List[dict]:
    """At most four, from fixed rules in priority order: another brand's
    price (>= 5), fabricated brand-direct facts (>= 5), wrong prices on one
    product (>= 3), any unverifiable price, any access problem."""
    t, per = metrics['total'], metrics['agents']
    where = _surface_label(surface)
    out = []
    if t['other_brand'] >= 5:
        title, detail = TEMPLATES['signal.other_brand']
        asked = t['scored'] + t['left_out'] + t['unverifiable']
        out.append({'id': 'other_brand', 'title': title.format(n=t['other_brand'], questions=_n(t['other_brand'], 'question', 'questions')),
                    'detail': detail.format(n=t['other_brand'], asked=asked, surface=where,
                                            split=_split({a: m['other_brand'] for a, m in per.items()})),
                    'tag': 'Lost pool', 'tone': 'bad', 'route': 'answers', 'rule': 'other_brand', 'count': t['other_brand']})
    if t['fabricated'] >= 5:
        title, detail = TEMPLATES['signal.fabricated']
        text_ = detail.format(n=t['fabricated'], asked=t['brand_scored'], surface=where,
                              split=_split({a: m['fabricated'] for a, m in per.items()}))
        start = _day(cycle_start)
        if start is None or start < GROUNDING_SOURCES_FROM:
            text_ += ' ' + TEMPLATES['signal.fabricated_caveat']
        out.append({'id': 'fabricated', 'title': title.format(n=t['fabricated'], brand=brand), 'detail': text_,
                    'tag': 'Missed pool', 'tone': 'bad', 'route': 'answers', 'rule': 'fabricated', 'count': t['fabricated']})
    worst = max(products, key=lambda p: (p['wrong_runs'], p['name']), default=None)
    if worst and worst['wrong_runs'] >= 3:
        title, detail = TEMPLATES['signal.wrong_product']
        out.append({'id': f"wrong:{worst['sku']}", 'title': title.format(product=worst['name'], n=worst['wrong_runs']),
                    'detail': detail.format(quote=worst['quote'] or 'a price', live=worst['live_price'] or 'the reference',
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
        n = len(access_problems)
        out.append({'id': 'access', 'title': title.format(n=n, identities=_n(n, 'identity', 'identities')),
                    'detail': detail.format(who=', '.join(r.get('identity') or '?' for r in access_problems)),
                    'tag': 'Access', 'tone': 'bad', 'route': 'accessibility', 'rule': 'access', 'count': n})
    return out[:4]


def build_summary(metrics: dict, headline: dict, signals: List[dict]) -> dict:
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
        acc = TEMPLATES['summary.no_price']
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


def changes_status(now: dict, prev: Optional[dict], prev_code: Optional[str]) -> tuple:
    """('first_cycle' | 'not_comparable' | 'compared', note). Two cycles are
    compared on a surface only when the same agents answered there and both
    read named/first over the same tier; otherwise the block says why and
    shows no delta."""
    if prev is None:
        return 'first_cycle', TEMPLATES['changes.first_cycle']
    a, b = set(now['agent_set']), set(prev['agent_set'])
    if a != b:
        if b and b < a:
            return 'not_comparable', TEMPLATES['changes.not_comparable_subset'].format(code=prev_code, agents=_agents_text(b))
        return 'not_comparable', TEMPLATES['changes.not_comparable'].format(
            code=prev_code, prev=_agents_text(b) if b else 'no agent', now=_agents_text(a) if a else 'no agent')
    if now['tier'] == UNPROMPTED and not prev['total']['named_of']:
        return 'not_comparable', TEMPLATES['changes.not_comparable_tier'].format(code=prev_code)
    return 'compared', None


def build_changes(now: dict, prev: Optional[dict], prev_code: Optional[str]) -> List[dict]:
    """Each metric this cycle against the previous scored one, both on the
    same surface and agent set, each over its own denominator (CHANGE_METRICS).
    [] unless changes_status says 'compared'."""
    if changes_status(now, prev, prev_code)[0] != 'compared':
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
                   study_questions: Optional[int] = None) -> dict:
    """
    GET /api/console/overview: This week's blocks for one cycle, per surface.

    rows: load_overview_rows (one per run). visibility: the 2C-1 read with
    extend_visibility applied. true_value: build_true_value. access: supply's
    access payload, or None. previous: {'code', 'rows', 'visibility'} for the
    newest earlier scored cycle, or None.
    """
    vis_rows = visibility.get('byQuestion') or []
    surface_list = ordered_surfaces({_surface_of(r) for r in rows} | {v['surface'] for v in vis_rows})
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
        status, note = changes_status(metrics, prev_metrics, (previous or {}).get('code'))
        if prev_metrics is not None:
            prev_metrics['code'] = previous.get('code')
        head = visibility_headline(vis_rows, s, next((r['name'] for r in (visibility.get('ranking') or {}).get('rows') or [] if r.get('you')), None))
        products = build_products(true_value, vis_rows, s, variant_of_run=variant_of_run, reason_of_run=reason_of_run)
        signals = build_signals(metrics, products, surface=s, brand=brand, cycle_start=cycle.get('start_date'),
                                access_problems=access_problems)
        by_surface[s] = {
            'agents': build_agents(metrics, prev_metrics, status),
            'products': products,
            'signals': signals,
            'summary': build_summary(metrics, head, signals),
            'changes': build_changes(metrics, prev_metrics, (previous or {}).get('code')),
            'changes_status': status,
            'changes_note': note,
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
        'changes_note': None if previous else TEMPLATES['changes.first_cycle'],
        'ranking': visibility.get('ranking'),
        # 2C-2c: questions is the study's count, the one Studies shows; asked
        # is how many of them this cycle ran
        'coverage': {'questions': study_questions if study_questions is not None else len({r.get('query_code') for r in rows}),
                     'asked': len({r.get('query_code') for r in rows}), 'agents': len({surfaces.agent_of(r.get('platform')) or r.get('platform') for r in rows}),
                     'runs': len(rows), 'answers': sum(1 for r in rows if r.get('answer_status') == surfaces.ANSWERED),
                     'unprompted': sum(1 for v in answered if v.get('tier') == UNPROMPTED)},
        'access_run': (access or {}).get('access_run'),
        'read_errors': read_errors or {},
        'rules': {k: v for k, v in TEMPLATES.items()},
    }


# ─── Accessibility checks ──────────────────────────────────────────────────

def _measured(request: dict) -> bool:
    """An identity whose probe was never configured is not measured, which
    is not a problem: it never counts as one."""
    if request.get('measured') is not None:
        return bool(request['measured'])
    return not str(request.get('result') or '').startswith('not measured')


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
    a program price nor a question has no caption."""
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
            for sf in sorted({r.get('surface') or 'unlabelled' for r in runs}):
                mine = [r for r in runs if (r.get('surface') or 'unlabelled') == sf]
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


def catalog_stages(rows: List[dict], *, quoted_variants: Dict[str, dict], published_listings: Iterable,
                   ) -> List[dict]:
    """Per catalog row: `measured` when a scored cycle quoted it, `published`
    when any channel published it, `verified` when the latest scored cycle's
    prices for it all agree with the record (and at least one was scored)."""
    pub = set(published_listings)
    out = []
    for row in rows:
        key = row.get('variant_id') or rm._gtin14(row.get('gtin'))
        q = quoted_variants.get(row.get('variant_id')) or quoted_variants.get(rm._gtin14(row.get('gtin')) or '') or {}
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

def load_overview_rows(conn, cycle: dict) -> List[dict]:
    rows = []
    for r in conn.execute(text("""
        SELECT r.id AS run_id, r.platform, r.surface, r.answer_status,
               q.tier, q.stage, q.query_code, q.source_ref, o.outcome, o.reason_code
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        LEFT JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c
    """), {'c': cycle['id']}).mappings():
        row = dict(r)
        row['variant_id'] = (_json(row.pop('source_ref')) or {}).get('variant_id')
        rows.append(row)
    return rows


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
