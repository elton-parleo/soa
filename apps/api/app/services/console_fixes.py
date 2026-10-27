"""
2T-8 (B4, B5): the Fix queue and Approvals of a brand at retail (supply's
`mode` manufacturer), derived from what exists: the Overview's ranked
signals, supply's compliance rules (their `approval`, `on` and history), the
held release (the hold's rows and their journal) and the brand's stated
send, and the brand pages' GTIN rows. No table, no owner, no date, no "New
fix", no team chain: `owner`, `due`, `condition` and every team are served
None, because nothing records them. The demo (parleohq/truesync console-demo,
data/pg.ts `fixes`, `approvals`, and the seed Fix queue and Approvals
screens) is the shape. Copy: FIX_TEMPLATES. Deterministic; no model.

One fix per source, ranked by what it wins back (the pool's modeled value
the Overview ranks its signals by, then the signal's count), numbered in
rank order. States: needs_decision, in_flight, queued, shipped.
"""
from typing import Dict, Iterable, List, Optional

from app.services import console_manufacturer as manu
from app.services import console_release as rel

FIX_TEMPLATES = {
    'size_chart.title': 'One size chart per line, on every surface',
    'size_chart.group': '{lines} {size}: {range}',
    'size_chart.markup': "Start with {domain_s} own markup, where {where}, then the record retailers receive.",
    'size_chart.markup.one': '{line} says {was} for {size}',
    'size_chart.retailers': 'Then the record retailers receive.',
    'gtin.title': 'Fix the GTIN mapping on {domain}',
    'gtin.zero': '{lines} {gtins} {verb} the leading zero',
    'gtin.twice': '{gtin} sits on {counts}',
    'gtin.team': "{brand_s} web team fixes it on {domain}.",
    'retired.title': 'Retire {retired}, with {successor} as the successor',
    'retired.text': ("Mark {retired} retired in the record and point it at {successor}. {named} of {of} category "
                     "answers named {retired} this cycle."),
    'store.title': 'Show {line} as club only',
    'store.text': ("The record lists {clubs}, the same way, as the line's sellers. {n} of {m} answers about it sent the "
                   "shopper to {stores}."),
    'release.title': 'Send the Manufacturer Center file',
    'release.text': ("{n} records compiled in manufacturer mode, no price, every retailer shown the same way. "
                     "{brand_s} own team sends it."),
    'deals.title': 'Publish {brand}-funded deals retailer-neutral, with dates',
    'deals.text': ("When {brand} funds a deal it goes in the record with its terms, end date and every retailer that "
                   "honors it, listed the same way. Manufacturer mode never sets a price."),
    'scope.lines': '{lines} {lines_w}, {skus} {skus_w}',
    'scope.pages': '{n} product {pages}',
    'scope.records': '{n} {records}',
    'scope.line': '1 line',
    'scope.skus': '{n} {skus}',
    'scope.deals': '{brand}-funded deals only',
    'state.needs_decision': 'Needs a decision',
    'state.in_flight': 'Approved, in flight',
    'state.in_flight.held': 'Compiled, held',
    'state.queued': 'Queued',
    'state.shipped': 'Shipped',
    'hero': '{k} of {n} fixes need a decision.',
    'hero.first': ' First up: {title}.',
    'hero.none': 'Nothing waits on a decision. Every fix is in flight, queued or shipped.',
    'hero.empty': 'No fix: no signal, rule or held release asks for one this cycle.',
    'order_note': ("The first three need no new discount: they publish what already exists where agents read. Inside "
                   "each group the queue is ranked by what the fix wins back."),
    'approvals.release.title': '{n} records, Manufacturer Center first',
    'approvals.release.text': ("The held file: {n} records compiled in manufacturer mode, no price, every retailer shown "
                               "the same way. {brand_s} own team sends it. Its send is stated on Publishing."),
    'approvals.requested.rule': 'Rule seeded',
    'approvals.requested.release': 'Hold compiled',
    'approvals.hero': '{k} of {n} requests waiting.',
    'approvals.hero.first': ' {title} waits on approval.',
    'approvals.hero.none': 'Every request is decided.',
    'approvals.approver': 'Approver',
}

T = FIX_TEMPLATES

STATES = ('needs_decision', 'in_flight', 'queued', 'shipped')
POOLS = ('missed', 'lost', 'both', 'root')

#: The demo's surface tags, in its order.
SURFACE_TAGS = ('Product record', 'Site markup', 'Manufacturer Center', 'GTIN', 'Deals', 'Next release')

#: B5: the rule that gates each kind of fix.
GATE = {'size_chart': 'r5', 'retired': 'r6', 'deals': 'r4', 'store': 'r2'}

#: A signal's tone -> the fix's severity (High / Medium); a one-line fix is Quick.
SEVERITY = {'bad': 'High', 'warn': 'Medium'}

#: B5's static chains copy (the demo's "Who has to say yes, by what changes"); no team is configured, so None.
CHAINS = ('Price or program price', 'Member benefits', 'Claims, coupons, retailer order', 'Edge and access',
          'Retailer communications')


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _possessive(name: str) -> str:
    from soa_shared.possessive import possessive
    return possessive(name)


def _rule(rules: Optional[List[dict]], code: str) -> Optional[dict]:
    return next((r for r in rules or [] if r.get('code') == code), None)


def rule_on_at(rule: Optional[dict]) -> Optional[str]:
    """When the rule was last switched on (its history's newest change of `on` to true), else approved; None for a
    rule that came on without a recorded change."""
    turned = [str(h.get('at')) for h in (rule or {}).get('history') or []
              if ((h.get('changes') or {}).get('on') or [None, None])[-1] is True and h.get('at')]
    return max(turned) if turned else (rule or {}).get('approved_at')


def newest_hold(pubs: List[dict]) -> Optional[str]:
    """The newest compile-and-hold's compiled_at (supply's held rows)."""
    return max((str(p['compiled_at']) for p in pubs or [] if p.get('compiled_at')), default=None)


def _ts(value) -> str:
    """A comparable stamp: supply writes some with an offset and some without; both are UTC."""
    text = str(value or '').replace('T', ' ')
    return text[:19]


def gated_state(rule: Optional[dict], pubs: List[dict]) -> str:
    """B4: needs_decision while the rule is not approved and on; in_flight when it is on and the newest hold
    predates the change; shipped when a hold after it exists."""
    if not rule or rule.get('approval') != 'approved' or not rule.get('on'):
        return 'needs_decision'
    hold = newest_hold(pubs)
    on_at = rule_on_at(rule)
    if hold is None:
        return 'in_flight'
    if on_at is not None and _ts(hold) < _ts(on_at):
        return 'in_flight'
    return 'shipped'


def _lines_skus(feed_rows: Optional[List[dict]], brand: Optional[str]) -> tuple:
    live = [r for r in feed_rows or [] if r.get('lifecycle') != 'retired']
    lines = {rel.line_key(r.get('product_name'), brand) for r in live if r.get('product_name')}
    return len(lines), len(live)


def _scope_lines(feed_rows, brand) -> str:
    lines, skus = _lines_skus(feed_rows, brand)
    return T['scope.lines'].format(lines=lines, lines_w=_plural(lines, 'line', 'lines'), skus=skus,
                                   skus_w=_plural(skus, 'SKU', 'SKUs'))


def size_chart_text(signal: dict, drift: List[dict], domain: str) -> str:
    """From the chart facts (2T-3 (4): the size's ranges, every line on each) and the markup lines."""
    facts = signal.get('facts') or {}
    parts = []
    for two in facts.get('two') or []:
        for g in two.get('groups') or []:
            parts.append(T['size_chart.group'].format(lines=manu._and(g['lines']), size=two['size'], range=g['range']))
    markup = [r for r in drift or [] if r.get('kind') == 'markup']
    where = []
    for r in markup[:2]:
        field = str(r.get('field') or '')
        line = field.split('.')[0].replace('_', ' ').title().replace('Zzz', 'Zzz')
        size = field.split('.')[1].replace('_', ' ').capitalize() if '.' in field else ''
        where.append(T['size_chart.markup.one'].format(line=line, was=r['was'].replace(' lb', ''), size=size))
    text = '. '.join(parts) + ('.' if parts else '')
    if where:
        text += (' ' if text else '') + T['size_chart.markup'].format(domain_s=_possessive(domain), where=' and '.join(where))
    elif not parts:
        text = signal.get('detail') or ''
    return text.strip()


def gtin_text(gtin_rows: List[dict], twice: List[dict], *, brand: str, domain: str) -> str:
    groups: Dict[str, int] = {}
    for f in gtin_rows:
        if f.get('digits') == 11:
            groups[f.get('line') or ''] = groups.get(f.get('line') or '', 0) + 1
    parts = [T['gtin.twice'].format(gtin=t['gtin'], counts=' and '.join(t['counts'])) for t in twice]
    if groups:
        lines = manu._and([g for g in groups if g])
        n = sum(groups.values())
        parts.append(T['gtin.zero'].format(lines=f"Every {lines}" if lines else 'Every', gtins='GTIN', verb='drops'))
    text = '. '.join(p[:1].upper() + p[1:] for p in parts)
    return f"{text}. {T['gtin.team'].format(brand_s=_possessive(brand), domain=domain)}".strip()


def gtin_twice(pages: List[dict]) -> List[dict]:
    """One GTIN on two pack counts in the brand page's markup (a variant's offers, or two variants): [{gtin, counts}]."""
    from app.services import console_product_record as pr
    seen: Dict[str, List[str]] = {}
    for page in pages or []:
        bp = page.get('brand_page') or page
        for node in pr._variants(bp.get('json_ld')):
            f = pr.node_facts(node)
            g = pr._gtin14(f['gtin'])
            if not g:
                continue
            for o in pr._offers(node) or [{'seller': None, 'count': f['count']}]:
                if o['count']:
                    words = f"{o['seller']} {o['count']} ct" if o['seller'] else f"{o['count']} ct"
                    if words not in seen.setdefault(f['gtin'], []):
                        seen[f['gtin']].append(words)
    return [{'gtin': g, 'counts': c} for g, c in seen.items() if len({w.split()[-2] for w in c}) > 1]


def build_fixes(*, signals: List[dict], rules: Optional[List[dict]], pubs: List[dict], feed_rows: Optional[List[dict]],
                drift: List[dict], gtin_rows: List[dict], twice: List[dict], values: Dict[str, float],
                brand: str, domain: str, records: int, skus: Optional[int]) -> dict:
    """B4: {fixes, summary}. Each fix {id, n, kind, title, text, pool, severity, state, state_label, scope,
    surfaces, owner: None, due: None, gate (the rule code), signal (its id), count, value}."""
    by_kind = {}
    for s in signals or []:
        by_kind.setdefault(s.get('kind'), s)
    made = []

    def add(kind, title, text, pool, severity, state, scope, tags, signal=None, gate=None, label=None):
        value = values.get('lost', 0.0) + values.get('missed', 0.0) if pool == 'both' else values.get(pool, 0.0)
        made.append({'id': kind, 'kind': kind, 'title': title, 'text': text, 'pool': pool, 'severity': severity,
                     'state': state, 'state_label': label or T[f'state.{state}'], 'scope': scope,
                     'surfaces': [t for t in SURFACE_TAGS if t in tags], 'owner': None, 'due': None, 'gate': gate,
                     'signal': (signal or {}).get('id'), 'count': (signal or {}).get('count') or 0, 'value': value})

    size = by_kind.get('size_chart')
    if size:
        add('size_chart', T['size_chart.title'], size_chart_text(size, drift, domain), size.get('pool') or 'missed',
            SEVERITY.get(size.get('tone'), 'Medium'), gated_state(_rule(rules, 'r5'), pubs), _scope_lines(feed_rows, brand),
            ('Product record', 'Site markup'), signal=size, gate='r5')
    if gtin_rows or twice:
        pages = {f.get('line') for f in gtin_rows if f.get('where') == 'markup'}
        n = len(pages) + len(twice)
        add('gtin', T['gtin.title'].format(domain=domain), gtin_text(gtin_rows, twice, brand=brand, domain=domain),
            'missed', 'High', 'needs_decision',
            T['scope.pages'].format(n=n, pages=_plural(n, 'page', 'pages')), ('Site markup', 'GTIN'))
    retired = by_kind.get('retired')
    if retired:
        f = retired.get('facts') or {}
        r6 = _rule(rules, 'r6')
        state = 'shipped' if r6 and r6.get('on') and newest_hold(pubs) else 'needs_decision'
        add('retired', T['retired.title'].format(retired=f.get('retired'), successor=f.get('successor')),
            T['retired.text'].format(retired=f.get('retired'), successor=f.get('successor'), named=f.get('n', 0),
                                     of=f.get('of', 0)),
            retired.get('pool') or 'lost', SEVERITY.get(retired.get('tone'), 'Medium'), state,
            T['scope.records'].format(n=2, records='records'), ('Product record', 'Manufacturer Center'),
            signal=retired, gate='r6')
    store = by_kind.get('store')
    if store:
        f = store.get('facts') or {}
        add('store', T['store.title'].format(line=f.get('line_label') or f.get('line')),
            T['store.text'].format(clubs=manu._and(f.get('clubs') or []), n=f.get('elsewhere', 0), m=f.get('answers', 0),
                                   stores=manu._and((f.get('stores') or [])[:2])),
            store.get('pool') or 'missed', 'Quick', gated_state(_rule(rules, 'r2'), pubs), T['scope.line'],
            ('Product record',), signal=store, gate='r2')
    rows = [p for p in pubs or [] if manu.is_held(p) or p.get('status') == manu.LIVE_STATUS]
    if rows:
        sent = manu.first_sent(pubs)
        state = 'shipped' if sent else 'in_flight'
        add('release', T['release.title'], T['release.text'].format(n=records, brand_s=_possessive(brand)), 'both', 'High',
            state, T['scope.skus'].format(n=skus if skus is not None else records,
                                          skus=_plural(skus if skus is not None else records, 'SKU', 'SKUs')),
            ('Manufacturer Center',), label=None if sent else T['state.in_flight.held'])
    r4 = _rule(rules, manu.DEALS_RULE)
    if r4 is not None:
        deal = by_kind.get('deal')
        state = 'needs_decision' if r4.get('approval') != 'approved' else 'queued' if not r4.get('on') \
            else gated_state(r4, pubs)
        add('deals', T['deals.title'].format(brand=brand), T['deals.text'].format(brand=brand),
            (deal or {}).get('pool') or 'missed', 'Medium', state, T['scope.deals'].format(brand=brand),
            ('Deals', 'Next release'), signal=deal, gate=manu.DEALS_RULE)
    ranked = sorted(enumerate(made), key=lambda e: (-e[1]['value'], -e[1]['count'], e[0]))
    fixes = []
    for i, (_, f) in enumerate(ranked):
        fixes.append({**f, 'n': i + 1})
    return {'fixes': fixes, 'summary': fix_summary(fixes)}


def fix_summary(fixes: List[dict]) -> dict:
    by_state = {s: sum(1 for f in fixes if f['state'] == s) for s in STATES}
    by_pool = {p: sum(1 for f in fixes if f['pool'] == p) for p in POOLS}
    by_surface = {t: sum(1 for f in fixes if t in f['surfaces']) for t in SURFACE_TAGS}
    need = [f for f in fixes if f['state'] == 'needs_decision']
    if not fixes:
        hero = T['hero.empty']
    elif need:
        hero = T['hero'].format(k=len(need), n=len(fixes)) + T['hero.first'].format(title=need[0]['title'])
    else:
        hero = T['hero.none']
    return {'by_state': by_state, 'by_pool': {k: v for k, v in by_pool.items() if v},
            'by_surface': {k: v for k, v in by_surface.items() if v}, 'hero': hero,
            'first': need[0]['id'] if need else None, 'order_note': T['order_note'], 'total': len(fixes)}


# ─── B5: Approvals ────────────────────────────────────────────────────────

APPROVAL_STATE = {'needs_approval': 'pending', 'approved': 'approved', 'declined': 'returned'}


def build_approvals(*, fixes: List[dict], rules: Optional[List[dict]], pubs: List[dict], records: int,
                    skus: Optional[int], brand: str) -> dict:
    """B5: {requests, summary, chains}. One request per rule that gates a fix (r5, r6, r4, r2, in the fixes'
    order), then the release. Each {code, kind, title, text, requested {what, at, by}, scope, state (pending |
    approved | returned | held | sent), approval, pool, condition: None, chain [TrueSync, the team or
    "Approver"], team: None, writable, fix}."""
    out = []
    for f in fixes:
        code = f.get('gate')
        rule = _rule(rules, code) if code else None
        if rule is None:
            continue
        history = sorted(rule.get('history') or [], key=lambda h: str(h.get('at') or ''))
        first = history[0] if history else {}
        out.append({'code': code, 'kind': 'rule', 'title': rule.get('name') or f['title'], 'text': rule.get('detail') or '',
                    'requested': {'what': T['approvals.requested.rule'], 'at': None, 'by': 'TrueSync'},
                    'decided': {'at': rule.get('approved_at'), 'by': rule.get('approved_by'), 'note': rule.get('note')}
                    if rule.get('approval') != 'needs_approval' else None,
                    'scope': skus, 'state': APPROVAL_STATE.get(rule.get('approval'), 'pending'),
                    'approval': rule.get('approval'), 'on': bool(rule.get('on')), 'pool': f['pool'],
                    'condition': None, 'chain': ['TrueSync', T['approvals.approver']], 'team': None, 'writable': True,
                    'fix': f['id'], 'fix_title': f['title'], 'first_change': first.get('at')})
    rows = [p for p in pubs or [] if manu.is_held(p) or p.get('status') == manu.LIVE_STATUS]
    if rows:
        compiled = [e for p in rows for e in p.get('journal') or [] if e.get('event') == 'compiled']
        newest = max(compiled, key=lambda e: str(e.get('at') or '')) if compiled else {}
        sent = manu.first_sent(pubs)
        release_fix = next((f for f in fixes if f['id'] == 'release'), None)
        out.append({'code': 'release', 'kind': 'release',
                    'title': T['approvals.release.title'].format(n=records),
                    'text': T['approvals.release.text'].format(n=records, brand_s=_possessive(brand)),
                    'requested': {'what': T['approvals.requested.release'], 'at': newest.get('at') or newest_hold(pubs),
                                  'by': newest.get('by') or 'TrueSync'},
                    'decided': {'at': sent.get('sent_at'), 'by': sent.get('stated_by'), 'note': None} if sent else None,
                    'scope': skus if skus is not None else records, 'state': 'sent' if sent else 'held',
                    'approval': None, 'on': None, 'pool': (release_fix or {}).get('pool', 'both'), 'condition': None,
                    'chain': ['TrueSync', T['approvals.approver']], 'team': None, 'writable': False,
                    'fix': 'release', 'fix_title': (release_fix or {}).get('title'), 'first_change': None})
    waiting = [r for r in out if r['state'] == 'pending']
    if not out:
        hero = T['approvals.hero.none']
    else:
        hero = T['approvals.hero'].format(k=len(waiting), n=len(out))
        pending = next((r for r in out if r['state'] == 'pending'), None)
        hero += T['approvals.hero.first'].format(title=pending['title']) if pending else ''
    return {'requests': out,
            'summary': {'hero': hero, 'waiting': len(waiting), 'total': len(out),
                        'by_state': {s: sum(1 for r in out if r['state'] == s)
                                     for s in ('pending', 'approved', 'returned', 'held', 'sent')}},
            'chains': [{'change': c, 'team': None} for c in CHAINS], 'teams': None}
