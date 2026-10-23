"""
2M-2: promo pass-through, the demo's fifth brand tile.

`promoPassThrough.rule = "answer names a specific deal that was live on a
retailer shelf for that SKU that day"`, over the answered cheapest-place
answers (source_ref.intent 'cheapest_place', 2L-4); where-to-buy answers
are counted the same way and reported apart.

The shelf half is supply's: GET /api/truesync/merchants/{slug}/deals?as_of=
(parleo-supply-app 2M-2, truesync/fullloop/deals.py), the deals each
retailer page ran on each variant on the cycle's read date, grouped by
retailer and deal text with the variants each was live on. A deal is live
for a question when the question's variant is one of the deal's variants.

Named, deterministic per deal kind: the answer names the deal's retailer
and
  multi_buy        the multi-buy terms: "buy 2", the percent ("40%",
                   "40 percent"), or the two-box total (two at the shelf
                   price with the percent off one);
  rollback_or_was  the word Rollback, or the struck price ("was $59.77").
                   The demo's rule: quoting the Rollback price without the
                   word does not count;
  sale             the sale price;
  coupon           the coupon amount, or the word "coupon";
  member_cash      the program's name ("Sam's Cash", "ExtraBucks");
  other            the deal's amount, or its text.
Loose: any of deal, sale, off, coupon, save, promo, discount, rollback,
clearance. Subscribe: "Subscribe & Save", "auto-delivery", "subscription"
(the charter's standing program, not a deal). No model.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional

CHEAPEST_PLACE = 'cheapest_place'
WHERE_TO_BUY = 'where_to_buy'
INTENTS = (CHEAPEST_PLACE, WHERE_TO_BUY)
RULE = 'answer names a specific deal that was live on a retailer shelf for that SKU that day'

KIND_WORDS = {'multi_buy': 'multi-buy', 'rollback_or_was': 'Rollback', 'sale': 'sale price',
              'coupon': 'coupon', 'member_cash': 'reward', 'other': 'deal'}

LOOSE = re.compile(r"\b(?:deals?|sale|sales|off|coupons?|save|saves|saving|savings|promos?|promotions?|promo\w*|"
                   r"discounts?|discounted|rollbacks?|clearance)\b", re.I)
SUBSCRIBE = re.compile(r"subscribe\s*(?:&|and|\+)\s*save|auto-?\s?delivery|subscriptions?\b", re.I)
#: Aliases that name a program rather than the store (soa_shared/retailers.KNOWN_RETAILERS).
_PROGRAM_ALIASES = ('rollback', 'subscribe & save', 'target circle', 'autoship (chewy)')
_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b|per cent\b)", re.I)
_NUMBER_WORDS = {'2': 'two', '3': 'three', '4': 'four'}


def _money(value) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(',', '').replace('$', '').strip()).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def amounts(text: Optional[str]) -> set:
    """Every dollar amount an answer writes ("$47.99", "$8", "$1,299.00")."""
    out = set()
    for m in _AMOUNT.finditer(text or ''):
        out.add(_money(f"{m.group(1)}.{m.group(2) or '0'}"))
    return out


def percents(text: Optional[str]) -> set:
    return {_money(m.group(1)) for m in _PERCENT.finditer(text or '')}


def _gtin14(value) -> Optional[str]:
    digits = re.sub(r'\D', '', str(value or ''))
    return digits.zfill(14) if 8 <= len(digits) <= 14 else None


def variant_keys(ref: Optional[dict]) -> set:
    """The keys a question's variant goes by in supply's rows (GTIN-14, variant_ref, sku, sku:<sku>)."""
    ref = ref or {}
    keys = {_gtin14(ref.get('gtin')), _gtin14(ref.get('variant_id'))}
    for k in ('variant_id', 'variant_ref', 'sku'):
        if ref.get(k):
            keys.add(str(ref[k]))
    if ref.get('sku'):
        keys.add(f"sku:{ref['sku']}")
    return {k for k in keys if k}


def _entry_keys(v: dict) -> set:
    keys = {_gtin14(v.get('gtin')), v.get('variant_ref'), v.get('sku'), f"sku:{v['sku']}" if v.get('sku') else None}
    ref = str(v.get('variant_ref') or '')
    if ':' in ref:
        keys.add(ref.split(':', 1)[1])   # feed_sku:<n> answers to its <n>
    return {str(k) for k in keys if k}


def deal_id(deal: dict) -> str:
    return f"{deal.get('retailer_domain')}|{deal.get('kind')}|{(deal.get('text') or '').casefold()}"


def live_for(deals_payload: Optional[dict], ref: Optional[dict]) -> List[dict]:
    """The deals live for the question's variant: [{**deal, variant: its entry}], supply's order."""
    mine = variant_keys(ref)
    out = []
    for deal in (deals_payload or {}).get('deals') or []:
        entry = next((v for v in deal.get('variants') or [] if _entry_keys(v) & mine), None)
        if entry is not None:
            out.append({**deal, 'variant': entry})
    return out


def retailer_aliases(domain: Optional[str]) -> List[str]:
    from soa_shared import retailers as af
    domain = (domain or '').lower().removeprefix('www.')
    names = [a for a, d in af.KNOWN_RETAILERS.items() if d == domain and a not in _PROGRAM_ALIASES]
    display = af.retailer_name(domain)
    return list(dict.fromkeys([*(n for n in (display, domain) if n), *names]))


def _says(text: str, words: Iterable[str]) -> bool:
    low = (text or '').lower().replace('’', "'")
    for w in words:
        w = (w or '').lower().replace('’', "'").strip()
        if w and re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", low):
            return True
    return False


def names_retailer(text: str, domain: Optional[str]) -> bool:
    return _says(text, retailer_aliases(domain))


def _buy_n(terms: Optional[str], text: Optional[str]) -> Optional[str]:
    m = re.search(r"\bbuy\s+(\d+|two|three|four)\b", f"{terms or ''} {text or ''}", re.I)
    return m.group(1).lower() if m else None


def names_terms(answer: str, deal: dict) -> bool:
    """Whether the answer states the deal's own terms, by kind (see the module doc)."""
    kind = deal.get('kind')
    said_amounts, said_percents = amounts(answer), percents(answer)
    value = _money(deal.get('value'))
    variant = deal.get('variant') or {}
    if kind == 'multi_buy':
        n = _buy_n(deal.get('terms'), deal.get('text'))
        if n and _says(answer, [f"buy {n}", f"buy {_NUMBER_WORDS.get(n, n)}"]):
            return True
        if deal.get('value_unit') == 'percent' and value is not None:
            if value in said_percents:
                return True
            shelf = _money(variant.get('shelf_price'))
            if shelf is not None:
                two = (shelf + shelf * (Decimal(100) - value) / Decimal(100)).quantize(Decimal('0.01'))
                if any(abs(a - two) <= Decimal('0.01') for a in said_amounts):
                    return True
        return bool(value is not None and deal.get('value_unit') == 'usd' and value in said_amounts) or \
            bool(amounts(deal.get('text')) & said_amounts)
    if kind == 'rollback_or_was':
        was = _money(variant.get('was_price'))
        return _says(answer, ['rollback', 'rolled back']) or (was is not None and was in said_amounts)
    if kind == 'sale':
        price = _money(variant.get('price'))
        return price is not None and price in said_amounts
    if kind == 'coupon':
        return _says(answer, ['coupon', 'coupons']) or (value is not None and value in said_amounts)
    if kind == 'member_cash':
        return _says(answer, [deal.get('program')] if deal.get('program') else [])
    if value is not None and (value in said_amounts or value in said_percents):
        return True
    return bool(deal.get('text')) and _says(answer, [deal['text']])


def names_deal(answer: Optional[str], deal: dict) -> bool:
    """The rule: the answer names the deal's retailer and its terms."""
    return bool(answer) and names_retailer(answer, deal.get('retailer_domain')) and names_terms(answer, deal)


def judge(answer: Optional[str], live: List[dict]) -> dict:
    """One answer against the deals live for its variant: {named: [deal ids], loose, subscribe}."""
    return {'named': [deal_id(d) for d in live if names_deal(answer, d)],
            'loose': bool(LOOSE.search(answer or '')), 'subscribe': bool(SUBSCRIBE.search(answer or ''))}


#: 2N-1: what each retailer calls a price cut against a struck price, in its
#: own words: Walmart's Rollback, Amazon's list price cut, Target's sale,
#: Kroger's sale price. The kind supply reads is one (rollback_or_was); the
#: name is the retailer's.
RETAILER_CUT_WORDS = {'walmart.com': 'Rollback', 'amazon.com': 'list price cut', 'target.com': 'sale',
                      'kroger.com': 'sale price'}
#: The struck price each retailer's cut is taken off, for the title.
RETAILER_CUT_BASIS = {'amazon.com': 'list price', 'walmart.com': 'Rollback', 'target.com': 'sale',
                      'kroger.com': 'sale price'}
_GENERIC_TAIL = {'diapers', 'diaper', 'pants', 'wipes', 'nappies', 'underwear'}


def kind_words(deal: dict) -> str:
    """The deal's kind as its retailer names it ("Rollback", "list price cut", "sale")."""
    if deal.get('kind') == 'rollback_or_was':
        return RETAILER_CUT_WORDS.get(deal.get('retailer_domain'), 'price cut')
    if deal.get('kind') == 'member_cash' and deal.get('program'):
        return deal['program']
    return KIND_WORDS.get(deal.get('kind'), 'deal')


def deal_line(variant: dict) -> Optional[str]:
    """"AMORE Size 1" from the variant's product name and label: the line
    without the brand's word in front or the generic tail, and the size."""
    from soa_shared import attribute_accuracy as aa
    name = variant.get('product_name') or ''
    head = re.split(r",|\bsize\b|\b\d+\s*(?:ct|count)\b", name, maxsplit=1, flags=re.I)[0]
    words = [w for w in head.split() if w.lower() not in _GENERIC_TAIL]
    if len(words) > 1:
        words = words[1:]
    size = aa.size_label(variant.get('variant_label')) or aa.size_label(name)
    line = ' '.join(words + ([size] if size else []))
    return line or variant.get('variant_label') or None


def _pct_off(deal: dict) -> Optional[str]:
    if deal.get('value') is not None and deal.get('value_unit') == 'percent':
        return format(Decimal(str(deal['value'])).normalize(), 'f')
    for v in deal.get('variants') or [deal.get('variant') or {}]:
        was, price = _money(v.get('was_price')), _money(v.get('price'))
        if was and price and was > price:
            return str(int(((was - price) / was * 100).quantize(Decimal('1'))))
    return None


def _clean_text(deal: dict) -> Optional[str]:
    """supply's text for the deal when it is a phrase ("Save 40% on 1 when you
    buy 2", "$15 Sam's Cash on $100 of P&G"), never shelf evidence."""
    text = (deal.get('text') or '').strip().rstrip('.')
    if not text or len(text) > 60 or re.search(r"\$\s+\d|/\s*count|per count|list price:", text, re.I):
        return None
    return text[0].lower() + text[1:] if re.match(r"(?:save|get|buy|earn|clip|spend|take)\b", text, re.I) else text


def _phrase(deal: dict) -> str:
    """The kind phrase from the deal's fields (or supply's phrase for it), never its evidence."""
    kind, domain = deal.get('kind'), deal.get('retailer_domain')
    pct = _pct_off(deal)
    if kind == 'rollback_or_was':
        basis = RETAILER_CUT_BASIS.get(domain)
        if domain == 'walmart.com':
            return f"Rollback, {pct}% off" if pct else 'Rollback'
        if pct:
            return f"{pct}% off {basis}" if basis else f"{pct}% off the was price"
        return kind_words(deal)
    if kind == 'sale':
        return f"{kind_words(deal)}, {pct}% off" if pct else kind_words(deal)
    text = _clean_text(deal)
    if text:
        return text
    if kind == 'multi_buy':
        return f"{pct}% off when you buy {deal.get('terms') or 'more'}" if pct else 'multi-buy'
    if kind == 'coupon' and deal.get('value') is not None:
        amount = f"{deal['value']}%" if deal.get('value_unit') == 'percent' else f"${Decimal(str(deal['value'])).quantize(Decimal('0.01'))}"
        return f"{amount} coupon"
    if kind == 'member_cash':
        return deal.get('program') or 'member reward'
    return KIND_WORDS.get(kind, 'deal')


def title(deal: dict) -> str:
    """2N-1: "<Retailer>: <kind phrase> on <line>", from the deal's fields:
    "Amazon: 25% off list price on AMORE Size 1, $36.18 from $47.99". A deal
    on more than one line names none (the row's detail lists them). The
    evidence string is the detail's (evidence()), never the title."""
    from soa_shared import retailers as af
    variants = deal.get('variants') or ([deal['variant']] if deal.get('variant') else [])
    lines = list(dict.fromkeys(x for x in (deal_line(v) for v in variants) if x))
    phrase = _phrase(deal)
    # one line, and a phrase that names none of its own ("... on $100 of P&G"); more than one: the detail lists them
    on = f" on {lines[0]}" if len(lines) == 1 and ' on ' not in f" {phrase} " else ''
    prices = ''
    if len(variants) == 1 and variants[0].get('price') and variants[0].get('was_price'):
        prices = f", ${variants[0]['price']} from ${variants[0]['was_price']}"
    return f"{af.retailer_name(deal.get('retailer_domain'))}: {phrase}{on}{prices}"


def short(deal: dict) -> str:
    """"Amazon multi-buy", "Walmart Rollback", "Amazon list price cut", "Sam's Club Sam's Cash": the tile note's
    name. 2N-2: the retailer and kind_words(), the kind_label the Trade promotions row shows, so every reader
    of the deal's kind (tile note, Changes, Impact baseline, narratives) says what the row says."""
    from soa_shared import retailers as af
    return f"{af.retailer_name(deal.get('retailer_domain'))} {kind_words(deal)}"


#: The price-per-count noise a shelf's evidence carries: "$0.27 per count",
#: "( $0.27 $0.27 / count)", a price split by spaces ("$ 36 . 18").
_PER_COUNT = re.compile(r"\(\s*(?:\$\s?\d+(?:\.\d+)?\s*)+/\s*(?:count|ct|diaper|unit)\s*\)|"
                        r"\$\s?\d+(?:\.\d+)?\s*(?:per|/)\s*(?:count|ct|diaper|unit)s?\b", re.I)
_SPLIT_PRICE = re.compile(r"\$\s+\d+\s*\.\s*\d+")


def evidence(text: Optional[str]) -> Optional[str]:
    """The shelf's own words for a deal, for the row's detail, trimmed of the
    price-per-count noise: "$36.18 with 25 percent savings -25% $ 36 . 18
    $0.27 per count ( $0.27 $0.27 / count) List Price: $47.99" -> "$36.18
    with 25 percent savings -25% List Price: $47.99"."""
    if not text:
        return None
    out = _SPLIT_PRICE.sub(' ', _PER_COUNT.sub(' ', text))
    out = re.sub(r"\(\s*\)", ' ', out)
    return ' '.join(out.split()) or None


def count(answers: List[dict], deals_payload: Optional[dict], intent: str = CHEAPEST_PLACE) -> dict:
    """
    `answers`: [{run_id, surface, intent, source_ref, text}] (answered runs).
    Returns {n, k, loose, subscribe, per_deal, by_surface, judged} over the
    answers of `intent`: n the answers, k those naming a live deal; per_deal
    one entry per deal live on any asked variant {id, retailer, retailer_domain,
    text, kind, title, short, kind_label, asked, named} (asked: answers about a SKU it was live on),
    most asked first; by_surface {surface: {n, k, loose, subscribe}}; judged
    per answer {run_id, surface, live: [ids], named: [ids], loose, subscribe}.
    """
    mine = [a for a in answers if a.get('intent') == intent]
    per: Dict[str, dict] = {}
    judged, by_surface = [], {}
    for a in mine:
        live = live_for(deals_payload, a.get('source_ref'))
        verdict = judge(a.get('text'), live)
        for d in live:
            entry = per.setdefault(deal_id(d), {
                'id': deal_id(d), 'retailer_domain': d.get('retailer_domain'),
                'retailer': title(d).split(':', 1)[0], 'text': d.get('text'), 'kind': d.get('kind'),
                'title': title(d), 'short': short(d), 'kind_label': kind_words(d), 'asked': 0, 'named': 0})
            entry['asked'] += 1
            entry['named'] += deal_id(d) in verdict['named']
        cell = by_surface.setdefault(a.get('surface'), {'n': 0, 'k': 0, 'loose': 0, 'subscribe': 0})
        cell['n'] += 1
        cell['k'] += bool(verdict['named'])
        cell['loose'] += verdict['loose']
        cell['subscribe'] += verdict['subscribe']
        judged.append({'run_id': a.get('run_id'), 'surface': a.get('surface'), 'variant_id': (a.get('source_ref') or {}).get('variant_id'),
                       'live': [deal_id(d) for d in live], **verdict})
    order = {deal_id(d): i for i, d in enumerate((deals_payload or {}).get('deals') or [])}
    return {
        'n': len(mine), 'k': sum(1 for j in judged if j['named']),
        'loose': sum(1 for j in judged if j['loose']), 'subscribe': sum(1 for j in judged if j['subscribe']),
        'per_deal': sorted(per.values(), key=lambda e: (-e['asked'], order.get(e['id'], 0))),
        'by_surface': by_surface, 'judged': judged,
    }


def deals_from_rows(rows: Optional[List[dict]]) -> dict:
    """
    supply's /deals shape built from retailer-prices rows that carry `deals`
    (2M-2: each row's deals), retailer rows only: the cycle's cached
    reference (soa_cycles.reference_prices) read at the cycle's as_of, which
    is what the narratives' facts read.
    """
    groups: Dict[tuple, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get('role') not in (None, 'retailer'):
            continue
        for deal in row.get('deals') or []:
            key = (row.get('retailer_domain'), deal.get('kind'), (deal.get('text') or '').casefold())
            group = groups.setdefault(key, {'retailer_domain': row.get('retailer_domain'), **{
                k: deal.get(k) for k in ('kind', 'text', 'value', 'value_unit', 'terms', 'program')}, 'variants': []})
            group['variants'].append({**{k: row.get(k) for k in ('variant_ref', 'gtin', 'sku', 'variant_label')},
                                      'shelf_price': row.get('price'), 'price': deal.get('price'),
                                      'was_price': deal.get('was_price'), 'evidence': deal.get('evidence')})
    return {'deals': list(groups.values())}


def times(n: int) -> str:
    return 'once' if n == 1 else 'twice' if n == 2 else f"{n} times"


def named_words(per_deal: List[dict]) -> str:
    """"Amazon multi-buy twice, Walmart Rollback twice and Sam's Club Sam's Cash once": the deals answers named."""
    said = [f"{d['short']} {times(d['named'])}" for d in per_deal if d.get('named')]
    return said[0] if len(said) == 1 else ', '.join(said[:-1]) + f" and {said[-1]}" if said else ''


def biggest(per_deal: List[dict]) -> Optional[dict]:
    """The deal asked about most (the tile note's): first of per_deal."""
    return per_deal[0] if per_deal else None
