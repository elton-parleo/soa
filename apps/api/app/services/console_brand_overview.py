"""
2T-1 (B1, B2, B4): the Overview for a brand at retail (supply's `mode`
manufacturer, 2R-2), to the console demo's shape (parleohq/truesync
console-demo, data/pg.ts and screens/v2.tsx): the lead signal, the TrueSync
card, the charter block, the strip, the revenue head, the week in short, the
agents' facts and deals, the signals ranked by their pool, the products'
live deals and checks, the first-pick footnote, the activity, the labels.

Every number comes from a helper a tile or a block already reads: the
score's brand tiles (console_score.build_brand_metrics, served on /score),
the attribute answers and their accuracy, Visibility's routing and retired
lines, the promo pass-through and supply's deals, the revenue model's
pools, TrueSync's workspace (console_release). Nothing is counted twice and
nothing is invented: a demo field with no source is None. The copy is
BRAND_OVERVIEW_TEMPLATES, in one place. The router (app/routers/
console_manufacturer.py, brand_overview) does the reads. Shapes:
docs/console-read-models.md, "2T-1". Deterministic; no model.
"""
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional

from app.services import console_manufacturer as manu
from app.services import console_read_models as rm
from soa_shared import attribute_accuracy, surfaces
from soa_shared import promo_pass_through as ppt
from soa_shared.possessive import possessive

#: Warehouse clubs: a line sold only there is club only.
CLUB_DOMAINS = ('costco.com', 'samsclub.com', 'bjs.com')

#: Each existing signal's kind and pool (the demo's v21.ts POOLS): another
#: brand's price is a first pick lost; a fact or a price wrong is missed; an
#: access problem is the root of both and has no pool of its own.
SIGNAL_KIND = {'other_brand': ('price', 'lost'), 'fabricated': ('claim', 'missed'),
               'wrong_product': ('price', 'missed'), 'unverifiable': ('access', 'root'), 'access': ('access', 'root')}
POOL_TAG = {'lost': 'Lost pool', 'missed': 'Missed pool', 'root': 'Access'}

#: The charter's four tiles, in the demo's order, and the score tile each reads.
CHARTER = (('attribute', 'Attribute accuracy'), ('coverage', 'Retailer coverage'), ('presence', 'Category presence'),
           ('promo', 'Promo pass-through, retailer side'))

BRAND_OVERVIEW_TEMPLATES = {
    # the lead: one sentence per kind of top signal
    'lead.headline.size_chart': ("Agents read {brand} from sources that disagree, {domain} included. One push of one "
                                 "record fixes every surface."),
    'lead.headline.retired': ("Agents still send shoppers to {retired}, which {by} retired, and seldom to {successor}. "
                              "One push of one record fixes every surface."),
    'lead.headline.deal': ("{deal} ran on {skus} and {named} of {asked} answers named it. Deals stop at the retailer "
                           "page until one record carries them."),
    'lead.headline.price': ("Agents quote {brand} prices no retailer charged. One record per SKU sends every agent to "
                            "the retailers the same way."),
    'lead.headline.claim': ("Agents state {brand} facts {domain} never published. One push of one record fixes every "
                            "surface."),
    'lead.headline.store': ("Agents send shoppers for a club-only {line} to a store that does not sell it. One record "
                            "lists every retailer that does, the same way."),
    'lead.headline.access': "Agents can't read {domain}, so they quote other sources. One record reaches them anyway.",
    'lead.do': "Compile one {brand} record per SKU and hold it for {name_s} team to send: {surfaces}.",
    'lead.do.none': "Compile one {brand} record per SKU. Nothing is compiled yet.",
    'lead.cta.push': 'See the one push',
    'lead.cta.answers': 'See the answers',
    # the lead's two tiles, per kind
    'fact.size_chart.who': '{line} {size} weight range',
    'fact.size_chart.of': 'ranges',
    'fact.size_chart.cap': '{sources}',
    'fact.size_chart.source': '{who} says {range}',
    'fact.size_chart.source_short': '{who} {range}',
    'fact.markup.who': '{domain} markup',
    'fact.markup.of': 'lines',
    'fact.markup.cap': "where {domain_s} own markup contradicts its size chart: {lines}",
    'fact.answers.who': '{size} weight answers',
    'fact.answers.cap': 'gave the range {domain} states',
    'fact.retired.who': '{retired} named',
    'fact.retired.cap': 'brand-choice answers named {retired}, which {by} retired',
    'fact.successor.who': '{successor} named',
    'fact.successor.cap': 'named {successor}, its successor',
    'fact.deal.cap': 'answers on its SKUs named it',
    'fact.promo.who': 'Promo pass-through',
    'fact.promo.cap': 'cheapest-place answers named a deal live that day',
    'fact.signal.cap': '{title}',
    'fact.other_brand.who': "Another brand's price",
    'fact.fabricated.who': 'Facts never published',
    'fact.wrong_product.who': 'Wrong prices on one product',
    'fact.unverifiable.who': 'Prices not checked',
    'fact.access.who': 'Agents shut out',
    'fact.prices.who': 'Prices right',
    'fact.prices.cap': 'scored price answers matched the retailer',
    'fact.store.who': '{line}',
    'fact.store.cap': 'where-to-buy answers named a club',
    'fact.store_sent.who': 'Sent elsewhere',
    'fact.store_sent.cap': 'cheapest-place answers sent the shopper to {stores}',
    # the new signals
    'signal.size_chart.two': '{domain} runs two {size} charts, and agents repeat both.',
    'signal.size_chart.markup': "{domain_s} own markup contradicts its size chart on {n} {lines}.",
    'signal.size_chart.pages': 'Retailer pages state other weight ranges than {domain}.',
    'signal.size_chart.detail.chart': '{line} {size} is {range}',
    'signal.size_chart.detail.page': '{retailer} lists {line} {size} at {range}',
    'signal.size_chart.detail.markup': "{line} {size} markup says {was}, the chart {now}",
    'signal.size_chart.detail.answers': '{k} of {n} agent answers on {sizes} gave the range {domain} states',
    'signal.retired.title': 'Agents named {retired} {n} {times} and {successor} {k} {k_times}.',
    'signal.retired.detail': ("{by} retired {retired} for {successor}. Across {of} brand-choice answers agents named "
                              "{retired} in {n} and {successor} in {k}. {agents} of {agents_of} agents named {retired}."),
    'signal.store.title': 'A club-only {line}, sent to {stores}.',
    'signal.store.detail': ("The feed lists {line} only at {clubs}. {n} of {m} answers about it named {stores}, and "
                            "{k} of {where} where-to-buy answers named a club."),
    'signal.deal.title': '{deal} ran on {skus}. {named_words} named it.',
    'signal.deal.detail': ("{text} was live on {skus} on {day}. {named} of {asked} cheapest-place answers on those SKUs "
                           "mentioned it."),
    'signal.deal.none': 'No answer',
    # the charter's second lines
    'charter.attribute.cap': "{k} of {n} retailer pages and answers match {domain_s} weight range",
    'charter.attribute.line': 'Retailer pages got it right {pk} of {pn} times and agent answers {ak} of {an}.',
    'charter.coverage.cap': '{k} of {n} answers name 2 or more of {names}',
    'charter.coverage.line': '{n} of {m} answers on the club-only {line} also named a warehouse club.',
    'charter.coverage.line_all': 'All {m} answers on the club-only {line} also named a warehouse club.',
    'charter.presence.cap': 'category answers put {brand} first, {named} name it',
    'charter.presence.line': '{rival} came first in {n} of the same answers.',
    'charter.promo.cap': '{k} of {n} cheapest-place answers name a deal live on the shelf that day',
    'charter.promo.line': '{retailer} ran a {kind} on {skus}, and {named} of {asked} answers on them named it.',
    'charter.not_measured': 'Not measured',
    # the strip
    'strip.moved': '{n} of {of} numbers moved',
    'strip.first': 'First cycle. Nothing to move against yet',
    # revenue
    'revenue.headline.facts': ("Sales ride on answers built from {brand} facts that disagree. {things} {are} all "
                               "{name_s} to fix."),
    'revenue.headline.first_pick': ("Another brand gets the first pick in {n} of {of} brand-choice answers{rival}. "
                                    "One record per SKU puts {brand} where agents look."),
    'revenue.headline.first_pick.rival': ', {rival} most often',
    'revenue.thing.size_charts': 'the size charts',
    'revenue.thing.retired': 'the retired lines',
    'revenue.thing.gtins': 'the GTINs',
    'revenue.mode_note': ("Manufacturer mode: {brand} never sets a price. Revenue is modeled from these answers, not "
                          "scored."),
    # the week in short
    'week.attribute': '{k} of {n} weight ranges on retailer pages and in answers match {domain}.',
    'week.misses': 'The misses sit on {size}{where}.',
    'week.misses.two': ', where {domain} runs two charts',
    'week.misses.markup': ' and its own markup copies the wrong one on {n} {lines}',
    'week.coverage': 'Where to buy holds up: {line}.',
    'week.promo': 'On the retailer side, {k} of {n} cheapest-place answers named a deal that was live that day.',
    # agents and products
    'agent.deals': 'Named {k} of {n} live deals',
    'product.weight': 'Weight right in {k} of {n}.',
    'product.live_deal': '{retailer} ${price} with {deal}',
    'product.more': '+{n} more',
    # first picks
    'first_pick.singles': 'One first pick each for {names}.',
    'first_pick.none': '{n} {answers} named no single first pick.',
    'first_pick.lines': '{successor} was named in {k} of {of}, {retired} in {n}.',
    # activity
    'activity.started': 'Study started: {questions} prompts, {agents} agents',
    'activity.brand_page': '{domain} read: {pages} product {page_word}',
    'activity.shelf': 'Shelf reads at {n} retailers: {read} read{walled}',
    'activity.shelf.walled': ', {names} walled',
    'activity.complete': 'Study complete: {answers} answers from {agents} agents, {usable} usable',
    'activity.compiled': 'Compiled and held: {records} records, {surfaces}',
    # labels and the header
    'vs_label': 'vs {day}',
}

T = BRAND_OVERVIEW_TEMPLATES


def _times(n: int) -> str:
    return 'time' if n == 1 else 'times'


def _pct(k: int, n: int) -> Optional[int]:
    return round(k * 100 / n) if n else None


def _domain(d) -> str:
    return str(d or '').lower().removeprefix('www.')


def _name(domain: Optional[str]) -> str:
    return rm._retailer_name(_domain(domain))


# ─── signals ──────────────────────────────────────────────────────────────

def _line_label(product_name: Optional[str], brand: Optional[str]) -> str:
    return manu._line_display(product_name, brand)


def size_chart_signal(drift: List[dict], reference: Optional[dict], accuracy: Optional[dict], *,
                      domain: str, brand: Optional[str]) -> Optional[dict]:
    """From 2M-1's weight rows (rm.build_weight_drift): the brand's own two
    charts for one size (two lines' truths differ), else its markup against
    its chart, else retailer pages against it. None with no weight row."""
    if not drift:
        return None
    by_ref = {v.get('variant_ref'): v for v in (reference or {}).get('attributes') or []}
    phrase = attribute_accuracy.phrase
    # the brand's truths per size, by line: two lines, one size, two ranges is two charts
    truths: Dict[str, Dict[str, str]] = {}
    for v in by_ref.values():
        size = attribute_accuracy.size_label(v.get('variant_label'))
        truth = phrase(v.get('truth') or v.get('chart'))
        if size and truth:
            truths.setdefault(size, {}).setdefault(truth, _line_label(v.get('product_name') or v.get('variant_label'),
                                                                     brand))
    two = [(size, lines) for size, lines in truths.items() if len(lines) > 1]
    rows_by_variant: Dict[str, List[dict]] = {}
    for r in drift:
        rows_by_variant.setdefault(r.get('variant_ref'), []).append(r)

    def disagreement(ref):
        rows = rows_by_variant[ref]
        truth_ = phrase((by_ref.get(ref) or {}).get('truth') or (by_ref.get(ref) or {}).get('chart'))
        return (len({r['was'] for r in rows} | {truth_}), sum(1 for r in rows if r.get('kind') == 'page'))
    # the variant whose sources disagree most (the most ranges, then the most retailer pages against it);
    # a tie keeps the weight rows' order
    order = list(rows_by_variant)
    top_ref = max(order, key=lambda k: (*disagreement(k), -order.index(k)))
    top = by_ref.get(top_ref) or {}
    size = attribute_accuracy.size_label(top.get('variant_label'))
    line = _line_label(top.get('product_name') or top.get('variant_label'), brand)
    truth = phrase(top.get('truth') or top.get('chart'))
    sources = [{'who': domain, 'range': truth, 'prov': 'brand'}] if truth else []
    for r in rows_by_variant[top_ref]:
        if r.get('kind') == 'page' and r['was'] not in {s['range'] for s in sources}:
            sources.append({'who': _name(re.search(r'\(([^)]+)\)', r['field']).group(1)) if '(' in r['field'] else 'A retailer',
                            'range': r['was'], 'prov': 'retail'})
    markup = [r for r in drift if r.get('kind') == 'markup']
    markup_lines = list(dict.fromkeys(_line_label((by_ref.get(r.get('variant_ref')) or {}).get('product_name'), brand)
                                      for r in markup))
    misses = (accuracy or {}).get('misses') or []
    answers = (accuracy or {}).get('answers') or {}
    if two:
        sz, lines = max(two, key=lambda t: len(t[1]))
        title = T['signal.size_chart.two'].format(domain=domain, size=sz)
    elif markup:
        title = T['signal.size_chart.markup'].format(domain_s=possessive(domain), n=len(markup_lines),
                                                     lines='line' if len(markup_lines) == 1 else 'lines')
    else:
        title = T['signal.size_chart.pages'].format(domain=domain)
    parts = []
    for sz, lines in two[:1]:
        parts.append('. '.join(T['signal.size_chart.detail.chart'].format(line=l, size=sz, range=rng)
                               for rng, l in lines.items()))
    for r in [r for r in drift if r.get('kind') == 'page'][:3]:
        v = by_ref.get(r.get('variant_ref')) or {}
        retailer = re.search(r'\(([^)]+)\)', r['field'])
        parts.append(T['signal.size_chart.detail.page'].format(
            retailer=_name(retailer.group(1)) if retailer else 'A retailer',
            line=_line_label(v.get('product_name') or v.get('variant_label'), brand),
            size=attribute_accuracy.size_label(v.get('variant_label')) or '', range=r['was']))
    for r in markup[:2]:
        v = by_ref.get(r.get('variant_ref')) or {}
        parts.append(T['signal.size_chart.detail.markup'].format(
            line=_line_label(v.get('product_name') or v.get('variant_label'), brand),
            size=attribute_accuracy.size_label(v.get('variant_label')) or '', was=r['was'], now=r['now']))
    if answers.get('n'):
        sizes = list(dict.fromkeys(m['size'] for m in misses if m.get('kind') == 'answer' and m.get('size')))
        parts.append(T['signal.size_chart.detail.answers'].format(k=answers['k'], n=answers['n'],
                                                                   sizes=manu._and(sizes) or 'every size',
                                                                   domain=domain))
    return {'id': 'size_chart', 'kind': 'size_chart', 'pool': 'missed', 'rule': 'size_chart',
            'title': title, 'detail': '. '.join(p for p in parts if p) + '.', 'tag': 'Size chart', 'tone': 'bad',
            'route': 'record', 'count': len(misses) or len(drift),
            'facts': {'line': line, 'size': size, 'sources': sources, 'markup_lines': markup_lines,
                      'two': [{'size': sz, 'lines': [{'line': l, 'range': rng} for rng, l in lines.items()]}
                              for sz, lines in two],
                      'answers': answers, 'size_answers': [m for m in misses if m.get('size') == size]}}


def retired_signal(retired_named: Optional[dict]) -> Optional[dict]:
    """Visibility's first retired line (2L-2) agents still name."""
    line = ((retired_named or {}).get('lines') or [None])[0]
    if not line:
        return None
    every = (line.get('brand_choice') or {}).get('all') or {}
    n = every.get('named') or 0
    if not n:
        return None
    succ = (line.get('successor') or {}).get('label') or 'its successor'
    k = every.get('successor_named') or 0
    by = (retired_named or {}).get('retired_by') or 'The brand'
    agents = line.get('agents') or {}
    return {'id': 'retired', 'kind': 'retired', 'pool': 'lost', 'rule': 'retired',
            'title': T['signal.retired.title'].format(retired=line.get('label'), n=n, times=_times(n), successor=succ,
                                                      k=k, k_times=_times(k)),
            'detail': T['signal.retired.detail'].format(by=by[:1].upper() + by[1:], retired=line.get('label'),
                                                        successor=succ, of=every.get('answers') or 0, n=n, k=k,
                                                        agents=agents.get('named', 0), agents_of=agents.get('of', 0)),
            'tag': 'Retired product', 'tone': 'bad', 'route': 'answers', 'count': n,
            'facts': {'retired': line.get('label'), 'successor': succ, 'n': n, 'k': k, 'of': every.get('answers') or 0,
                      'by': by}}


def club_lines(feed_rows: Optional[List[dict]], own_domains: Iterable[str]) -> List[dict]:
    """The feed's club-only variants: every retailer the feed lists for it,
    the brand's own site aside, is a warehouse club."""
    own = {_domain(d) for d in own_domains or ()}
    out = []
    for row in feed_rows or []:
        listed = [_domain(r.get('domain')) for r in row.get('retailers') or [] if _domain(r.get('domain')) not in own]
        if listed and all(d in CLUB_DOMAINS for d in listed):
            out.append({'keys': {k for k in (row.get('sku'), row.get('variant_key'), rm._gtin14(row.get('gtin'))) if k},
                        'line': row.get('product_name'), 'label': row.get('variant_label'), 'clubs': listed})
    return out


def club_counts(lines: List[dict], store_answers: List[dict]) -> Optional[dict]:
    """Over the answers about club-only variants: where-to-buy answers naming
    a club, and answers sending the shopper to a store that is not one."""
    clubs = {_name(d) for d in CLUB_DOMAINS}
    keys = set().union(*(l['keys'] for l in lines)) if lines else set()
    mine = [a for a in store_answers if keys & set(a.get('keys') or ())]
    if not lines or not mine:
        return None
    where = [a for a in mine if a.get('intent') == 'where_to_buy']
    elsewhere = [a for a in mine if (a.get('stores') or [None])[0] not in clubs and a.get('stores')]
    stores = Counter(a['stores'][0] for a in elsewhere)
    return {'line': lines[0]['line'], 'clubs': [_name(d) for d in lines[0]['clubs']],
            'where': len(where), 'club_named': sum(1 for a in where if clubs & set(a.get('stores') or ())),
            'answers': len(mine), 'elsewhere': len(elsewhere), 'stores': [s for s, _ in stores.most_common()]}


def store_signal(counts: Optional[dict], brand: Optional[str]) -> Optional[dict]:
    if not counts or not counts['elsewhere']:
        return None
    line = _line_label(counts['line'], brand)
    stores = manu._and(counts['stores'][:2])
    return {'id': 'store', 'kind': 'store', 'pool': 'missed', 'rule': 'store',
            'title': T['signal.store.title'].format(line=line, stores=stores),
            'detail': T['signal.store.detail'].format(line=line, clubs=manu._and(counts['clubs']), n=counts['elsewhere'],
                                                      m=counts['answers'], stores=stores, k=counts['club_named'],
                                                      where=counts['where']),
            'tag': 'Wrong store', 'tone': 'warn', 'route': 'answers', 'count': counts['elsewhere'],
            'facts': {**counts, 'line_label': line}}


def _deal_id(entry: dict) -> str:
    return entry.get('id') or f"{entry.get('retailer_domain')}|{entry.get('kind')}|{(entry.get('text') or '').casefold()}"


def deal_signal(promo: Optional[dict], day: Optional[str]) -> Optional[dict]:
    """The biggest live deal (asked about most) and how many answers named it."""
    top = ppt.biggest((promo or {}).get('per_deal') or [])
    if not top or not top.get('asked') or top.get('named', 0) >= top['asked']:
        return None
    variant_ids = sorted({j['variant_id'] for j in (promo or {}).get('judged') or [] if _deal_id(top) in (j.get('live') or [])
                          and j.get('variant_id')})
    skus = len(variant_ids)
    sku_words = f"{skus} SKU{'s' if skus != 1 else ''}"
    named = top.get('named') or 0
    return {'id': f"deal:{_deal_id(top)}", 'kind': 'deal', 'pool': 'missed', 'rule': 'deal',
            'title': T['signal.deal.title'].format(deal=top['title'], skus=sku_words,
                                                   named_words=f"{named} of {top['asked']} answers" if named
                                                   else T['signal.deal.none']),
            'detail': T['signal.deal.detail'].format(text=top.get('text') or top['short'], skus=sku_words,
                                                     day=day or 'the read day', named=named, asked=top['asked']),
            'tag': 'Deal missed', 'tone': 'bad', 'route': 'prove', 'count': top['asked'] - named,
            'facts': {'deal': top['title'], 'short': top['short'], 'retailer': top.get('retailer'),
                      'kind_label': top.get('kind_label'), 'skus': skus, 'variant_ids': variant_ids, 'named': named,
                      'asked': top['asked']}}


def with_pool(signal: dict) -> dict:
    """An existing signal with its kind and pool (SIGNAL_KIND)."""
    kind, pool = SIGNAL_KIND.get(signal.get('rule'), ('other', 'root'))
    return {**signal, 'kind': signal.get('kind') or kind, 'pool': signal.get('pool') or pool}


def pool_values(model: Optional[dict]) -> Dict[str, float]:
    """Each pool's modeled value: the dollars when the model has them, else
    its measured share (the dollars are the share times one scale, so the
    order is the same). An access signal's pool has none."""
    today = (model or {}).get('today')
    if today:
        return {'lost': today['lost'], 'missed': today['missed'], 'root': 0.0}
    shares = (model or {}).get('shares') or {}
    return {'lost': shares.get('lost') or 0.0, 'missed': shares.get('missed') or 0.0, 'root': 0.0}


def rank_signals(existing: List[dict], new: List[Optional[dict]], values: Dict[str, float]) -> List[dict]:
    """The existing signals (every one kept) and the new ones, ranked by
    their pool's value, then their count; a tie keeps the order they were
    made in, the existing first. Each carries `rank`, `pool_value`, `tag`."""
    made = [with_pool(s) for s in existing] + [s for s in new if s]
    ranked = sorted(enumerate(made), key=lambda e: (-values.get(e[1]['pool'], 0.0), -(e[1].get('count') or 0), e[0]))
    out = []
    for i, (_, s) in enumerate(ranked):
        out.append({**s, 'rank': i + 1, 'pool_value': values.get(s['pool'], 0.0),
                    'tag': s.get('tag') or POOL_TAG.get(s['pool'])})
    return out


# ─── the lead ─────────────────────────────────────────────────────────────

def _tile(who, value, of, cap, **beside):
    return {'who': who, 'value': value, 'of': of, 'cap': cap, **beside}


def lead_facts(signal: dict, *, domain: str, totals: dict, promo: Optional[dict]) -> List[dict]:
    """The lead's two tiles, from the top signal's own numbers."""
    f, kind = signal.get('facts') or {}, signal['kind']
    if kind == 'size_chart':
        sources = f['sources']
        cap = ', '.join([T['fact.size_chart.source'].format(**sources[0])] +
                        [T['fact.size_chart.source_short'].format(**s) for s in sources[1:]]) if sources else ''
        first = _tile(T['fact.size_chart.who'].format(line=f['line'], size=f['size'] or ''), len(sources),
                      T['fact.size_chart.of'], cap, sources=sources)
        if f['markup_lines']:
            second = _tile(T['fact.markup.who'].format(domain=domain), len(f['markup_lines']), T['fact.markup.of'],
                           T['fact.markup.cap'].format(domain_s=possessive(domain), lines=manu._and(f['markup_lines'])),
                           lines=f['markup_lines'])
        else:
            here = [m for m in f['size_answers'] if m.get('kind') == 'answer']
            answers = f['answers']
            second = _tile(T['fact.answers.who'].format(size=f['size']), answers.get('k', 0), f"of {answers.get('n', 0)}",
                           T['fact.answers.cap'].format(domain=domain), misses=len(here))
        return [first, second]
    if kind == 'retired':
        return [_tile(T['fact.retired.who'].format(retired=f['retired']), f['n'], f"of {f['of']}",
                      T['fact.retired.cap'].format(retired=f['retired'], by=f['by'])),
                _tile(T['fact.successor.who'].format(successor=f['successor']), f['k'], f"of {f['of']}",
                      T['fact.successor.cap'].format(successor=f['successor']))]
    if kind == 'deal':
        return [_tile(f['deal'], f['named'], f"of {f['asked']}", T['fact.deal.cap'], skus=f['skus']),
                _tile(T['fact.promo.who'], (promo or {}).get('k', 0), f"of {(promo or {}).get('n', 0)}",
                      T['fact.promo.cap'])]
    if kind == 'store':
        return [_tile(T['fact.store.who'].format(line=f['line_label']), f['club_named'], f"of {f['where']}",
                      T['fact.store.cap']),
                _tile(T['fact.store_sent.who'], f['elsewhere'], f"of {f['answers']}",
                      T['fact.store_sent.cap'].format(stores=manu._and(f['stores'][:2])))]
    prices = _tile(T['fact.prices.who'], totals.get('exact', 0), f"of {totals.get('scored', 0)}", T['fact.prices.cap'])
    # an existing signal: its count over the denominator its own detail line states (console_parity.build_signals)
    rule = signal.get('rule')
    of = {'other_brand': totals.get('scored', 0) + totals.get('left_out', 0) + totals.get('unverifiable', 0),
          'fabricated': totals.get('brand_scored'),
          'unverifiable': totals.get('scored', 0) + totals.get('unverifiable', 0)}.get(rule)
    return [_tile(T.get(f'fact.{rule}.who', signal['title']), signal.get('count', 0), f"of {of}" if of else None,
                  T['fact.signal.cap'].format(title=signal['title'])),
            prices]


def build_lead(signals: List[dict], *, brand: str, name: str, domain: str, totals: dict, promo: Optional[dict],
               workspace: Optional[dict]) -> Optional[dict]:
    """The demo's hero: the headline chosen by the top ranked signal's kind,
    its two tiles, the compile-and-hold sentence with the surfaces held, no
    owner (none is recorded), the routes."""
    if not signals:
        return None
    top = signals[0]
    f = top.get('facts') or {}
    said = {'brand': brand, 'domain': domain, 'retired': f.get('retired'), 'by': f.get('by'),
            'successor': f.get('successor'), 'deal': f.get('deal'), 'named': f.get('named'), 'asked': f.get('asked'),
            'skus': f"{f.get('skus')} SKU{'s' if f.get('skus') != 1 else ''}", 'line': f.get('line_label')}
    headline = T[f"lead.headline.{top['kind']}"].format(**said) if f"lead.headline.{top['kind']}" in T else top['title']
    held = [s['name'] for s in (workspace or {}).get('surfaces') or [] if s['compiled']]
    do = T['lead.do'].format(brand=brand, name_s=possessive(name), surfaces=manu._and(held)) if held \
        else T['lead.do.none'].format(brand=brand)
    return {'headline': headline, 'kind': top['kind'], 'signal': top['id'], 'pool': top['pool'],
            'facts': lead_facts(top, domain=domain, totals=totals, promo=promo), 'do': do, 'owner': None,
            'ctas': [{'label': T['lead.cta.push'], 'route': 'truesync'},
                     {'label': T['lead.cta.answers'], 'route': top.get('route') or 'answers'}]}


def build_truesync_card(workspace: Optional[dict]) -> Optional[dict]:
    """The Overview's TrueSync card: TrueSync's own workspace, no second count."""
    if not workspace:
        return None
    return {'products': workspace['records'], 'cells': dict(workspace['compiled']), 'drifting': workspace['disagree'],
            'published': workspace['published'], 'blocked': workspace['blocked'],
            'surfaces': [dict(s) for s in workspace['surfaces']], 'mode_note': workspace['mode_note']}


# ─── the charter ──────────────────────────────────────────────────────────

def build_charter(score: Optional[dict], *, domain: str, club: Optional[dict], promo: Optional[dict]) -> List[dict]:
    """The demo's four charter tiles, each the score's brand tile (same
    value and denominator, asserted in a test), with its second line from the
    tile's own counts: pages and answers (attribute), the club-only line
    (coverage), the rival first (presence), the biggest deal (promo)."""
    if not score:
        return []
    tiles = {m['key']: m for m in (score.get('metrics_by_kind') or {}).get('brand') or []}
    counts = ((score.get('metric_counts') or {}).get(score.get('metric_surface')) or {})
    out = []
    for key, label in CHARTER:
        m = tiles.get(key)
        if m is None:
            continue
        c = counts.get(key) or {}
        tile = {'key': key, 'label': label, 'state': m['state'], 'value': m.get('value'), 'of': m.get('denominator'),
                'delta': m.get('delta'), 'reason': m.get('reason'), 'cap': None, 'second_line': None}
        if m['state'] != 'measured':
            out.append(tile)
            continue
        k, n = m['value'], m['denominator']
        if key == 'attribute':
            tile.update(pct=_pct(k, n), big=f"{_pct(k, n)}%",
                        cap=T['charter.attribute.cap'].format(k=k, n=n, domain_s=possessive(domain)),
                        second_line=T['charter.attribute.line'].format(pk=c['pages']['k'], pn=c['pages']['n'],
                                                                       ak=c['answers']['k'], an=c['answers']['n']))
        elif key == 'coverage':
            tile.update(pct=_pct(k, n), big=f"{_pct(k, n)}%",
                        cap=T['charter.coverage.cap'].format(k=k, n=n, names=manu._and(c.get('names') or [])))
            if club and club['where']:
                key_ = 'charter.coverage.line_all' if club['club_named'] == club['where'] else 'charter.coverage.line'
                tile['second_line'] = T[key_].format(n=club['club_named'], m=club['where'], line=club['line'])
        elif key == 'presence':
            # the demo's big number is the first picks; value and of stay the tile's (named of answers)
            first = c.get('first', 0)
            tile.update(first=first, big=str(first), small=f"of {n}", pct=_pct(first, n),
                        cap=T['charter.presence.cap'].format(brand=c.get('brand') or 'the brand', named=k))
            if c.get('rival'):
                tile['second_line'] = T['charter.presence.line'].format(rival=c['rival']['name'], n=c['rival']['first'])
        elif key == 'promo':
            tile.update(pct=_pct(k, n), big=f"{_pct(k, n)}%", cap=T['charter.promo.cap'].format(k=k, n=n))
            deal = c.get('deal')
            top = ppt.biggest((promo or {}).get('per_deal') or [])
            if deal and deal.get('asked') and top:
                skus = len({j['variant_id'] for j in (promo or {}).get('judged') or [] if _deal_id(top) in (j.get('live') or [])})
                tile['second_line'] = T['charter.promo.line'].format(
                    retailer=top.get('retailer'), kind=deal.get('kind_label') or 'deal',
                    skus=f"{skus} SKU{'s' if skus != 1 else ''}", named=deal['named'], asked=deal['asked'])
        out.append(tile)
    return out


# ─── the strip, B4's pillar deltas ────────────────────────────────────────

def build_strip(score: Optional[dict]) -> Optional[dict]:
    """The score and its delta, "N of 5 numbers moved" (the brand tiles whose
    value changed against the prior cycle), the pillars each with its delta
    as its own field, approvals and actions None (none are recorded)."""
    if not score:
        return None
    prev = score.get('previous') or {}
    tiles = (score.get('metrics_by_kind') or {}).get('brand') or []
    measured = [m for m in tiles if m.get('state') == 'measured']
    compared = [m for m in measured if m.get('delta') is not None]
    moved = [m['key'] for m in compared if m['delta'] != 0]
    deltas = {d['code']: d for d in prev.get('pillar_deltas') or []}
    pillars = []
    for p in score.get('pillars') or []:
        d = deltas.get(p['code']) or {}
        pillars.append({'code': p['code'], 'name': p.get('name'), 'score': p.get('score'), 'max': p.get('max'),
                        'applicable_max': p.get('applicable_max'),
                        'delta': d.get('delta') if prev.get('comparable') else None})
    return {'score': score.get('score'), 'delta': prev.get('delta') if prev.get('comparable') else None,
            'vs_cycle': prev.get('cycle'), 'moved': {'n': len(moved), 'of': len(tiles), 'keys': moved},
            'moved_line': T['strip.moved'].format(n=len(moved), of=len(tiles)) if compared else T['strip.first'],
            'pillars': pillars, 'approvals': None, 'actions': None}


# ─── revenue ──────────────────────────────────────────────────────────────

def revenue_headline(top: Optional[dict], *, model: dict, brand: str, name: str, things: List[str]) -> str:
    """Facts that disagree when the top signal is a fact (a size chart, a
    retired line, a claim), else the first-pick sentence."""
    if top and top['kind'] in ('size_chart', 'retired', 'claim') and things:
        return T['revenue.headline.facts'].format(brand=brand, things=manu._and(things)[:1].upper() + manu._and(things)[1:],
                                                  are='are' if len(things) > 1 else 'is', name_s=possessive(name))
    lost = (model.get('counts') or {}).get('lost') or {}
    rivals = (model.get('counts') or {}).get('lost_rivals') or []
    return T['revenue.headline.first_pick'].format(
        n=lost.get('n', 0), of=lost.get('of', 0), brand=brand,
        rival=T['revenue.headline.first_pick.rival'].format(rival=rivals[0][0]) if rivals else '')


def build_revenue(model: dict, *, headline: str, brand: str) -> dict:
    """The Overview's revenue block: the model's own fields (its shares, its
    drivers, the basis the console shows as how it is calculated), the
    headline, the manufacturer-mode note. Modeled, never scored."""
    keep = ('measured', 'reason', 'dollars', 'dollars_reason', 'currency', 'scope', 'influence', 'horizon', 'penalty',
            'lost_gainable', 'drivers', 'byAgent', 'shares', 'counts', 'heroBasis', 'today', 'by_2030', 'cycle')
    return {**{k: model.get(k) for k in keep}, 'headline': headline, 'how_calculated': model.get('basis'),
            'mode_note': T['revenue.mode_note'].format(brand=brand)}


# ─── the week in short ────────────────────────────────────────────────────

def week_in_short(*, accuracy: Optional[dict], size_signal: Optional[dict], retired_named: Optional[dict],
                  routing: Optional[dict], promo: Optional[dict], domain: str) -> List[dict]:
    """Five facts in the demo's order: attribute, where the misses sit,
    the retired line, coverage, promo. Each from the block a tile reads; a
    fact with nothing to count is left out."""
    out = []
    if accuracy:
        out.append({'key': 'attribute', 'route': 'record',
                    'text': T['week.attribute'].format(k=accuracy['k'], n=accuracy['n'], domain=domain)})
        sizes = Counter(m['size'] for m in accuracy.get('misses') or [] if m.get('size'))
        if sizes:
            size = sizes.most_common(1)[0][0]
            f = (size_signal or {}).get('facts') or {}
            where = ''
            if any(t['size'] == size for t in f.get('two') or []):
                where += T['week.misses.two'].format(domain=domain)
            if f.get('markup_lines'):
                n = len(f['markup_lines'])
                where += T['week.misses.markup'].format(n=n, lines='line' if n == 1 else 'lines')
            out.append({'key': 'misses', 'route': 'record', 'text': T['week.misses'].format(size=size, where=where)})
    line = ((retired_named or {}).get('lines') or [None])[0]
    if line and line.get('sentence'):
        out.append({'key': 'retired', 'route': 'answers', 'text': line['sentence']})
    if (routing or {}).get('coverage_line'):
        out.append({'key': 'coverage', 'route': 'visibility', 'text': T['week.coverage'].format(line=routing['coverage_line'])})
    if promo and promo.get('n'):
        out.append({'key': 'promo', 'route': 'prove', 'text': T['week.promo'].format(k=promo['k'], n=promo['n'])})
    return out


# ─── agents ───────────────────────────────────────────────────────────────

def extend_agents(agents: List[dict], *, attribute_answers: List[dict], promo: Optional[dict],
                  agent_of_run: Dict[int, str], surface: str) -> List[dict]:
    """Each agent row with `facts_right` {right, of}: its weight facts (the
    attribute answers it got right) plus its price facts (exact of scored),
    and `deals_line`: of its cheapest-place answers about a SKU with a live
    deal, how many named one."""
    out = []
    for a in agents:
        mine = [x for x in attribute_answers or [] if x.get('verdict') is not None
                and (surfaces.agent_of(x.get('platform')) or x.get('platform')) == a['agent']
                and surfaces.on_surface(x.get('surface'), surface)]
        weight_k = sum(1 for x in mine if x['verdict'] == 'match')
        judged = [j for j in (promo or {}).get('judged') or [] if agent_of_run.get(j.get('run_id')) == a['agent']
                  and j.get('live') and surfaces.on_surface(j.get('surface'), surface)]
        named = sum(1 for j in judged if j.get('named'))
        out.append({**a, 'facts_right': {'right': weight_k + (a.get('exact') or 0), 'of': len(mine) + (a.get('scored') or 0),
                                         'weight': {'right': weight_k, 'of': len(mine)},
                                         'price': {'right': a.get('exact') or 0, 'of': a.get('scored') or 0}},
                    'deals_line': T['agent.deals'].format(k=named, n=len(judged)) if judged else None,
                    'deals': {'named': named, 'of': len(judged)}})
    return out


# ─── products ─────────────────────────────────────────────────────────────

_MONEY = re.compile(r'\$\d[\d,]*(?:\.\d{2})?')


def collapse_quoted(quoted: Optional[str], shown: int = 3) -> tuple:
    """(the top three amounts quoted, "+N more" after them; the full text):
    the quoted line's sentences are its amounts, most runs first."""
    parts = [p.strip() for p in (quoted or '').split('. ') if p.strip()]
    priced = [p for p in parts if _MONEY.search(p)]
    rest = [p for p in parts if not _MONEY.search(p)]
    if len(priced) <= shown:
        return quoted, quoted
    top = '. '.join(priced[:shown])
    more = len(priced) - shown
    return f"{top}. {T['product.more'].format(n=more)}" + (f". {'. '.join(rest)}" if rest else ''), quoted


def live_deals(product: dict, deals: Optional[dict]) -> List[str]:
    """The deals live on the product's SKU that day, each as the demo's
    reference cell writes it: "Amazon $27.97 with buy 2, save 40% on 1"."""
    ref = {'variant_id': product.get('sku'), 'sku': product.get('sku')}
    out = []
    for d in ppt.live_for(deals, ref):
        entry = d.get('variant') or {}
        price = entry.get('shelf_price') or entry.get('price')
        text = (d.get('text') or ppt.short(d)).strip()
        line = T['product.live_deal'].format(retailer=_name(d.get('retailer_domain')), price=price,
                                             deal=text[:1].lower() + text[1:]) if price else ppt.title(d)
        if line not in out:
            out.append(line)
    return out


def check_of(runs: List[dict]) -> str:
    """right | partly_right | wrong | none over the product's priced runs:
    partly right when some runs are right and some wrong and none quoted
    another brand's price."""
    outcomes = [r.get('outcome') for r in runs if r.get('outcome') not in (None, 'absent', 'unverifiable')]
    other = any(r.get('reason') == 'other_brand' for r in runs)
    right = sum(1 for o in outcomes if o == 'exact')
    wrong = sum(1 for o in outcomes if o in ('wrong', 'stale', 'partial'))
    if not outcomes:
        return 'none'
    if right and not wrong and not other:
        return 'right'
    if right and wrong and not other:
        return 'partly_right'
    return 'wrong'


def extend_products(products: List[dict], *, attribute_answers: List[dict], deals: Optional[dict],
                    true_value: dict, surface: str, signals: List[dict]) -> List[dict]:
    """Each product with `live` (the reference cell plus the deals live on the
    SKU), `check` (check_of), the weight fact on its issue line when the SKU
    has a weight check, `quoted` collapsed to the top three amounts
    (`quoted_all` the full list), and the ranked signal it belongs to."""
    rows = {r['sku']: r for r in true_value.get('rows') or []}
    out = []
    for p in products:
        row = rows.get(p['sku']) or {}
        other = p.get('issue_rule') == 'product.other_brand'
        runs = [{**q, 'reason': 'other_brand' if other else None}
                for cell in (row.get('retailer_cells') or row.get('cells') or {}).values()
                for q in cell.get('quotes') or [] if surfaces.on_surface(q.get('surface'), surface)]
        weight = [a for a in attribute_answers or [] if a.get('variant_id') == p['sku'] and a.get('verdict') is not None
                  and surfaces.on_surface(a.get('surface'), surface)]
        deals_live = live_deals(p, deals)
        quoted, quoted_all = collapse_quoted(p.get('quoted'))
        issue = p.get('issue') or ''
        if weight:
            fact = T['product.weight'].format(k=sum(1 for a in weight if a['verdict'] == 'match'), n=len(weight))
            issue = f"{fact} {issue}".strip()
        signal = next((s['id'] for s in signals if s['id'] == f"wrong:{p['sku']}"
                       or p['sku'] in ((s.get('facts') or {}).get('variant_ids') or ())), None)
        out.append({**p, 'live': '. '.join([p.get('live') or ''] + deals_live).strip('. ') if deals_live else p.get('live'),
                    'live_deals': deals_live, 'check': check_of(runs), 'issue': issue,
                    'weight_check': {'right': sum(1 for a in weight if a['verdict'] == 'match'), 'of': len(weight)}
                    if weight else None,
                    'quoted': quoted, 'quoted_all': quoted_all, 'signal': signal})
    return out


# ─── first picks ──────────────────────────────────────────────────────────

def first_pick_footnote(vis: dict, *, retired_named: Optional[dict]) -> Optional[dict]:
    """The ranking's footnote: the brands with one first pick each, the
    answers with no single first pick, the retired line and its successor."""
    ranking = vis.get('ranking') or {}
    rows = [v for v in vis.get('byQuestion') or [] if v.get('answered') and (v.get('brand_choice') if 'brand_choice' in v
                                                                               else v.get('unprompted'))]
    if not rows:
        return None
    firsts = Counter((v.get('first') or {}).get('name') for v in rows if v.get('first'))
    singles = sorted(n for n, c in firsts.items() if c == 1 and n)
    none = sum(1 for v in rows if not v.get('first'))
    parts = []
    if singles:
        parts.append(T['first_pick.singles'].format(names=manu._and(singles)))
    if none:
        parts.append(T['first_pick.none'].format(n=none, answers='answer' if none == 1 else 'answers'))
    line = ((retired_named or {}).get('lines') or [None])[0]
    if line:
        every = (line.get('brand_choice') or {}).get('all') or {}
        parts.append(T['first_pick.lines'].format(successor=(line.get('successor') or {}).get('label') or 'its successor',
                                                  k=every.get('successor_named') or 0, of=every.get('answers') or 0,
                                                  retired=line.get('label'), n=every.get('named') or 0))
    return {'footnote': ' '.join(parts), 'singles': singles, 'no_single_pick': none, 'of': len(rows),
            'denom': ranking.get('denom')}


# ─── activity ─────────────────────────────────────────────────────────────

def build_activity(*, cycle: dict, first_at, last_at, answers: int, usable: int, agents: int, questions: int,
                   prices: Optional[List[dict]], own_domains: Iterable[str], pubs: List[dict],
                   workspace: Optional[dict]) -> List[dict]:
    """The loop's stages for the cycle, newest first, each {at, day, text,
    icon, stage}: the study started (its first run), the brand page read, the
    shelf reads (walled named), the study complete (its last run, the usable
    answers), the compile and hold. Approvals come later (none are recorded)."""
    own = {_domain(d) for d in own_domains or ()}
    out = []
    if first_at:
        out.append({'at': str(first_at), 'icon': 'week', 'stage': 'started',
                    'text': T['activity.started'].format(questions=questions, agents=agents)})
    pages = [r for r in prices or [] if (r.get('role') == 'own' or _domain(r.get('retailer_domain')) in own)
             and r.get('observed_at') and manu.row_brand_page(r)]
    if pages:
        n = len({r.get('url') for r in pages})
        out.append({'at': max(str(r['observed_at']) for r in pages), 'icon': 'record', 'stage': 'brand_page',
                    'text': T['activity.brand_page'].format(domain=next(iter(sorted(own)), 'the brand site'), pages=n,
                                                           page_word='page' if n == 1 else 'pages')})
    shelf = [r for r in prices or [] if r.get('role') != 'own' and _domain(r.get('retailer_domain')) not in own
             and r.get('observed_at')]
    if shelf:
        domains = {_domain(r.get('retailer_domain')) for r in shelf}
        walled = sorted({_name(r.get('retailer_domain')) for r in shelf if r.get('price') is None
                         and r.get('method') in ('none', 'wall')})
        out.append({'at': max(str(r['observed_at']) for r in shelf), 'icon': 'record', 'stage': 'shelf',
                    'text': T['activity.shelf'].format(n=len(domains), read=len(domains) - len(walled),
                                                       walled=T['activity.shelf.walled'].format(names=manu._and(walled))
                                                       if walled else '')})
    if last_at and cycle.get('status') == 'complete':
        out.append({'at': str(last_at), 'icon': 'answers', 'stage': 'complete',
                    'text': T['activity.complete'].format(answers=answers, agents=agents, usable=usable)})
    compiled = [e for p in pubs or [] for e in p.get('journal') or [] if e.get('event') == 'compiled']
    if compiled and workspace:
        held = [s['name'] for s in workspace['surfaces'] if s['compiled']]
        out.append({'at': max(str(e.get('at') or '') for e in compiled), 'icon': 'truesync', 'stage': 'compiled',
                    'text': T['activity.compiled'].format(records=workspace['records'],
                                                          surfaces=f"held on {manu._and(held)}" if held else 'none held')})
    out.sort(key=lambda e: rm._ts(e['at']), reverse=True)
    for e in out:
        e['day'] = manu.short_day(e['at'])
    return out


def vs_label(prev_day: Optional[str]) -> Optional[str]:
    return T['vs_label'].format(day=manu.short_day(prev_day)) if prev_day else None


def size_things(drift: List[dict], retired_named: Optional[dict], gtin_flags: List[dict]) -> List[str]:
    """What the brand's facts disagree on, for the revenue headline."""
    out = []
    if drift:
        out.append(T['revenue.thing.size_charts'])
    if ((retired_named or {}).get('lines') or []):
        out.append(T['revenue.thing.retired'])
    if gtin_flags:
        out.append(T['revenue.thing.gtins'])
    return out
