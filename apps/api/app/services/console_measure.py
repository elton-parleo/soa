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
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional

from app.services import console_read_models as rm
from soa_shared import promo_pass_through as ppt
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


# ─── True Value ──────────────────────────────────────────────────────────

#: TV9: the cell captions in brand mode (a brand sets no price, so every price is a retailer's)
TV_CAPTIONS = {
    'exact': 'The price the retailer\'s page showed',
    'wrong': "A price the retailer's page did not show",
    'partial': 'Near the page, not on it',
    'missed': 'The retailer listed it and no answer quoted it',
    'unverifiable': 'The page could not be read',
    'none': 'Not read, not sold there, or not priced',
}
#: a status that counts as a price read (TV1): one an answer could be judged against
READ_STATUSES = ('exact', 'wrong', 'partial', 'missed')
_COUNT = re.compile(r'(\d+)\s*(?:ct|count)\b', re.I)


def _domain(value) -> str:
    return str(value or '').lower().removeprefix('www.')


def _money(value) -> Optional[str]:
    if value in (None, ''):
        return None
    try:
        return f"${Decimal(str(value)):.2f}"
    except (InvalidOperation, ValueError):
        return None


def row_keys(row: dict) -> set:
    """Every key a True Value row's variant goes by (its variant_id, sku, feed code, GTIN)."""
    keys = {row.get('variant_id'), row.get('sku'), row.get('gtin'), row.get('feed_sku')}
    if row.get('feed_sku'):
        keys |= {f"sku:{row['feed_sku']}", f"feed_sku:{row['feed_sku']}"}
    return {str(k) for k in keys if k}


def _ref_of(row: dict) -> dict:
    return {'variant_id': row.get('variant_id'), 'gtin': row.get('gtin'), 'sku': row.get('feed_sku') or row.get('sku')}


def _reads_for(reads: Optional[List[dict]], row: dict, domain: Optional[str] = None) -> List[dict]:
    keys = row_keys(row)
    out = []
    for r in reads or []:
        mine = {str(k) for k in (r.get('variant_ref'), r.get('sku'), f"sku:{r['sku']}" if r.get('sku') else None,
                                 r.get('gtin')) if k}
        if mine & keys and (domain is None or _domain(r.get('retailer_domain')) == domain):
            out.append(r)
    return sorted(out, key=lambda r: str(r.get('observed_at') or ''), reverse=True)


def order_columns(columns: List[dict], own_domains: Iterable[str]) -> List[dict]:
    """TV3: the brand's own domain first, then the retailers alphabetical by name."""
    own = {_domain(d) for d in own_domains or () if d}
    return sorted(columns, key=lambda c: (not (c.get('you') or _domain(c.get('id')) in own), str(c.get('name')).lower()))


def cell_deals(row: dict, domain: str, deals: Optional[dict]) -> List[str]:
    """TV4: the deals live on the row's SKU at that retailer that day, each as its one label (ppt.label)."""
    out = []
    for d in ppt.live_for(deals, _ref_of(row)):
        if _domain(d.get('retailer_domain')) == domain:
            line = ppt.label(d, d.get('variant'))
            if line not in out:
                out.append(line)
    return out


def brand_note(row: dict, reads: Optional[List[dict]], own_domains: Iterable[str], brand: Optional[str]) -> Optional[str]:
    """TV4: the brand column's note from the brand page's read: "Retired. Redirects to AMORE", "No 84 ct listed.
    Markup prices the 140 ct at $44.94", "No price in markup. GTIN has 11 digits". None with no read of it."""
    retired = row.get('retired')
    own = [_domain(d) for d in own_domains or () if d]
    page = next((r for d in own for r in _reads_for(reads, row, d)), None)
    if retired:
        succ = ((retired.get('successor') or {}).get('label')) or None
        moved = page is not None and page.get('final_url') and page.get('url') and \
            rel_key(page['final_url']) != rel_key(page['url'])
        if succ:
            return f"Retired. Redirects to {succ}" if moved else f"Retired. {succ} is its successor"
        return 'Retired'
    if page is None:
        return None
    from app.services import console_manufacturer as manu
    from soa_shared import attribute_accuracy
    bp = manu.row_brand_page(page) or {}
    nodes = manu._products(bp.get('json_ld'))
    if not nodes:
        return 'No markup read' if page.get('read_status') in ('ok', 'empty') else None
    label = row.get('product') or ''
    size, count = attribute_accuracy.size_of(label), (_COUNT.search(label) or [None, None])[1]

    def words(node):
        return ' '.join(str(node.get(k) or '') for k in ('name', 'size', 'sku'))

    def node_size(node):   # the markup's size is "1" as often as "Size 1" (manu.markup_gtins)
        raw = str(node.get('size') or '')
        return attribute_accuracy.size_of(f"Size {raw}" if raw.isdigit() else raw or words(node))

    same_size = [n for n in nodes if not size or node_size(n) == size]
    match = next((n for n in same_size if count and (_COUNT.search(words(n)) or [None, None])[1] == count), None)
    parts = []
    if match is None and count and same_size:
        parts.append(f"No {count} ct listed")
        priced = next(((n, o) for n in same_size for o in _offers(n) if _money(o.get('price'))), None)
        if priced:
            other = (_COUNT.search(words(priced[0])) or [None, None])[1]
            parts.append(f"Markup prices {'the ' + other + ' ct' if other else size or 'it'} at "
                         f"{_money(priced[1].get('price'))}")
    else:
        node = match or (same_size[0] if same_size else None)
        if node is not None and not any(_money(o.get('price')) for o in _offers(node)):
            parts.append('No price in markup')
        if node is not None:
            gtin = next((node.get(k) for k in ('gtin13', 'gtin12', 'gtin14', 'gtin') if node.get(k)), None)
            if gtin and manu.gtin_correction(gtin):
                parts.append(f"GTIN has {len(''.join(ch for ch in str(gtin) if ch.isdigit()))} digits")
    return '. '.join(parts) if parts else None


def _offers(node: dict) -> List[dict]:
    offers = node.get('offers')
    if isinstance(offers, dict):
        offers = offers.get('offers') if isinstance(offers.get('offers'), list) else [offers]
    return [o for o in offers or [] if isinstance(o, dict)]


def rel_key(url) -> str:
    from app.services import console_release as rel
    return rel._url_key(url)


def clash_text(cell: dict) -> Optional[str]:
    """TV8: a cell whose wrong quotes mostly named a variant the record does not have shows it, as the
    Overview's signal does (console_parity.variant_clash): "$44.99 for Size 3, 116 ct"."""
    from app.services import console_parity as parity
    wrong = [q for q in cell.get('quotes') or [] if q.get('outcome') in ('wrong', 'stale') and q.get('stated')]
    clashed = [q for q in wrong if q.get('clash')]
    if not clashed or len(clashed) * 2 <= len(wrong):
        return None
    (stated, named), _n = Counter((q['stated'], q['clash']) for q in clashed).most_common(1)[0]
    return f"{_money(stated) or stated} for {parity.variant_words(named) or named}"


def _judged_for(row: dict, promo: Optional[dict]) -> List[dict]:
    keys = row_keys(row)
    return [j for j in (promo or {}).get('judged') or [] if str(j.get('variant_id') or '') in keys]


def product_line(row: dict, *, deals: Optional[dict], promo: Optional[dict], attribute_answers: List[dict]) -> Optional[str]:
    """TV5: the row's deal clause and weight clause, from the Overview's helpers: "Amazon: save 40% on 1 when you
    buy 2 and Kroger: spend $60, save $15 were live. 0 of 5 cheapest-place answers named either. Weight right in 5
    of 5." None when it has neither."""
    parts = []
    live = []
    for d in ppt.live_for(deals, _ref_of(row)):
        line = ppt.label(d, d.get('variant'))
        if line not in live:
            live.append(line)
    if live:
        judged = _judged_for(row, promo)
        which = 'it' if len(live) == 1 else 'either' if len(live) == 2 else 'any'
        parts.append(T['tv.line.deals'].format(deals=_join(live), verb='was' if len(live) == 1 else 'were',
                                               named=sum(1 for j in judged if j.get('named')), asked=len(judged),
                                               which=which) if judged else
                     f"{_join(live)} {'was' if len(live) == 1 else 'were'} live.")
    keys = row_keys(row)
    weight = [a for a in attribute_answers or [] if str(a.get('variant_id') or '') in keys
              and a.get('verdict') is not None]
    if weight:
        parts.append(T['tv.line.weight'].format(k=sum(1 for a in weight if a['verdict'] == 'match'), n=len(weight)))
    return ' '.join(parts) or None


def anatomy(rows: List[dict], *, reads: Optional[List[dict]], deals: Optional[dict], promo: Optional[dict],
            brand: Optional[str], day: Optional[str]) -> Optional[dict]:
    """TV6: the most-asked SKU on its most-asked retailer, line by line, from the reference row and the
    quotes: list price, the price cut (sale against list), the one-time price, each deal live there with how
    many answers named it, what agents quoted and who. No modeled dollars."""
    best = None
    for row in rows:
        for domain, cell in (row.get('retailer_cells') or row.get('cells') or {}).items():
            if cell.get('runs') and (best is None or cell['runs'] > best[2]['runs']):
                best = (row, domain, cell)
    if best is None:
        return None
    row, domain, cell = best
    read = next(iter(_reads_for(reads, row, _domain(domain))), None) or {}
    price, listed = read.get('price'), read.get('list_price')
    lines = []
    if _money(listed):
        lines.append({'k': 'List price', 'v': _money(listed), 'tag': domain})
    if _money(listed) and _money(price) and Decimal(str(listed)) > Decimal(str(price)):
        cut = Decimal(str(listed)) - Decimal(str(price))
        lines.append({'k': f"{rm._retailer_name(domain)} price cut", 'v': f"-${cut:.2f}", 'kind': 'minus',
                      'tag': f"-{round(cut / Decimal(str(listed)) * 100)}% vs list"})
    if _money(price):
        lines.append({'k': 'One-time price', 'v': _money(price), 'kind': 'big'})
    judged = _judged_for(row, promo)
    for d in ppt.live_for(deals, _ref_of(row)):
        if _domain(d.get('retailer_domain')) != _domain(domain):
            continue
        asked = [j for j in judged if ppt.deal_id(d) in (j.get('live') or [])]
        named = sum(1 for j in asked if ppt.deal_id(d) in (j.get('named') or []))
        lines.append({'k': f"Or {ppt.label(d, d.get('variant')).split(': ', 1)[-1]}", 'v': _money(
            (d.get('variant') or {}).get('price')) or '', 'tag': f"Named {named} of {len(asked)}"})
    said: Dict[str, List[str]] = {}
    for q in cell.get('quotes') or []:
        if q.get('stated'):
            said.setdefault(_money(q['stated']) or q['stated'], []).append(rm.AGENT_NAMES.get(q.get('agent'), q.get('agent')))
    if said:
        lines.append({'k': 'What agents quoted', 'v': ', '.join(said), 'kind': 'plus',
                      'tag': _join(list(dict.fromkeys(a for v in said.values() for a in v if a)))})
    return {'title': T['tv.anatomy.title'].format(brand=brand or 'the brand'),
            'sub': T['tv.anatomy.sub'].format(product=row.get('product'), retailer=rm._retailer_name(domain),
                                              day=day or 'the read day'),
            'sku': row.get('sku'), 'variant_id': row.get('variant_id'), 'retailer': domain, 'runs': cell['runs'],
            'rows': lines, 'observed_at': read.get('observed_at')}


def true_value_hero(rows: List[dict]) -> dict:
    """TV1: from the tiles: "<wrong + left out> of <read> prices read are wrong or missing · <wrong> quoted prices
    are off the live page, and <left out> retailer prices were left out"."""
    cells = [c for r in rows for c in (r.get('retailer_cells') or r.get('cells') or {}).values()]
    wrong = sum(1 for c in cells if c.get('status') == 'wrong')
    left = sum(1 for c in cells if c.get('status') == 'missed')
    read = sum(1 for c in cells if c.get('status') in READ_STATUSES)
    sub = T['tv.hero.sub'].format(n=wrong + left, read=read)
    claim = T['tv.hero.claim'].format(wrong=_plural(wrong, 'quoted price is', 'quoted prices are'),
                                      left=_plural(left, 'retailer price was', 'retailer prices were'))
    return {'n': wrong + left, 'read': read, 'wrong': wrong, 'left_out': left, 'sub': sub, 'claim': claim,
            'text': f"{wrong + left} {sub.split(' ', 1)[1]} · {claim}"}


def true_value_brand(body: dict, *, reads: Optional[List[dict]], deals: Optional[dict], promo: Optional[dict],
                     attribute_answers: List[dict], feed_rows: Optional[List[dict]], own_domains: Iterable[str],
                     brand: Optional[str]) -> dict:
    """TV1 to TV9 on the body build_true_value served, for a brand at retail. Mutates and returns it."""
    own = [_domain(d) for d in own_domains or () if d]
    if body.get('column_kind') == 'retailer':
        body['columns'] = order_columns(body.get('columns') or [], own)
        body['retailer_columns'] = order_columns(body.get('retailer_columns') or [], own)
        body['columns_by_surface'] = {s: order_columns(cols, own) for s, cols in (body.get('columns_by_surface') or {}).items()}
    sold_at: Dict[str, set] = {}
    for f in feed_rows or []:
        code = str(f.get('sku') or '')
        sold_at.setdefault(code, set()).update(_domain(x.get('domain')) for x in f.get('retailers') or []
                                               if isinstance(x, dict) and x.get('domain'))
    day = rm._short_day((deals or {}).get('read_date') or body.get('as_of')) if \
        ((deals or {}).get('read_date') or body.get('as_of')) else None
    for row in body.get('rows') or []:
        listed = sold_at.get(str(row.get('feed_sku') or '')) if feed_rows is not None else None
        for domain, cell in (row.get('retailer_cells') or row.get('cells') or {}).items():
            d = _domain(domain)
            if d in own:
                cell['note'] = brand_note(row, reads, own, brand)
                continue
            found = cell_deals(row, d, deals)
            cell['live_deal'] = '. '.join(found) if found else None
            cell['live_deals'] = found
            # the feed lists no page for it at this retailer (None when the feed was not read)
            cell['not_sold'] = None if listed is None else d not in listed
            clash = clash_text(cell)
            if clash:
                cell['clash'] = clash
        row['line'] = product_line(row, deals=deals, promo=promo, attribute_answers=attribute_answers)
    body['hero'] = true_value_hero(body.get('rows') or [])
    body['anatomy'] = anatomy(body.get('rows') or [], reads=reads, deals=deals, promo=promo, brand=brand, day=day)
    body['captions'] = TV_CAPTIONS
    if not body.get('programs'):
        body['programs'] = None
        body['programs_reason'] = 'the brand runs no programs of its own (its owned incentives are empty)'
    body['mode'] = 'manufacturer'
    return body


# ─── Accessibility ───────────────────────────────────────────────────────

#: AC2: the identities the demo's request log shows (pg.ts accessibility.requests), the vendor each speaks for
DEMO_IDENTITIES = (('GPTBot', 'chatgpt'), ('OAI-SearchBot', 'chatgpt'), ('ChatGPT-User', 'chatgpt'),
                   ('Googlebot', 'aimode'), ('Google-Extended', 'gemini'), ('PerplexityBot', 'perplexity'),
                   ('Bingbot', 'copilot'), ('ClaudeBot', 'claude'))
IDENTITY_GAP_NOTE = ("supply's access run requests these identities by its own config; soa serves what it ran and "
                     "adds none")
RIVALS_REASON = 'no access reads of rival domains'


def identities(requests: Iterable[dict]) -> dict:
    """AC2: {served, missing, note}: the identities supply's access run requested, and the demo's it did not
    (case and the "(control)" suffix aside). soa serves only what supply ran."""
    served = [r.get('identity') for r in requests or [] if r.get('identity')]
    have = {str(s).split(' (')[0].strip().lower() for s in served}
    missing = [name for name, _v in DEMO_IDENTITIES if name.lower() not in have]
    return {'served': served, 'missing': missing, 'note': IDENTITY_GAP_NOTE if missing else None}


def accessibility_brand(body: dict) -> dict:
    """AC2 and AC6 beside 2T-4's brand-mode body: `identities`, and `rivals` null with its reason until rival
    domains are read."""
    body['identities'] = identities(body.get('requests') or [])
    body['rivals'] = None
    body['rivals_reason'] = RIVALS_REASON
    return body
