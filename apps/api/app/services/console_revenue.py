"""
2I-9: the revenue model behind the console's Impact screen, its Overview
block and the dollars on the screens the demo puts them on.

The model is the console demo's (parleohq/truesync apps/console/src/data/
v2common.ts computeRevenue), unchanged: the console computes the dollars; soa
serves the inputs and the measured shares in the RevenueModel shape it takes.

Inputs (B1): one row per org x merchant (soa_merchant_revenue_inputs), the
merchant's sales in scope and its own values of the three public parameters
and the win-back share of Lost. A null field reads the default
(soa_shared/revenue.py); sales in scope has none, and with no sales in scope
the console shows the shares and no dollars. Sales in scope is a customer's
financial figure: it is served on that merchant's own console reads (these
endpoints) and nowhere else.

Pure functions over rows (the loaders at the bottom do the SQL).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from app.services import console_read_models as rm
from soa_shared import revenue as defaults

INPUT_FIELDS = ('scope_value', 'scope_display', 'scope_source', 'influence', 'horizon', 'penalty', 'lost_gainable',
                'currency')


def _billions(value: float, cur: str) -> str:
    """$3.99e9 -> '$4.0B', as the demo's scope display reads."""
    a = float(value)
    if a >= 1e9:
        return f"{cur}{a / 1e9:.{0 if a >= 1e10 else 1}f}B"
    if a >= 1e6:
        return f"{cur}{a / 1e6:.{1 if a < 9.95e6 else 0}f}M"
    return f"{cur}{a:,.0f}"


def inputs_view(row: Optional[dict], merchant: str) -> dict:
    """The inputs as the console reads them: each field with its value, its
    display, its source line and whether it is the default. Sales in scope
    with no value is `entered: false`."""
    row = row or {}
    cur = row.get('currency') or defaults.DEFAULT_CURRENCY
    scope_value = row.get('scope_value')
    scope_value = float(scope_value) if scope_value is not None else None
    out = {
        'merchant': merchant,
        'currency': cur,
        'scope': {'label': defaults.SCOPE['label'], 'value': scope_value, 'entered': scope_value is not None,
                  'display': (row.get('scope_display') or _billions(scope_value, cur)) if scope_value is not None else None,
                  'source': row.get('scope_source') or defaults.SCOPE['source']},
        'updated_by': row.get('updated_by'),
        'updated_at': _iso(row.get('updated_at')),
        'saved': bool(row),
    }
    for field, d in defaults.SHARE_DEFAULTS.items():
        v = row.get(field)
        value = float(v) if v is not None else d['value']
        out[field] = {'label': d['label'], 'value': value, 'display': defaults.display_share(value),
                      'source': d['source'], 'default': v is None, 'default_value': d['value']}
    return out


def _iso(v) -> Optional[str]:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, 'isoformat') else str(v)


class InputError(ValueError):
    """A value the inputs refuse, with the reason."""


def validated(body: dict) -> dict:
    """The fields of a PUT body to write: those sent, each checked. A field
    sent as null resets to its default. Unknown fields are refused."""
    unknown = set(body) - set(INPUT_FIELDS)
    if unknown:
        raise InputError(f"unknown field {sorted(unknown)[0]!r}")
    out = {}
    for field, value in body.items():
        if field in defaults.RANGES:
            why = defaults.out_of_range(field, value)
            if why:
                raise InputError(why)
            out[field] = None if value is None else float(value)
        elif field == 'currency':
            if value is not None and value not in defaults.CURRENCIES:
                raise InputError(f"currency must be one of {', '.join(repr(c) for c in defaults.CURRENCIES)}")
            out[field] = value
        else:
            if value is not None and (not isinstance(value, str) or len(value) > 600):
                raise InputError(f'{field} must be text of at most 600 characters')
            out[field] = value.strip() or None if isinstance(value, str) else None
    return out


# ─── loaders ───────────────────────────────────────────────────────────────

def load_inputs(conn, org_id: int, merchant: str) -> Optional[dict]:
    row = conn.execute(text("""
        SELECT * FROM soa_merchant_revenue_inputs WHERE org_id = :o AND merchant_slug = :m
    """), {'o': org_id, 'm': merchant}).mappings().fetchone()
    return dict(row) if row else None


def save_inputs(conn, org_id: int, merchant: str, fields: dict, user: Optional[str]) -> None:
    """Upsert the fields sent (the others keep their stored value)."""
    current = load_inputs(conn, org_id, merchant)
    now = datetime.now(timezone.utc)
    if current is None:
        values = {f: fields.get(f) for f in INPUT_FIELDS}
        conn.execute(text(f"""
            INSERT INTO soa_merchant_revenue_inputs (org_id, merchant_slug, {', '.join(INPUT_FIELDS)}, updated_by, updated_at)
            VALUES (:org_id, :merchant_slug, {', '.join(':' + f for f in INPUT_FIELDS)}, :updated_by, :updated_at)
        """), {'org_id': org_id, 'merchant_slug': merchant, **values, 'updated_by': user, 'updated_at': now})
        return
    if not fields:
        return
    sets = ', '.join(f"{f} = :{f}" for f in fields)
    conn.execute(text(f"""
        UPDATE soa_merchant_revenue_inputs SET {sets}, updated_by = :updated_by, updated_at = :updated_at
        WHERE org_id = :org_id AND merchant_slug = :merchant_slug
    """), {**fields, 'updated_by': user, 'updated_at': now, 'org_id': org_id, 'merchant_slug': merchant})


def delete_inputs(conn, org_id: int, merchant: str) -> None:
    conn.execute(text("DELETE FROM soa_merchant_revenue_inputs WHERE org_id = :o AND merchant_slug = :m"),
                 {'o': org_id, 'm': merchant})


# ═══ B2: the measured shares ═══════════════════════════════════════════════
#
# Lost: of the answered unprompted runs (soa_shared/unprompted.py, 2I-7's
#   rule), every agent together (2I-8's `all`), the share whose first pick is
#   a brand other than ours, in the comparison set or not. An answer naming no
#   brand is in the denominator and not lost; for a brand merchant so is one
#   whose first pick is a retailer (soa_shared/retailers.py names it). For a
#   seller the comparison set is other stores, so another store first is lost.
#   The denominator is the unprompted set because that is where a brand choice
#   can happen; the share is applied to all AI-touched sales on the demo's
#   assumption that the study's question mix stands in for the shopper's
#   journey.
#   2K-1: over the brand-choice set (soa_shared/unprompted.is_brand_choice):
#   the unprompted runs plus the comparison tier's ("Pampers vs Huggies for
#   newborns" names the brand, so it is not unprompted, but its first pick is
#   a brand choice). With no comparison question the set is the unprompted
#   one and every sentence reads as before; with one, they say brand-choice.
# Missed (2K-4 §B5, Elton, Oct 21: an agent that declines to price is not a
#   wrong answer): of the scored price answers (exact, partial, stale, wrong,
#   and another brand's price), the share that got the price wrong (wrong or
#   stale) or quoted another brand's price. An answer that gave no price at
#   all (`absent`, not another brand's) is counted on its own, `no_price`,
#   and said on the driver's second line; 2I-9 counted it as missed when the
#   reference had a price ("missing or wrong", the demo's Petco wording).
#   Unverifiable is outside both, as everywhere. Then counted once, by the
#   demo's rule: missed = raw x (1 - lost), a price miss counted only for
#   shoppers the brand choice did not already send elsewhere.

SCORED_PRICE = ('exact', 'partial', 'stale', 'wrong')
MISSED_PRICE = ('wrong', 'stale')
AGENT_ORDER = ('chatgpt', 'gemini', 'aimode', 'perplexity', 'copilot', 'claude')

#: Every sentence the money screens show from soa, by rule and merchant kind
#: (brand | retailer). House copy: no dashes, no semicolons.
TEMPLATES = {
    'lost.title.brand': "Another brand gets the first pick",
    'lost.title.retailer': "Agents put another store first",
    'lost.measured.brand': "{n} of the {of} {set} answers put another brand first, {pct}.{rivals}{you}",
    'lost.measured.retailer': "{n} of the {of} {set} answers put another store first, {pct}.{rivals}{you}",
    'lost.rivals': " {lead} first in {k}{rest}.",
    'lost.you': " {name} came first in {k}.",
    'lost.fix.brand': "Publish the brand's facts as one record agents can read, so brand-choice answers can find it",
    'lost.fix.retailer': "Publish the offer record so cheapest-place answers can see your price",
    'missed.title.brand': "Prices and deals agents get wrong",
    'missed.title.retailer': "{name}'s price is wrong",
    'missed.measured': ("{n} of the {of} price answers got the price wrong or quoted another brand's price, {pct}. "
                        "Counted once: only for shoppers the brand choice did not already send elsewhere, {once}."),
    'missed.no_price': "{n} {answers} gave no price at all.",
    'missed.fix.brand': "One record per SKU, on every surface retailers and agents read",
    'missed.fix.retailer': "One offer record with the price and program terms, published to every surface",
    'access.title': "Agents can't read {domain}, so they quote other sources",
    'access.measured': "{n} agent {identities} could not read the pages in the last access run: {who}.",
    'access.fix': "Feeds put the offer where agents look, with no crawl needed",
    'access.none': "Every measured agent identity read the pages in the last access run.",
    'basis': ("Each share is measured on the questions where it can happen, over every agent, in cycle {cycle}. Brand "
              "choice: {lost_n} of {lost_of} {set} answers put another {rival} first ({lost_pct}). Price: "
              "{miss_n} of {miss_of} price answers got the price wrong or quoted another brand's ({miss_raw}). The model assumes "
              "an AI-assisted purchase passes through both, a {choice} and then a price, and counts a price miss only "
              "where the {choice} didn't already go elsewhere, so no shopper counts twice ({miss_pct} once). The "
              "{set} share is applied to all AI-touched sales, on the assumption that the study's question mix "
              "stands in for the shopper's journey. Gainable counts all of Missed, since you own the record, plus "
              "{win_back} of Lost, the win-back share set on Impact."),
    'hero_basis': ("{lost_pct} of {set} answers put another {rival} first, plus {miss_raw} of price answers get "
                   "{name} wrong, each shopper counted once"),
    'by_agent.note': "{agent}: {n} of the {of} answers that go against you.",
    'not_measured.no_unprompted': "no unprompted question this cycle",
    'not_measured.no_answers': "no answered unprompted question this cycle",
    'dollars.no_scope': "enter sales in scope on Impact",
}


def _pct(x: float) -> str:
    return f"{round(x * 100):d}%"


def _ident(n: int) -> str:
    return 'identity' if n == 1 else 'identities'


def is_retailer_name(name: Optional[str]) -> bool:
    from soa_shared.retailers import retailers_named
    return bool(name) and bool(retailers_named(name))


def revenue_shares(vis_rows: list, catalog_rows: list, lost_gainable: float = 0.0, *, kind: str = 'brand') -> dict:
    """The two shares, the counts behind them and the runs in each set.

    vis_rows: Visibility's byQuestion (answered, unprompted, brand_choice,
    tier, first, agent, run) over every surface. catalog_rows: one per
    catalog-tier run (run_id, platform, answer_status, outcome, reason_code,
    reference_price). 2K-1: Lost is over the brand-choice rows."""
    from soa_shared import surfaces

    def choice(v) -> bool:
        return v['brand_choice'] if 'brand_choice' in v else bool(v.get('unprompted'))
    unprompted = [v for v in vis_rows if v.get('answered') and choice(v)]
    asked_unprompted = any(choice(v) for v in vis_rows)
    # 2P-1: the console's copy names the set one way (parity._answers)
    set_words = 'brand-choice'

    def lost_pick(v) -> bool:
        f = v.get('first')
        if not f or f.get('you'):
            return False
        return not (kind == 'brand' and is_retailer_name(f.get('name')))
    lost = [v for v in unprompted if lost_pick(v)]

    answered = [r for r in catalog_rows if r.get('answer_status') == surfaces.ANSWERED]

    other_brand = lambda r: r.get('outcome') == 'absent' and r.get('reason_code') == 'other_brand'  # noqa: E731

    def missed_price(r) -> bool:
        return r.get('outcome') in MISSED_PRICE or other_brand(r)
    denom = [r for r in answered if r.get('outcome') in SCORED_PRICE or other_brand(r)]
    missed = [r for r in denom if missed_price(r)]
    # 2K-4: an answer that gave no price is not a wrong one: counted on its own
    no_price = [r for r in answered if r.get('outcome') == 'absent' and not other_brand(r)]

    lost_share = len(lost) / len(unprompted) if unprompted else None
    raw = len(missed) / len(denom) if denom else None
    once = raw * (1 - lost_share) if raw is not None and lost_share is not None else None
    reason = (None if unprompted else
              TEMPLATES['not_measured.no_answers'] if asked_unprompted else TEMPLATES['not_measured.no_unprompted'])

    agent_of = lambda r: surfaces.agent_of(r.get('platform')) or r.get('platform')  # noqa: E731
    against = [v['agent'] for v in lost] + [agent_of(r) for r in missed]
    per = {}
    for a in against:
        per[a] = per.get(a, 0) + 1
    order = {a: i for i, a in enumerate(AGENT_ORDER)}
    by_agent = [{'agent': a, 'n': n, 'share': n / len(against)}
                for a, n in sorted(per.items(), key=lambda kv: (order.get(kv[0], 99), kv[0]))]
    rivals = {}
    for v in lost:
        rivals[v['first']['name']] = rivals.get(v['first']['name'], 0) + 1
    you_first = sum(1 for v in unprompted if (v.get('first') or {}).get('you'))
    run_key = lambda run: int(str(run).replace('run-', '') or 0)  # noqa: E731
    return {
        'measured': lost_share is not None, 'reason': reason,
        'lost': {'share': lost_share, 'n': len(lost), 'of': len(unprompted), 'you_first': you_first,
                 'rivals': sorted(rivals.items(), key=lambda kv: (-kv[1], kv[0])),
                 'first_answer': min((v['run'] for v in lost), key=run_key, default=None),
                 'gainable': float(lost_gainable or 0.0)},
        'missed': {'raw': raw, 'share': once, 'n': len(missed), 'of': len(denom),
                   'unverifiable': sum(1 for r in answered if r.get('outcome') == 'unverifiable'),
                   'no_price_runs': len(no_price),
                   'first_answer': f"run-{min(r['run_id'] for r in missed)}" if missed else None, 'gainable': 1.0},
        'by_agent': by_agent, 'against': len(against),
        # 2K-1: what the Lost set is called in every sentence
        'set': set_words,
    }


def compute(model: dict, influence: Optional[float] = None) -> Optional[dict]:
    """v2common.ts computeRevenue, for the history endpoint (the console
    computes its own screens): None when there are no dollars to compute."""
    if not model.get('dollars'):
        return None
    scope = model['scope']['value']
    ai = scope * (influence if influence is not None else model['influence']['value'])
    pen = model['penalty']['value']
    drivers = [{'id': d['id'], 'kind': d['kind'], 'value': ai * d['share'] * pen} for d in model['drivers']]
    for d, src in zip(drivers, model['drivers']):
        d['gainable'] = d['value'] * src['gainable']
    lost = sum(d['value'] for d in drivers if d['kind'] == 'lost')
    missed = sum(d['value'] for d in drivers if d['kind'] == 'missed')
    return {'ai_touched': ai, 'in_answers': ai * min(1.0, sum(d['share'] for d in model['drivers'])),
            'lost': lost, 'missed': missed, 'exposed': lost + missed, 'gainable': sum(d['gainable'] for d in drivers)}


def build_model(shares: dict, inputs: dict, *, cycle: str, kind: str, name: str, domain: Optional[str],
                access_requests: Optional[list] = None) -> dict:
    """The RevenueModel the console's computeRevenue takes, with the counts
    behind it. `dollars` is false (and `dollars_reason` says why) when Lost
    is not measured or sales in scope is not entered: never a $0."""
    from app.services.console_read_models import AGENT_NAMES
    k = 'brand' if kind == 'brand' else 'retailer'
    L, M = shares['lost'], shares['missed']
    set_words = shares.get('set') or 'brand-choice'
    drivers = []
    if shares['measured']:
        rivals = L['rivals']
        lead = (TEMPLATES['lost.rivals'].format(lead=rivals[0][0], k=rivals[0][1],
                                                rest=f", {rivals[1][0]} in {rivals[1][1]}" if len(rivals) > 1 else '')
                if rivals else '')
        you = TEMPLATES['lost.you'].format(name=name, k=L['you_first'])
        drivers.append({'id': 'lost', 'kind': 'lost', 'title': TEMPLATES[f'lost.title.{k}'],
                        'measured': TEMPLATES[f'lost.measured.{k}'].format(n=L['n'], of=L['of'], pct=_pct(L['share']),
                                                                            rivals=lead, you=you, set=set_words),
                        'share': L['share'], 'gainable': L['gainable'], 'fix': TEMPLATES[f'lost.fix.{k}'],
                        'route': 'visibility', **({'answerId': L['first_answer']} if L['first_answer'] else {})})
        if M['share'] is not None:
            drivers.append({'id': 'missed', 'kind': 'missed', 'title': TEMPLATES[f'missed.title.{k}'].format(name=name),
                            'measured': TEMPLATES['missed.measured'].format(n=M['n'], of=M['of'], pct=_pct(M['raw']),
                                                                            once=_pct(M['share'])),
                            'share': M['share'], 'gainable': 1.0, 'fix': TEMPLATES[f'missed.fix.{k}'],
                            'route': 'true-value', **({'answerId': M['first_answer']} if M['first_answer'] else {}),
                            # 2K-4: the answers that gave no price, said on a second line, never counted
                            **({'no_price': {'count': M['no_price_runs'], 'line': TEMPLATES['missed.no_price'].format(
                                n=M['no_price_runs'], answers='answer' if M['no_price_runs'] == 1 else 'answers')}}
                               if M['no_price_runs'] else {})})
    entered = inputs['scope']['entered']
    dollars = shares['measured'] and entered
    rival = 'brand' if k == 'brand' else 'store'
    blocked = [r for r in access_requests or [] if r.get('measured', True) and not r.get('ok')]
    access = None
    if access_requests is not None:
        # 2K-4 (B4): each display name once, its tokens counted ("Googlebot (2 tokens)")
        groups = rm.group_identities(blocked)
        who = ', '.join(g['label'] for g in groups)
        access = {'n': len(groups), 'identities': [g['identity'] for g in groups], 'tokens': len(blocked),
                  'title': TEMPLATES['access.title'].format(domain=domain or 'your pages'),
                  'measured': (TEMPLATES['access.measured'].format(n=len(groups), identities=_ident(len(groups)), who=who)
                               if blocked else TEMPLATES['access.none']),
                  'fix': TEMPLATES['access.fix'], 'route': 'accessibility'}
    model = {
        'cycle': cycle,
        'measured': shares['measured'], 'reason': shares['reason'],
        'dollars': bool(dollars),
        'dollars_reason': None if dollars else (shares['reason'] if not shares['measured'] else TEMPLATES['dollars.no_scope']),
        'currency': inputs['currency'],
        'scope': inputs['scope'],
        'influence': inputs['influence'], 'horizon': inputs['horizon'], 'penalty': inputs['penalty'],
        'lost_gainable': inputs['lost_gainable'],
        'drivers': drivers,
        'byAgent': [{'agent': b['agent'], 'share': b['share'], 'n': b['n'],
                     'note': TEMPLATES['by_agent.note'].format(agent=AGENT_NAMES.get(b['agent'], b['agent']), n=b['n'],
                                                               of=shares['against'])} for b in shares['by_agent']],
        'access': access,
        'shares': {'lost': L['share'], 'missed_raw': M['raw'], 'missed': M['share']},
        'counts': {'lost': {k2: L[k2] for k2 in ('n', 'of', 'you_first')}, 'lost_set': set_words,
                   'lost_rivals': [list(x) for x in L['rivals']],
                   'missed': {k2: M[k2] for k2 in ('n', 'of', 'unverifiable', 'no_price_runs')}, 'against': shares['against']},
        'basis': (TEMPLATES['basis'].format(cycle=cycle, lost_n=L['n'], lost_of=L['of'], lost_pct=_pct(L['share']),
                                            rival=rival, miss_n=M['n'], miss_of=M['of'],
                                            miss_raw=_pct(M['raw']) if M['raw'] is not None else 'not measured',
                                            choice='brand choice' if k == 'brand' else 'store choice',
                                            miss_pct=_pct(M['share']) if M['share'] is not None else 'not measured',
                                            win_back=_pct(L['gainable']), set=set_words)
                  if shares['measured'] else None),
        'heroBasis': (TEMPLATES['hero_basis'].format(lost_pct=_pct(L['share']), rival=rival, set=set_words,
                                                     miss_raw=_pct(M['raw']) if M['raw'] is not None else '0%', name=name)
                      if shares['measured'] else None),
        'rules': TEMPLATES,
    }
    model['today'] = compute(model)
    model['by_2030'] = compute(model, model['horizon']['value']) if dollars else None
    return model


def load_catalog_rows(conn, cycle: dict) -> list:
    """One row per catalog-tier run, with the reference price its expectation
    carried (the record's or the page's, as scored)."""
    from app.services import console_read_models as rm
    unpriced = rm.brand_sets_no_price_runs(conn, cycle)   # 2K-1
    out = []
    for r in conn.execute(text("""
        SELECT r.id AS run_id, r.platform, r.answer_status, o.outcome, o.reason_code, o.expected_answer
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        LEFT JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c AND q.tier = 'catalog_accuracy'
        ORDER BY r.id
    """), {'c': cycle['id']}).mappings():
        row = rm.not_priced(dict(r), unpriced)
        exp = row.pop('expected_answer')
        if isinstance(exp, str):
            import json as _j
            try:
                exp = _j.loads(exp)
            except ValueError:
                exp = None
        row['reference_price'] = (exp or {}).get('amount') if isinstance(exp, dict) else None
        out.append(row)
    return out
